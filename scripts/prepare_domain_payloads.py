#!/usr/bin/env python3
"""Post-process finalized domains into per-domain subagent payloads.

Run this AFTER you (the orchestrator) have reviewed and, if needed,
re-clustered rss_classifier.py's rough draft into domains that actually
reflect the feed set's real content (see SKILL.md Step 1.5). This script
does two purely mechanical things that don't need judgment:

1. Extracts objective engagement metrics where the RSS itself provides them
   (currently: Hacker News Front Page embeds "Points: N" / "# Comments: N"
   in its <description>). Articles get an `objective_metric` string and a
   `_score` used to sort them within their domain. Sources without any such
   field are left alone — never fabricate a metric that isn't in the feed.

2. Computes a proportional "Top N to select" per domain instead of a flat
   Top 5 everywhere, so a 230-article domain and a 20-article domain don't
   get treated as equally deep. Total budget is split proportionally to
   each domain's article count, clamped to [min_n, max_n].

3. Guarantees each source a floor of at least `--per-source-floor` (default
   3) articles in the candidate pool handed to the subagent, on top of the
   existing score-based ordering — not instead of it. A domain can have many
   source feeds of very different volume (e.g. one magazine with 100
   articles next to a niche blog with 5); pure score/volume-based capping
   would let the high-volume source crowd the low-volume one out of the
   pool entirely, and the subagent's Top N picks then end up monolingual by
   source even though its editorial judgment logic hasn't changed at all.
   The floor doesn't force the low-volume source into the final Top N —
   that's still the subagent's call — it just makes sure the subagent can
   actually see and consider it.

   The floor is skipped for a source that's gone stale: if its own
   most-recent article is older than 7 days, it's not force-included, and
   that source can legitimately end up with fewer than the floor (even
   zero) in the pool. A dead/slow feed shouldn't get manufactured presence
   just to hit a quota — the floor exists to protect low-volume-but-active
   sources, not to pad out ones that haven't posted anything recent.

   The floor is also only ever filled FROM articles published within the
   last 7 days — even for a source that isn't stale overall, an individual
   article older than 7 days is never used to top up its floor. A source
   with only 1-2 recent articles legitimately floors at 1-2, not 3;
   reaching into its older backlog to force a 3rd would misrepresent an
   old piece as current coverage, which defeats the point of the floor
   (visibility into what a source is doing lately, not padding a count).
   Undated articles (unparseable pubDate) get the benefit of the doubt and
   are still eligible, same as in the staleness check above.

Input: a JSON file shaped like rss_classifier.py's output —
  {"domains": {"<name>": {"todays_articles": [...], "other_articles": [...]}, ...}}
(the domain names/grouping can be your re-clustered version, not necessarily
what rss_classifier.py produced directly).

Output: one JSON file per domain in --output-dir, each containing
  {"domain": ..., "top_n_to_select": N, "todays_articles": [...], "other_articles_sample": [...]}
ready to hand to a subagent.
"""

import argparse
import json
import re
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from rss_classifier import _parse_article_datetime  # noqa: E402

STALE_FLOOR_WINDOW = timedelta(days=7)

# Weekly-cadence sources whose latest issue must always reach the report.
# A daily 24h window misses a weekly issue on 6 days out of 7, so these use a
# 7-day window and bypass pool caps. Value = title substring that marks a real
# issue (the feed may also carry unrelated posts).
MUST_INCLUDE_SOURCES = {
    '科技爱好者周刊': '科技爱好者周刊',
}
MUST_INCLUDE_WINDOW = timedelta(days=7)


def collect_must_include(articles: list[dict], now: datetime) -> list[dict]:
    picks = []
    for a in articles:
        marker = MUST_INCLUDE_SOURCES.get(a.get('source_title', ''))
        if marker is None or marker not in (a.get('title') or ''):
            continue
        d = _parse_article_datetime(a.get('date', ''))
        if d is not None and d >= now - MUST_INCLUDE_WINDOW:
            picks.append(a)
    return picks


def extract_objective_metric(article: dict):
    """Pull a verifiable engagement metric straight out of the RSS payload.

    Only Hacker News Front Page is known to embed one today. Extend this
    function (not the subagent prompts) if you add a feed that has real
    engagement data — never ask a subagent to invent one.
    """
    src = article.get('source_title', '')
    desc = article.get('description', '') or ''

    if src == 'Hacker News Front Page':
        pts = re.search(r'Points:\s*(\d+)', desc)
        cmts = re.search(r'#\s*Comments:\s*(\d+)', desc)
        if pts:
            score = int(pts.group(1))
            n_cmts = int(cmts.group(1)) if cmts else 0
            return f'Hacker News: {score} 讚, {n_cmts} 則留言', score

    return None, None


def redirect_hn_link_to_discussion(article: dict):
    """For Hacker News Front Page entries, point `link` at the HN discussion
    thread instead of the external article the submission is about.

    hnrss's <link> element is the external article URL — useful for most
    feeds, but wrong for a link a reader clicks from a digest of *Hacker
    News*: the point of an HN pick is the discussion, not just the story.
    The comments URL (news.ycombinator.com/item?id=...) is embedded in the
    description as "Comments URL: <a href="...">". When present, swap it in
    as `link` and preserve the original article URL as `external_link` so
    it isn't lost — subagents can still cite it inline in the summary.
    Leave the article alone if the description doesn't have a comments URL
    (e.g. a rare HN entry with no discussion yet).
    """
    if article.get('source_title') != 'Hacker News Front Page':
        return
    desc = article.get('description', '') or ''
    m = re.search(r'Comments URL:\s*<a href="([^"]+)"', desc)
    if not m:
        return
    discussion_url = m.group(1)
    original_link = article.get('link')
    if original_link and original_link != discussion_url:
        article['external_link'] = original_link
    article['link'] = discussion_url


def annotate(articles: list[dict]):
    for a in articles:
        redirect_hn_link_to_discussion(a)
        metric, score = extract_objective_metric(a)
        if metric:
            a['objective_metric'] = metric
            a['_score'] = score


def allocate_top_n(counts: dict[str, int], budget: int, min_n: int, max_n: int) -> dict[str, int]:
    total = sum(counts.values()) or 1
    return {
        name: max(min_n, min(max_n, round(cnt / total * budget)))
        for name, cnt in counts.items()
    }


def _is_stale(group: list[dict], now: datetime) -> bool:
    """A source is stale if none of its articles were published within the
    last STALE_FLOOR_WINDOW. Unparseable/missing dates don't count as
    recent, but also don't count as proof of staleness on their own — the
    group is only stale if every dated article is old and there's nothing
    undated to give it the benefit of the doubt.
    """
    dates = [_parse_article_datetime(a.get('date', '')) for a in group]
    dates = [d for d in dates if d is not None]
    if not dates:
        return False
    return max(dates) < now - STALE_FLOOR_WINDOW


def cap_with_source_floor(articles: list[dict], cap: int, per_source_floor: int) -> list[dict]:
    """Cap a list to `cap` items, but first guarantee each source_title gets
    up to `per_source_floor` of its own highest-scoring articles in the pool,
    before filling the rest by global score. Keeps the current score-based
    ranking as the primary ordering — this only prevents a high-volume
    source from silently pushing a low-volume source out of the pool.

    A source whose most recent article is older than STALE_FLOOR_WINDOW is
    exempt from the floor guarantee (see module docstring point 3) — it's
    left to fall out via ordinary score-based capping like any other
    article, which can drop it below the floor entirely.

    The floor is filled only from that source's own articles published
    within STALE_FLOOR_WINDOW (undated articles included, benefit of the
    doubt) — an individual article older than the window is never pulled
    in just to reach the floor count, even for a source that isn't stale
    overall (see module docstring point 3).
    """
    if len(articles) <= cap:
        return sorted(articles, key=lambda a: a.get('_score', -1), reverse=True)

    now = datetime.now(timezone.utc)
    by_source: dict[str, list[dict]] = {}
    for a in articles:
        by_source.setdefault(a.get('source_title', ''), []).append(a)
    for group in by_source.values():
        group.sort(key=lambda a: a.get('_score', -1), reverse=True)

    def _is_recent(a: dict) -> bool:
        d = _parse_article_datetime(a.get('date', ''))
        return d is None or d >= now - STALE_FLOOR_WINDOW

    floor_picks = []
    for group in by_source.values():
        if _is_stale(group, now):
            continue
        recent = [a for a in group if _is_recent(a)]
        floor_picks.extend(recent[:per_source_floor])
    floor_ids = {id(a) for a in floor_picks}

    remaining = [a for a in articles if id(a) not in floor_ids]
    remaining.sort(key=lambda a: a.get('_score', -1), reverse=True)

    combined = floor_picks + remaining[:max(0, cap - len(floor_picks))]
    combined.sort(key=lambda a: a.get('_score', -1), reverse=True)
    return combined[:cap]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('input', help='JSON file with a top-level "domains" key')
    parser.add_argument('--output-dir', '-o', required=True)
    parser.add_argument('--budget', type=int, default=30,
                         help='Total "top articles" to distribute across all domains (default 30)')
    parser.add_argument('--min-n', type=int, default=3)
    parser.add_argument('--max-n', type=int, default=10)
    parser.add_argument('--today-cap', type=int, default=80,
                         help='Max todays_articles to include per domain payload')
    parser.add_argument('--other-cap', type=int, default=50,
                         help='Max other_articles to include per domain payload')
    parser.add_argument('--per-source-floor', type=int, default=3,
                         help='Guarantee each source at least this many articles in the pool, if it has that many and its most recent article is within 7 days (default 3)')
    args = parser.parse_args()

    data = json.loads(Path(args.input).read_text())
    domains = data['domains']

    for content in domains.values():
        annotate(content.get('todays_articles', []))
        annotate(content.get('other_articles', []))

    counts = {
        name: len(c.get('todays_articles', [])) + len(c.get('other_articles', []))
        for name, c in domains.items()
    }
    alloc = allocate_top_n(counts, args.budget, args.min_n, args.max_n)

    out_dir = Path(args.output_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    now = datetime.now(timezone.utc)
    print('文章數與分配的 Top N：')
    for name, content in domains.items():
        today = cap_with_source_floor(content.get('todays_articles', []), args.today_cap, args.per_source_floor)
        other = cap_with_source_floor(content.get('other_articles', []), args.other_cap, args.per_source_floor)
        must = collect_must_include(
            content.get('todays_articles', []) + content.get('other_articles', []), now)
        payload = {
            'domain': name,
            'top_n_to_select': alloc[name],
            'must_include_articles': must,
            'todays_articles': today[:args.today_cap],
            'other_articles_sample': other[:args.other_cap],
        }
        fname = out_dir / f'{name.replace("/", "_")}.json'
        fname.write_text(json.dumps(payload, ensure_ascii=False, indent=2))
        note = f'，必收 {len(must)} 篇' if must else ''
        print(f'  {name}: {counts[name]} 篇 -> Top {alloc[name]}{note}  ({fname})')


if __name__ == '__main__':
    main()
