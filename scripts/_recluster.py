import json

d = json.load(open('/tmp/rss_parsed.json'))
all_arts_today = []
all_arts_other = []
for c in d['domains'].values():
    all_arts_today.extend(c['todays_articles'])
    all_arts_other.extend(c['other_articles'])

SOURCE_TO_DOMAIN = {
    'Hacker News Front Page': '科技與軟體工程',
    "The latest from GitHub's engineering team - The GitHub Blog": '科技與軟體工程',
    'GitHub All Languages Daily Trending': '科技與軟體工程',
    'GitHub All Languages Weekly Trending': '科技與軟體工程',
    'Julia Evans': '科技與軟體工程',
    ' The Cloudflare Blog ': '科技與軟體工程',
    'Changelog': '科技與軟體工程',
    'OMG! Ubuntu!': '科技與軟體工程',
    'Sysprogs': '科技與軟體工程',
    'Cool3c': '科技與軟體工程',
    '電獺少女': '科技與軟體工程',
    'Engineering at Meta': '科技與軟體工程',
    'Netflix TechBlog': '科技與軟體工程',
    'AWS Architecture Blog': '科技與軟體工程',
    'Slack Engineering': '科技與軟體工程',
    'Stripe Blog': '科技與軟體工程',
    'The Pragmatic Engineer': '科技與軟體工程',
    '科技爱好者周刊': '科技與軟體工程',

    '商業週刊+': '財經商業與生活時事',
    '天下雜誌': '財經商業與生活時事',

    'Google News': '國際時事與社會新聞',
    'TechNews': '國際時事與社會新聞',

    'GQ': '時尚娛樂與影劇',
    'Vogue Taiwan': '時尚娛樂與影劇',
    'COOL-STYLE 潮流生活網': '時尚娛樂與影劇',
    'Deadline': '時尚娛樂與影劇',

    '巴哈姆特': '遊戲動漫與數位社群',
    '宅宅新聞': '遊戲動漫與數位社群',
    'Discord Blog': '遊戲動漫與數位社群',
}

EXCLUDE_SOURCES = {'r18'}

new_domains = {}
excluded_count = 0
unmapped = set()

for art in all_arts_today + all_arts_other:
    src = art.get('source_title', '?')
    if src in EXCLUDE_SOURCES:
        excluded_count += 1
        continue
    dom = SOURCE_TO_DOMAIN.get(src)
    if dom is None:
        unmapped.add(src)
        dom = '其他'
    new_domains.setdefault(dom, {'todays_articles': [], 'other_articles': []})

for art in all_arts_today:
    src = art.get('source_title', '?')
    if src in EXCLUDE_SOURCES:
        continue
    dom = SOURCE_TO_DOMAIN.get(src, '其他')
    new_domains[dom]['todays_articles'].append(art)

for art in all_arts_other:
    src = art.get('source_title', '?')
    if src in EXCLUDE_SOURCES:
        continue
    dom = SOURCE_TO_DOMAIN.get(src, '其他')
    new_domains[dom]['other_articles'].append(art)

out = {'domains': new_domains, 'failed_feeds': d.get('failed_feeds', [])}
json.dump(out, open('/tmp/rss_reclustered.json', 'w'), ensure_ascii=False)

print('excluded (adult content, r18):', excluded_count)
print('unmapped sources:', unmapped)
for dom, c in new_domains.items():
    print(dom, 'today=', len(c['todays_articles']), 'other=', len(c['other_articles']), 'total=', len(c['todays_articles'])+len(c['other_articles']))
