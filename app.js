// 选词雷达监控站 — 前端逻辑
let DATA = null;
let TASKS = null;
let currentChannel = 'ai_tools';

const TASK_TYPE_META = {
new_page: { icon: '🎯', label: '新词建页' },
watch: { icon: '👀', label: '观察' },
traffic_rescue: { icon: '📉', label: '流量抢救' },
content_update: { icon: '🔄', label: '内容更新' },
};
const TASK_STATUS_META = {
pending: '待处理',
in_progress: '进行中',
done: '已完成',
};
const TASK_STATUS_ORDER = ['pending', 'in_progress', 'done'];
const TASK_STATUS_ACTION = {
pending: '开始处理',
in_progress: '标记完成',
done: '重新打开',
};
const STATUS_OVERRIDE_KEY = 'radar_task_status_v1';

function getStatusOverrides() {
try { return JSON.parse(localStorage.getItem(STATUS_OVERRIDE_KEY) || '{}'); }
catch (e) { return {}; }
}
function setStatusOverride(id, status) {
const o = getStatusOverrides();
o[id] = status;
try { localStorage.setItem(STATUS_OVERRIDE_KEY, JSON.stringify(o)); } catch (e) {}
}
function taskStatus(t) {
const o = getStatusOverrides();
return o[t.id] || t.status || 'pending';
}

const DIMENSIONS = {
ai_tools: [
{ key: 'trend', label: '趋势动量', weight: 25, max: 25},
{ key: 'demand', label: '搜索需求', weight: 20, max: 20},
{ key: 'vacuum', label: 'SERP真空度', weight: 20, max: 20},
{ key: 'buildable', label: '可做度', weight: 15, max: 15},
{ key: 'monetize', label: '变现潜力', weight: 10, max: 10},
{ key: 'brand', label: '品牌风险', weight: 10, max: 10},
]
};

function scoreClass(s) {
return s >= 60? 'high': s >= 40? 'mid': 'low';
}
function scoreLabel(s) {
return s >= 60? '有机会': s >= 40? '观望': '暂缓';
}
function deltaClass(d) {
if (typeof d === 'string' && d.startsWith('+')) return 'up';
if (typeof d === 'string' && d.startsWith('-')) return 'down';
return 'flat';
}
function trendsClass(t) {
if (t.includes('上涨') || t.includes('上')) return 'up';
if (t.includes('下降') || t.includes('下')) return 'down';
return 'flat';
}

function drawSpark(canvas, data) {
const ctx = canvas.getContext('2d');
const w = canvas.width = 110, h = canvas.height = 34;
const min = Math.min(...data), max = Math.max(...data);
const range = max - min || 1;
ctx.clearRect(0, 0, w, h);
ctx.strokeStyle = '#43a047';
ctx.lineWidth = 2;
ctx.beginPath();
data.forEach((v, i) => {
const x = (i / (data.length - 1)) * (w - 4) + 2;
const y = h - 4 - ((v - min) / range) * (h - 8);
i === 0? ctx.moveTo(x, y): ctx.lineTo(x, y);
});
ctx.stroke();
// fill under
ctx.lineTo(w - 2, h); ctx.lineTo(2, h); ctx.closePath();
ctx.fillStyle = 'rgba(67,160,71,.12)';
ctx.fill();
}

function compLevelClass(level) {
if (level === '激烈') return 'high';
if (level === '中等') return 'mid';
return '';
}

function renderTable(keywords) {
const body = document.getElementById('kwBody');
body.innerHTML = '';
// sort by score desc
const sorted = [...keywords].sort((a, b) => b.score - a.score);
sorted.forEach((kw, idx) => {
const tr = document.createElement('tr');

const bars = kw.competition.bars.map(b =>
`<span class="${b === 1? 'f1': b === 2? 'f2': b === 3? 'f3': ''}"></span>`
).join('');

tr.innerHTML = `
<td class="col-term" data-label="">
<div class="kw-term">${kw.term_cn}</div>
<div class="kw-term-cn">${kw.term}</div>
</td>
<td data-label="曲线">
<div class="spark-wrap">
<canvas id="spark-${idx}"></canvas>
<span class="spark-count">${kw.spark_count} ${kw.spark_unit}</span>
</div>
</td>
<td data-label="标签">
<div class="tags">${kw.tags.map(t => `<span class="tag ${t.type}">${t.text}</span>`).join('')}</div>
</td>
<td data-label="机会等级">
<span class="score-badge ${scoreClass(kw.score)}">${kw.score} ${scoreLabel(kw.score)}</span>
</td>
<td data-label="热度"><span class="heat-num">${kw.heat.toLocaleString()}</span></td>
<td data-label="较上次"><span class="delta ${deltaClass(kw.heat_delta)}">${kw.heat_delta}</span></td>
<td data-label="真空度">
<div class="vacuum-bar">
<div class="vacuum-track"><div class="vacuum-fill" style="width:${kw.vacuum}%;background:${kw.vacuum >= 60? '#43a047': kw.vacuum >= 40? '#fb8c00': '#b0b5bf'}"></div></div>
<span class="vacuum-num">${kw.vacuum}</span>
</div>
</td>
<td data-label="Trends"><span class="trends-tag ${trendsClass(kw.trends)}">${kw.trends}</span></td>
<td data-label="首页竞争">
<div class="comp-bars">${bars}</div>
<span class="comp-level ${compLevelClass(kw.competition.level)}">${kw.competition.level}</span>
<div class="comp-detail">${kw.competition.details}</div>
</td>
<td data-label=""><button class="review-btn" data-idx="${idx}">深审报告</button></td>
`;
body.appendChild(tr);
drawSpark(document.getElementById(`spark-${idx}`), kw.spark);
});

// wire review buttons
body.querySelectorAll('.review-btn').forEach(btn => {
btn.addEventListener('click', () => showReview(sorted[+btn.dataset.idx]));
});
}

function showReview(kw) {
const dims = DIMENSIONS.ai_tools;
// derive dimension scores from available data (mock logic for Phase 1)
const d = [
{...dims[0], score: Math.min(25, Math.round(kw.spark[kw.spark.length - 1] / 4)), note: `近${kw.spark_count}${kw.spark_unit}趋势${kw.trends}`},
{...dims[1], score: Math.min(20, Math.round(kw.heat / 200)), note: `热度指数 ${kw.heat.toLocaleString()}`},
{...dims[2], score: Math.round(kw.vacuum / 5), note: `真空度 ${kw.vacuum}/100`},
{...dims[3], score: 12, note: '内容页可做，工具页视模型API'},
{...dims[4], score: 7, note: 'AI工具站变现路径成熟'},
{...dims[5], score: kw.term.includes('flux') || kw.term.includes('nano') || kw.term.includes('gpt') || kw.term.includes('magnific') || kw.term.includes('krea') || kw.term.includes('qwen')? 4: 9, note: '品牌词，长尾为主'},
];
const total = d.reduce((s, x) => s + x.score, 0);
const verdict = total >= 60? ['go', '✅ 建议做', '机会明确，内容页先行，一天可出。']
: total >= 40? ['wait', '⏳ 观望', '再观察几天趋势，或等竞争格局变化。']
: ['skip', '⏭ 暂缓', '窗口已过或竞争过强，不投入。'];

document.getElementById('modalTitle').textContent = `${kw.term_cn}`;
document.getElementById('modalBody').innerHTML = `
<div style="margin-bottom:14px;font-size:15px">综合评分：<b style="font-size:22px">${total}</b> / 100（${scoreLabel(total)}）</div>
${d.map(x => `
<div class="dim-row">
<div class="dim-head"><span>${x.label}（${x.weight}%）</span><span><b>${x.score}</b> / ${x.max}</span></div>
<div class="dim-track"><div class="dim-fill" style="width:${(x.score / x.max) * 100}%"></div></div>
<div class="dim-note">${x.note}</div>
</div>`).join('')}
<div class="verdict ${verdict[0]}"><b>${verdict[1]}</b><br>${verdict[2]}</div>
`;
document.getElementById('modalBackdrop').classList.add('open');
}

function renderDaily(keywords) {
const cards = document.getElementById('dailyCards');
const top = [...keywords].sort((a, b) => b.score - a.score)[0];
const rising = keywords.filter(k => k.trends.includes('上涨')).length;
const avgVacuum = Math.round(keywords.reduce((s, k) => s + k.vacuum, 0) / keywords.length);
cards.innerHTML = `
<div class="daily-card"><div class="dc-num">${keywords.length}</div><div class="dc-label">监控关键词</div></div>
<div class="daily-card"><div class="dc-num">${rising}</div><div class="dc-label">趋势上涨</div></div>
<div class="daily-card"><div class="dc-num">${avgVacuum}</div><div class="dc-label">平均真空度</div></div>
<div class="daily-card"><div class="dc-num" style="font-size:20px">${top? top.term_cn: '—'}</div><div class="dc-label">最高机会（${top? top.score: '—'}分）</div></div>
`;
}

function switchChannel(ch) {
currentChannel = ch;
document.querySelectorAll('.nav-item[data-channel]').forEach(b =>
b.classList.toggle('active', b.dataset.channel === ch));
document.querySelectorAll('.view').forEach(v => v.classList.remove('active'));

if (ch === 'ai_tools') {
document.getElementById('view-ai_tools').classList.add('active');
document.getElementById('channelTitle').textContent = 'AI工具词';
renderTable(DATA.channels.ai_tools.keywords);
} else if (ch === 'games') {
document.getElementById('view-games').classList.add('active');
document.getElementById('channelTitle').textContent = '游戏词';
}
// close sidebar on mobile
document.getElementById('sidebar').classList.remove('open');
}

function taskCard(t) {
const m = TASK_TYPE_META[t.type] || { icon: '📝', label: t.type };
const st = taskStatus(t);
const nextStatus = st === 'pending' ? 'in_progress' : st === 'in_progress' ? 'done' : 'pending';
const created = (t.created_at || '').slice(0, 10);
return `
<div class="task-card" data-task-id="${t.id}">
<div class="task-type"><span>${m.icon}</span> ${m.label}</div>
<div class="task-term">${t.term_cn || ''}</div>
<div class="task-term-en">${t.term || ''}</div>
<div class="task-meta">
<span class="score-badge ${scoreClass(t.priority || 0)}">${t.priority || 0}分</span>
<span class="task-date">创建 ${created}</span>
</div>
<div class="task-action">${t.action || ''}</div>
<div class="task-btns">
<button class="task-btn status" data-act="status" data-next="${nextStatus}">${TASK_STATUS_ACTION[st]}</button>
<button class="task-btn draft" data-act="draft">生成草稿</button>
${t.draft ? `<button class="task-btn publish" data-act="publish">发布</button>` : ''}
</div>
</div>`;
}

function renderTasks() {
const board = document.getElementById('kanban');
if (!TASKS || !TASKS.tasks) {
board.innerHTML = '<div class="kanban-empty">任务数据加载中…</div>';
return;
}
board.innerHTML = TASK_STATUS_ORDER.map(st => {
const list = TASKS.tasks
.filter(t => taskStatus(t) === st)
.sort((a, b) => (b.priority || 0) - (a.priority || 0));
return `
<div class="kanban-col">
<div class="kanban-head"><span>${TASK_STATUS_META[st]}</span><span class="kanban-count">${list.length}</span></div>
<div class="kanban-list">
${list.length ? list.map(taskCard).join('') : '<div class="kanban-empty">暂无任务</div>'}
</div>
</div>`;
}).join('');

// wire buttons
board.querySelectorAll('.task-btn').forEach(btn => {
btn.addEventListener('click', (e) => {
const card = e.target.closest('.task-card');
const id = card.dataset.taskId;
const act = e.target.dataset.act;
if (act === 'status') {
setStatusOverride(id, e.target.dataset.next);
renderTasks();
} else if (act === 'draft') {
showDraftInfo(id);
} else if (act === 'publish') {
alert('发布功能第二阶段上线：草稿需你审批后才会发布。');
}
});
});
}

function showDraftInfo(id) {
const t = (TASKS.tasks || []).find(x => x.id === id);
if (!t) return;
document.getElementById('modalTitle').textContent = `📝 草稿生成（第二阶段）`;
document.getElementById('modalBody').innerHTML = `
<div style="font-size:14px;line-height:1.8">
<p><b>${t.term_cn}</b>（${t.term}） · ${t.priority}分</p>
<p style="margin-top:10px;color:var(--muted)">第二阶段上线后，AI 会按下面这条建议自动写好页面草稿，推到 GitHub 等你点"发布"：</p>
<div class="task-action" style="margin-top:10px">${t.action || ''}</div>
<p style="margin-top:10px;color:var(--muted)">现在你可以先手动按这条建议建页，建完点"标记完成"。不自动发布，决定权在你手里。</p>
</div>`;
document.getElementById('modalBackdrop').classList.add('open');
}

function showTasks() {
document.querySelectorAll('.nav-item').forEach(b => b.classList.remove('active'));
document.querySelector('[data-view="tasks"]').classList.add('active');
document.querySelectorAll('.view').forEach(v => v.classList.remove('active'));
document.getElementById('view-tasks').classList.add('active');
document.getElementById('channelTitle').textContent = '任务看板';
renderTasks();
document.getElementById('sidebar').classList.remove('open');
}

function showDaily() {
document.querySelectorAll('.nav-item').forEach(b => b.classList.remove('active'));
document.querySelector('[data-view="daily"]').classList.add('active');
document.querySelectorAll('.view').forEach(v => v.classList.remove('active'));
document.getElementById('view-daily').classList.add('active');
document.getElementById('channelTitle').textContent = '日报总览';
renderDaily(DATA.channels.ai_tools.keywords);
document.getElementById('sidebar').classList.remove('open');
}

async function init() {
const res = await fetch('data.json');
DATA = await res.json();
try {
const tres = await fetch('tasks.json');
TASKS = await tres.json();
} catch (e) { TASKS = { tasks: [] }; }

document.getElementById('updateTime').textContent =
new Date(DATA.updated_at).toLocaleString('zh-CN', { hour12: false});

document.querySelectorAll('.nav-item[data-channel]').forEach(b =>
b.addEventListener('click', () => switchChannel(b.dataset.channel)));
document.querySelector('[data-view="tasks"]').addEventListener('click', showTasks);
document.querySelector('[data-view="daily"]').addEventListener('click', showDaily);

document.getElementById('menuBtn').addEventListener('click', () =>
document.getElementById('sidebar').classList.toggle('open'));
document.getElementById('modalClose').addEventListener('click', () =>
document.getElementById('modalBackdrop').classList.remove('open'));
document.getElementById('modalBackdrop').addEventListener('click', e => {
if (e.target.id === 'modalBackdrop')
document.getElementById('modalBackdrop').classList.remove('open');
});

switchChannel('ai_tools');
}

init();
