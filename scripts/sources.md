# 选词雷达 — 数据源说明

> 诚实原则：每个关键词必须能追溯到至少一个真实来源（`sources` 字段）。
> 每个评分离度标注状态：`measured`（实测）/ `heuristic`（启发式）/ `unknown`（未知）。

## 1. RainbowSea（主来源）

- **地址**：`https://rainbowsea.org/board.json`
- **提供**：每日更新的 rising 新站榜单。5490 个站点，10 个分类。
- **我们用的字段**：
  - `c` = 分类（取 `ai`）
  - `d` = 域名 → 派生关键词（去 TLD 小写，如 `machinegeist.ai` → `machinegeist`）
  - `t`/`de`/`dz` = 标题、中/英文描述 → 可做度、变现潜力判断
  - `gm` = 增长倍数 → 搜索需求分、heat 换算
  - `n` = 1 表示"新上榜"徽章
  - `ra` = 域名注册日期 → 过滤近 12 个月新站
  - `h` = 排名历史数组（数字越小排名越好）→ **趋势动量（实测）**
  - `r1`/`r7`/`r30` = 近 1/7/30 天排名
- **过滤**：`n==1` 或 `gm>=3.0` 或 `ra >= 近12个月`。
- **局限**：
  - 给的是**站点**不是关键词，域名派生的词（如 `typesafe`）是品牌名，适合" watch 新名字"不适合直接做词。
  - 榜单头部多为企业级 AI（typesafe.ai、mineos.ai），对独立开发者直接可做的价值有限；看 `New` 徽章 + 注册日期近的。
  - 它自己承认：显示的是排名位移，不是真实访问量——方向性信号。
  - 快照日期可能滞后 1 天（`snapshotDate` 字段）。

## 2. trends-monitor-seen.md（去重 + 真空确认）

- **地址**：`~/workspace/goals/website-seo-improvement/hidden_files/trends-monitor-seen.md`
- **提供**：每 6 小时跑的 Google Trends 真空监控的结论。
- **我们用的**：
  - `淘汰-` 开头的结论 → 淘汰词集合，新候选命中则跳过（不重复加）。
  - `已推送` / `真空确认` → 真空度实测分（当前为 0 条，有则自动生效）。
- **局限**：目前全部是淘汰结论，无确认真空词；所以新词的 `serp_vacuum` 维度当前恒为 `unknown`（0 分，如实标注）。

## 3. HuggingFace Hub API（新模型名）

- **地址**：`https://huggingface.co/api/models?pipeline_tag=text-to-image|text-to-video&sort=lastModified&direction=-1`
- **提供**：最新模型列表（含 likes、downloads）。
- **过滤**：`likes>=10` 或 `downloads>=10000`（过滤测试仓库噪声）。
- **关键词派生**：模型 id 后半段去后缀，如 `nphSi/Z-Image-Lora` → `z-image`。
- **局限**：
  - 大量 LoRA/微调/测试仓库，名字噪声大。
  - 无历史趋势曲线，趋势动量只能按下载量启发式估算。
  - 模型名多为品牌名，品牌风险需人工复核。

## 4. Google Trends / pytrends（不可用）

- **状态**：本 VM 直连 `trends.google.com` 超时（pytrends 4.9.2 实测 25s 超时）。
- **替代**：趋势动量改用 RainbowSea 排名历史（实测数据），见来源 1。
- **如需恢复**：需走浏览器通道（trends-vacuum-monitor 现有模式）或换网络环境。

## 5. Google Autocomplete（联想词展开）

- **地址**：`https://suggestqueries.google.com/complete/search?client=chrome&q={词}&hl=en&gl=US`
- **提供**：Google 基于真实搜索数据返回的联想词（无需 key，免费）。
- **我们用的**：对 data.json 里 top 10 高分词逐个查联想，取比原词更长的长尾（如 `flux 3 image klein` → `flux 3 image klein generator free`）。
- **关键词派生**：联想词原样收录（空格转连字符），带 `long_tail_of` 指向父词。
- **评分**：`搜索需求` 按 **measured** 计 18/20——联想词是 Google 根据真实用户搜索返回的，是最接近"有人在搜"的免费信号。
- **局限**：
  - 只给词，不给搜索量数字（有词无量）。
  - 联想词偏向头部热门 query，长尾覆盖不如付费词库。
  - Google 可能限流：每次间隔 1 秒，每天最多展开 10 个 seed。

## 6. Product Hunt（新品发布）

- **地址**：`https://www.producthunt.com/feed`（Atom，无需 key）
- **提供**：PH 每日新品榜（标题、发布时间、链接、简介）。
- **我们用的**：过滤近 7 天发布 + 标题/简介命中 AI 图像/视频/音频关键词的产品；词 = 产品名小写去符号。
- **局限**：
  - PH 排名 ≠ 搜索需求：PH 热度是社区投票，很多人搜的不一定上 PH，PH 火的也不一定有人搜。
  - feed 只给最近一批，7 天窗口外的漏掉。
  - 产品名多为品牌名，品牌风险需人工复核。

## 7. Hacker News（技术圈热议）

- **地址**：`https://hacker-news.firebaseio.com/v0/topstories.json` + `/v0/item/{id}.json`（免费，无需 key）
- **提供**：HN top 30 故事（标题、分数、链接）。
- **我们用的**：只收 `Show HN:` / `Launch HN:` 开头且标题命中 AI 关键词的产品名；普通讨论帖不派生词（标题是句子，噪声大）。
- **局限**：
  - 命中率低：top 30 里 AI 产品帖经常只有 0–2 条。
  - HN 分数反映的是开发者兴趣，不是大众搜索需求。
  - 每天只看一次 top 30，快帖可能错过。

## 8. GitHub Trending（search API）

- **地址**：`https://api.github.com/search/repositories?q=ai+image+generator+created:>2026-09-03&sort=stars&order=desc`
- **提供**：近 45 天创建的 AI 图像/视频生成仓库（star 数、描述、推送时间）。未登录每小时 60 次限额，我们只用 2 次。
- **我们用的**：star ≥ 20 的仓库名派生词。
- **局限**：
  - star 反映开发者热度，不是搜索需求；很多高 star 项目是库/框架，不是终端工具。
  - 仓库名经常是缩写/代号（如 `z-image`），可读性差，需人工判断。
  - search API 的 `created:` 过滤依赖仓库元数据，不完全准。

## 9. Reddit（不可用）

- **状态**：`https://www.reddit.com/r/StableDiffusion/hot.json` 返回 **HTTP 403**（本 VM IP 被 Reddit 墙）。
- **如需恢复**：需换 IP / 走浏览器通道，或用 Reddit 官方 API（需注册 app 拿 token，免费但要走 OAuth）。
- r/artificial、r/StableDiffusion 是 AI 工具讨论最活跃的两个版块，恢复后优先接。

## 10. OpenSERP（暂缓）

- **状态**：开源免费 SERP API，但需**自建服务器**跑（`localhost:7000`），本 VM 暂不部署。
- **价值**：接上后可把 `SERP真空度` 从 unknown 变成 measured——自动查每个词 Google 前 10，看独立站占比。
- **后续**：等有空闲服务器或用户批准后再搭。

## 评分维度状态说明

| 维度 | 权重 | 主要依据 | 状态 |
|------|------|----------|------|
| 趋势动量 | 25 | RainbowSea 排名历史首尾比；新源用各自热度信号 | measured（RS 历史）/ heuristic（PH/HN/GH/联想）/ unknown |
| 搜索需求 | 20 | 来源数 + 增长倍数；**联想词按 measured 计** | measured（联想词）/ heuristic（其他） |
| SERP真空度 | 20 | trends-monitor 确认结论 | unknown（当前无确认数据；OpenSERP 接入后可转 measured） |
| 可做度 | 15 | 描述关键词（工具类 vs 企业级）；联想词直接可做内容页 | heuristic / unknown |
| 变现潜力 | 10 | 描述关键词 | heuristic / unknown |
| 品牌风险 | 10 | 品牌词表直接匹配 | measured（命中）/ heuristic（未命中） |

## 每日行为

1. 八个可用来源各在 try/except 中独立抓取，失败记日志不中断（Reddit/pytrends 跳过）。
2. 去重：已存在（不分大小写）或 trends-monitor 已淘汰的跳过。
3. 主源新词按总分排序，每天最多加 5 个；联想词长尾独立预算，最多加 5 个。
4. 现有词分数**不自动改**（无新实测数据不调整），只刷新 `updated_at`。
5. 全部来源失败 → 数据保持不变，记日志，不模拟。
6. git commit 本地，通过 GitHub Contents API 自动 push（custom.github 连接器）。
