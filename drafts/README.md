# 草稿生成 (Draft Generation) — SEO Phase 2

## 工作流

```
雷达发现高分词 → generate_tasks.py 建 "新词建页" 任务
    → generate_draft.py 生成 HTML 草稿 → drafts/<slug>.html
    → 用户审阅（手机看）→ 批准 → 手动部署到 modelpixlab.com
```

**铁律：AI 只起草，用户批准后才发布。脚本永不自动发布。**

## 运行

```bash
# 自动模式：从 data.json + Wikipedia/HuggingFace 自动研究组装
python3 scripts/generate_draft.py

# 简报模式：Agent 写好内容节，脚本套模板
python3 scripts/generate_draft.py --brief brief.json
```

- 每次最多 2 个草稿（质量优先）
- 只处理 `type=new_page` 且 `status=pending/in_progress`、未关闭、未起草过的任务

## 简报格式 (brief.json)

```json
{
  "flux-3-image-klein": {
    "intro": "段落：X 是什么（只写核验过的事实）",
    "features": [["标题", "描述（可含 HTML 链接）"]],
    "steps": [["步骤标题", "描述"]],
    "faqs": [["问题", "答案（可含 HTML）"]],
    "pricing_note": "定价说明（可选，未核验则省略整个字段）",
    "verdict": "结尾判断句"
  }
}
```

## 状态流转 (drafts/index.json)

`pending_review` → `approved` → `published`（或 `rejected`）

- `generate_draft.py` 只创建 `pending_review`
- 用户说"批准"后，parent agent 改 `approved` 并部署
- 部署验证 live URL 后改 `published`，填 `published_url`

## 质量规则

1. **英文内容**（网站纯英文）
2. **不编造**：pricing/specs/dates 未核验就省略，不写"据报道"式模糊话
3. 模板严格匹配现有页面：inline CSS、header/footer、FAQ `<details>` 结构
4. 每个草稿必含 FAQPage + BreadcrumbList JSON-LD
5. 内链指向现有页面（generator/pricing/how-to-use）
6. CTA 统一导向 `/gpt-image-2-5-generator/`

## 页面类型

当前实现：`What is X` 内容页（新 AI 模型/工具类关键词）。
后续可扩展：vs 对比页、教程页。
