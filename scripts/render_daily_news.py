#!/usr/bin/env python3
"""Deterministic HTML renderer for penguin-yeh/daily-news (GitHub Pages digest).

Sibling to render_email.py, same purpose: the visual markup/CSS is Python
string literals here, not something an LLM regenerates from prose each run,
so it can't drift between days. The orchestrator's job is only to assemble
content into the JSON payload (same shape as render_email.py's
PAYLOAD_SCHEMA_EXAMPLE — see that script, or run --print-schema here) and
call this script.

This repo's output is no longer delivered by email (see daily-news/README.md
and daily-news/STYLE.md) — it's committed as penguin-yeh/daily-news's
YYYY-MM-DD.html (and copied to index.html) and pushed to that repo's `main`,
which GitHub Pages deploys directly (legacy mode, no build step). Because
there's no Gmail-safe-width constraint anymore, this renders at 820px and
uses a card grid for Top N instead of a numbered list, per daily-news's
STYLE.md — read that file in the daily-news checkout before changing
anything here, it's the actual spec this script implements.

Usage:
    python3 scripts/render_daily_news.py payload.json --output 2026-11-15.html
    python3 scripts/render_daily_news.py payload.json --images images.json -o out.html

`--images` is an optional JSON file mapping an item's `link` to a verified
https image URL (see fetch_article_images.py) — merged into each card if
present. Never invent an image URL by hand; only pass a map that script (or
equivalent verification) produced.
"""

import argparse
import html
import json
import re
import sys

FONT_SANS = "-apple-system,BlinkMacSystemFont,'PingFang TC','Microsoft JhengHei','Noto Sans TC',Helvetica,Arial,sans-serif"
FONT_SERIF = "Georgia,'Noto Serif TC',serif"
FONT_MONO = "ui-monospace,SFMono-Regular,Consolas,monospace"

PAPER_BG = "#f2f0ea"
CARD_BG = "#fffdf9"
INK = "#1c1b19"
SOFT_INK = "#6b6459"
BODY_TEXT = "#374151"
HAIRLINE = "#ddd8cc"
GOLD = "#9c6b12"
GOLD_DEEP = "#7a5209"
TECH_COMPARISON_BG = "#f6ecd9"
COMMENTARY_BG = "#f5f3ff"
COMMENTARY_LABEL = "#5b21b6"
BONUS_BG = "#f7f5ef"

STAMP_COLOR_ROTATION = ["#b3402f", "#2c5f7c", "#5b4a8a", "#5c6b3f", "#8a6d1f"]

MAX_WIDTH = "820px"


def esc(s):
    return html.escape(s or "", quote=False)


def stamp_color_for(index):
    return STAMP_COLOR_ROTATION[index % len(STAMP_COLOR_ROTATION)]


def render_masthead(data):
    lines = "<br>".join(data["meta_lines"])
    return f'''<div style="padding:30px 30px 20px 30px;border-bottom:3px double {INK};background-color:{CARD_BG}">
  <div style="font-family:{FONT_MONO};font-size:11px;letter-spacing:2px;color:{SOFT_INK};text-transform:uppercase;margin-bottom:10px">{esc(data["eyebrow"])}</div>
  <div style="font-family:{FONT_SERIF};font-size:30px;font-weight:700;color:{INK};line-height:1.2">{esc(data["title"])}</div>
  <div style="font-family:{FONT_MONO};font-size:12px;color:{SOFT_INK};margin-top:12px;line-height:1.8">
    {lines}
  </div>
</div>'''


def render_excluded_box(text):
    if not text:
        return ""
    return f'''<div style="border:1px solid {HAIRLINE};border-radius:6px;padding:12px 16px;margin:20px 30px 0 30px;font-family:{FONT_SANS};font-size:12px;color:{SOFT_INK};line-height:1.8;background-color:{CARD_BG}">
  <strong style="color:{INK}">已排除內容：</strong>{esc(text)}
</div>'''


def render_failed_feeds(failed_feeds):
    if not failed_feeds:
        return ""
    lines = "<br>\n  ".join(
        f'・{esc(f["name"])}：{esc(f["reason"])}' for f in failed_feeds
    )
    return f'''<div style="border:1px solid {HAIRLINE};border-radius:6px;padding:12px 16px;margin:14px 30px 0 30px;font-family:{FONT_SANS};font-size:12px;color:{SOFT_INK};line-height:1.8;background-color:{CARD_BG}">
  ⚠️ <strong>本次共有 {len(failed_feeds)} 個來源抓取失敗</strong>，其文章數為 0 不代表「今天沒新聞」，而是抓取本身失敗：<br>
  {lines}
</div>'''


BRACKET_PREFIX_RE = re.compile(r"^【[^】]+】")


def _source_label(item):
    """Pull a display source name for the '[date] · 來源名' line.

    Prefers an explicit `source` field; falls back to stripping a
    '【Source】' bracket the orchestrator may already have put in the title.
    """
    if item.get("source"):
        return item["source"]
    m = BRACKET_PREFIX_RE.match(item.get("title", ""))
    return m.group(0)[1:-1] if m else None


def render_tech_comparison(tc):
    if not tc:
        return ""
    return f'''<div style="background-color:{TECH_COMPARISON_BG};border-left:3px solid {GOLD};border-radius:0 6px 6px 0;padding:10px 14px;margin:8px 0 4px;font-family:{FONT_SANS};font-size:12.5px;color:{BODY_TEXT};line-height:1.8">
        <strong style="color:{GOLD_DEEP}">新舊比較：</strong>
        <strong>先前：</strong>{esc(tc["before"])}　<strong>新在哪：</strong>{esc(tc["new"])}　<strong>解決了什麼：</strong>{esc(tc["benefit"])}
      </div>'''


def render_card(item, stamp, idx, images):
    link = item["link"]
    title = item["title"]
    if not BRACKET_PREFIX_RE.match(title):
        src = _source_label(item)
        if src:
            title = f"【{src}】{title}"
    title = esc(title)

    src_label = _source_label(item)
    date_line = f"[{item['date']}]"
    if src_label:
        date_line += f" · {esc(src_label)}"

    obj = item.get("objective_metric")
    obj_html = (
        f'<div style="font-family:{FONT_MONO};font-size:11.5px;color:{GOLD};margin:2px 0 4px">{esc(obj)}</div>'
        if obj else ""
    )

    img_url = (images or {}).get(link)
    img_html = ""
    if img_url and img_url.startswith("https://"):
        img_html = (
            f'<a href="{link}"><img src="{img_url}" alt="{title}" loading="lazy" '
            f'style="display:block;width:100%;height:150px;object-fit:cover;'
            f'border-bottom:1px solid {HAIRLINE};background-color:{BONUS_BG}"></a>\n    '
        )

    tc_html = render_tech_comparison(item.get("tech_comparison"))

    return f'''  <div style="border:1px solid {HAIRLINE};border-radius:6px;background-color:{CARD_BG};overflow:hidden;display:flex;flex-direction:column">
    {img_html}<div style="padding:12px 14px">
      <div style="font-family:{FONT_SANS};font-size:14px;line-height:1.6;margin:0 0 3px">
        <span style="font-family:{FONT_MONO};font-size:12.5px;color:{stamp};margin-right:6px;font-weight:700">{idx}.</span>
        <a href="{link}" style="color:{INK};text-decoration:underline">{title}</a>
      </div>
      <div style="font-family:{FONT_MONO};font-size:11px;color:{SOFT_INK};margin:0 0 4px">{date_line}</div>
      {obj_html}
      <div style="font-family:{FONT_SANS};font-size:13px;color:{BODY_TEXT};line-height:1.8">{esc(item["summary"])}</div>
      {tc_html}
    </div>
  </div>'''


DATE_PAREN_RE = re.compile(r"^（(\d{4}-\d{2}-\d{2}|無法解析發佈日期[^）]*)）\s*(.*)$")


def _normalize_bonus_note(note):
    """Accepts either '（YYYY-MM-DD）說明' or '說明（日期：YYYY-MM-DD）' and
    always renders the latter — the convention STYLE.md's skeleton uses."""
    m = DATE_PAREN_RE.match(note)
    if not m:
        return note
    date_part, rest = m.group(1), m.group(2).strip()
    suffix = "（日期：無法解析）" if "無法解析" in date_part else f"（日期：{date_part}）"
    return f"{rest} {suffix}".strip() if rest else suffix


def render_bonus_reading(bonus):
    if not bonus or not bonus.get("items"):
        return ""
    items_html = "<br>\n  ".join(
        f'・<a href="{b["link"]}" style="color:{INK};text-decoration:underline">{esc(b["title"])}</a> '
        f'<span style="color:{SOFT_INK}">— {esc(_normalize_bonus_note(b["note"]))}</span>'
        for b in bonus["items"]
    )
    return f'''<div style="background-color:{BONUS_BG};border:1px dashed {HAIRLINE};border-radius:8px;padding:12px 16px;margin:14px 0 0">
  <div style="font-family:{FONT_SANS};font-size:12.5px;color:{SOFT_INK};margin:0 0 8px">🗞️ <strong style="color:{INK}">小額外閱讀：</strong>{esc(bonus["intro"])}</div>
  <div style="font-family:{FONT_SANS};font-size:12.5px;color:{INK};line-height:1.9">
  {items_html}
  </div>
</div>'''


def render_domain(domain, index, images):
    stamp = stamp_color_for(index)
    cards = "\n".join(
        render_card(item, stamp, i + 1, images) for i, item in enumerate(domain["items"])
    )
    grid = f'''<div style="display:grid;grid-template-columns:repeat(auto-fill,minmax(250px,1fr));gap:14px;margin:12px 0 0">
{cards}
</div>'''
    commentary = f'''<div style="background-color:{COMMENTARY_BG};border-radius:10px;padding:16px 18px;margin:20px 0 18px">
  <strong style="color:{COMMENTARY_LABEL}">評語：</strong>
  <span style="color:{BODY_TEXT};font-size:13.5px;line-height:1.9;font-family:{FONT_SANS}">{esc(domain["commentary"])}</span>
</div>'''
    bonus_html = render_bonus_reading(domain.get("bonus_reading"))
    n = domain["article_count"]
    topn = len(domain["items"])
    return f'''<div style="padding:24px 30px;border-top:3px solid {stamp};background-color:{CARD_BG}">
  <table style="border-collapse:collapse;margin:0 0 10px"><tr>
    <td style="background-color:{stamp};border-radius:3px;padding:4px 10px"><span style="font-family:{FONT_MONO};font-size:11px;color:#fff;letter-spacing:0.5px">{esc(domain["name"])}</span></td>
    <td style="padding:0 0 0 10px;font-family:{FONT_MONO};font-size:12px;color:{SOFT_INK}">{n} 篇 → Top {topn}</td>
  </tr></table>
  <div style="font-family:{FONT_SERIF};font-size:14.5px;line-height:1.9;color:{INK};margin:0 0 6px">{esc(domain["summary"])}</div>
{grid}
{commentary}{bonus_html}
</div>'''


def render_tally_chart(tally):
    if not tally:
        return ""
    max_count = max(t["count"] for t in tally)
    rows = []
    for t in tally:
        pct = round(t["count"] / max_count * 100)
        rows.append(f'''    <tr>
      <td style="width:130px;padding:5px 8px;font-size:12.5px;color:{INK};white-space:nowrap;font-family:{FONT_SANS}">{esc(t["name"])}</td>
      <td style="padding:5px 8px">
        <table width="100%" style="border-collapse:collapse"><tr>
          <td style="width:{pct}%;background-color:{INK};height:11px;border-radius:2px;font-size:0;line-height:0">&nbsp;</td>
          <td style="width:{100 - pct}%;font-size:0;line-height:0">&nbsp;</td>
        </tr></table>
      </td>
      <td style="width:28px;padding:5px 8px;font-size:12.5px;color:{SOFT_INK};text-align:right;font-family:{FONT_SANS}">{t["count"]}</td>
    </tr>''')
    rows_html = "\n".join(rows)
    return f'''<div style="padding:24px 30px;border-top:1px solid {HAIRLINE};background-color:{CARD_BG}">
  <h2 style="font-family:{FONT_SERIF};font-size:19px;font-weight:700;color:{INK};margin:0 0 4px">來源統計</h2>
  <div style="font-family:{FONT_SANS};font-size:12px;color:{SOFT_INK};margin:0 0 4px">Top N + 小額外閱讀 合計（依來源分佈，非代表主要精選列表本身平均分佈）</div>
  <table width="100%" style="border-collapse:collapse;margin-top:10px">
{rows_html}
  </table>
</div>'''


def render_footer(footer_summary):
    if not footer_summary:
        return ""
    return f'<div style="padding:16px 30px;border-top:1px solid {HAIRLINE};font-family:{FONT_MONO};font-size:11px;color:{SOFT_INK};text-align:center;background-color:{CARD_BG}">{esc(footer_summary)}</div>'


def render_page(data, images, date_str):
    masthead = render_masthead(data)
    excluded = render_excluded_box(data.get("excluded_note"))
    failed = render_failed_feeds(data.get("failed_feeds"))
    domains_html = "\n".join(
        render_domain(d, i, images) for i, d in enumerate(data["domains"])
    )
    tally = render_tally_chart(data.get("source_tally"))
    footer = render_footer(data.get("footer_summary"))

    body = "\n".join(
        part for part in [masthead, excluded, failed, domains_html, tally, footer] if part
    )

    html_out = f'''<!doctype html><html lang="zh-Hant"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>Penguin 每日報報 · {date_str}</title></head><body style="margin:0;background-color:{PAPER_BG}">
<div style="padding:32px 12px;font-family:{FONT_SANS};background-color:{PAPER_BG}">
<div style="max-width:{MAX_WIDTH};margin:0 auto;background-color:{CARD_BG};border:1px solid {HAIRLINE}">
{body}
</div></div>
</body></html>'''

    _self_check(html_out)
    return html_out


def _self_check(html_out):
    assert "<style" not in html_out.lower(), "A <style> block snuck in — STYLE.md forbids it."
    assert "class=" not in html_out, "A class= attribute snuck in — everything must be inline style=."
    assert f'max-width:{MAX_WIDTH}' in html_out, "820px outer width token missing."
    assert f"background-color:{CARD_BG}" in html_out, "Card background token missing."
    assert re.search(r"<title>Penguin 每日報報 · \d{4}-\d{2}-\d{2}</title>", html_out), "Title tag missing/malformed."

    for m in re.finditer(r'style="([^"]*)"', html_out):
        style_val = m.group(1)
        color_decls = re.findall(r"(?<!-)color:", style_val)
        if len(color_decls) > 1:
            raise AssertionError(f"Duplicate color: in one style attribute: {style_val!r}")


PAYLOAD_SCHEMA_EXAMPLE = {
    "title": "Penguin 每日報報",
    "eyebrow": "RSS FEED 主題分類與摘要",
    "meta_lines": [
        "2026-08-18（二）台北時間 09:17 發行　·　統計區間：過去 24 小時（約自 2026-08-17 09:00 起算）",
        "分類依實際內容動態分群，非固定 7 類標籤；Top N 依各領域文章量比例分配；有客觀熱度數據時優先採用",
        "Hacker News 排名為 <strong style=\"color:#1c1b19\">2026-08-18 09:04 台北時間（01:04 UTC）</strong> 當下快照",
    ],
    "excluded_note": "訂閱來源「r18」明確標示為成人內容，依規定排除於分類與摘要之外。",
    "failed_feeds": [{"name": "r18", "reason": "HTTP 404 Not Found"}],
    "domains": [
        {
            "name": "科技與軟體工程",
            "article_count": 234,
            "is_technology": True,
            "summary": "今天的重點是……",
            "items": [
                {
                    "title": "文章標題",
                    "source": "來源名（用於卡片的「[日期] · 來源名」行；省略則嘗試從標題的【】前綴推斷）",
                    "link": "https://example.com/article",
                    "date": "2026-08-17",
                    "summary": "2-3 句具體摘要。",
                    "objective_metric": "依 Hacker News 熱度：74讚/28留言排序",
                    "tech_comparison": {
                        "before": "先前做法",
                        "new": "新在哪裡",
                        "benefit": "解決了什麼問題",
                    },
                }
            ],
            "commentary": "今天新聞內容本身的觀察。",
            "bonus_reading": {
                "intro": "以下文章未進入 Top N，但為呈現來源完整報導樣貌一併收錄。",
                "items": [
                    {"title": "次要文章", "link": "https://example.com/b", "note": "湊足保底（日期：2026-08-10）"}
                ],
            },
        }
    ],
    "source_tally": [{"name": "Hacker News", "count": 6}, {"name": "TechNews", "count": 4}],
    "footer_summary": "Penguin 每日報報 · 共 632 篇文章 · 4 個領域 · 已排除 1 個成人內容來源 · 5 個來源抓取失敗",
}


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("payload", nargs="?", help="Path to the digest JSON payload (same shape as render_email.py's)")
    parser.add_argument("--output", "-o", help="Write HTML here instead of stdout")
    parser.add_argument("--date", help="YYYY-MM-DD for the <title> tag; defaults to the first meta_lines entry's leading date, else today")
    parser.add_argument("--images", help="JSON file mapping item link -> verified https image URL (see fetch_article_images.py)")
    parser.add_argument("--print-schema", action="store_true", help="Print an example payload JSON and exit")
    args = parser.parse_args()

    if args.print_schema or not args.payload:
        json.dump(PAYLOAD_SCHEMA_EXAMPLE, sys.stdout, ensure_ascii=False, indent=2)
        sys.stdout.write("\n")
        if not args.payload:
            sys.exit(0 if args.print_schema else 2)
        return

    with open(args.payload, encoding="utf-8") as f:
        data = json.load(f)

    images = {}
    if args.images:
        with open(args.images, encoding="utf-8") as f:
            images = json.load(f)

    date_str = args.date
    if not date_str:
        m = re.match(r"(\d{4}-\d{2}-\d{2})", data.get("meta_lines", [""])[0])
        date_str = m.group(1) if m else "0000-00-00"

    out = render_page(data, images, date_str)

    if args.output:
        with open(args.output, "w", encoding="utf-8") as f:
            f.write(out)
    else:
        sys.stdout.write(out)


if __name__ == "__main__":
    main()
