#!/usr/bin/env python3
"""
SEO 自动运营 — 机会→任务流水线 (Phase 1)
- 读取 data.json（AI工具词频道）
- score >= 60 且无对应任务 → 新建 "🎯 新词建页" 任务（待处理）
- 40 <= score < 60 且无对应任务 → 新建 "👀 观察" 任务（待处理）
- 已有任务保留（不覆盖状态：用户可能已在看板上标记进行中/已完成）
- 写 tasks.json，git commit；有 GITHUB_TOKEN 则 push
只读采集，不对外发布任何内容。
"""
import json
import os
import subprocess
from datetime import datetime, timezone, timedelta

REPO_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA_PATH = os.path.join(REPO_DIR, "data.json")
TASKS_PATH = os.path.join(REPO_DIR, "tasks.json")

BEIJING = timezone(timedelta(hours=8))

TYPE_META = {
    "new_page": {"icon": "🎯", "label": "新词建页"},
    "watch": {"icon": "👀", "label": "观察"},
    "traffic_rescue": {"icon": "📉", "label": "流量抢救"},   # Phase 1+ 预留
    "content_update": {"icon": "🔄", "label": "内容更新"},   # Phase 1+ 预留
}


def log(msg):
    print(f"[tasks] {msg}", flush=True)


def suggested_action(task_type, term, term_cn):
    if task_type == "new_page":
        return (
            f"新建内容页 targeting '{term}'（标题含{term_cn}）："
            "用 HowTo/对比结构 + FAQ Schema，一天可出，上线后提交 GSC 收录"
        )
    return (
        f"跟踪 '{term}' 趋势 3 天：热度持续上涨则转建页，"
        "下跌则关闭任务"
    )


def run(cmd):
    return subprocess.run(
        cmd, cwd=REPO_DIR, capture_output=True, text=True, timeout=60
    )


def main():
    if not os.path.exists(DATA_PATH):
        log(f"data.json 不存在: {DATA_PATH}，跳过")
        return 0

    with open(DATA_PATH, encoding="utf-8") as f:
        data = json.load(f)

    if os.path.exists(TASKS_PATH):
        with open(TASKS_PATH, encoding="utf-8") as f:
            tasks_doc = json.load(f)
    else:
        tasks_doc = {"tasks": [], "updated_at": None}

    tasks = tasks_doc.get("tasks", [])
    existing = {(t.get("term"), t.get("type")) for t in tasks}

    now = datetime.now(BEIJING)
    today = now.strftime("%Y%m%d")
    new_count = 0

    keywords = data.get("channels", {}).get("ai_tools", {}).get("keywords", [])
    for kw in keywords:
        score = kw.get("score", 0) or 0
        term = (kw.get("term") or "").strip()
        term_cn = kw.get("term_cn") or term
        if not term:
            continue
        if score >= 60:
            task_type = "new_page"
        elif score >= 40:
            task_type = "watch"
        else:
            continue
        if (term, task_type) in existing:
            continue
        slug = term.lower().replace(" ", "-").replace("/", "-")
        task = {
            "id": f"{task_type}-{slug}-{today}",
            "type": task_type,
            "term": term,
            "term_cn": term_cn,
            "priority": score,
            "status": "pending",  # pending | in_progress | done
            "action": suggested_action(task_type, term, term_cn),
            "created_at": now.isoformat(),
            "updated_at": now.isoformat(),
            "draft": None,  # Phase 2: 草稿内容
        }
        tasks.append(task)
        existing.add((term, task_type))
        new_count += 1
        log(f"新建任务 [{TYPE_META[task_type]['label']}] {term_cn} ({score}分)")

    # 按优先级排序：待处理优先、高分在前
    status_order = {"pending": 0, "in_progress": 1, "done": 2}
    tasks.sort(key=lambda t: (status_order.get(t.get("status"), 9), -(t.get("priority") or 0)))
    tasks_doc["tasks"] = tasks
    tasks_doc["updated_at"] = now.isoformat()

    with open(TASKS_PATH, "w", encoding="utf-8") as f:
        json.dump(tasks_doc, f, ensure_ascii=False, indent=2)
    log(f"tasks.json 已更新：共 {len(tasks)} 个任务，本次新增 {new_count} 个")

    # git commit
    r = run(["git", "add", "tasks.json"])
    if r.returncode != 0:
        log(f"git add 失败: {r.stderr.strip()}")
        return 1
    r = run(["git", "status", "--porcelain"])
    if not r.stdout.strip():
        log("无变化，无需提交")
        return 0
    r = run(["git", "commit", "-m", f"chore: 每日任务更新 ({today})，新增 {new_count} 个"])
    if r.returncode != 0:
        log(f"git commit 失败: {r.stderr.strip()}")
        return 1
    log("已 commit")

    # push（需要 GITHUB_TOKEN）
    token = os.environ.get("GITHUB_TOKEN")
    if not token:
        log("未设置 GITHUB_TOKEN，跳过 push（本地已提交）")
        return 0
    r = run(["git", "push",
             f"https://{token}@github.com/lovevii1900-cloud/keyword-radar.git",
             "main"])
    if r.returncode != 0:
        log(f"git push 失败: {r.stderr.strip()[-300:]}")
        return 1
    log("已 push 到 GitHub")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
