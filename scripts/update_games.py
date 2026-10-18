#!/usr/bin/env python3
"""
选词雷达 — 游戏词频道每日更新 (Phase 3)
只收"最新"的游戏：
  1. 近 30 天内发布的 Steam 新游
  2. 即将发布的高热度游戏（铺词黄金期，wiki/攻略竞争还没到）
  3. 60 天内有大版本更新的游戏（本轮仅记录发布/即将发布；更新检测后续接 Steam 新闻源）
全部只读采集，尊重频率限制。每个关键词必须追溯到真实来源。
"""
import json
import os
import re
import sys
import time
from datetime import datetime, timezone, timedelta
from urllib.parse import quote
from urllib.request import Request, urlopen

REPO_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA_PATH = os.path.join(REPO_DIR, 'data.json')
BJ = timezone(timedelta(hours=8))

UA = {'User-Agent': 'keyword-radar/1.0 (+game-channel)'}
BS = chr(92)  # backslash constant (avoids escape hell)
STEAM_SEARCH = "https://store.steampowered.com/search/results/"
APPDETAILS = "https://store.steampowered.com/api/appdetails"
AC_ENDPOINT = "https://suggestqueries.google.com/complete/search"

# 成人向/赌博类关键词过滤
ADULT_HINTS = ['hentai', 'porn', 'sex', 'nsfw', 'adult', 'erotic', 'nudity',
               'sexual content', '赌博', '色情', '成人']
# 已知大厂/3A 系列（竞争过大，直接跳过）
AAA_FRANCHISES = ['call of duty', 'battlefield', 'fifa', 'ea sports fc', 'grand theft auto',
                  'gta ', 'cyberpunk', 'elden ring', 'god of war', 'assassin',
                  'far cry', 'resident evil', 'final fantasy', 'monster hunter',
                  'overwatch', 'diablo', 'world of warcraft', 'league of legends',
                  'counter-strike', 'dota', 'fortnite', 'minecraft', 'pubg',
                  'apex legends', 'valorant', 'destiny 2', 'halo', 'gears of war',
                  'the witcher', 'red dead', 'starfield', 'hogwarts legacy',
                  'baldur', 'star wars', 'marvel', 'nba 2k', 'madden']
# wiki 友好的类型（机制深度高）
DEEP_GENRES = {'rpg', 'strategy', 'simulation', 'adventure'}
GUIDE_SUFFIXES = ['wiki', 'guide', 'walkthrough', 'release date', 'tier list',
                  'best build', 'map', 'boss guide']

MAX_NEW_PER_DAY = 5
RELEASE_WINDOW_DAYS = 30   # 发布窗口：近 30 天
MAX_AGE_DAYS = 60          # 超过 60 天且无更新的直接淘汰


def log(msg):
    print(f"[games] {msg}", flush=True)


def http_get(url, timeout=25):
    req = Request(url, headers=UA)
    with urlopen(req, timeout=timeout) as r:
        return r.read().decode('utf-8', errors='ignore')


def fetch_steam_search(filter_name, count=60):
    """抓 Steam 搜索页（新品 / 即将发布），返回 [(appid, slug_name)]。"""
    url = (f"{STEAM_SEARCH}?query&start=0&count={count}&dynamic_data=&sort_by=Released_DESC"
           f"&os=win&filter={filter_name}&snr=1_7_7_230_7&infinite=1")
    try:
        html = http_get(url).replace(BS + '"', '"').replace(BS + '/', '/')
        appids = re.findall(r'data-ds-appid="(\d+)"', html)
        # 名字从链接 slug 取：/app/<id>/<Name_With_Underscores>/
        slugs = re.findall(r'/app/\d+/([A-Za-z0-9_]{2,80})/', html)
        seen, out = set(), []
        for aid, slug in zip(appids, slugs):
            if aid in seen:
                continue
            seen.add(aid)
            name = slug.replace('_', ' ').strip()
            out.append((aid, name))
        log(f"Steam {filter_name}: {len(out)} games")
        return out
    except Exception as e:
        log(f"Steam {filter_name} failed: {e}")
        return []


def fetch_appdetails(appids):
    """逐个查游戏详情（Steam appdetails 仅支持单 appid）。返回 {appid: {...}}。"""
    out = {}
    for aid in appids[:25]:
        try:
            url = (f"{APPDETAILS}?appids={aid}&cc=US&l=en"
                   f"&filters=release_date,genres,short_description")
            data = json.loads(http_get(url, timeout=20))
            node = data.get(aid, {})
            if not node.get('success'):
                continue
            d = node.get('data', {})
            rd = d.get('release_date', {})
            out[aid] = {
                'name': d.get('name', ''),
                'date': rd.get('date', ''),
                'coming_soon': bool(rd.get('coming_soon')),
                'genres': [g.get('description', '') for g in d.get('genres', [])],
                'desc': (d.get('short_description') or '')[:300],
                'descriptors': [],
            }
        except Exception as e:
            log(f"appdetails {aid} failed: {e}")
        time.sleep(1)
    log(f"appdetails resolved: {len(out)}/{min(len(appids), 25)}")
    return out


def parse_steam_date(s):
    """'Oct 16, 2026' / 'Q1 2027' / 'Coming soon' → date 或 None。"""
    if not s:
        return None
    s = s.strip()
    for fmt in ('%b %d, %Y', '%B %d, %Y'):
        try:
            return datetime.strptime(s, fmt).date()
        except ValueError:
            pass
    m = re.match(r'Q([1-4])\s+(\d{4})', s)
    if m:
        q, y = int(m.group(1)), int(m.group(2))
        return datetime(y, (q - 1) * 3 + 1, 1).date()
    m = re.match(r'(\d{4})', s)
    if m:
        return datetime(int(m.group(1)), 1, 1).date()
    return None


def is_adult(info):
    blob = (info['name'] + ' ' + info['desc'] + ' ' +
            ' '.join(info['descriptors'])).lower()
    return any(h in blob for h in ADULT_HINTS)


def is_aaa(name):
    n = name.lower()
    return any(f in n for f in AAA_FRANCHISES)


def autocomplete_count(query):
    """查 Google 联想返回条数（真实搜索需求信号）。"""
    try:
        url = f"{AC_ENDPOINT}?client=chrome&q={quote(query)}&hl=en&gl=US"
        data = json.loads(http_get(url, timeout=15))
        sug = data[1] if len(data) > 1 else []
        return [s for s in sug if isinstance(s, str)]
    except Exception as e:
        log(f"autocomplete '{query}' failed: {e}")
        return []


def guide_demand(name):
    """攻略需求 = '{name} wiki/guide/walkthrough' 联想命中数（实测）。"""
    hits, samples = 0, []
    for suffix in GUIDE_SUFFIXES[:4]:  # wiki, guide, walkthrough, release date
        sug = autocomplete_count(f"{name} {suffix}")
        # 命中：联想词包含游戏名
        matched = [s for s in sug if name.lower() in s.lower()]
        if matched:
            hits += 1
            samples.extend(matched[:3])
        time.sleep(1)
    return hits, samples[:6]


def score_game(name, info, demand):
    """游戏六维打分。每维返回 (score, status, note)。"""
    dims = {}
    today = datetime.now(BJ).date()
    rel = parse_steam_date(info['date'])
    age_days = (today - rel).days if rel else None
    is_upcoming = info['coming_soon']

    # 1. 玩家动量 25 — 发布新近度/即将发布（实测：Steam 日期）
    if is_upcoming:
        dims['momentum'] = (22, 'measured', '即将发布，铺词黄金期')
    elif age_days is not None and age_days <= 7:
        dims['momentum'] = (24, 'measured', f'发布 {age_days} 天，最新热度')
    elif age_days is not None and age_days <= 30:
        dims['momentum'] = (17, 'measured', f'发布 {age_days} 天')
    elif age_days is not None and age_days <= 60:
        dims['momentum'] = (8, 'measured', f'发布 {age_days} 天，热度衰减')
    else:
        dims['momentum'] = (0, 'unknown', '发布日期未知')

    # 2. 搜索需求 20 — 联想词攻略命中（实测）
    hits, samples = demand
    if hits >= 3:
        dims['demand'] = (18, 'measured', f'{hits}/4 攻略类联想命中：{", ".join(samples[:2])}')
    elif hits >= 1:
        dims['demand'] = (12, 'measured', f'{hits}/4 攻略类联想命中')
    else:
        dims['demand'] = (4, 'measured', '暂无攻略类联想，玩家还没开始搜')

    # 3. SERP 机会 20 — 暂无实测（OpenSERP 后续）
    dims['serp'] = (0, 'unknown', 'SERP 未核查（OpenSERP 接入后实测）')

    # 4. 机制深度 15 — 类型启发式（实测类型 → 启发式判断）
    genres = {g.lower() for g in info['genres']}
    deep = genres & DEEP_GENRES
    if deep:
        dims['depth'] = (13, 'heuristic', f'类型 {"/".join(sorted(deep))}，wiki 素材多')
    elif genres:
        dims['depth'] = (7, 'heuristic', f'类型 {"/".join(sorted(genres))}，中等深度')
    else:
        dims['depth'] = (5, 'unknown', '类型未知')

    # 5. 工具潜力 10 — 能否做 wiki/工具页（启发式）
    if deep:
        dims['tool'] = (9, 'heuristic', '适合做 wiki/数据库站')
    else:
        dims['tool'] = (5, 'heuristic', '可做攻略内容页')

    # 6. 品牌纯净 10 — 是否续作/大厂 IP（启发式）
    n = name.lower()
    if re.search(r'\b(2|3|4|ii|iii|iv)\b', n):
        dims['brand'] = (4, 'heuristic', '疑似续作，品牌词竞争大')
    else:
        dims['brand'] = (9, 'heuristic', '新 IP，品牌干净')

    total = sum(v[0] for v in dims.values())
    return total, dims


def score_label(s):
    if s >= 60:
        return '有机会'
    if s >= 40:
        return '观望'
    return '待核查'


def build_entry(term, name, info, total, dims, demand, src_tag):
    today = datetime.now(BJ)
    hits, samples = demand
    tags = [{'text': '游戏', 'type': 'cat'}]
    if info['coming_soon']:
        tags.append({'text': '即将发布', 'type': 'hot'})
    elif info.get('age_days') is not None and info['age_days'] <= 7:
        tags.append({'text': f'发布 {info["age_days"]} 天', 'type': 'hot'})
    if hits >= 3:
        tags.append({'text': f'攻略需求 {hits}/4', 'type': 'hot'})
    if dims['serp'][1] == 'unknown':
        tags.append({'text': '真空待查', 'type': 'warn'})

    term_cn = ' '.join(w.capitalize() for w in name.split())
    return {
        'term': term,
        'term_cn': term_cn,
        'heat': 200 + hits * 150,
        'heat_delta': 'new',
        'spark': [50] * 7,
        'spark_count': 7,
        'spark_unit': '天',
        'trends': '即将发布' if info['coming_soon'] else '新发布',
        'vacuum': 0,
        'score': total,
        'score_label': score_label(total),
        'tags': tags,
        'competition': {
            'bars': [1 if total >= 60 else 0] + [0] * 7,
            'details': 'Steam 新游自动采集，SERP 未人工核查',
            'level': '有机会' if total >= 60 else '观望' if total >= 40 else '待核查',
        },
        'sources': ['steam', src_tag],
        'score_detail': {k: {'score': v[0], 'status': v[1], 'note': v[2]}
                         for k, v in dims.items()},
        'discovered': today.strftime('%Y-%m-%d'),
        'steam_appid': info.get('appid', ''),
        'release_date': info.get('date', ''),
    }


def load_data():
    with open(DATA_PATH, encoding='utf-8') as f:
        return json.load(f)


def main():
    log("Starting game channel update (LATEST ONLY)")
    data = load_data()
    ch = data['channels']['games']
    existing = {k['term'].lower() for k in ch['keywords']}
    today = datetime.now(BJ).date()

    # 1. 抓新品 + 即将发布
    new_rel = fetch_steam_search('topsellers', 60)      # 近期热销≈新发布排序
    upcoming = fetch_steam_search('popularcomingsoon', 60)
    # 补充：Released_DESC 排序的新品页
    fresh = []
    try:
        url = (f"{STEAM_SEARCH}?query&start=0&count=60&dynamic_data=&sort_by=Released_DESC"
               f"&os=win&snr=1_7_7_230_7&infinite=1")
        html = http_get(url).replace(BS + '"', '"').replace(BS + '/', '/')
        appids = re.findall(r'data-ds-appid="(\d+)"', html)
        slugs = re.findall(r'/app/\d+/([A-Za-z0-9_]{2,80})/', html)
        seen = set()
        for aid, slug in zip(appids, slugs):
            if aid not in seen:
                seen.add(aid)
                fresh.append((aid, slug.replace('_', ' ').strip()))
        log(f"Steam new-releases: {len(fresh)} games")
    except Exception as e:
        log(f"Steam new-releases failed: {e}")

    # 合并去重， upcoming 优先
    ordered, seen_ids = [], set()
    for aid, name in upcoming + fresh + new_rel:
        if aid not in seen_ids:
            seen_ids.add(aid)
            ordered.append((aid, name, 'popularcomingsoon' if (aid, name) in
                            [(a, n) for a, n in upcoming] else 'new-releases'))

    # 2. 详情（每天最多查 40 个，控制节奏）
    details = fetch_appdetails([a for a, _, _ in ordered[:40]])

    # 3. 过滤：30 天内发布 / 即将发布；淘汰 >60 天、3A、成人
    cands = []
    for aid, name, src_tag in ordered[:40]:
        info = details.get(aid)
        if not info:
            continue
        info['appid'] = aid
        if not info['name']:
            info['name'] = name  # fallback to search-page slug name
        rel = parse_steam_date(info['date'])
        age = (today - rel).days if rel else None
        info['age_days'] = age
        if info['coming_soon']:
            pass  # 即将发布：最高优先级
        elif age is None or age > MAX_AGE_DAYS:
            continue
        elif age > RELEASE_WINDOW_DAYS:
            continue  # 30~60 天且无更新信号：跳过
        if is_adult(info):
            log(f"skip adult: {info['name']}")
            continue
        if is_aaa(info['name']):
            log(f"skip AAA: {info['name']}")
            continue
        term = re.sub(r'[^a-z0-9]+', '-', info['name'].lower()).strip('-')
        if not term or len(term) < 3 or term in existing:
            continue
        cands.append((term, info, src_tag))
        if len(cands) >= 12:
            break
    log(f"candidates after filter: {len(cands)}")

    # 4. 攻略需求 + 打分（最多 8 个，控制联想词请求量）
    added = 0
    for term, info, src_tag in cands[:8]:
        demand = guide_demand(info['name'])
        total, dims = score_game(info['name'], info, demand)
        entry = build_entry(term, info['name'], info, total, dims, demand, src_tag)
        ch['keywords'].append(entry)
        existing.add(term)
        added += 1
        age_str = 'UPCOMING' if info['coming_soon'] else f"age={info['age_days']}d"
        log(f"NEW: {info['name']} score={total} demand={demand[0]}/4 {age_str}")
        if added >= MAX_NEW_PER_DAY:
            break

    # 5. 按分数排序，更新状态
    ch['keywords'].sort(key=lambda k: k['score'], reverse=True)
    if ch['keywords']:
        ch['status'] = 'live'
    data['updated_at'] = datetime.now(BJ).isoformat()
    with open(DATA_PATH, 'w', encoding='utf-8') as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    log(f"done: +{added} games, total {len(ch['keywords'])}")
    return 0


if __name__ == '__main__':
    sys.exit(main())
