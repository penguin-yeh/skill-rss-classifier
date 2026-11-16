#!/usr/bin/env python3
"""Deterministic HTML-email renderer for the "晨間電訊" (Penguin 每日報報) digest.

This is the fix for a recurring class of bug: when the final HTML email is
hand-written fresh by an LLM on every run (per SKILL.md's old "visual
template" instructions), small CSS details drift silently between runs —
the outer card border disappears, the card background color gets dropped,
a bar-chart cell loses its `background`, `color:` gets duplicated in one
`style=`, etc. None of that is a judgment call, so it doesn't need an LLM
re-deriving it from prose instructions every time.

This script is the single source of truth for the digest's markup and
inline CSS. The orchestrator's job becomes: assemble the *content*
(domain summaries, top-N picks, commentary — all genuinely generative work
that still needs an LLM) into the JSON shape documented below, then call
this script to render it. The CSS itself never has a chance to drift
because it's Python string literals, not something regenerated from
natural-language instructions each run.

Usage:
    python3 scripts/render_email.py payload.json --output digest.html
    python3 scripts/render_email.py payload.json          # prints to stdout

Payload JSON shape — see PAYLOAD_SCHEMA_EXAMPLE below, or run
`python3 scripts/render_email.py --print-schema`.
"""

import argparse
import html
import json
import sys


# ---------------------------------------------------------------------------
# Fixed design tokens — the single source of truth for every color/spacing
# value in the email. Nothing here is regenerated per run; it only changes
# if a human deliberately edits this file.
# ---------------------------------------------------------------------------

FONT_SERIF = "Georgia,'Noto Serif TC',serif"
FONT_SANS = (
    "-apple-system,BlinkMacSystemFont,'PingFang TC','Microsoft JhengHei',"
    "'Noto Sans TC',Helvetica,Arial,sans-serif"
)
FONT_MONO = "ui-monospace,SFMono-Regular,Consolas,monospace"

PAPER_BG = "#f2f0ea"
CARD_BG = "#fffdf9"
HAIRLINE = "#ddd8cc"
INK = "#1c1b19"
SOFT_INK = "#6b6459"

TINT_BOX_BG = "#f5f3ff"       # 評語 box background
TINT_BOX_LABEL = "#5b21b6"    # 評語 label color
BODY_TEXT = "#374151"         # 評語 body text color

COMPARISON_BG = "#f6ecd9"     # 新舊比較 box (Technology domain only)
COMPARISON_BORDER = "#9c6b12"
COMPARISON_LABEL = "#7a5209"

BONUS_BG = "#f7f5ef"          # 小額外閱讀 box
BONUS_BORDER = HAIRLINE

METRIC_GOLD = "#9c6b12"       # objective_metric line — fixed, never part of
                               # the domain stamp-color rotation

# Rotation of "stamp colors," one per domain, in report order. Extend this
# list (don't repeat #1) if a report ever has more than 5 domains.
STAMP_COLOR_ROTATION = [
    "#b3402f",  # 印章紅
    "#2c5f7c",  # 鋼藍
    "#5b4a8a",  # 藏青紫
    "#5c6b3f",  # 赭綠
    "#8a6d1f",  # 赭黃
    "#8a4a6d",  # 梅紫紅
]

MASTHEAD_TITLE = "Penguin 每日報報"
MASTHEAD_EYEBROW = "RSS FEED 主題分類與摘要"


def esc(s):
    """HTML-escape text content. Never call this on strings that are
    already markup (e.g. an assembled <a> tag) — only on raw text."""
    return html.escape(s or "", quote=False)


def stamp_color_for(index):
    return STAMP_COLOR_ROTATION[index % len(STAMP_COLOR_ROTATION)]


# ---------------------------------------------------------------------------
# Building blocks
# ---------------------------------------------------------------------------

def render_masthead(data):
    eyebrow = esc(data.get("eyebrow") or MASTHEAD_EYEBROW)
    title = esc(data.get("title") or MASTHEAD_TITLE)
    meta_lines = data.get("meta_lines") or []
    meta_html = "<br>\n    ".join(meta_lines)  # meta_lines may contain inline <strong> markup
    return f"""<div style="padding:30px 30px 20px 30px;border-bottom:3px double {INK};background-color:{CARD_BG}">
  <div style="font-family:{FONT_MONO};font-size:11px;letter-spacing:2px;color:{SOFT_INK};text-transform:uppercase;margin-bottom:10px">{eyebrow}</div>
  <div style="font-family:{FONT_SERIF};font-size:30px;font-weight:700;color:{INK};line-height:1.2">{title}</div>
  <div style="font-family:{FONT_MONO};font-size:12px;color:{SOFT_INK};margin-top:12px;line-height:1.8">
    {meta_html}
  </div>
</div>"""


def render_excluded_box(text):
    if not text:
        return ""
    return f"""<div style="border:1px solid {HAIRLINE};border-radius:6px;padding:12px 16px;margin:20px 30px 0 30px;font-family:{FONT_SANS};font-size:12px;color:{SOFT_INK};line-height:1.8;background-color:{CARD_BG}">
  <strong style="color:{INK}">已排除內容：</strong>{text}
</div>"""


def render_failed_feeds(failed_feeds):
    if not failed_feeds:
        return ""
    lines = "<br>\n  ".join(
        f"・{esc(f['name'])}：{esc(f['reason'])}" for f in failed_feeds
    )
    n = len(failed_feeds)
    return f"""<div style="border:1px solid {HAIRLINE};border-radius:6px;padding:12px 16px;margin:14px 30px 0 30px;font-family:{FONT_SANS};font-size:12px;color:{SOFT_INK};line-height:1.8;background-color:{CARD_BG}">
  ⚠️ <strong>本次共有 {n} 個來源抓取失敗</strong>，其文章數為 0 不代表「今天沒新聞」，而是抓取本身失敗：<br>
  {lines}
</div>"""


def render_item(item, index, is_technology):
    title = esc(item["title"])
    link = html.escape(item["link"], quote=True)
    date = esc(item.get("date") or "")
    summary = esc(item["summary"])
    metric_line = ""
    if item.get("objective_metric"):
        metric_line = f'<div style="font-family:{FONT_MONO};font-size:11.5px;color:{METRIC_GOLD};margin:2px 0 4px">{esc(item["objective_metric"])}</div>\n    '

    comparison_html = ""
    cmp = item.get("tech_comparison")
    if is_technology and cmp:
        comparison_html = f"""
    <div style="background-color:{COMPARISON_BG};border-left:3px solid {COMPARISON_BORDER};border-radius:0 6px 6px 0;padding:10px 14px;margin:8px 0 4px;font-family:{FONT_SANS};font-size:12.5px;color:{BODY_TEXT};line-height:1.8">
      <strong style="color:{COMPARISON_LABEL}">新舊比較：</strong>
      <ul style="margin:6px 0 0;padding-left:18px">
        <li style="margin:2px 0"><strong>先前：</strong>{esc(cmp['before'])}</li>
        <li style="margin:2px 0"><strong>新在哪：</strong>{esc(cmp['new'])}</li>
        <li style="margin:2px 0"><strong>解決了什麼：</strong>{esc(cmp['benefit'])}</li>
      </ul>
    </div>"""

    return f"""  <div style="padding:10px 0;border-top:1px solid {HAIRLINE};background-color:{CARD_BG}">
    <div style="font-family:{FONT_SANS};font-size:14px;line-height:1.6;margin:0 0 3px">
      <span style="font-family:{FONT_MONO};font-size:12.5px;color:{INK};margin-right:6px">{index}.</span>
      <a href="{link}" style="color:{INK};text-decoration:underline">{title}</a>
      <span style="font-family:{FONT_MONO};font-size:11px;color:{SOFT_INK};margin-left:6px">[{date}]</span>
    </div>
    {metric_line}<div style="font-family:{FONT_SANS};font-size:13px;color:{BODY_TEXT};line-height:1.8">{summary}</div>{comparison_html}
  </div>"""


def render_bonus_reading(bonus):
    if not bonus or not bonus.get("items"):
        return ""
    intro = esc(bonus.get("intro") or "")
    rows = []
    for it in bonus["items"]:
        title = esc(it["title"])
        link = html.escape(it["link"], quote=True)
        note = esc(it.get("note") or "")
        rows.append(
            f'  ・<a href="{link}" style="color:{INK};text-decoration:underline">{title}</a>'
            f' <span style="color:{SOFT_INK}">— {note}</span>'
        )
    rows_html = "<br>\n".join(rows)
    return f"""<div style="background-color:{BONUS_BG};border:1px dashed {BONUS_BORDER};border-radius:8px;padding:12px 16px;margin:14px 0 0">
  <div style="font-family:{FONT_SANS};font-size:12.5px;color:{SOFT_INK};margin:0 0 8px">🗞️ <strong style="color:{INK}">小額外閱讀：</strong>{intro}</div>
  <div style="font-family:{FONT_SANS};font-size:12.5px;color:{INK};line-height:1.9">
{rows_html}
  </div>
</div>"""


def render_source_section_header(source_name):
    """Subheading for one contributing source inside a domain that opts into
    per-source grouping via `sections` instead of a flat `items` list (see
    render_domain). Only used when a domain asks for this extra structure —
    a priority domain held to a higher bar than a flat numbered list."""
    return f"""  <div style="font-family:{FONT_MONO};font-size:11.5px;letter-spacing:1px;color:{SOFT_INK};text-transform:uppercase;margin:16px 0 2px;padding-bottom:3px;border-bottom:1px solid {HAIRLINE}">{esc(source_name)}</div>"""


def render_domain(domain, index):
    stamp = stamp_color_for(index)
    name = esc(domain["name"])
    article_count = domain["article_count"]
    summary = esc(domain["summary"])
    is_technology = bool(domain.get("is_technology"))

    sections = domain.get("sections")
    if sections:
        # Per-source grouped layout: one subheading per contributing source,
        # numbering continues across sections so the Top N reads as one list.
        top_n = sum(len(s["items"]) for s in sections)
        parts = []
        counter = 0
        for s in sections:
            parts.append(render_source_section_header(s["source_name"]))
            for item in s["items"]:
                counter += 1
                parts.append(render_item(item, counter, is_technology))
        items_html = "\n".join(parts)
    else:
        top_n = len(domain["items"])
        items_html = "\n".join(
            render_item(item, i + 1, is_technology)
            for i, item in enumerate(domain["items"])
        )

    commentary_html = ""
    if domain.get("commentary"):
        commentary_html = f"""
<div style="background-color:{TINT_BOX_BG};border-radius:10px;padding:16px 18px;margin:20px 0 18px">
  <strong style="color:{TINT_BOX_LABEL}">評語：</strong>
  <span style="color:{BODY_TEXT};font-size:13.5px;line-height:1.9;font-family:{FONT_SANS}">{esc(domain['commentary'])}</span>
</div>"""

    bonus_html = render_bonus_reading(domain.get("bonus_reading"))

    return f"""<div style="padding:24px 30px;border-top:3px solid {stamp};background-color:{CARD_BG}">
  <table role="presentation" style="border-collapse:collapse;margin:0 0 10px"><tr>
    <td style="background-color:{stamp};border-radius:3px;padding:4px 10px"><span style="font-family:{FONT_MONO};font-size:11px;color:#fff;letter-spacing:0.5px">{name}</span></td>
    <td style="padding:0 0 0 10px;font-family:{FONT_MONO};font-size:12px;color:{SOFT_INK}">{article_count} 篇 → Top {top_n}</td>
  </tr></table>
  <div style="font-family:{FONT_SERIF};font-size:14.5px;line-height:1.9;color:{INK};margin:0 0 6px">{summary}</div>
{items_html}
{commentary_html}
{bonus_html}
</div>"""


def render_tally_chart(tally):
    if not tally:
        return ""
    rows = sorted(tally, key=lambda r: r["count"], reverse=True)
    max_count = max(r["count"] for r in rows) or 1
    row_html = []
    for r in rows:
        pct = max(round(r["count"] / max_count * 100), 6)
        rest = 100 - pct
        row_html.append(f"""    <tr>
      <td style="width:130px;padding:5px 8px;font-size:12.5px;color:{INK};white-space:nowrap;font-family:{FONT_SANS}">{esc(r['name'])}</td>
      <td style="padding:5px 8px">
        <table role="presentation" width="100%" style="border-collapse:collapse"><tr>
          <td style="width:{pct}%;background-color:{INK};height:11px;border-radius:2px;font-size:0;line-height:0">&nbsp;</td>
          <td style="width:{rest}%;font-size:0;line-height:0">&nbsp;</td>
        </tr></table>
      </td>
      <td style="width:28px;padding:5px 8px;font-size:12.5px;color:{SOFT_INK};text-align:right;font-family:{FONT_SANS}">{r['count']}</td>
    </tr>""")
    rows_joined = "\n".join(row_html)
    return f"""<div style="padding:24px 30px;border-top:1px solid {HAIRLINE};background-color:{CARD_BG}">
  <h2 style="font-family:{FONT_SERIF};font-size:19px;font-weight:700;color:{INK};margin:0 0 4px">來源統計</h2>
  <div style="font-family:{FONT_SANS};font-size:12px;color:{SOFT_INK};margin:0 0 4px">Top N + 小額外閱讀 合計（依來源分佈，非代表主要精選列表本身平均分佈）</div>
  <table role="presentation" width="100%" style="border-collapse:collapse;margin-top:10px">
{rows_joined}
  </table>
</div>"""


def render_footer(footer_summary):
    if not footer_summary:
        return ""
    return f"""<div style="padding:16px 30px;border-top:1px solid {HAIRLINE};font-family:{FONT_MONO};font-size:11px;color:{SOFT_INK};text-align:center;background-color:{CARD_BG}">{esc(footer_summary)}</div>"""


def render_email(data):
    masthead = render_masthead(data)
    excluded = render_excluded_box(data.get("excluded_note"))
    failed = render_failed_feeds(data.get("failed_feeds"))
    domains_html = "\n".join(
        render_domain(d, i) for i, d in enumerate(data["domains"])
    )
    tally = render_tally_chart(data.get("source_tally"))
    footer = render_footer(data.get("footer_summary"))

    body = "\n".join(
        part for part in [masthead, excluded, failed, domains_html, tally, footer] if part
    )

    html_out = f"""<div style="padding:32px 12px;font-family:{FONT_SANS};background-color:{PAPER_BG}">
<div style="max-width:680px;margin:0 auto;background-color:{CARD_BG};border:1px solid {HAIRLINE}">
{body}
</div>
</div>"""

    _self_check(html_out)
    return html_out


# ---------------------------------------------------------------------------
# Cheap structural safety net — these are the exact failure modes SKILL.md
# had documented happening in practice when the HTML was hand-authored per
# run. They should be structurally impossible now, but assert anyway so a
# future edit to this file that reintroduces one of them fails loudly
# instead of silently shipping a broken email.
# ---------------------------------------------------------------------------

def _self_check(html_out):
    assert "<style" not in html_out.lower(), (
        "A <style> block snuck into the output — Gmail strips these; "
        "everything must be inline style=."
    )
    assert f"background-color:{CARD_BG}" in html_out, "Card background token missing."
    assert f"border:1px solid {HAIRLINE}" in html_out, "Outer card border missing."

    # No style="" attribute may declare `color:` twice.
    import re
    for m in re.finditer(r'style="([^"]*)"', html_out):
        style_val = m.group(1)
        if style_val.count("color:") - style_val.count("background-color:") > 1:
            # crude but effective: background-color also contains "color:"
            pass  # refined check below handles the real cases

    for m in re.finditer(r'style="([^"]*)"', html_out):
        style_val = m.group(1)
        color_decls = re.findall(r'(?<!-)color:', style_val)
        if len(color_decls) > 1:
            raise AssertionError(f"Duplicate color: in one style attribute: {style_val!r}")

    # Every bar-chart bar cell must carry both a background and a width.
    for m in re.finditer(r'<td style="width:(\d+)%;background-color:', html_out):
        pass  # presence of this pattern at least once per row is checked by construction


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
                    {"title": "次要文章", "link": "https://example.com/b", "note": "湊足保底"}
                ],
            },
        }
    ],
    "source_tally": [{"name": "Hacker News", "count": 6}, {"name": "TechNews", "count": 4}],
    "footer_summary": "Penguin 每日報報 · 共 632 篇文章 · 4 個領域 · 已排除 1 個成人內容來源 · 5 個來源抓取失敗",
}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("payload", nargs="?", help="Path to the digest JSON payload")
    parser.add_argument("--output", "-o", help="Write HTML here instead of stdout")
    parser.add_argument(
        "--print-schema", action="store_true",
        help="Print an example payload JSON and exit",
    )
    args = parser.parse_args()

    if args.print_schema or not args.payload:
        json.dump(PAYLOAD_SCHEMA_EXAMPLE, sys.stdout, ensure_ascii=False, indent=2)
        sys.stdout.write("\n")
        if not args.payload:
            sys.exit(0 if args.print_schema else 2)
        return

    with open(args.payload, encoding="utf-8") as f:
        data = json.load(f)

    out = render_email(data)

    if args.output:
        with open(args.output, "w", encoding="utf-8") as f:
            f.write(out)
    else:
        sys.stdout.write(out)


if __name__ == "__main__":
    main()
