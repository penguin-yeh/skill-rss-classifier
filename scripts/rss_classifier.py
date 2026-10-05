#!/usr/bin/env python3
"""RSS/OPML Parser & Classifier — deterministic preprocessing only.

This script handles the parts of the pipeline that are mechanical and don't
benefit from an LLM: parsing OPML/RSS XML, fetching feeds, and doing a rough
keyword-based first-pass classification into topic domains.

It deliberately does NOT generate any summaries, comparisons, or analysis —
that is generative work and belongs to the subagents that SKILL.md dispatches
per domain (one subagent per topic, reading the articles this script grouped
together and writing the actual write-up in Traditional Chinese).

Output: a JSON blob (to stdout or --output file) with articles grouped under
Traditional Chinese domain labels, plus a per-domain "today" subset so the
downstream subagent knows which articles are freshest without having to
re-parse dates itself.
"""

import argparse
import json
import time
import urllib.error
from datetime import datetime, date, timedelta, timezone
from pathlib import Path
import urllib.request
import xml.etree.ElementTree as ET
from collections import defaultdict


FEED_USER_AGENT = (
    'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 '
    '(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36'
)


def fetch_feed_content(xml_url: str) -> tuple[str, str]:
    """Fetch XML content from a feed URL.

    Returns (content, error). A feed that 403s or 402s fails silently if you
    only check "did I get articles" — it looks identical to a feed that
    legitimately had nothing new. Callers MUST surface `error` to the user
    instead of just treating 0 articles as "this source had no news today."

    Uses a real browser User-Agent string, not just a bare "Mozilla/5.0" —
    sites like old.reddit.com bot-filter on UA and 403 the bare string while
    happily serving a full Chrome-style UA. A 402 (e.g. a paid rss.app feed
    past its quota) isn't fixable by changing the UA — that's an account/
    billing issue on the feed provider's side, not this script's.

    Retries with backoff on a 429 (rate limited) — fetching many feeds
    back-to-back can trip a host's short-window rate limiter transiently.
    Reddit's in particular is tight enough that a single 3s retry isn't
    always enough, so this backs off twice (3s, then 8s) before giving up.
    """
    req = urllib.request.Request(xml_url, headers={'User-Agent': FEED_USER_AGENT})
    backoffs = [3, 8]
    for attempt in range(len(backoffs) + 1):
        try:
            with urllib.request.urlopen(req, timeout=15) as response:
                return response.read().decode('utf-8', errors='replace'), ''
        except urllib.error.HTTPError as e:
            if e.code == 429 and attempt < len(backoffs):
                time.sleep(backoffs[attempt])
                continue
            return '', str(e)
        except Exception as e:
            return '', str(e)
    return '', 'unreachable'


def parse_opml_file(filepath: str) -> list[dict]:
    """Parse an OPML file and extract RSS feed outlines."""
    tree = ET.parse(filepath)
    root = tree.getroot()

    outlines = []
    for outline in root.findall('.//outline'):
        item = {
            'text': outline.get('text', ''),
            'title': outline.get('title', ''),
            'description': outline.get('description', ''),
            'xmlUrl': outline.get('xmlUrl', ''),
            'type': outline.get('type', ''),
            'htmlUrl': outline.get('htmlUrl', ''),
        }
        if item['xmlUrl'] or item['text']:
            outlines.append(item)

    return outlines


def parse_rss_xml(xml_content: str) -> list[dict]:
    """Parse RSS/XML content and extract items."""
    try:
        root = ET.fromstring(xml_content)
    except ET.ParseError:
        return []

    items = []

    items_elements = root.findall('.//item')
    if not items_elements:
        items_elements = root.findall('.//{http://www.w3.org/2005/Atom}entry')

    for elem in items_elements:
        item = {}
        title_elem = elem.find('title')
        if title_elem is None:
            title_elem = elem.find('{http://www.w3.org/2005/Atom}title')
        item['text'] = title_elem.text if title_elem is not None else ''
        item['title'] = item['text']

        desc_elem = elem.find('description')
        if desc_elem is None:
            desc_elem = elem.find('{http://www.w3.org/2005/Atom}summary')
        item['description'] = desc_elem.text if desc_elem is not None else ''

        link_elem = elem.find('link')
        if link_elem is None:
            link_elem = elem.find('{http://www.w3.org/2005/Atom}link')
        if link_elem is not None and link_elem.get('href'):
            item['link'] = link_elem.get('href')
        elif link_elem is not None and link_elem.text:
            item['link'] = link_elem.text
        else:
            item['link'] = ''

        date_elem = elem.find('pubDate')
        if date_elem is None:
            date_elem = elem.find('{http://www.w3.org/2005/Atom}published')
        if date_elem is None:
            date_elem = elem.find('{http://www.w3.org/2005/Atom}updated')
        if date_elem is None:
            date_elem = elem.find('{http://purl.org/rss/1.0/}date')
        item['date'] = date_elem.text if date_elem is not None else ''

        categories = []
        for cat in list(elem.findall('category')) + list(elem.findall('{http://www.w3.org/2005/Atom}category')):
            term = cat.get('term') or cat.get('label', '') or (cat.text or '')
            if term:
                categories.append(term)
        item['categories'] = categories

        auth_elem = elem.find('author')
        if auth_elem is None:
            auth_elem = elem.find('{http://www.w3.org/2005/Atom}author')
        item['author'] = ''
        if auth_elem is not None:
            name_elem = auth_elem.find('name')
            if name_elem is None:
                name_elem = auth_elem.find('{http://www.w3.org/2005/Atom}name')
            if name_elem is not None:
                item['author'] = name_elem.text or ''
            elif auth_elem.text:
                item['author'] = auth_elem.text

        items.append(item)

    return items


# English internal keys -> Traditional Chinese domain labels used in output.
DOMAIN_LABELS = {
    'Technology': '科技',
    'Technology & Security': '科技與資安',
    'Science': '科學',
    'Business': '商業',
    'Politics': '政治',
    'Health': '健康',
    'General News': '綜合新聞',
}

TOPIC_KEYWORDS = {
    'Technology': [
        'ai', 'artificial intelligence', 'machine learning', 'deep learning',
        'software', 'programming', 'coding', 'python', 'javascript',
        'tech', 'startup', 'silicon valley', 'computer', 'hardware',
        'app', 'application', 'web', 'internet', 'cloud', 'analytics',
        'api', 'framework', 'library', 'debug', 'github', 'stack overflow',
        'llm', 'model', 'chip', 'gpu', 'open source',
    ],
    'Science': [
        'science', 'research', 'study', 'discovery', 'experiment',
        'physics', 'chemistry', 'biology', 'astronomy', 'mathematics',
        'nasa', 'space', 'genetics', 'climate', 'ecology',
        'scientist', 'researchers', 'published', 'journal',
    ],
    'Business': [
        'business', 'finance', 'economy', 'market', 'stock', 'investment',
        'ceo', 'company', 'corporation', 'entrepreneur',
        'funding', 'ipo', 'earnings', 'profit',
        'e-commerce', 'retail', 'wall street', 'bank', 'financial',
    ],
    'Politics': [
        'politics', 'election', 'government', 'president', 'congress',
        'senate', 'policy', 'legislation', 'vote', 'democrat', 'republican',
        'campaign', 'diplomacy', 'international', 'foreign affairs',
        'parliament', 'supreme court', 'regulation',
    ],
    'Health': [
        'health', 'medical', 'medicine', 'doctor', 'hospital',
        'treatment', 'therapy', 'clinical',
        'fda', 'pharmaceutical', 'wellness', 'fitness', 'nutrition',
        'public health', 'outbreak', 'vaccine', 'symptoms',
    ],
    'Technology & Security': [
        'security', 'cyber', 'hack', 'data breach', 'privacy',
        'encryption', 'vulnerability', 'malware', 'ransomware',
        'cybersecurity', 'threat', 'attack', 'phishing',
    ],
}

CATEGORY_TO_TOPIC = {
    'tech': 'Technology',
    'software': 'Technology',
    'ai': 'Technology',
    'science': 'Science',
    'health': 'Health',
    'business': 'Business',
    'politics': 'Politics',
    'security': 'Technology & Security',
}


def classify_topics(articles: list[dict]) -> dict[str, list[dict]]:
    """Rough first-pass classification by keyword/category matching.

    This is intentionally simple and deterministic — it just groups articles
    so each topic's subagent gets a manageable, relevant batch to read. It is
    NOT meant to produce the final domain labels seen by the user.

    Known limitation: TOPIC_KEYWORDS is English-only, so it silently fails on
    non-English titles/descriptions (Chinese, etc.) and dumps them all into
    "General News" regardless of what they're actually about. On a feed set
    with non-English sources, expect this first pass to be substantially
    wrong, not just approximate — don't just trust the bucket sizes.

    The mandatory fix-up step (see SKILL.md Step 1.5) is to look at what each
    source_title actually publishes (sample a few real titles per source)
    and re-cluster by that, rather than patching this keyword list. A feed's
    real topic is usually much better predicted by "what does this specific
    source publish" than by scanning translated keywords — a fashion
    magazine feed and a gaming news feed will both get keyword-matched into
    the same wrong bucket here, but sampling 3 real titles from each makes
    the actual topic obvious immediately.
    """
    classified = defaultdict(list)

    for article in articles:
        text_to_check = ' '.join(filter(None, [
            (article.get('title') or article.get('text') or '').lower(),
            (article.get('description') or '').lower(),
            ' '.join(article.get('categories', [])).lower(),
        ]))

        best_match = None
        best_score = 0
        for topic, keywords in TOPIC_KEYWORDS.items():
            score = sum(1 for kw in keywords if kw in text_to_check)
            if score > best_score:
                best_score = score
                best_match = topic

        if not best_match and article.get('categories'):
            for cat in article['categories']:
                cat_lower = cat.lower()
                if cat_lower in CATEGORY_TO_TOPIC:
                    best_match = CATEGORY_TO_TOPIC[cat_lower]
                    break

        classified[best_match or 'General News'].append(article)

    return dict(classified)


def _parse_article_datetime(article_date: str):
    """Parse an RSS date string to a timezone-aware UTC datetime, or None.

    A naive result (from formats with no offset — %Z is unreliable for
    parsing arbitrary GMT-style text and often produces a naive datetime
    anyway) is treated as UTC. That's an approximation, but RSS dates are
    overwhelmingly UTC/GMT by convention, and being off by a source's local
    UTC offset matters far less here than the previous behavior of only
    comparing bare calendar dates, which silently drops the time-of-day
    entirely.
    """
    for fmt in ('%a, %d %b %Y %H:%M:%S %Z', '%a, %d %b %Y %H:%M:%S %z',
                '%Y-%m-%dT%H:%M:%S%z', '%Y-%m-%d'):
        try:
            dt = datetime.strptime(article_date, fmt)
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
            return dt
        except ValueError:
            continue
    return None


def split_recent_articles(articles: list[dict], window_hours: int = 24) -> tuple[list[dict], list[dict]]:
    """Split articles into (published within the last `window_hours`, everything else).

    This is a rolling window ending "now" (when the script runs), not a
    bare calendar-date match — a scheduled run at a fixed local time (e.g.
    a daily 9am digest) wants "everything since roughly this time
    yesterday," not "everything whose date string happens to equal today's
    calendar date," which both under- and over-counts depending on when in
    the day the run happens and what timezone each feed's dates are in.

    Articles with an unparseable/missing date are treated as "other" rather
    than assumed to be recent.
    """
    cutoff = datetime.now(timezone.utc) - timedelta(hours=window_hours)
    recent, others = [], []
    for article in articles:
        parsed = _parse_article_datetime(article.get('date', '')) if article.get('date') else None
        if parsed and parsed >= cutoff:
            recent.append(article)
        else:
            others.append(article)
    return recent, others


# Backwards-compatible alias — same rolling-window behavior, kept because
# earlier SKILL.md revisions and ad-hoc scripts call this name directly.
split_todays_articles = split_recent_articles


def process_rss_file(filepath: str, window_hours: int = 24) -> dict:
    """Parse + classify a RSS/OPML file. No summarization here — see SKILL.md
    for how the resulting groups get handed off to per-domain subagents."""

    file_path = Path(filepath)

    is_opml = file_path.suffix.lower() == '.opml' or 'opml' in file_path.read_text()[:200].lower()

    articles = []
    failed_feeds = []  # [(source_name, url, error), ...] — surfaced to the caller, never silently dropped
    if is_opml:
        for outline in parse_opml_file(filepath):
            src_name = outline.get('text') or outline.get('title') or 'Unknown'
            if outline.get('xmlUrl'):
                feed_content, err = fetch_feed_content(outline['xmlUrl'])
                if feed_content:
                    feed_articles = parse_rss_xml(feed_content)
                    if not feed_articles:
                        failed_feeds.append((src_name, outline['xmlUrl'], 'fetched OK but 0 items parsed out of it — check the feed\'s actual XML shape'))
                    for art in feed_articles:
                        art['source_title'] = src_name
                    articles.extend(feed_articles)
                else:
                    failed_feeds.append((src_name, outline['xmlUrl'], err))
            else:
                articles.append({
                    'text': outline.get('text', ''),
                    'title': outline.get('title', ''),
                    'description': outline.get('description', ''),
                    'source_title': 'OPML Outline',
                })
    else:
        content = file_path.read_text()
        articles = parse_rss_xml(content)
        if not articles:
            # fall back to treating it as OPML
            for outline in parse_opml_file(filepath):
                src_name = outline.get('text') or outline.get('title') or 'Unknown'
                if outline.get('xmlUrl'):
                    feed_content, err = fetch_feed_content(outline['xmlUrl'])
                    if feed_content:
                        feed_articles = parse_rss_xml(feed_content)
                        if not feed_articles:
                            failed_feeds.append((src_name, outline['xmlUrl'], 'fetched OK but 0 items parsed out of it — check the feed\'s actual XML shape'))
                        for art in feed_articles:
                            art['source_title'] = src_name
                        articles.extend(feed_articles)
                    else:
                        failed_feeds.append((src_name, outline['xmlUrl'], err))

    if not articles:
        return {
            'error': 'Could not parse the RSS/OPML file. Please ensure it is a valid OPML or RSS/XML format.',
            'failed_feeds': failed_feeds,
            'domains': {},
        }

    classified = classify_topics(articles)

    result = {
        'date_generated': datetime.now().isoformat(),
        'total_articles': len(articles),
        'failed_feeds': failed_feeds,
        'domains': {},
    }

    for topic_key, domain_articles in classified.items():
        todays, others = split_recent_articles(domain_articles, window_hours)
        result['domains'][DOMAIN_LABELS.get(topic_key, topic_key)] = {
            'article_count': len(domain_articles),
            'todays_articles': todays,
            'other_articles': others,
        }

    return result


def main():
    parser = argparse.ArgumentParser(
        description='解析並初步分類 OPML/RSS 檔案（純解析與分類，不產生摘要）。'
                    '摘要與科技比較分析請依 SKILL.md 指示派發 subagent 處理。'
    )
    parser.add_argument('input', help='OPML 或 RSS/XML 檔案路徑')
    parser.add_argument('--output', '-o', help='輸出 JSON 檔案路徑（預設印到 stdout）')
    parser.add_argument('--window-hours', type=int, default=24,
                         help='「近期文章」的滾動時間窗（小時，預設 24）。'
                              '例如排程在每天 9 點跑，24 小時窗大致等於「昨天9點到今天9點」。')

    args = parser.parse_args()

    result = process_rss_file(args.input, window_hours=args.window_hours)

    output_json = json.dumps(result, indent=2, ensure_ascii=False)
    if args.output:
        with open(args.output, 'w') as f:
            f.write(output_json)
        print(f"已將解析結果寫入: {args.output}")
        print(f"共 {result.get('total_articles', 0)} 篇文章，分成 {len(result.get('domains', {}))} 個主題領域。")
    else:
        print(output_json)

    failed = result.get('failed_feeds') or []
    if failed:
        print(f"\n⚠️  {len(failed)} 個來源抓取失敗，其文章數為 0 不代表「今天沒新聞」——請在最終報告中告知使用者：")
        for src, url, err in failed:
            print(f"  - {src} ({url}): {err}")


if __name__ == '__main__':
    main()
