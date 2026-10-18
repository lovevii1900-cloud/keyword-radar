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

## 评分维度状态说明

| 维度 | 权重 | 主要依据 | 状态 |
|------|------|----------|------|
| 趋势动量 | 25 | RainbowSea 排名历史首尾比 | measured（有历史）/ heuristic（HF）/ unknown |
| 搜索需求 | 20 | 来源数 + 增长倍数 | heuristic |
| SERP真空度 | 20 | trends-monitor 确认结论 | unknown（当前无确认数据） |
| 可做度 | 15 | 描述关键词（工具类 vs 企业级） | heuristic / unknown |
| 变现潜力 | 10 | 描述关键词 | heuristic / unknown |
| 品牌风险 | 10 | 品牌词表直接匹配 | measured（命中）/ heuristic（未命中） |

## 每日行为

1. 四个来源各在 try/except 中独立抓取，失败记日志不中断。
2. 去重：已存在（不分大小写）或 trends-monitor 已淘汰的跳过。
3. 新词按总分排序，每天最多加 5 个。
4. 现有词分数**不自动改**（无新实测数据不调整），只刷新 `updated_at`。
5. 全部来源失败 → 数据保持不变，记日志，不模拟。
6. git commit 本地，push 需要 `GITHUB_TOKEN`（无则记日志跳过）。
