#!/usr/bin/env python3
"""
SEO Phase 2 — 草稿生成 (Draft Generation)
- 读取 tasks.json，找 pending 的 new_page（新词建页）任务
- 为每个任务生成完整的 HTML 页面草稿，严格匹配 modelpixlab.com 现有页面模板
- 输出: drafts/<keyword-slug>.html + drafts/index.json
- 只生成草稿，绝不发布（发布需要用户明确批准）

两种模式:
1. 自动模式 (默认): 从 data.json + Wikipedia/official 源自动研究组装
2. 简报模式: --brief brief.json，由 Agent 提供写好的内容节

质量规则:
- 英文内容（网站纯英文）
- 不编造事实：pricing/specs/dates 未核验则省略或标注
- FAQPage + BreadcrumbList schema，与现有页面一致
"""
import json
import os
import re
import sys
import html as html_lib
import urllib.request
import urllib.parse
from datetime import datetime, timezone, timedelta

REPO_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
TASKS_PATH = os.path.join(REPO_DIR, "tasks.json")
DATA_PATH = os.path.join(REPO_DIR, "data.json")
DRAFTS_DIR = os.path.join(REPO_DIR, "drafts")
INDEX_PATH = os.path.join(DRAFTS_DIR, "index.json")

# 本地网站模板源
SITE_DIR = os.path.expanduser("~/workspace/goals/website-seo-improvement/modelpixlab-site")
TEMPLATE_PAGE = os.path.join(SITE_DIR, "ai-image-prompt-guide", "index.html")

BEIJING = timezone(timedelta(hours=8))
MAX_DRAFTS_PER_RUN = 2
SITE_URL = "https://modelpixlab.com"

# 内链：现有页面
INTERNAL_LINKS = {
    "gpt25": "/gpt-image-2-5-generator/",
    "nano2": "/nano-banana-2-generator/",
    "pricing": "/pricing/",
    "howto": "/how-to-use/",
    "prompt_guide": "/ai-image-prompt-guide/",
    "photo_guide": "/ai-photo-editing-guide/",
}


def log(msg):
    print(f"[draft] {msg}", flush=True)


def slugify(term):
    s = term.lower().strip()
    s = re.sub(r"[^a-z0-9\s-]", "", s)
    s = re.sub(r"[\s_]+", "-", s)
    s = re.sub(r"-+", "-", s)
    return s.strip("-")


def esc(t):
    return html_lib.escape(t or "", quote=True)


# --------------------------------------------------------------------------
# 模板提取：从现有页面读取共用的 style/header/footer
# --------------------------------------------------------------------------

_template_cache = {}


def load_template_parts():
    """从参考页面提取 <style>、header、footer"""
    if _template_cache:
        return _template_cache
    with open(TEMPLATE_PAGE, encoding="utf-8") as f:
        src = f.read()

    m = re.search(r"<style>(.*?)</style>", src, re.S)
    style = m.group(1) if m else ""
    m = re.search(r'<header class="site">.*?</header>', src, re.S)
    header = m.group(0) if m else ""
    m = re.search(r'<footer class="site">.*?</footer>', src, re.S)
    footer = m.group(0) if m else ""

    _template_cache.update({"style": style, "header": header, "footer": footer})
    return _template_cache


# --------------------------------------------------------------------------
# 自动研究：从免费源抓取事实
# --------------------------------------------------------------------------

def fetch_json(url, timeout=15):
    req = urllib.request.Request(url, headers={
        "User-Agent": "Mozilla/5.0 (compatible; keyword-radar/1.0)",
        "Accept": "application/json",
    })
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read().decode("utf-8", "ignore"))


def research_wikipedia(term):
    """Wikipedia 摘要 API — 通用主题的事实基础"""
    try:
        title = urllib.parse.quote(term.replace(" ", "_"))
        url = f"https://en.wikipedia.org/api/rest_v1/page/summary/{title}"
        data = fetch_json(url)
        if data.get("type") == "disambiguation":
            return None
        return {
            "title": data.get("title", ""),
            "extract": data.get("extract", ""),
            "url": (data.get("content_urls", {}).get("desktop", {}) or {}).get("page", ""),
        }
    except Exception as e:
        log(f"Wikipedia 查询失败 ({term}): {e}")
        return None


def research_huggingface(term):
    """HuggingFace 模型页 — AI 模型类关键词"""
    try:
        q = urllib.parse.quote(term)
        url = f"https://huggingface.co/api/models?search={q}&limit=5"
        data = fetch_json(url)
        if not data:
            return None
        # 找最相关的
        term_l = term.lower().replace(" ", "")
        for m in data:
            mid = (m.get("id") or "").lower().replace("-", "").replace("_", "")
            if term_l in mid or all(w in mid for w in term.lower().split() if len(w) > 2):
                return {
                    "id": m.get("id"),
                    "likes": m.get("likes"),
                    "downloads": m.get("downloads"),
                    "tags": m.get("tags", [])[:10],
                    "url": f"https://huggingface.co/{m.get('id')}",
                }
        return None
    except Exception as e:
        log(f"HuggingFace 查询失败 ({term}): {e}")
        return None


def auto_research(term, term_cn):
    """汇总自动研究结果"""
    log(f"研究关键词: {term}")
    result = {"term": term, "term_cn": term_cn, "wikipedia": None, "huggingface": None}
    result["wikipedia"] = research_wikipedia(term)
    # AI 模型类词查 HuggingFace
    if any(k in term.lower() for k in ["flux", "stable diffusion", "midjourney",
                                        "dall", "imagen", "model", "lora", "checkpoint"]):
        result["huggingface"] = research_huggingface(term)
    return result


# --------------------------------------------------------------------------
# HTML 构建
# --------------------------------------------------------------------------

def build_faq_schema(faqs, page_url):
    items = []
    for q, a in faqs:
        # 去掉答案中的 HTML 标签给 schema
        a_text = re.sub(r"<[^>]+>", "", a)
        items.append(
            '{"@type":"Question","name":%s,"acceptedAnswer":{"@type":"Answer","text":%s}}'
            % (json.dumps(q), json.dumps(a_text))
        )
    return ('<script type="application/ld+json">\n'
            '{"@context":"https://schema.org","@type":"FAQPage","mainEntity":[\n'
            + ",\n".join(items) + "\n]}\n</script>")


def build_breadcrumb_schema(page_title, page_slug):
    return (
        '<script type="application/ld+json">\n'
        '{"@context":"https://schema.org","@type":"BreadcrumbList","itemListElement":['
        '{"@type":"ListItem","position":1,"name":"Home","item":"%s/"},'
        '{"@type":"ListItem","position":2,"name":%s,"item":"%s/%s/"}'
        ']}\n</script>'
        % (SITE_URL, json.dumps(page_title), SITE_URL, page_slug)
    )


def build_what_is_page(term, term_cn, slug, research, brief=None):
    """
    "What is X" 内容页 — 新 AI 模型/工具类关键词的标准结构
    brief: 可选，由 Agent 提供的写好的内容节 {
        "intro": str, "features": [(title, desc)], "steps": [(title, desc)],
        "faqs": [(q, a)], "pricing_note": str|None, "verdict": str
    }
    """
    parts = load_template_parts()
    page_url = f"{SITE_URL}/{slug}/"
    display = term_cn  # 如 "FLUX 3 Image Klein"

    # ---- 内容组装 ----
    if brief:
        intro = brief.get("intro", "")
        features = brief.get("features", [])
        steps = brief.get("steps", [])
        faqs = brief.get("faqs", [])
        pricing_note = brief.get("pricing_note")
        verdict = brief.get("verdict", "")
    else:
        # 自动模式：从研究结果组装，诚实标注
        wiki = (research or {}).get("wikipedia")
        hf = (research or {}).get("huggingface")
        intro_parts = []
        if wiki and wiki.get("extract"):
            intro_parts.append(wiki["extract"].split(". ")[0] + ".")
        else:
            intro_parts.append(
                f"{display} is a new name gaining attention in the AI image generation space. "
                "This page collects what is publicly known so far — "
                "details are still emerging and will be updated as official information appears."
            )
        intro = " ".join(intro_parts)

        features = []
        if hf:
            features.append((
                "Open model on HuggingFace",
                f'Listed as <code>{esc(hf["id"])}</code> on HuggingFace'
                + (f' with {hf["likes"]} likes' if hf.get("likes") else "")
                + f'. <a href="{esc(hf["url"])}" style="color:var(--ink)">View the model page</a>.'
            ))
        if wiki and wiki.get("url"):
            features.append((
                "Background",
                f'More context on <a href="{esc(wiki["url"])}" style="color:var(--ink)">Wikipedia</a>.'
            ))
        features.append((
            "Try similar generation now",
            f'While details emerge, you can generate images with current top models on '
            f'<a href="{INTERNAL_LINKS["gpt25"]}" style="color:var(--ink)">ModelPixLab</a> — '
            'new accounts get 3 free images.'
        ))

        steps = [
            ("Learn what it is",
             "Read the overview below so you know what the model does and who it is for."),
            ("Check official sources",
             "For the latest specs and availability, check the developer's official announcement and documentation."),
            ("Generate images today",
             f'You do not need to wait — <a href="{INTERNAL_LINKS["gpt25"]}" style="color:var(--ink)">try GPT Image 2.5 on ModelPixLab</a> free and compare results yourself.'),
        ]

        faqs = [
            (f"What is {display}?",
             intro),
            (f"Is {display} free?",
             "Pricing has not been officially confirmed in our sources. Check the developer's official announcement for the latest pricing. "
             "For a free starting point, ModelPixLab gives new accounts 3 free image generations."),
            (f"How does {display} compare to GPT Image 2.5?",
             f'Direct comparisons are still early. GPT Image 2.5 is available to try right now on '
             f'<a href="{INTERNAL_LINKS["gpt25"]}" style="color:var(--ink)">ModelPixLab</a> — '
             'generate the same prompt on both when access opens and judge the results yourself.'),
            (f"Where can I try {display}?",
             "Watch the developer's official channels for access announcements. "
             "In the meantime, current leading models are available on ModelPixLab with no credit card required."),
        ]
        pricing_note = None
        verdict = (
            f"{display} is new and information is still emerging. "
            "This page will be updated as official details are confirmed."
        )

    # ---- HTML ----
    title = f"What Is {display}? Features, Pricing & How to Use | ModelPixLab"
    desc = (f"{display} explained: what it is, key features, pricing and how to use it. "
            f"Plus how to generate images free on ModelPixLab right now.")[:158]

    # features HTML
    feats_html = ""
    for i, (ft, fd) in enumerate(features, 1):
        feats_html += (
            f'<article class="feat"><div class="num">{i:02d}</div>'
            f"<h3>{esc(ft)}</h3><p>{fd}</p></article>\n"
        )

    # steps HTML
    steps_html = ""
    for i, (st, sd) in enumerate(steps, 1):
        steps_html += (
            f'<div class="step"><div class="n">{i} · STEP</div>'
            f"<h3>{esc(st)}</h3><p>{sd}</p></div>\n"
        )

    # FAQ HTML + schema
    faq_html = ""
    for q, a in faqs:
        faq_html += (
            f"<details><summary>{esc(q)}</summary>"
            f'<div class="a">{a}</div></details>\n'
        )

    pricing_section = ""
    if pricing_note:
        pricing_section = f"""
<section class="block" style="padding:40px 0 8px">
  <div class="sec-head"><div><p class="kicker">Pricing</p><h2 style="margin:0;font-size:30px;letter-spacing:-.03em">What does it cost?</h2></div></div>
  <p style="color:var(--muted);max-width:640px">{pricing_note}</p>
</section>"""

    page = f"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8" />
<meta name="viewport" content="width=device-width, initial-scale=1, viewport-fit=cover" />
<meta name="color-scheme" content="light dark" />
<link rel="icon" type="image/png" href="/mp-icon.png" />
<title>{esc(title)}</title>
<meta name="description" content="{esc(desc)}" />
<link rel="canonical" href="{page_url}" />
<meta property="og:type" content="website" />
<meta property="og:site_name" content="ModelPixLab" />
<meta property="og:title" content="{esc(title)}" />
<meta property="og:description" content="{esc(desc)}" />
<meta property="og:url" content="{page_url}" />
<meta property="og:image" content="{SITE_URL}/assets/gpt25-sample-3.jpg" />
<meta name="twitter:card" content="summary_large_image" />
<meta name="twitter:image" content="{SITE_URL}/assets/gpt25-sample-3.jpg" />
<style>{parts["style"]}</style>
{build_faq_schema(faqs, page_url)}
{build_breadcrumb_schema(f"What Is {display}?", slug)}
</head>
<body>
{parts["header"]}
<main>
<div class="wrap">

<section class="hero" style="padding:44px 0 8px">
  <span class="eyebrow"><i></i>Model guide</span>
  <h1>What is {esc(display)}<span class="thin">?</span></h1>
  <div class="hero-side" style="max-width:640px;padding-top:18px">
    <p>{intro}</p>
  </div>
</section>

<section class="block" style="padding:34px 0 8px">
  <div class="sec-head"><div><p class="kicker">Key points</p><h2 style="margin:0;font-size:30px;letter-spacing:-.03em">What to know about {esc(display)}</h2></div></div>
  <div class="feats">
{feats_html}  </div>
</section>
{pricing_section}
<section class="block" style="padding:40px 0 8px">
  <div class="sec-head"><div><p class="kicker">Get started</p><h2 style="margin:0;font-size:30px;letter-spacing:-.03em">How to use {esc(display)}</h2></div></div>
  <div class="steps">
{steps_html}  </div>
</section>

<section class="block" id="faq" style="padding:40px 0 30px">
  <div class="sec-head"><div><p class="kicker">FAQ</p><h2 style="margin:0;font-size:30px;letter-spacing:-.03em">{esc(display)} questions</h2></div></div>
  <div class="faq">
{faq_html}  </div>
  <p style="color:var(--muted);max-width:640px;margin-top:18px">{esc(verdict)}</p>
  <p style="margin-top:26px"><a class="hcta" href="{INTERNAL_LINKS["gpt25"]}" style="text-decoration:none"><b></b>Generate images free</a></p>
</section>

</div>
</main>
{parts["footer"]}
</body>
</html>
"""
    return page


# --------------------------------------------------------------------------
# 主流程
# --------------------------------------------------------------------------

def load_tasks():
    with open(TASKS_PATH, encoding="utf-8") as f:
        return json.load(f)


def load_index():
    if os.path.exists(INDEX_PATH):
        with open(INDEX_PATH, encoding="utf-8") as f:
            return json.load(f)
    return {"drafts": []}


def save_index(idx):
    os.makedirs(DRAFTS_DIR, exist_ok=True)
    with open(INDEX_PATH, "w", encoding="utf-8") as f:
        json.dump(idx, f, ensure_ascii=False, indent=2)


def find_keyword_context(term):
    """从 data.json 找关键词的上下文"""
    try:
        with open(DATA_PATH, encoding="utf-8") as f:
            data = json.load(f)
        kws = data.get("channels", {}).get("ai_tools", {}).get("keywords", [])
        for kw in kws:
            if (kw.get("term") or "").lower() == term.lower():
                return kw
    except Exception as e:
        log(f"data.json 读取失败: {e}")
    return None


def main():
    brief_path = None
    if "--brief" in sys.argv:
        i = sys.argv.index("--brief")
        if i + 1 < len(sys.argv):
            brief_path = sys.argv[i + 1]

    brief_data = None
    if brief_path:
        with open(brief_path, encoding="utf-8") as f:
            brief_data = json.load(f)
        log(f"使用简报: {brief_path}")

    tasks_doc = load_tasks()
    tasks = tasks_doc.get("tasks", [])
    index = load_index()
    drafted_slugs = {d.get("slug") for d in index.get("drafts", [])}

    # 找 pending 的 new_page 任务（未起草）
    candidates = []
    for t in tasks:
        if t.get("type") != "new_page":
            continue
        if t.get("status") == "closed":
            continue
        if t.get("status") not in ("pending", "in_progress"):
            continue
        slug = slugify(t.get("term", ""))
        if not slug or slug in drafted_slugs:
            continue
        if t.get("draft"):
            continue
        candidates.append(t)

    # 高分优先
    candidates.sort(key=lambda t: -(t.get("priority") or 0))
    candidates = candidates[:MAX_DRAFTS_PER_RUN]

    if not candidates:
        log("没有待起草的 new_page 任务")
        return 0

    log(f"待起草: {len(candidates)} 个")
    os.makedirs(DRAFTS_DIR, exist_ok=True)

    for t in candidates:
        term = t.get("term", "")
        term_cn = t.get("term_cn") or term
        slug = slugify(term)
        log(f"生成草稿: {term_cn} ({term}) -> {slug}.html")

        # 简报：按 slug 匹配，否则用通用
        brief = None
        if brief_data:
            brief = brief_data.get(slug) or brief_data.get("default")

        research = auto_research(term, term_cn) if not brief else None
        html_page = build_what_is_page(term, term_cn, slug, research, brief)

        out_path = os.path.join(DRAFTS_DIR, f"{slug}.html")
        with open(out_path, "w", encoding="utf-8") as f:
            f.write(html_page)
        log(f"已写入: {out_path} ({len(html_page)} 字符)")

        # 更新 index.json
        now = datetime.now(BEIJING).isoformat()
        index["drafts"].append({
            "slug": slug,
            "term": term,
            "term_cn": term_cn,
            "task_id": t.get("id"),
            "priority": t.get("priority"),
            "created_at": now,
            "status": "pending_review",  # pending_review | approved | published | rejected
            "file": f"drafts/{slug}.html",
            "reviewed_at": None,
            "published_url": None,
        })
        save_index(index)

        # 回写任务
        t["draft"] = f"drafts/{slug}.html"
        t["updated_at"] = now

    # 保存 tasks.json
    with open(TASKS_PATH, "w", encoding="utf-8") as f:
        json.dump(tasks_doc, f, ensure_ascii=False, indent=2)
    log(f"完成: {len(candidates)} 个草稿")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
