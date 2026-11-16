import argparse, json, glob, html, re, sys

# usage: render_daily_news.py PAYLOAD.json --images IMAGES.json --date YYYY-MM-DD --output FILE.html (per daily-news/STYLE.md)
ap = argparse.ArgumentParser()
ap.add_argument('payload')
ap.add_argument('--images', default='/tmp/images.json')
ap.add_argument('--date', required=True)
ap.add_argument('--output', required=True)
args = ap.parse_args()
DATE = args.date
payload = json.load(open(args.payload))
images = json.load(open(args.images))
esc = lambda s: html.escape(s or '', quote=True)

def linkify(text):
    # 摘要內的 http(s) 網址（如「原文出處：…」）轉成可點的連結
    out, last = [], 0
    for m in re.finditer(r'https?://[^\s<>"\u3000-\u303f\uff00-\uffef，。、）)]+', text or ''):
        url = m.group(0).rstrip('.,;:')
        out.append(esc(text[last:m.start()]))
        out.append(f'<a href="{esc(url)}" style="color:#1c1b19;text-decoration:underline">{esc(url)}</a>')
        last = m.start() + len(url)
    out.append(esc(text[last:]))
    return ''.join(out)

by_link_src = {}
for f in glob.glob('/tmp/domain_payloads/*.json'):
    p = json.load(open(f))
    for a in p.get('todays_articles', []) + p.get('other_articles_sample', []):
        if a.get('link'):
            by_link_src[a['link']] = (a.get('source_title') or '').strip()

SANS = "-apple-system,BlinkMacSystemFont,'PingFang TC','Microsoft JhengHei','Noto Sans TC',Helvetica,Arial,sans-serif"
SERIF = "Georgia,'Noto Serif TC',serif"
MONO = "ui-monospace,SFMono-Regular,Consolas,monospace"
STAMPS = ['#b3402f', '#2c5f7c', '#5b4a8a', '#5c6b3f', '#8a6d1f']

def card(it, n, color, tech):
    link = it['link']
    src = by_link_src.get(link, '')
    out = ['  <div style="border:1px solid #ddd8cc;border-radius:6px;background-color:#fffdf9;overflow:hidden;display:flex;flex-direction:column">']
    if link in images:
        out.append(f'    <a href="{esc(link)}"><img src="{esc(images[link])}" alt="{esc(it["title"])}" loading="lazy" style="display:block;width:100%;height:150px;object-fit:cover;border-bottom:1px solid #ddd8cc;background-color:#f7f5ef"></a>')
    out.append('    <div style="padding:12px 14px">')
    out.append(f'      <div style="font-family:{SANS};font-size:14px;line-height:1.6;margin:0 0 3px"><span style="font-family:{MONO};font-size:12.5px;color:{color};margin-right:6px;font-weight:700">{n}.</span><a href="{esc(link)}" style="color:#1c1b19;text-decoration:underline">【{esc(src)}】{esc(it["title"])}</a></div>')
    out.append(f'      <div style="font-family:{MONO};font-size:11px;color:#6b6459;margin:0 0 4px">[{esc(it.get("date",""))}] · {esc(src)}</div>')
    if it.get('objective_metric'):
        out.append(f'      <div style="font-family:{MONO};font-size:11.5px;color:#9c6b12;margin:2px 0 4px">{esc(it["objective_metric"])}</div>')
    out.append(f'      <div style="font-family:{SANS};font-size:13px;color:#374151;line-height:1.8">{linkify(it["summary"])}</div>')
    c = it.get('tech_comparison')
    if c:
        out.append(f'      <div style="background-color:#f6ecd9;border-left:3px solid #9c6b12;border-radius:0 6px 6px 0;padding:10px 14px;margin:8px 0 4px;font-family:{SANS};font-size:12.5px;color:#374151;line-height:1.8"><strong style="color:#7a5209">新舊比較：</strong><strong>先前：</strong>{esc(c["before"])}　<strong>新在哪：</strong>{esc(c["new"])}　<strong>解決了什麼：</strong>{esc(c["benefit"])}</div>')
    out.append('    </div>\n  </div>')
    return '\n'.join(out)

def domain_html(d, idx):
    color = STAMPS[idx % len(STAMPS)]
    items = list(d.get('items') or [])
    for s in d.get('sections') or []:
        items += s['items']
    top_n = len(items)
    cards = '\n'.join(card(it, i + 1, color, d['is_technology']) for i, it in enumerate(items))
    h = [f'<div style="padding:24px 30px;border-top:3px solid {color};background-color:#fffdf9">',
         f'  <table style="border-collapse:collapse;margin:0 0 10px"><tr><td style="background-color:{color};border-radius:3px;padding:4px 10px"><span style="font-family:{MONO};font-size:11px;color:#fff;letter-spacing:0.5px">{esc(d["name"])}</span></td><td style="padding:0 0 0 10px;font-family:{MONO};font-size:12px;color:#6b6459">{d["article_count"]} 篇 → Top {top_n}</td></tr></table>',
         f'  <div style="font-family:{SERIF};font-size:14.5px;line-height:1.9;color:#1c1b19;margin:0 0 6px">{esc(d["summary"])}</div>',
         f'<div style="display:grid;grid-template-columns:repeat(auto-fill,minmax(250px,1fr));gap:14px;margin:12px 0 0">\n{cards}\n</div>',
         f'<div style="background-color:#f5f3ff;border-radius:10px;padding:16px 18px;margin:20px 0 18px"><strong style="color:#5b21b6">評語：</strong><span style="color:#374151;font-size:13.5px;line-height:1.9;font-family:{SANS}">{esc(d["commentary"])}</span></div>']
    b = d.get('bonus_reading')
    if b and b.get('items'):
        rows = ''.join(f'  ・<a href="{esc(x["link"])}" style="color:#1c1b19;text-decoration:underline">{esc(x["title"])}</a> <span style="color:#6b6459">— {esc(x.get("note",""))}</span><br>\n' for x in b['items'])
        h.append(f'<div style="background-color:#f7f5ef;border:1px dashed #ddd8cc;border-radius:8px;padding:12px 16px;margin:14px 0 0"><div style="font-family:{SANS};font-size:12.5px;color:#6b6459;margin:0 0 8px">🗞️ <strong style="color:#1c1b19">小額外閱讀：</strong>{esc(b.get("intro",""))}</div><div style="font-family:{SANS};font-size:12.5px;color:#1c1b19;line-height:1.9">\n{rows}</div></div>')
    h.append('</div>')
    return '\n'.join(h)

def box(inner, first):
    mt = '20px' if first else '14px'
    return f'<div style="border:1px solid #ddd8cc;border-radius:6px;padding:12px 16px;margin:{mt} 30px 0 30px;font-family:{SANS};font-size:12px;color:#6b6459;line-height:1.8;background-color:#fffdf9">{inner}</div>'

meta = payload['meta_lines']
META2 = meta[2].replace('<strong>', '<strong style="color:#1c1b19">')
body = [
 f'<div style="padding:32px 12px;font-family:{SANS};background-color:#f2f0ea">',
 '<div style="max-width:820px;margin:0 auto;background-color:#fffdf9;border:1px solid #ddd8cc">',
 f'<div style="padding:30px 30px 20px 30px;border-bottom:3px double #1c1b19;background-color:#fffdf9"><div style="font-family:{MONO};font-size:11px;letter-spacing:2px;color:#6b6459;text-transform:uppercase;margin-bottom:10px">RSS FEED 主題分類與摘要</div><div style="font-family:{SERIF};font-size:30px;font-weight:700;color:#1c1b19;line-height:1.2">Penguin 每日報報</div><div style="font-family:{MONO};font-size:12px;color:#6b6459;margin-top:12px;line-height:1.8">{meta[0]}<br>{meta[1]}<br>{META2}</div></div>',
 box(f'<strong style="color:#1c1b19">已排除內容：</strong>{esc(payload["excluded_note"])}', True),
 box(f'⚠️ <strong style="color:#1c1b19">本次共有 {len(payload["failed_feeds"])} 個來源抓取失敗</strong>，其文章數為 0 不代表「今天沒新聞」，而是抓取本身失敗：<br>' + '<br>'.join(f'・{esc(f["name"])}：{esc(f["reason"])}' for f in payload['failed_feeds']), False),
]
for i, d in enumerate(payload['domains']):
    body.append(domain_html(d, i))

tally = payload['source_tally']
mx = max(t['count'] for t in tally)
rows = []
for t in tally:
    pct = round(t['count'] / mx * 100)
    rows.append(f'<tr><td style="width:130px;padding:5px 8px;font-size:12.5px;color:#1c1b19;white-space:nowrap;font-family:{SANS}">{esc(t["name"])}</td><td style="padding:5px 8px"><table width="100%" style="border-collapse:collapse"><tr><td style="width:{pct}%;background-color:#1c1b19;height:11px;border-radius:2px;font-size:0;line-height:0">&nbsp;</td><td style="width:{100-pct}%;font-size:0;line-height:0">&nbsp;</td></tr></table></td><td style="width:28px;padding:5px 8px;font-size:12.5px;color:#6b6459;text-align:right;font-family:{SANS}">{t["count"]}</td></tr>')
body.append(f'<div style="padding:24px 30px;border-top:1px solid #ddd8cc;background-color:#fffdf9"><h2 style="font-family:{SERIF};font-size:19px;font-weight:700;color:#1c1b19;margin:0 0 4px">來源統計</h2><div style="font-family:{SANS};font-size:12px;color:#6b6459;margin:0 0 4px">Top N + 小額外閱讀 合計（依來源分佈，非代表主要精選列表本身平均分佈）</div><table width="100%" style="border-collapse:collapse;margin-top:10px">{"".join(rows)}</table></div>')
body.append(f'<div style="padding:16px 30px;border-top:1px solid #ddd8cc;font-family:{MONO};font-size:11px;color:#6b6459;text-align:center;background-color:#fffdf9">{esc(payload["footer_summary"])}</div>')
body.append('</div></div>')

doc = ('<!DOCTYPE html>\n<html lang="zh-Hant"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">'
       f'<title>Penguin 每日報報 · {DATE}</title></head><body style="margin:0;background-color:#f2f0ea">\n' + '\n'.join(body) + '\n</body></html>\n')
assert '<style' not in doc
open(args.output, 'w', encoding='utf-8').write(doc)
print('wrote', args.output, len(doc), 'bytes; cards with images:', doc.count('<img '))
