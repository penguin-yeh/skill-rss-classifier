import json, re, glob, sys, urllib.request, urllib.parse
from concurrent.futures import ThreadPoolExecutor

UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"
# usage: fetch_article_images.py PAYLOAD.json OUT_IMAGES.json  (payload dir: /tmp/domain_payloads)
PAYLOAD, OUT = (sys.argv[1:3] + ['/tmp/digest_payload.json', '/tmp/images.json'][len(sys.argv[1:3]):])[:2]
payload = json.load(open(PAYLOAD))

# link -> article (for external_link of HN)
pool = {}
for f in glob.glob('/tmp/domain_payloads/*.json'):
    p = json.load(open(f))
    for a in p.get('todays_articles', []) + p.get('other_articles_sample', []):
        if a.get('link'):
            pool[a['link']] = a

def get(url, maxb=400000):
    req = urllib.request.Request(url, headers={'User-Agent': UA, 'Accept-Language': 'en,zh-TW'})
    return urllib.request.urlopen(req, timeout=12)

def og_image(page_url):
    try:
        r = get(page_url)
        html = r.read(400000).decode('utf-8', 'ignore')
    except Exception:
        return None
    for pat in (r'<meta[^>]+property=["\']og:image["\'][^>]+content=["\']([^"\']+)',
                r'<meta[^>]+content=["\']([^"\']+)["\'][^>]+property=["\']og:image["\']',
                r'<meta[^>]+name=["\']twitter:image["\'][^>]+content=["\']([^"\']+)'):
        m = re.search(pat, html, re.I)
        if m:
            img = urllib.parse.urljoin(page_url, m.group(1).replace('&amp;', '&'))
            if img.startswith('https://'):
                try:
                    rr = get(img)
                    ct = rr.headers.get('Content-Type', '')
                    if rr.status == 200 and ct.startswith('image/'):
                        return img
                except Exception:
                    pass
    return None

jobs = {}
for d in payload['domains']:
    items = list(d.get('items') or [])
    for s in d.get('sections') or []:
        items += s['items']
    for it in items:
        link = it['link']
        a = pool.get(link, {})
        target = a.get('external_link') or link
        if 'news.google.com' in target:
            continue
        jobs[link] = target

with ThreadPoolExecutor(8) as ex:
    res = dict(zip(jobs.keys(), ex.map(og_image, jobs.values())))
images = {k: v for k, v in res.items() if v}
json.dump(images, open(OUT, 'w'), ensure_ascii=False, indent=1)
print(f'{len(images)}/{len(jobs)} verified images (Google News links skipped)')
