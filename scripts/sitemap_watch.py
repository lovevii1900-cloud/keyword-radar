#!/usr/bin/env python3
"""
Sitemap 盯梢 — 哥飞方法自动化
《找不到新词？用 Sitemap 盯住同行最近更新的页面》（2026-10-18）

核心：监控一批高频上新页面的同行 AI 工具站的 sitemap，
两次抓取做 diff，只看新出现的工具页 URL，从 slug 提取候选词。

- 站点清单：scripts/sitemap_sites.json（8 个已验证 sitemap 可达的 AI 工具目录站）
- 基线：scripts/sitemap_baseline.json（domain → [url]）
- 首次运行只建基线，不产出候选词（避免 flooding）
- 供 daily_update.py 调用：fetch_sitemap_watch() -> [(term, info)]
  info: {spotted_on, url, first_seen}
只读采集，站点间 sleep 2s。
"""
import json
import os
import re
import time
import html
from datetime import datetime, timezone, timedelta
from urllib.request import Request, urlopen
from urllib.error import URLError, HTTPError

HERE = os.path.dirname(os.path.abspath(__file__))
SITES_PATH = os.path.join(HERE, 'sitemap_sites.json')
BASELINE_PATH = os.path.join(HERE, 'sitemap_baseline.json')

UA = {'User-Agent': 'keyword-radar/1.0 (+sitemap-watch)'}
BJ = timezone(timedelta(hours=8))

ADULT_HINTS = [
    'eros', 'porn', 'hentai', 'nsfw', 'uncensored', 'adult',
    'sexy', 'escort', 'camgirl', 'onlyfans',
]

# 跳过的 URL 类型：分页 / 标签 / 作者 / 分类 / 搜索页
SKIP_URL_HINTS = [
    '/page/', '/tag/', '/tags/', '/author/', '/category/', '/categories/',
    '/search', '?', '#', '/amp/',
]


def log(msg):
    print(f"[sitemap-watch] {msg}", flush=True)


def http_get(url, timeout=25):
    req = Request(url, headers=UA)
    with urlopen(req, timeout=timeout) as r:
        return r.read().decode('utf-8', errors='ignore')


def clean_xml(xml):
    """处理 CDATA 包裹的 loc。"""
    return xml.replace('<![CDATA[', '').replace(']]>', '')


def parse_sitemap_index(xml):
    """返回子 sitemap 的 loc 列表（去重保序，unescape &amp;）。"""
    xml = clean_xml(xml)
    locs = re.findall(r'<loc>([^<]+)</loc>', xml)
    seen, out = set(), []
    for u in locs:
        u = html.unescape(u.strip())
        if u and u not in seen:
            seen.add(u)
            out.append(u)
    return out


def parse_urlset(xml):
    """返回 [(loc, lastmod)]。"""
    xml = clean_xml(xml)
    # 按 <url> 块切分，避免 loc/lastmod 错位
    urls = []
    for m in re.finditer(r'<url>(.*?)</url>', xml, re.S):
        block = m.group(1)
        loc = re.search(r'<loc>([^<]+)</loc>', block)
        lm = re.search(r'<lastmod>([^<]+)</lastmod>', block)
        if loc:
            urls.append((html.unescape(loc.group(1).strip()),
                         lm.group(1).strip()[:10] if lm else ''))
    return urls


def is_sitemap_index(xml):
    return '<sitemapindex' in xml


def slug_to_term(slug, slug_strip):
    """slug 清洗 → 关键词 term（保留连字符格式，与现有词一致）。"""
    if slug_strip:
        slug = re.sub(slug_strip, '', slug)
    slug = slug.strip('-').lower()
    if not slug or len(slug) < 3 or len(slug) > 40:
        return None
    if re.fullmatch(r'[0-9a-f]{6,}', slug):  # 纯 hash，无意义
        return None
    if re.fullmatch(r'\d+', slug):  # 纯数字 ID
        return None
    if any(h in slug for h in ADULT_HINTS):
        return None
    if not re.fullmatch(r'[a-z0-9][a-z0-9-]*', slug):
        return None
    return slug


def fetch_site_urls(site):
    """抓取一个站点的工具页 URL 集合。返回 set(url)。"""
    domain = site['domain']
    urls = set()
    try:
        index_xml = http_get(site['index_url'])
    except Exception as e:
        log(f"{domain}: index fetch failed: {type(e).__name__}")
        return urls

    if is_sitemap_index(index_xml):
        subs = parse_sitemap_index(index_xml)
        # 只留内容型子 sitemap（tool 相关），排除 blog/news/category 等
        inc = site.get('sub_include', 'tool')
        exc = site.get('sub_exclude', [])
        subs = [s for s in subs
                if inc in s.lower()
                and not any(x in s.lower() for x in exc)]
        # 尾部优先（新工具集中在编号最大的子 sitemap），限量
        if site.get('tail_only'):
            subs = sorted(subs)[-site.get('max_subs', 3):]
        else:
            subs = subs[:site.get('max_subs', 5)]
        log(f"{domain}: {len(subs)} content sub-sitemaps")
        for sub in subs:
            try:
                xml = http_get(sub)
                if is_sitemap_index(xml):  # 嵌套索引，展开一层
                    for s2 in parse_sitemap_index(xml)[:5]:
                        try:
                            xml2 = http_get(s2)
                            for loc, _ in parse_urlset(xml2):
                                urls.add(loc)
                        except Exception:
                            continue
                else:
                    for loc, _ in parse_urlset(xml):
                        urls.add(loc)
            except Exception as e:
                log(f"{domain}: sub {sub[:60]} failed: {type(e).__name__}")
            time.sleep(1)
    else:
        # 直连 urlset
        for loc, _ in parse_urlset(index_xml):
            urls.add(loc)
    return urls


def load_baseline():
    if os.path.exists(BASELINE_PATH):
        with open(BASELINE_PATH, encoding='utf-8') as f:
            return json.load(f)
    return {}


def save_baseline(baseline):
    with open(BASELINE_PATH, 'w', encoding='utf-8') as f:
        json.dump(baseline, f, ensure_ascii=False, indent=1)


def fetch_sitemap_watch():
    """
    主入口。返回 [(term, info)]，info = {spotted_on, url, first_seen}。
    首次运行（无基线）只建基线，返回空列表。
    """
    with open(SITES_PATH, encoding='utf-8') as f:
        sites = json.load(f)
    baseline = load_baseline()
    first_run = not baseline
    today = datetime.now(BJ).strftime('%Y-%m-%d')

    candidates = []
    new_baseline = {}
    for site in sites:
        domain = site['domain']
        page_re = re.compile(site['page_pattern'])
        slug_strip = site.get('slug_strip')
        try:
            urls = fetch_site_urls(site)
        except Exception as e:
            log(f"{domain}: failed: {e}")
            # 保留旧基线，避免下次误报全量新增
            if domain in baseline:
                new_baseline[domain] = baseline[domain]
            time.sleep(2)
            continue

        # 只保留工具页 URL（排除 i18n 变体：page_pattern 已限定主站路径）
        tool_urls = set()
        for u in urls:
            if any(h in u for h in SKIP_URL_HINTS):
                continue
            if page_re.match(u):
                tool_urls.add(u)

        old = set(baseline.get(domain, []))
        new_baseline[domain] = sorted(tool_urls)
        log(f"{domain}: {len(tool_urls)} tool urls (baseline {len(old)})")

        if first_run or not old:
            # 首次（或该站首次成功）：只建基线，不产出
            continue
        for u in sorted(tool_urls - old):
            m = page_re.match(u)
            if not m:
                continue
            term = slug_to_term(m.group(1), slug_strip)
            if not term:
                continue
            # 同一 term 同一站只收一次（URL 变体去重已由 set 保证）
            candidates.append((term, {
                'spotted_on': domain,
                'url': u,
                'first_seen': today,
            }))
        time.sleep(2)

    save_baseline(new_baseline)
    if first_run:
        log("first run: baseline established, 0 candidates (by design)")
        return []
    # 去重：同一 term 只保留一条（优先字典序小的站点）
    seen, out = set(), []
    for term, info in sorted(candidates, key=lambda x: (x[0], x[1]['spotted_on'])):
        if term not in seen:
            seen.add(term)
            out.append((term, info))
    log(f"diff complete: {len(out)} new candidate terms")
    return out


if __name__ == '__main__':
    cands = fetch_sitemap_watch()
    for term, info in cands[:20]:
        print(f"  NEW: {term} (via {info['spotted_on']})")
    print(f"total: {len(cands)}")
