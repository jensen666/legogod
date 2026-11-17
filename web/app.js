// ============================================================
// 前端路由与应用壳：
//   /            创作台（/?job=<id> 选中工作台任务）
//   /history     历史任务（?q=&status=&outcome=&page= 状态写入 URL）
//   /jobs/<id>   任务详情（?tab=work|steps|review；旧 overview/studio/logs 仍可用）
//   /parts       零件目录
// 页面与 Tab 均有独立 URL：pushState + popstate 支持刷新、复制链接与前进/后退；
// 服务端为这些路由返回同一应用壳。每次路由切换先销毁旧页面（3D 离开详情即销毁）。
// ============================================================
import { mountHome } from './pages/home.js';
import { mountHistory } from './pages/history.js';
import { mountJob } from './pages/job.js';
import { mountParts } from './pages/parts.js';
import { subscribe, refreshList, primeHistory } from './tasks.js';

const main = document.getElementById('main');
let cleanup = null;

// ---------- 路由解析 ----------
function parseRoute() {
  const path = location.pathname.replace(/\/+$/, '') || '/';
  const query = new URLSearchParams(location.search);
  if (path === '/' || path === '/index.html') return { page: 'home', query };
  if (path === '/history') return { page: 'history', query };
  if (path.startsWith('/jobs/')) return { page: 'job', id: decodeURIComponent(path.slice('/jobs/'.length)), query };
  if (path === '/parts') return { page: 'parts', query };
  return { page: 'home', query, fallback: path };
}

const TITLES = { home: '创作台', history: '历史任务', job: '任务详情', parts: '零件目录' };

function setActiveNav(page) {
  const key = page === 'job' ? '' : page;
  for (const a of document.querySelectorAll('.topnav nav a')) {
    a.classList.toggle('active', a.dataset.nav === key);
  }
}

// ---------- 渲染当前路由 ----------
let renderSeq = 0;
async function render() {
  if (cleanup) { try { cleanup(); } catch (e) { console.error(e); } cleanup = null; }
  const seq = ++renderSeq;
  const route = parseRoute();
  setActiveNav(route.page);
  document.title = `LEGOGOD · ${TITLES[route.page] || '乐高 Agent 工坊'}`;
  const ctx = { route, query: route.query };
  let node;
  try {
    if (route.page === 'home') node = await mountHome(main, ctx);
    else if (route.page === 'history') node = await mountHistory(main, ctx);
    else if (route.page === 'job') node = await mountJob(main, ctx);
    else node = await mountParts(main, ctx);
  } catch (e) {
    main.innerHTML = `<div class="page"><div class="empty"><div class="big">⚠️</div>` +
      `<p>页面加载失败：${String(e.message || e)}</p>` +
      `<div class="actions"><a class="btn btn-secondary btn-sm" href="/">返回创作台</a></div></div></div>`;
    return;
  }
  if (seq !== renderSeq) {
    // 等待期间路由又变了：立即销毁这次的结果，避免旧页面覆盖新页面
    const d = (typeof node === 'function') ? node : (node && node.destroy) || null;
    if (d) { try { d(); } catch (e) { /* 忽略 */ } }
    return;
  }
  cleanup = (typeof node === 'function') ? node : (node && node.destroy) || null;
}

// ---------- 导航（站内链接统一接管；仅本文件内部使用，不对外导出） ----------
function navigate(to, { replace = false } = {}) {
  const url = new URL(to, location.origin);
  // 记录来源：任务详情「返回」按来源回跳；直接打开详情时默认历史页
  const from = location.pathname + location.search;
  history[replace ? 'replaceState' : 'pushState']({ from }, '', url.pathname + url.search);
  render();
}

window.addEventListener('popstate', render);

document.addEventListener('click', e => {
  if (e.defaultPrevented || e.button !== 0 || e.metaKey || e.ctrlKey || e.shiftKey || e.altKey) return;
  const a = e.target.closest('a[href]');
  if (!a || a.target || a.hasAttribute('download') || a.dataset.ext !== undefined) return;
  const href = a.getAttribute('href');
  if (!href || !href.startsWith('/')) return;
  e.preventDefault();
  navigate(href);
});

// ---------- 导航角标：历史任务页显示进行中数量 ----------
function paintNavCount(list) {
  const el = document.querySelector('[data-nav-running]');
  const n = (list.running || []).length;
  if (!el) return;
  el.hidden = n === 0;
  el.textContent = String(n);
}
subscribe((type, data) => { if (type === 'list') paintNavCount(data); });

// ---------- 启动 ----------
// 先拿到进行中列表与历史快照再渲染：创作台首屏才能按「?job= → 最新进行中 → 最近查看」自动选中
await refreshList();
await primeHistory();
render();
// 列表周期刷新：导航角标 / 切换器 / 历史进行中专区共用（任务状态变化事件之外的兜底）
setInterval(refreshList, 8000);
