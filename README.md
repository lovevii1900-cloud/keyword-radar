# 选词雷达监控站

关键词机会监控仪表盘：AI工具词 / 游戏词 双频道，每日自动更新。

## 访问
- 线上：(Cloudflare Pages 部署后填写)
- 本地预览：`python3 -m http.server` 后打开 index.html

## 文件
- `index.html` / `styles.css` / `app.js` — 仪表盘前端（纯静态）
- `data.json` — 关键词数据（每日脚本自动更新）
- `scripts/daily_update.py` — 每日更新脚本

## 自动更新
cron 每日运行 `scripts/daily_update.py`：
1. 抓取 RainbowSea 免费榜单信号
2. 更新 data.json（热度、时间戳）
3. git commit + push → Cloudflare Pages 自动部署

## 数据说明
- Phase 1：AI工具词 8 个关键词（含真实近期词：FLUX 3 Image Klein、Magnific One 等）
- Phase 3：游戏词频道（待接入）
- Phase 4：六维评分引擎（待接入）
