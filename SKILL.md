---
name: rss-classifier
description: |
  Automatically classify and summarize RSS/OPML feed topics. When the user provides an RSS file (.opml or .xml), this skill parses it, re-clusters it into domains that actually reflect the feed set's real content (not a fixed category list), then dispatches a subagent per domain to write a Traditional Chinese summary of today's important events and a proportionally-sized trending-articles write-up — with extra depth for the Technology domain (comparing new tools/tech against what came before) and a closing commentary on what the day's news actually reveals. Make sure to use this skill whenever the user mentions RSS, OPML, feed classification, topic summarization, or news aggregation from syndicated feeds — even if they don't explicitly ask for 'classification' or 'summarization.'
compatibility:
  - Python 3.8+ (standard library only: xml, json, datetime, collections, urllib, re, argparse)
  - Agent tool, for dispatching one subagent per topic domain
---

# RSS/OPML Topic Classifier & Summarizer

## Why this is split into parse (script) + write (subagents)

Parsing OPML/RSS XML is mechanical and deterministic — a script handles
that reliably and fast. But writing a good summary of "what matters today
in this domain," ranking the top articles, and — especially for
Technology — explaining how a new tool improves on what came before is a
*judgment and writing* task. A script that tries to do this with keyword
templates produces generic, repetitive filler. A subagent that actually
reads the article titles/descriptions and reasons about them writes
something a person would find useful.

So the pipeline is:

1. **Parse & rough-classify (script, deterministic)** — extract articles from
   the OPML/RSS file and get a first-pass grouping.
2. **Re-cluster by actual content (you, the orchestrator)** — the script's
   first pass is a rough draft, not the final domain list. Fix it up based
   on what the feeds actually publish before dispatching anything.
3. **Compute objective ranking signals + proportional Top N (script)** —
   mechanical post-processing: pull real engagement metrics where the RSS
   provides them, and size each domain's "Top N" to its actual article
   volume instead of a flat number everywhere.
4. **Dispatch one subagent per domain (generative)** — each subagent reads
   its domain's articles and writes the summary + Top N write-up + closing
   commentary, in Traditional Chinese.
5. **Aggregate** — combine each subagent's write-up into the final report.

All user-facing output — domain names, summaries, article write-ups — must
be in **Traditional Chinese (繁體中文)**, regardless of the language the
original feed content is in.

## Step 1: Parse & rough-classify

```bash
python3 scripts/rss_classifier.py <path-to-opml-or-rss-file> --output /tmp/rss_parsed.json
```

This fetches feed content (for OPML files with `xmlUrl`s), parses items, and
does a first-pass keyword grouping. **This keyword matcher is English-only**
and will misfire badly on non-English feeds — treat its bucket sizes as
noise, not signal, until you've done Step 1.5.

**Check `failed_feeds` in the output before anything else.** A feed that
403s (many sites block non-browser User-Agents — old.reddit.com does this
routinely) or that hit a paid proxy's quota (rss.app-hosted feeds returning
402) fails silently as far as article counts go — it just contributes 0
articles, indistinguishable from "this source genuinely had nothing new
today." The script now tracks these separately in `failed_feeds` (source
name, URL, error) precisely so they don't get misread that way. Always
report failed feeds to the user in your final summary (e.g. "r/programming
和 AILogora 這兩個來源今天抓取失敗，回傳 403/402，不是沒有新聞") — don't
let a fetch failure quietly masquerade as "this source was checked and had
nothing."

## Step 1.5: Re-cluster by actual content — mandatory, not optional

Do not dispatch subagents straight off the script's buckets. First sample
the real data:

```bash
python3 -c "
import json
from collections import Counter, defaultdict
d = json.load(open('/tmp/rss_parsed.json'))
all_arts = [a for c in d['domains'].values() for a in c['todays_articles'] + c['other_articles']]
by_src = defaultdict(list)
for a in all_arts:
    by_src[a.get('source_title','?')].append(a.get('title') or a.get('text') or '')
for src in sorted(by_src):
    print('---', src, len(by_src[src]))
    for t in by_src[src][:3]:
        print('   ', t[:70])
"
```

Reading 2-3 real titles per source almost always makes the actual topic
obvious immediately — a feed named "GQ" or "巴哈姆特" tells you very little,
but 3 real titles tell you everything. Then build the final domain grouping
yourself, driven by what's actually there rather than a fixed list:

- **Classify primarily by source identity** for single-topic feeds (a
  gaming news feed is 100% gaming regardless of keyword scores).
- **Classify per-article by content keywords** (in whatever language the
  feed actually uses — build the keyword list from words you saw in the
  sampled titles, not a generic English list) only for genuinely broad/mixed
  sources (a general newspaper feed, a general-interest magazine).
- **Merge tiny domains** (roughly under 15-20 articles) into the nearest
  related domain rather than dispatching a subagent for a near-empty bucket.
- **Split out a real sub-theme** if a bucket is large and clearly contains
  one (e.g. a cluster of gaming articles sitting inside a generic "General
  News" catch-all).
- **Exclude adult content** (e.g. explicitly-adult feeds) rather than
  summarizing it — note the exclusion and the count in the final report.
- **Name domains after what's actually there**, not from a preset list —
  a feed set can legitimately produce domains like 遊戲動漫,
  時尚生活與影劇娛樂, 財經商業與職場生活, etc. The 7-label set in the
  script (科技/科學/商業/政治/健康/科技與資安/綜合新聞) is a fallback
  vocabulary for when nothing better fits, not the target output.

Write the finalized grouping to a new JSON file with the same
`{"domains": {"<name>": {"todays_articles": [...], "other_articles": [...]}}}`
shape expected by Step 1.6 (a quick Python re-shuffle of the parsed data is
enough — no need to re-fetch feeds).

## Step 1.6: Objective ranking + proportional Top N (script)

```bash
python3 scripts/prepare_domain_payloads.py <your-reclustered-domains.json> \
  --output-dir /tmp/domain_payloads --budget 30 --min-n 3 --max-n 10
```

This does two mechanical things, so subagents don't have to guess or (worse)
fabricate signal that isn't there:

- **Objective metrics where the RSS actually provides them.** Right now
  that's Hacker News Front Page, which embeds `Points: N` / `# Comments: N`
  in its description — the script extracts these into an `objective_metric`
  field and sorts those articles by it. No other bundled source has a real
  engagement number in the feed itself; don't ask a subagent to estimate one
  for sources that don't provide it, and don't treat a source's total volume
  or its publisher's general reputation as a substitute metric.
- **Proportional Top N per domain**, not a flat "Top 5" everywhere. A
  domain with 230 articles and a domain with 20 articles convey very
  different amounts of competition — a flat Top 5 would mean "picked from
  1/46" in one case and "listed 1/4 of everything" in the other. The script
  splits a total budget (default 30) across domains proportionally to each
  one's article count, clamped to `[min_n, max_n]` (default 3–10) so no
  domain gets 0 or an absurdly long list.
- **A per-source floor in the candidate pool** (default 3, `--per-source-floor`).
  A domain can legitimately span many source feeds of very different
  volume — a 100-article magazine feed next to a 5-article niche blog. On
  top of the score-based ordering above (unchanged), the script guarantees
  each source at least `per_source_floor` of its own articles survive into
  the pool handed to the subagent, so a high-volume source can't silently
  crowd a low-volume one out before the subagent ever sees it. This doesn't
  force source diversity into the final Top N — that's still the
  subagent's editorial call (see the diversity note in Step 2) — it only
  guarantees visibility.

Extend `extract_objective_metric()` in `prepare_domain_payloads.py` (not the
subagent prompts) if you add a feed that has real engagement data.

**Hacker News's front page is a live ranking, not a fixed daily list — it
reorders continuously as items get upvoted.** If Step 1's fetch happened
significantly earlier than when you're about to send the final report (a
long session, a multi-round revision), the HN picks can go stale: items
that were top-scored at fetch time get pushed down by newer submissions
gaining votes, and the report ends up citing "top" stories that aren't
actually near the top anymore by the time the reader opens it. Re-fetch
`https://hnrss.org/frontpage` right before finalizing if meaningful time
has passed since Step 1, and note the snapshot time in the report (e.g.
"排名為 2026-08-16 22:54 當下快照") so the reader understands HN rankings
drift and isn't confused if it doesn't match what they see live.

## Step 2: Dispatch one subagent per domain

For each finalized domain, dispatch a subagent (`general-purpose` is a
reasonable default) with its payload file from Step 1.6. Give each subagent
its own prompt containing:

- The domain name (in Traditional Chinese)
- The path to its payload JSON (`todays_articles`, `other_articles_sample`,
  `top_n_to_select`)
- An explicit instruction: if an article has `objective_metric`, use it as
  the primary ranking signal and cite it inline (e.g. "依 Hacker News
  熱度：74讚/28留言排序"); articles without it are ranked by editorial
  judgment — never invent a number to fill the gap
- An explicit instruction to include each selected article's `link` field
  alongside its title in the output, so the final report/email can render
  the title as a clickable link back to the original article — never
  fabricate or guess a URL; if an article genuinely has no link, say so
  rather than inventing one
- **A hard quota, and it's mandatory, not optional: every source that
  fetched successfully at all must be represented by at least 3 articles
  somewhere in the final report, counting both the main Top N and the
  額外閱讀 bonus section below.** Dropping a source entirely is *not* a
  valid way to satisfy this — the only sources allowed to be absent are
  ones in `failed_feeds` (Step 1) that never returned content in the first
  place. If a source's real content is thin or off-topic for every domain
  it could plausibly belong to, it still needs a home: attach it to the
  domain it's least-badly related to, or — if truly nothing fits — ask the
  user rather than silently omitting it. Before finalizing, cross-check the
  full source list from Step 1's fetch against what actually appears
  anywhere in the report; anything successfully fetched but missing is a
  bug to fix, not an acceptable gap. Ranking/importance judgment stays
  exactly as before (`objective_metric` first, else editorial judgment) —
  the quota only decides *whether a source's 3rd (and any further topped-up)
  pick is genuinely one of the domain's most important stories or not*:
  - If it's genuinely newsworthy, it belongs in the numbered Top N like
    any other pick.
  - If it only exists to satisfy the quota and isn't actually important —
    a routine roundup, a lifestyle/how-to piece, a celebrity aside — don't
    let it dilute the Top N. Instead put it in a separate **🗞️ 小額外閱讀**
    (bonus reading) subsection placed after that domain's 評語: a one-line
    intro sentence describing what this batch is, then each item as a
    linked title with a single short clause (not a full 2-3 sentence
    summary) noting why it's here / what it's about. Never fabricate a
    reason to include something, but remember the source itself is not
    optional — pick its 3 least-thin available articles and say plainly
    that they're here for coverage completeness rather than importance,
    rather than omitting the source.
- The exact output format below
- An explicit instruction to write in Traditional Chinese

Dispatch these in parallel (multiple `Agent` calls in one turn) — the
domains are independent.

**If the user names a priority domain** ("I care most about X", "put X
first"), place that domain first in the final report and hold its subagent
to a higher bar than the others: longer/more detailed article summaries,
more granular source-grouped subsections (e.g. one subsection per
contributing source instead of one flat list), and a deeper closing 評語.
Say this explicitly in that domain's dispatch prompt — don't rely on the
subagent inferring extra effort is wanted just from going first in the
aggregation order.

### What each subagent should produce

**Summary of today's important events** — 4-5 sentences in Traditional
Chinese, with real context and causal connections between the day's stories,
not a mechanical concatenation of each article's first sentence. If there
are no `todays_articles`, fall back to the most notable `other_articles_sample`
items and say so explicitly ("以下為近期而非今日的重點").

**Top N trending articles** (N = `top_n_to_select` from the payload, not a
fixed 5) — for each: a title (rendered in Traditional Chinese) paired with
its real `link` and its real publish date from the payload's `date` field
(reformat to a plain `YYYY-MM-DD`, not the raw RFC-822 string), and a
**2-3 sentence** summary that gives concrete detail from the description
(what specifically happened, key numbers/names, why it matters) rather than
restating the title in different words. Don't fabricate detail the
description doesn't support, don't fabricate a link, and don't fabricate a
date. **Every article in the report — main Top N and 額外閱讀 bonus items
alike — must show its real publish date next to it.** This isn't optional
polish: a `todays_articles`/`other_articles` split only tells you whether
an article matched today's date *at classification time*; if you later pull
from the `other_articles` pool to top up a quota, that article can be
anywhere from yesterday to over a year old (a slow-updating feed's "3 most
recent" might still be ancient), and the reader has no way to know that
unless the date is right there.

If the article's `date` field doesn't parse (some blogs omit a proper
pubDate), say so plainly (e.g. "無法解析發佈日期") rather than omitting the
date silently or guessing one from the URL/content without labeling it as
an estimate. If a source's dates cluster far in the past relative to the
rest of the report (a feed that hasn't posted anything recent), flag it
inline (e.g. "⚠️ 這幾篇明顯較舊" or "⚠️ 此來源近期可能未更新") rather than
presenting it with the same visual weight as fresh content — a stale feed
is information the reader wants, not something to paper over.

**A domain's summary paragraph must never claim "today" (今天) for content
that isn't verifiably dated today.** Writing "GitHub 官方部落格今天…" about
an article actually from a week ago is a factual error, not a style choice
— check every article's real date before writing recency language in the
summary, and if the picks span a date range, say so explicitly (e.g. "以下
是過去兩週的精選，並非同一天發生") instead of implying same-day freshness.

**Closing commentary (評語)** — one paragraph reflecting on what *today's
articles themselves* reveal: a pattern across stories, an implicit lesson,
an irony or contradiction, something worth learning or applying. This must
be about the news content — never a meta-comment on the RSS source quality,
sample size, or data-collection method; that belongs to the orchestrator's
own notes, not the subagent's output.

### Extra depth required for the Technology domain

For the Technology domain specifically (however it ended up named after
Step 1.5 — often 科技, sometimes merged with security content), the
subagent's write-up must go beyond "what happened" — for any article that
introduces or covers a new tool, framework, model, or technique, include a
short comparison paragraph covering:

- **What existed before** — the tool/approach/workflow this is replacing or
  competing with
- **What's actually new or different** about it
- **What problem it mainly solves or improves** — e.g. faster iteration,
  lower cost, better accuracy, removes a manual step, fixes a known
  limitation of the prior approach

Ground this in the article's own content — don't fabricate a comparison if
the article doesn't give enough to base one on; it's fine to say the piece
introduces X without a clear predecessor to contrast against. Instruct the
subagent explicitly on this point when dispatching — don't rely on it
inferring the extra depth from the domain name alone.

## Step 3: Aggregate into the final report

```
# RSS Feed 主題分類與摘要
*（分類依實際內容動態分群；Top N 依文章量比例分配；有客觀熱度數據時優先採用；已排除的內容註明於此）*

## [領域名稱 1]（文章數 → Top N）
**今天重要事件摘要：** [4-5 句，帶脈絡與因果，聚焦今天最值得注意的內容]

**熱門文章 Top N：**
1. **標題：** [[文章標題]([文章連結])] — 標題本身即為指向原文的超連結
   **摘要：** [2-3 句，具體細節]
   **新舊比較：**（僅科技領域、涉及新工具的文章適用）...

... (共 N 篇)

**評語：** [一段，針對今天新聞內容本身的觀察/心得，不評論資料來源]

**🗞️ 小額外閱讀：**（僅在有來源需要湊足保底 3 篇、但湊數的文章新聞價值不足以進 Top N 時才出現；省略整節如果本領域每個入選來源本來就都 ≥3 篇）
[一句話說明這批是什麼、為什麼放在這裡]
・[[文章標題]([連結])] — [一句話帶過內容或說明為何屬於次要]
...

## [領域名稱 2]
...（依此類推，只列出實際有文章的領域）
```

Don't just paste each subagent's raw response — check that they all
followed Traditional Chinese and the format above (right N, real
`objective_metric` citations where applicable, a genuine content-focused
評語 rather than a methodology comment, and a real `link` + real date per
article), and lightly normalize headers/formatting so the final report
reads as one coherent document.

**Before sending/publishing, programmatically verify every (link, title,
date) triple against the source JSON** — don't trust hand-transcribed pairs.
Manually copying title+link+date across several rounds of edits is exactly
how a link and a title end up swapped between two different articles
(this has happened in practice: two finance articles' links got crossed,
so clicking one title's link opened a different, unrelated story). A quick
script that looks up each `link` used in the final draft and confirms the
`title`/`date` you wrote matches what's actually in the parsed data catches
this class of error before the reader does.

If the final report is delivered somewhere that renders markup (an HTML
email, a webpage, an artifact) rather than as plain text, render each
article's title as a clickable link to its real `link` — that's the whole
point of carrying the link through the pipeline. Never invent a URL for an
article that didn't have one.

Tally sources across the whole report — main Top N **plus** each domain's
🗞️ 小額外閱讀 combined — and append it (a simple table, or a bar chart if
the output format supports one). Because of the quota in Step 2, every
source that appears anywhere in the report should land at ≥3 in this tally;
if one doesn't, that's a sign the quota wasn't actually applied somewhere
and is worth double-checking before sending. Label the tally clearly as
"Top N + 小額外閱讀 合計" so it's not mistaken for a claim that the main
highlight list itself is evenly spread — it isn't, and doesn't need to be.

## Input format

Accepts an OPML or RSS/XML file, passed as a file path (URL/raw XML content
also fine — adapt the script call or feed it directly if parsing raw XML is
simpler than writing it to a file first):

- **OPML**: `<outline>` elements with `text`/`title`, `type="rss"`, `xmlUrl`
  (feed URL), possibly nested for sub-categories
- **RSS/Atom**: `<item>` or `<entry>` elements with title, description/
  summary, link, and optional category elements
