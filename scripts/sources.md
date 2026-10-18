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

## 11. Sitemap 盯梢（哥飞方法，2026-10-19 新增）

- **方法来源**：哥飞公众号文章《找不到新词？用 Sitemap 盯住同行最近更新的页面》（2026-10-18）。核心：监控高频上新的同行站 sitemap，两次抓取做 diff，新出现的工具页 URL 就是候选词。
- **监控清单**（`scripts/sitemap_sites.json`，7 个，全部实测 sitemap 可达）：
  | 站点 | 工具页 URL 格式 | 基线量 |
  |------|----------------|--------|
  | toolify.ai | `/tool/{slug}`（只取尾部 3 个子 sitemap） | ~5.8k |
  | futuretools.io | `/tools/{slug}-{8位hash}`（strip hash） | ~4.4k |
  | opentools.ai | `/tools/{slug}` | ~6.6k |
  | aidirectory.com | `/{slug}`（sitemap/tools.xml 已限定） | ~2.5k |
  | toolpilot.ai | `/products/{slug}`（Shopify） | ~3.4k |
  | aitoptools.com | 直连 urlset | ~11k |
  | aiassistantstore.com | `/products/{slug}`（Shopify） | ~60 |
- **基线**：`scripts/sitemap_baseline.json`（domain → [url]），首次运行只建基线不产出。
- **提词规则**：slug 清洗（去 hash、去首尾连字符）→ term；<3 字符、纯 hash、纯数字、成人词直接丢弃；分页/tag/author URL 跳过。
- **打分**：趋势动量 heuristic（同行新上架=对方编辑认为值得收录）；可做度 heuristic 高分（同行已做成工具页，可对标）；SERP真空度 unknown。
- **局限**（如实标注）：
  - lastmod ≠ 发布时间，diff 只看"新出现"不看 lastmod，避免误报。
  - toolify 只监控尾部 3 个子 sitemap（每个 2 万 URL，全量成本过高）；新工具理论上集中在尾部。
  - 有些站用 CDATA / `&amp;` 转义，已做兼容；aivalley.ai（新闻站非工具目录）、insidr.ai（仅 1 个产品页）已剔除。
  - sitemap 本身可能滞后 1 天；部分站可能屏蔽非常规 UA（当前 UA 正常）。

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

1. 九个可用来源各在 try/except 中独立抓取，失败记日志不中断（Reddit/pytrends 跳过）。
2. 去重：已存在（不分大小写）或 trends-monitor 已淘汰的跳过。
3. 主源新词按总分排序，每天最多加 5 个；联想词长尾独立预算，最多加 5 个。
4. 现有词分数**不自动改**（无新实测数据不调整），只刷新 `updated_at`。
5. 全部来源失败 → 数据保持不变，记日志，不模拟。
6. git commit 本地，通过 GitHub Contents API 自动 push（custom.github 连接器）。

---

## 游戏词频道数据源（2026-10-18 新增）

### G1. Steam 商店搜索（主来源）
- **地址**：`https://store.steampowered.com/search/results/?...&filter=topsellers|popularcomingsoon`
- **提供**：新品榜（Released_DESC 排序）+ 即将发布榜（popularcomingsoon），appid + 名字 slug。
- **局限**：
  - 返回的是 JSON 包裹的转义 HTML，需两次 unescape（`\"`→`"`，`\/`→`/`）。
  - 名字从 URL slug 取，偶有缺空格（如 `CielviaInherited By Defeat`），不影响关键词使用。

### G2. Steam appdetails API
- **地址**：`https://store.steampowered.com/api/appdetails?appids={单个id}&filters=release_date,genres,short_description`
- **提供**：发布日期、coming_soon 标记、类型、简介（实测）。
- **局限**：
  - **仅支持单个 appid**（多 id 返回 400）；`name` 不在 filters 白名单，用搜索页 slug 名。
  - 每次 1s 间隔，每天最多查 25 个。

### G3. Google 联想词（攻略需求实测）
- 对候选游戏名查 `{名} wiki / guide / walkthrough / release date` 联想命中数。
- 命中 ≥3/4 = 玩家已在搜攻略，建站窗口正在打开；0 命中 = 太早或没人搜。

### 过滤规则（只收最新的）
- 近 30 天发布，或 coming_soon=true（铺词黄金期）→ 收
- 30–60 天 → 跳过（除非后续接更新检测）
- >60 天 → 淘汰
- 3A 大厂系列（Franchise 黑名单）、成人向 → 跳过

### 游戏评分维度状态
| 维度 | 权重 | 依据 | 状态 |
|------|------|------|------|
| 玩家动量 | 25 | Steam 发布日期/coming_soon | measured |
| 搜索需求 | 20 | 联想词攻略命中数 | measured |
| SERP机会 | 20 | 待 OpenSERP | unknown |
| 机制深度 | 15 | Steam 类型 → 启发式 | heuristic |
| 工具潜力 | 10 | 类型 → 启发式 | heuristic |
| 品牌纯净 | 10 | 续作正则 → 启发式 | heuristic |
