#!/usr/bin/env python3
"""
选词雷达 — 每日数据更新脚本 (REAL DATA 版)

数据源（全部免费，无需 API key）：
1. RainbowSea board.json — 每日更新的 rising 新站榜单（AI 分类）
2. trends-monitor-seen.md — 趋势真空监控的结论（去重 + 真空确认）
3. HuggingFace Hub API — 新模型（有真实下载/点赞的才算）
4. Google Trends (pytrends) — 本 VM 直连超时不可用；
   趋势动量改用 RainbowSea 自带的排名历史（实测数据）
5. Google Autocomplete — 对 top 10 高分词做联想词展开，挖真实用户长尾搜索词
6. Product Hunt Atom feed — 近 7 天发布的 AI 图像/视频/音频工具
7. Hacker News API — top 30 中 Show HN / Launch HN 的 AI 产品
8. GitHub Search API — 近 45 天创建的 AI 图像/视频生成仓库（unauthenticated）
9. Reddit — 403 被墙，不可用
10. Sitemap 盯梢（哥飞方法）— 7 个同行 AI 工具站 sitemap diff，新上架工具页提词

每条关键词必须能追溯到至少一个真实来源（sources 字段）。
任一来源失败不影响其他来源；全部失败则保持数据不变，只记日志。
只读采集，Autocomplete 间隔 1 秒，其他间隔 2 秒。
详见 scripts/sources.md。
"""
import json
import os
import re
import subprocess
import sys
import time
from datetime import datetime, timezone, timedelta
from urllib.request import Request, urlopen
from urllib.error import URLError

REPO_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA_PATH = os.path.join(REPO_DIR, 'data.json')
SEEN_PATH = os.path.join(
    os.path.expanduser('~'),
    'workspace/goals/website-seo-improvement/hidden_files/trends-monitor-seen.md'
)

RAINBOWSEA_BOARD = 'https://rainbowsea.org/board.json'
HF_API = 'https://huggingface.co/api/models'

UA = {'User-Agent': 'keyword-radar/1.0 (+real-data-pipeline)'}
BJ = timezone(timedelta(hours=8))

# 成人/NSFW 相关：用户明确不做，直接过滤
ADULT_HINTS = [
    'eros', 'porn', 'hentai', 'nsfw', 'uncensored', 'adult',
    'sexy', 'escort', 'camgirl', 'onlyfans',
]

BRANDS = [
    'google', 'openai', 'midjourney', 'anthropic', 'meta', 'microsoft',
    'apple', 'adobe', 'nvidia', 'tesla', 'amazon', 'tiktok', 'bytedance',
    'quillbot', 'canva', 'luma', 'heygen', 'turnitin', 'gptzero',
    'character.ai', 'polybuzz',
]

# 描述里出现这些词 → 可做度高（用户能做的工具/页面类型）
BUILDABLE_HINTS = [
    'generator', 'editor', 'maker', 'converter', 'remover', 'enhancer',
    'photo', 'image', 'video', 'avatar', 'headshot', 'wallpaper',
    'upscale', 'background', 'portrait', 'anime', 'cartoon',
]
# 这些词 → 可做度低（重型 SaaS / 企业服务，用户做不了）
HEAVY_HINTS = [
    'enterprise', 'governance', 'infrastructure', 'platform for',
    'legal', 'medical', 'construction', 'veterinary', 'advertising',
    'api', 'multi-agent',
]


def log(msg):
    print(f"[radar] {msg}", flush=True)


def http_get_json(url, timeout=25):
    headers = dict(UA)
    headers['Accept'] = 'application/vnd.github.v3+json, application/json'
    req = Request(url, headers=headers)
    with urlopen(req, timeout=timeout) as r:
        return json.loads(r.read().decode('utf-8', errors='ignore'))


# ---------------- Source 1: RainbowSea ----------------

def fetch_rainbowsea():
    """解析 board.json，返回 AI 分类候选：[(term, info_dict)]。"""
    try:
        data = http_get_json(RAINBOWSEA_BOARD, timeout=30)
    except Exception as e:
        log(f"RainbowSea fetch failed: {e}")
        return None
    rows = data.get('rows', [])
    log(f"RainbowSea snapshot {data.get('snapshotDate')}, total {data.get('total')}")
    cands = []
    for r in rows:
        if r.get('c') != 'ai':
            continue
        gm = r.get('gm') or 0
        is_new = r.get('n') == 1
        ra = r.get('ra') or ''
        # 过滤：新站徽章，或增长倍数 >= 3，或近 12 个月注册
        if not (is_new or gm >= 3.0 or ra >= '2025-10-01'):
            continue
        domain = r.get('d') or ''
        title = r.get('t') or ''
        de = r.get('de') or ''
        # 关键词 = 去掉 TLD 的域名主体（小写），如 machinegeist.ai -> machinegeist
        term = re.sub(r'\.(ai|io|com|net|org|co|tech|app|dev|in|to)$', '', domain.lower())
        term = term.strip()
        if not term or len(term) < 3:
            continue
        # 成人内容过滤
        if any(h in term for h in ADULT_HINTS):
            continue
        cands.append((term, {
            'domain': domain,
            'title': title,
            'desc': de,
            'gm': gm,
            'is_new': is_new,
            'reg_date': ra,
            'rank_hist': r.get('h') or [],
        }))
    # 按增长倍数排序
    cands.sort(key=lambda x: x[1]['gm'], reverse=True)
    log(f"RainbowSea AI candidates: {len(cands)}")
    return cands


def trend_from_history(hist):
    """从排名历史算趋势。hist 越小=排名越好。返回 (label, ratio)。"""
    if not hist or len(hist) < 2:
        return '未知', None
    first, last = hist[0], hist[-1]
    if not first or first <= 0:
        return '未知', None
    ratio = last / first
    if ratio <= 0.5:
        return '上涨', ratio
    if ratio <= 0.9:
        return '小涨', ratio
    if ratio <= 1.1:
        return '平稳', ratio
    return '下降', ratio


# ---------------- Source 2: trends-monitor-seen.md ----------------

def fetch_trends_monitor():
    """解析 seen.md。返回 (eliminated_set, confirmed_list)。"""
    eliminated = set()
    confirmed = []
    try:
        with open(SEEN_PATH, encoding='utf-8', errors='ignore') as f:
            lines = f.readlines()
    except Exception as e:
        log(f"trends-monitor seen.md read failed: {e}")
        return None
    for line in lines:
        line = line.strip()
        if not line.startswith('2026-'):
            continue
        parts = [p.strip() for p in line.split('|')]
        if len(parts) < 3:
            continue
        raw_term, conclusion = parts[1], parts[2]
        # term 清理：去掉 (+X% ...) 后缀
        term = re.sub(r'\s*\(.*$', '', raw_term).strip().lower()
        if '淘汰' in conclusion:
            if term:
                eliminated.add(term)
        elif '已推送' in conclusion or '真空确认' in conclusion:
            confirmed.append({'term': term, 'note': conclusion})
    log(f"trends-monitor: eliminated={len(eliminated)}, confirmed={len(confirmed)}")
    return eliminated, confirmed


# ---------------- Source 3: HuggingFace ----------------

def fetch_huggingface():
    """新 text-to-image / text-to-video 模型，有真实热度才收。"""
    cands = []
    for pipeline in ['text-to-image', 'text-to-video']:
        url = f"{HF_API}?pipeline_tag={pipeline}&sort=lastModified&direction=-1&limit=40"
        try:
            models = http_get_json(url, timeout=25)
        except Exception as e:
            log(f"HuggingFace {pipeline} fetch failed: {e}")
            continue
        time.sleep(2)
        for m in models:
            mid = m.get('id', '')
            likes = m.get('likes', 0) or 0
            dls = m.get('downloads', 0) or 0
            # 真实热度门槛：likes>=10 或 downloads>=10000（过滤测试仓库噪声）
            if likes < 10 and dls < 10000:
                continue
            # 取模型名后半段，如 nphSi/Z-Image-Lora -> z-image-lora
            name = mid.split('/')[-1].lower()
            # 去掉常见后缀
            name = re.sub(r'-(lora|gguf|turbo|diff|loras|sft|4bit|int8).*$', '', name)
            name = re.sub(r'[^a-z0-9]+', '-', name).strip('-')
            if not name or len(name) < 3:
                continue
            # 成人内容过滤
            if any(h in name for h in ADULT_HINTS):
                continue
            # 跳过纯版本号/无意义名
            if re.fullmatch(r'[v0-9.\-]+', name):
                continue
            cands.append((name, {
                'model_id': mid,
                'likes': likes,
                'downloads': dls,
                'pipeline': pipeline,
            }))
    # 去重（保留热度最高的）
    seen = {}
    for term, info in cands:
        score = info['likes'] * 10 + info['downloads']
        if term not in seen or score > seen[term][1]:
            seen[term] = (info, score)
    result = [(t, v[0]) for t, v in seen.items()]
    log(f"HuggingFace candidates: {len(result)}")
    return result


# ---------------- Source 4: Google Autocomplete ----------------

AC_ENDPOINT = 'https://suggestqueries.google.com/complete/search'

def fetch_autocomplete(seed_terms):
    """对已有高分词做联想词展开。返回 [(long_tail, info)]，info 含 parent。
    联想词是 Google 基于真实搜索数据返回的 = 实测的需求信号。"""
    from urllib.parse import quote
    cands = []
    for seed in seed_terms[:10]:
        # seed 可能是 'flux-3-image-klein'，转为空格形式查联想
        q = seed.replace('-', ' ').strip()
        if not q:
            continue
        try:
            url = f"{AC_ENDPOINT}?client=chrome&q={quote(q)}&hl=en&gl=US"
            req = Request(url, headers=UA)
            with urlopen(req, timeout=15) as r:
                data = json.loads(r.read().decode('utf-8', errors='ignore'))
            suggestions = data[1] if len(data) > 1 else []
            for s in suggestions:
                s = s.strip().lower()
                # 只要比 seed 更长的长尾；太长/太短的不要
                if len(s) <= len(q) or len(s) > 60 or len(s.split()) > 8:
                    continue
                # 必须包含 seed 原词（防 Google 模糊纠错串到别的词，如 magnific one → magnificent one）
                if q not in s:
                    continue
                if any(h in s for h in ADULT_HINTS):
                    continue
                # 规范化：空格转连字符，与现有 term 格式统一
                term = re.sub(r'[^a-z0-9]+', '-', s).strip('-')
                if not term or len(term) < 5:
                    continue
                cands.append((term, {'parent': seed, 'raw': s}))
        except Exception as e:
            log(f"Autocomplete '{q}' failed: {e}")
        time.sleep(1)
    seen = set()
    result = []
    for term, info in cands:
        if term not in seen:
            seen.add(term)
            result.append((term, info))
    log(f"Autocomplete long-tails: {len(result)}")
    return result


# ---------------- Source 5: Product Hunt ----------------

def fetch_producthunt():
    """解析 PH Atom feed，取近 7 天发布的 AI 图像/视频/音频工具。"""
    try:
        req = Request('https://www.producthunt.com/feed', headers=UA)
        with urlopen(req, timeout=25) as r:
            xml = r.read().decode('utf-8', errors='ignore')
    except Exception as e:
        log(f"ProductHunt feed failed: {e}")
        return None
    entries = re.findall(r'<entry>(.*?)</entry>', xml, re.S)
    now = datetime.now(BJ)
    ai_pat = re.compile(
        r'\b(ai|gpt|image generat|video generat|text-to-image|text-to-video|'
        r'diffusion|avatar|headshot|upscal|photo enhanc|voice|music generat|'
        r'podcast|talking head)\b', re.I)
    cands = []
    for e in entries:
        m_title = re.search(r'<title>(.*?)</title>', e, re.S)
        m_pub = re.search(r'<published>(.*?)</published>', e)
        m_link = re.search(r'href="(https://www\.producthunt\.com/products/[^"]+)"', e)
        m_content = re.search(r'<content[^>]*>(.*?)</content>', e, re.S)
        if not m_title:
            continue
        title = re.sub(r'<[^>]+>', '', m_title.group(1)).strip()
        desc = re.sub(r'<[^>]+>', '', m_content.group(1)).strip() if m_content else ''
        # 7 天过滤
        if m_pub:
            try:
                pub_dt = datetime.fromisoformat(m_pub.group(1).replace('Z', '+00:00'))
                if (now - pub_dt.astimezone(BJ)).days > 7:
                    continue
            except Exception:
                pass
        if not ai_pat.search(title + ' ' + desc):
            continue
        term = re.sub(r'[^a-z0-9]+', '-', title.lower()).strip('-')
        if not term or len(term) < 3 or len(term) > 40 or any(h in term for h in ADULT_HINTS):
            continue
        cands.append((term, {
            'ph_title': title,
            'ph_url': m_link.group(1) if m_link else '',
            'desc': desc[:300],
            'published': m_pub.group(1)[:10] if m_pub else '',
        }))
    log(f"ProductHunt AI candidates: {len(cands)}")
    return cands


# ---------------- Source 6: Hacker News ----------------

def fetch_hackernews():
    """top 30 故事；只收 Show HN / Launch HN 的 AI 产品（标题派生，噪声可控）。"""
    try:
        ids = http_get_json('https://hacker-news.firebaseio.com/v0/topstories.json', timeout=20)
    except Exception as e:
        log(f"HackerNews topstories failed: {e}")
        return None
    ai_pat = re.compile(
        r'\b(ai|gpt|llm|diffusion|image generat|video generat|text-to-|'
        r'stable diffusion|midjourney|flux|agent)\b', re.I)
    show_pat = re.compile(r'^(Show HN|Launch HN)\s*:\s*(.+?)(?:\s+[–—-]\s+|\s+\(|\s*$)', re.I)
    cands = []
    for sid in (ids or [])[:30]:
        try:
            item = http_get_json(
                f'https://hacker-news.firebaseio.com/v0/item/{sid}.json', timeout=15)
        except Exception:
            continue
        title = item.get('title', '') or ''
        if not ai_pat.search(title):
            time.sleep(0.5)
            continue
        m = show_pat.match(title)
        if not m:  # 非产品发布类标题不派生词（噪声大）
            time.sleep(0.5)
            continue
        term = re.sub(r'[^a-z0-9]+', '-', m.group(2).strip().lower()).strip('-')
        if not term or len(term) < 3 or len(term) > 40 or any(h in term for h in ADULT_HINTS):
            time.sleep(0.5)
            continue
        cands.append((term, {
            'hn_title': title,
            'hn_score': item.get('score', 0),
            'hn_url': f'https://news.ycombinator.com/item?id={sid}',
            'desc': title,
        }))
        time.sleep(0.5)
    log(f"HackerNews AI candidates: {len(cands)}")
    return cands


# ---------------- Source 7: GitHub Trending (search API) ----------------

def fetch_github_trending():
    """近 45 天创建的 AI 图像/视频生成仓库（unauthenticated，每小时 60 次限额，只用 2 次）。"""
    cands = []
    any_ok = False
    for q in ['ai+image+generator', 'text-to-video+ai']:
        url = (f"https://api.github.com/search/repositories"
               f"?q={q}+created:%3E2026-09-03&sort=stars&order=desc&per_page=15")
        try:
            data = http_get_json(url, timeout=25)
            any_ok = True
        except Exception as e:
            log(f"GitHub search '{q}' failed: {e}")
            continue
        for repo in data.get('items', []):
            name = (repo.get('name', '') or '').lower()
            stars = repo.get('stargazers_count', 0) or 0
            if stars < 20:
                continue
            term = re.sub(r'[^a-z0-9]+', '-', name).strip('-')
            if not term or len(term) < 3 or len(term) > 40 or any(h in term for h in ADULT_HINTS):
                continue
            if re.fullmatch(r'[v0-9.\-]+', term):
                continue
            cands.append((term, {
                'repo': repo.get('full_name', ''),
                'stars': stars,
                'desc': (repo.get('description', '') or '')[:300],
                'pushed': (repo.get('pushed_at', '') or '')[:10],
                'url': repo.get('html_url', ''),
            }))
        time.sleep(2)
    seen = {}
    for term, info in cands:
        if term not in seen or info['stars'] > seen[term]['stars']:
            seen[term] = info
    result = list(seen.items())
    log(f"GitHub trending candidates: {len(result)}")
    return result if any_ok else None


# ---------------- Scoring ----------------

def score_keyword(term, src_info):
    """六维打分。每维返回 (score, status, note)，status ∈ measured/heuristic/unknown。"""
    dims = {}
    src = src_info.get('primary', 'rainbowsea')
    info = src_info.get('data', {})

    # 1. 趋势动量 25 — RainbowSea 排名历史（实测）
    if src == 'rainbowsea' and info.get('rank_hist'):
        label, ratio = trend_from_history(info['rank_hist'])
        if ratio is None:
            dims['trend'] = (0, 'unknown', '排名历史缺失')
        elif ratio <= 0.3:
            dims['trend'] = (24, 'measured', f'排名 {info["rank_hist"][0]}→{info["rank_hist"][-1]}，强势上涨')
        elif ratio <= 0.6:
            dims['trend'] = (18, 'measured', f'排名 {info["rank_hist"][0]}→{info["rank_hist"][-1]}，上涨')
        elif ratio <= 0.9:
            dims['trend'] = (11, 'measured', f'排名 {info["rank_hist"][0]}→{info["rank_hist"][-1]}，小涨')
        elif ratio <= 1.1:
            dims['trend'] = (6, 'measured', '排名基本平稳')
        else:
            dims['trend'] = (2, 'measured', '排名下滑')
    elif src == 'huggingface':
        dls = info.get('downloads', 0)
        if dls >= 100000:
            dims['trend'] = (18, 'heuristic', f'下载 {dls}，热度高（无历史曲线）')
        elif dls >= 10000:
            dims['trend'] = (12, 'heuristic', f'下载 {dls}，有热度（无历史曲线）')
        else:
            dims['trend'] = (8, 'heuristic', f'点赞 {info.get("likes", 0)}（无历史曲线）')
    elif src == 'google-autocomplete':
        # 联想词本身 = Google 基于真实搜索返回，趋势给中等启发式分
        dims['trend'] = (12, 'heuristic',
                         f'Google 联想词（父词 {info.get("parent", "")}），真实搜索派生')
    elif src == 'producthunt':
        pub = info.get('published', '')
        dims['trend'] = (12, 'heuristic', f'PH 近 7 天发布（{pub}），新品热度')
    elif src == 'hackernews':
        sc = info.get('hn_score', 0)
        if sc >= 200:
            dims['trend'] = (16, 'heuristic', f'HN {sc} 分，技术圈热议')
        elif sc >= 50:
            dims['trend'] = (11, 'heuristic', f'HN {sc} 分')
        else:
            dims['trend'] = (7, 'heuristic', f'HN {sc} 分，热度一般')
    elif src == 'github-trending':
        stars = info.get('stars', 0)
        if stars >= 500:
            dims['trend'] = (15, 'heuristic', f'GitHub {stars} stars，开发者热捧')
        elif stars >= 100:
            dims['trend'] = (11, 'heuristic', f'GitHub {stars} stars')
        else:
            dims['trend'] = (7, 'heuristic', f'GitHub {stars} stars，刚起量')
    elif src == 'sitemap-watch':
        # 同行工具站新上架的工具页 = 对方编辑认为值得收录，趋势给中等启发式分
        dims['trend'] = (10, 'heuristic',
                         f'{info.get("spotted_on", "")} 新上架工具页（sitemap diff 实测）')
    else:
        dims['trend'] = (0, 'unknown', '无趋势数据源')

    # 2. 搜索需求 20 — 来源数 + 增长倍数（启发式）
    n_src = len(src_info.get('sources', [src]))
    gm = info.get('gm', 0) or 0
    if gm >= 10:
        base = 17
    elif gm >= 5:
        base = 13
    elif gm >= 3:
        base = 9
    elif gm > 0:
        base = 5
    else:
        base = 4  # HF / trends-monitor 来源无 gm
    demand = min(20, base + (3 if n_src >= 2 else 0) + (2 if n_src >= 3 else 0))
    if src == 'google-autocomplete':
        # 联想词 = 用户真实键入的搜索词，需求维度按实测计高分
        demand = 18
        dims['demand'] = (demand, 'measured',
                          f'Google 联想返回的真实用户搜索词（父词 {info.get("parent", "")}）')
    else:
        dims['demand'] = (demand, 'heuristic',
                          f'{n_src} 个来源提及' + (f'，增长 {gm:.1f}x' if gm else ''))

    # 3. SERP 真空度 20 — 只有 trends-monitor 确认才算实测，否则 unknown
    if src_info.get('vacuum_confirmed'):
        dims['vacuum'] = (17, 'measured', src_info['vacuum_confirmed'])
    else:
        dims['vacuum'] = (0, 'unknown', '未做 SERP 核查')

    # 4. 可做度 15 — 描述关键词启发式
    desc = (info.get('desc') or '').lower()
    if any(h in desc for h in BUILDABLE_HINTS):
        dims['buildable'] = (12, 'heuristic', '工具/生成类，可做页面或小工具')
    elif any(h in desc for h in HEAVY_HINTS):
        dims['buildable'] = (4, 'heuristic', '重型 B2B/企业服务，难独立做')
    elif src == 'huggingface':
        dims['buildable'] = (10, 'heuristic', '新模型名，可做内容页/评测页')
    elif src == 'google-autocomplete':
        dims['buildable'] = (13, 'heuristic', '真实用户长尾搜索词，直接可做内容页')
    elif src in ('producthunt', 'github-trending'):
        dims['buildable'] = (10, 'heuristic', '新工具/新仓库，可做内容页或对标页')
    elif src == 'hackernews':
        dims['buildable'] = (8, 'heuristic', 'HN 热议产品，可做内容页')
    elif src == 'sitemap-watch':
        dims['buildable'] = (11, 'heuristic',
                             f'同行已做成工具页（{info.get("spotted_on", "")}），可对标建页')
    else:
        dims['buildable'] = (0, 'unknown', '类型不明')

    # 5. 变现潜力 10 — 启发式
    if any(h in desc for h in BUILDABLE_HINTS):
        dims['monetize'] = (7, 'heuristic', '工具类有明确付费意愿')
    elif src == 'huggingface':
        dims['monetize'] = (5, 'heuristic', '模型名主要吃内容/评测流量')
    else:
        dims['monetize'] = (0, 'unknown', '变现路径不明')

    # 6. 品牌风险 10 — 直接检查品牌词（实测）
    low = term.lower()
    hit = [b for b in BRANDS if b in low]
    if hit:
        dims['brand'] = (2, 'measured', f'命中品牌词：{", ".join(hit)}，高风险')
    else:
        dims['brand'] = (9, 'heuristic', '未命中已知品牌词')

    total = sum(v[0] for v in dims.values())
    return total, dims


def score_label(s):
    return '有机会' if s >= 60 else '观望' if s >= 40 else '暂缓'


# ---------------- Build keyword entry ----------------

def build_entry(term, src_info, total, dims):
    info = src_info.get('data', {})
    src = src_info.get('primary', 'rainbowsea')

    # heat：RainbowSea 用增长倍数换算；HF 用下载量换算
    gm = info.get('gm', 0) or 0
    if gm:
        heat = max(50, min(5000, int(gm * 150)))
    else:
        dls = info.get('downloads', 0) or 0
        heat = max(50, min(5000, int(dls / 50)))

    # spark：排名历史后 7 点归一化（排名越好→值越高）
    spark = [50] * 7
    hist = info.get('rank_hist') or []
    if len(hist) >= 7:
        seg = hist[-7:]
        lo, hi = min(seg), max(seg)
        if hi > lo:
            spark = [5 + int(90 * (hi - v) / (hi - lo)) for v in seg]
        else:
            spark = [50] * 7

    trend_label, _ = trend_from_history(hist) if hist else ('未知', None)
    if src == 'huggingface':
        trend_label = '新发现'

    vacuum_score = dims['vacuum'][0]
    comp_level = '有机会' if total >= 60 else '观望' if total >= 40 else '待核查'

    tags = []
    if info.get('is_new'):
        tags.append({'text': 'RainbowSea 新上榜', 'type': 'hot'})
    if gm and gm >= 5:
        tags.append({'text': f'增长 {gm:.1f}x', 'type': 'hot'})
    if src == 'huggingface':
        tags.append({'text': 'HF 新模型', 'type': 'hot'})
    if src == 'google-autocomplete':
        tags.append({'text': 'Google 联想词', 'type': 'hot'})
    if src == 'producthunt':
        tags.append({'text': 'PH 新品', 'type': 'hot'})
    if src == 'hackernews':
        tags.append({'text': f'HN {info.get("hn_score", 0)}分', 'type': 'hot'})
    if src == 'github-trending':
        tags.append({'text': f'GH {info.get("stars", 0)}★', 'type': 'hot'})
    if src == 'sitemap-watch':
        tags.append({'text': f'同行新页@{info.get("spotted_on", "")}', 'type': 'hot'})
    tags.append({'text': 'AI工具', 'type': 'cat'})
    if dims['vacuum'][1] == 'unknown':
        tags.append({'text': '真空待查', 'type': 'warn'})

    # term_cn：首字母大写展示
    term_cn = ' '.join(w.capitalize() for w in term.split('-')).replace('-', ' ')

    entry = {
        'term': term,
        'term_cn': term_cn,
        'heat': heat,
        'heat_delta': 'new',
        'spark': spark,
        'spark_count': 7,
        'spark_unit': '天',
        'trends': trend_label,
        'vacuum': vacuum_score,
        'score': total,
        'score_label': score_label(total),
        'tags': tags,
        'competition': {
            'bars': [1 if total >= 60 else 0] + [0] * 7,
            'details': '自动采集，SERP 未人工核查',
            'level': comp_level,
        },
        'sources': src_info.get('sources', [src]),
        'score_detail': {
            k: {'score': v[0], 'status': v[1], 'note': v[2]}
            for k, v in dims.items()
        },
        'discovered': datetime.now(BJ).strftime('%Y-%m-%d'),
    }
    # 长尾词关联父词
    if info.get('parent'):
        entry['long_tail_of'] = info['parent']
    return entry


# ---------------- Main ----------------

def load_data():
    with open(DATA_PATH, encoding='utf-8') as f:
        return json.load(f)


def main():
    log("Starting daily radar update (REAL DATA)")
    ok_sources = {}
    candidates = {}  # term -> {'sources': [], 'primary': ..., 'data': ..., 'vacuum_confirmed': ...}

    # Source 1: RainbowSea
    rs = fetch_rainbowsea()
    ok_sources['rainbowsea'] = rs is not None
    if rs:
        for term, info in rs:
            candidates.setdefault(term, {'sources': [], 'primary': 'rainbowsea', 'data': {}})
            if 'rainbowsea' not in candidates[term]['sources']:
                candidates[term]['sources'].append('rainbowsea')
            candidates[term]['data'].update(info)
    time.sleep(2)

    # Source 2: trends-monitor (去重 + 真空确认)
    tm = fetch_trends_monitor()
    ok_sources['trends_monitor'] = tm is not None
    eliminated = set()
    if tm:
        eliminated, confirmed = tm
        for c in confirmed:
            t = c['term']
            candidates.setdefault(t, {'sources': [], 'primary': 'trends_monitor', 'data': {}})
            if 'trends_monitor' not in candidates[t]['sources']:
                candidates[t]['sources'].append('trends_monitor')
            candidates[t]['vacuum_confirmed'] = c['note']
    time.sleep(2)

    # Source 3: HuggingFace
    hf = fetch_huggingface()
    ok_sources['huggingface'] = hf is not None
    if hf:
        for term, info in hf:
            candidates.setdefault(term, {'sources': [], 'primary': 'huggingface', 'data': {}})
            if 'huggingface' not in candidates[term]['sources']:
                candidates[term]['sources'].append('huggingface')
            # HF 数据不覆盖 RainbowSea 的排名历史
            if not candidates[term]['data'].get('rank_hist'):
                candidates[term]['data'].update(info)

    # Source 4: pytrends — 本 VM 不可用（见 sources.md）
    ok_sources['pytrends'] = False

    # Source 5: Product Hunt（近 7 天 AI 工具新品）
    ph = fetch_producthunt()
    ok_sources['producthunt'] = ph is not None
    if ph:
        for term, info in ph:
            candidates.setdefault(term, {'sources': [], 'primary': 'producthunt', 'data': {}})
            if 'producthunt' not in candidates[term]['sources']:
                candidates[term]['sources'].append('producthunt')
            candidates[term]['data'].update(info)
    time.sleep(2)

    # Source 6: Hacker News（Show HN / Launch HN 的 AI 产品）
    hn = fetch_hackernews()
    ok_sources['hackernews'] = hn is not None
    if hn:
        for term, info in hn:
            candidates.setdefault(term, {'sources': [], 'primary': 'hackernews', 'data': {}})
            if 'hackernews' not in candidates[term]['sources']:
                candidates[term]['sources'].append('hackernews')
            candidates[term]['data'].update(info)
    time.sleep(1)

    # Source 7: GitHub Trending（近 45 天 AI 图像/视频仓库）
    ght = fetch_github_trending()
    ok_sources['github_trending'] = ght is not None
    if ght:
        for term, info in ght:
            candidates.setdefault(term, {'sources': [], 'primary': 'github-trending', 'data': {}})
            if 'github-trending' not in candidates[term]['sources']:
                candidates[term]['sources'].append('github-trending')
            candidates[term]['data'].update(info)

    # Source 8: Reddit — 403 被墙，不可用（见 sources.md）
    ok_sources['reddit'] = False

    # Source 9: Sitemap 盯梢（哥飞方法）— 同行工具站新上架页面 diff
    try:
        sys.path.insert(0, os.path.join(REPO_DIR, 'scripts'))
        from sitemap_watch import fetch_sitemap_watch
        sw = fetch_sitemap_watch()
        ok_sources['sitemap_watch'] = True
        sw_added_terms = 0
        for term, info in sw:
            if not term or len(term) < 3 or len(term) > 40:
                continue
            if any(h in term for h in ADULT_HINTS):
                continue
            candidates.setdefault(term, {'sources': [], 'primary': 'sitemap-watch', 'data': {}})
            if 'sitemap-watch' not in candidates[term]['sources']:
                candidates[term]['sources'].append('sitemap-watch')
            candidates[term]['data'].update(info)
            sw_added_terms += 1
        log(f"sitemap-watch: {sw_added_terms} candidates from sitemap diffs")
    except Exception as e:
        ok_sources['sitemap_watch'] = False
        log(f"sitemap-watch failed: {e} (non-fatal)")
    time.sleep(1)

    if not any(ok_sources.values()):
        log("ALL sources failed — keeping existing data unchanged")
        return 1

    data = load_data()
    kws = data['channels']['ai_tools']['keywords']
    existing = {kw['term'].lower() for kw in kws}

    added = 0
    skipped_elim = 0
    # 按分数排序后取前 5（主源：新工具/新模型/新品）
    scored = []
    for term, src_info in candidates.items():
        if term.lower() in existing:
            continue
        if term.lower() in eliminated:
            skipped_elim += 1
            continue
        total, dims = score_keyword(term, src_info)
        scored.append((total, term, src_info, dims))
    scored.sort(reverse=True, key=lambda x: x[0])

    for total, term, src_info, dims in scored[:5]:
        entry = build_entry(term, src_info, total, dims)
        kws.append(entry)
        added += 1
        log(f"NEW: {term} score={total} sources={entry['sources']}")

    # Source 9: Google Autocomplete 长尾展开（独立预算 max 5）
    # 用当前 top 10 高分词做 seed，挖真实用户长尾搜索词
    existing.update(kw['term'].lower() for kw in kws)
    seeds = sorted(kws, key=lambda k: k.get('score', 0), reverse=True)[:10]
    seed_terms = [kw['term'] for kw in seeds]
    ac = fetch_autocomplete(seed_terms)
    ok_sources['autocomplete'] = ac is not None
    ac_added = 0
    if ac:
        ac_scored = []
        for term, info in ac:
            if term.lower() in existing or term.lower() in eliminated:
                continue
            src_info = {'sources': ['google-autocomplete'], 'primary': 'google-autocomplete',
                        'data': info}
            total, dims = score_keyword(term, src_info)
            ac_scored.append((total, term, src_info, dims))
        ac_scored.sort(reverse=True, key=lambda x: x[0])
        for total, term, src_info, dims in ac_scored[:5]:
            entry = build_entry(term, src_info, total, dims)
            kws.append(entry)
            existing.add(term.lower())
            ac_added += 1
            log(f"NEW long-tail: {term} score={total} parent={src_info['data'].get('parent')}")
    added += ac_added

    # 现有词：保留分数（无新实测数据不做调整），只刷新时间
    data['updated_at'] = datetime.now(BJ).isoformat()
    meta = data.setdefault('meta', {})
    meta['last_rainbowsea_ok'] = ok_sources['rainbowsea']
    meta['last_huggingface_ok'] = ok_sources['huggingface']
    meta['last_trends_monitor_ok'] = ok_sources['trends_monitor']
    meta['last_producthunt_ok'] = ok_sources.get('producthunt')
    meta['last_hackernews_ok'] = ok_sources.get('hackernews')
    meta['last_github_trending_ok'] = ok_sources.get('github_trending')
    meta['last_autocomplete_ok'] = ok_sources.get('autocomplete')
    meta['last_sitemap_watch_ok'] = ok_sources.get('sitemap_watch')
    meta['pytrends_available'] = False
    meta['reddit_available'] = False
    meta['new_added'] = added
    meta['skipped_eliminated'] = skipped_elim

    with open(DATA_PATH, 'w', encoding='utf-8') as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    log(f"data.json updated: +{added} new, {skipped_elim} skipped (eliminated)")

    # git commit/push（保持原逻辑）
    return git_commit_push()


def git_commit_push():
    """Push data.json via GitHub Contents API using the stored connector credential.
    Falls back to local git commit if the API path is unavailable."""
    # Local commit first (keeps repo history consistent)
    os.chdir(REPO_DIR)
    r = subprocess.run(['git', 'status', '--porcelain'], capture_output=True, text=True)
    if not r.stdout.strip():
        log("No changes, skipping commit")
        return 0
    subprocess.run(['git', 'add', 'data.json'], check=True)
    day = datetime.now(BJ).strftime('%Y-%m-%d')
    subprocess.run(['git', 'commit', '-m', f'Data: real radar update {day}'], check=True)
    # Push via GitHub API (Contents endpoint) — no plaintext token needed
    try:
        ok = _push_via_api('data.json', f'Data: real radar update {day}')
        if ok:
            log("Pushed to GitHub via API (Cloudflare Pages will auto-deploy)")
            return 0
        log("API push failed, trying git push as fallback")
    except Exception as e:
        log(f"API push error: {e}, trying git push as fallback")
    r = subprocess.run(['git', 'push', 'origin', 'main'], capture_output=True, text=True)
    if r.returncode != 0:
        log(f"git push failed: {r.stderr[:300]}")
        return 1
    log("Pushed to GitHub (Cloudflare Pages will auto-deploy)")
    return 0


def _push_via_api(path, message):
    """Update a repo file via GitHub Contents API using the custom.github connector."""
    import base64
    import urllib.request
    sys.path.insert(0, "/opt/muse/skills/custom-connector-setup/bin")
    from dynamic_credentials import add_surrogate_to_request, read_json_response

    owner, repo, branch = "lovevii1900-cloud", "keyword-radar", "main"
    base = f"https://api.github.com/repos/{owner}/{repo}/contents/{path}"

    class NoRedirect(urllib.request.HTTPRedirectHandler):
        def redirect_request(self, *args):
            raise RuntimeError("redirect refused")

    opener = urllib.request.build_opener(NoRedirect())
    # 1. Get current SHA
    req = urllib.request.Request(f"{base}?ref={branch}")
    add_surrogate_to_request(req, "custom.github", allowed_hosts=["api.github.com"])
    with opener.open(req, timeout=30) as resp:
        sha = read_json_response(resp)["sha"]
    # 2. Push new content
    with open(os.path.join(REPO_DIR, path), 'rb') as f:
        content = base64.b64encode(f.read()).decode()
    body = json.dumps({"message": message, "content": content, "sha": sha, "branch": branch}).encode()
    req = urllib.request.Request(base, data=body, method="PUT",
                                 headers={"Content-Type": "application/json"})
    add_surrogate_to_request(req, "custom.github", allowed_hosts=["api.github.com"])
    with opener.open(req, timeout=30) as resp:
        result = read_json_response(resp)
        return bool(result.get("commit"))


if __name__ == '__main__':
    sys.exit(main())
