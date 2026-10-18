#!/usr/bin/env python3
"""
选词雷达 — 每日数据更新脚本 (REAL DATA 版)

数据源（全部免费，无需 API key）：
1. RainbowSea board.json — 每日更新的 rising 新站榜单（AI 分类）
2. trends-monitor-seen.md — 趋势真空监控的结论（去重 + 真空确认）
3. HuggingFace Hub API — 新模型（有真实下载/点赞的才算）
4. Google Trends (pytrends) — 本 VM 直连超时不可用，已在 sources.md 注明；
   趋势动量改用 RainbowSea 自带的排名历史（实测数据）

每条关键词必须能追溯到至少一个真实来源（sources 字段）。
任一来源失败不影响其他来源；全部失败则保持数据不变，只记日志。
只读采集，请求间隔 2 秒。
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
    req = Request(url, headers=UA)
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
    tags.append({'text': 'AI工具', 'type': 'cat'})
    if dims['vacuum'][1] == 'unknown':
        tags.append({'text': '真空待查', 'type': 'warn'})

    # term_cn：首字母大写展示
    term_cn = ' '.join(w.capitalize() for w in term.split('-')).replace('-', ' ')

    return {
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

    if not any(ok_sources.values()):
        log("ALL sources failed — keeping existing data unchanged")
        return 1

    data = load_data()
    kws = data['channels']['ai_tools']['keywords']
    existing = {kw['term'].lower() for kw in kws}

    added = 0
    skipped_elim = 0
    # 按分数排序后取前 5
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

    # 现有词：保留分数（无新实测数据不做调整），只刷新时间
    data['updated_at'] = datetime.now(BJ).isoformat()
    meta = data.setdefault('meta', {})
    meta['last_rainbowsea_ok'] = ok_sources['rainbowsea']
    meta['last_huggingface_ok'] = ok_sources['huggingface']
    meta['last_trends_monitor_ok'] = ok_sources['trends_monitor']
    meta['pytrends_available'] = False
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
