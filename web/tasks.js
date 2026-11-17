// ============================================================
// 任务数据层：
// - 每个任务独立轮询器与日志缓存：创作台工作台与详情「运行记录」共用同一数据源，
//   后台任务只把增量写进自己的缓存，绝不抢占当前视图（不串台）
// - 零件目录懒加载（创作台不再等待 /api/parts）
// - 进行中任务列表周期刷新：导航角标、切换器、历史进行中专区共用
// - 所有网络调用统一走 web/api.js（Base URL/超时/错误对象/requestId），本文件不再直接 fetch
// ============================================================
import { sleep } from './ui.js';
import { buildJobPayload } from './modes.js';
import { api, apiUrl } from './api.js';

// ---------- 事件订阅（'job' 单任务更新；'list' 进行中/总数变化） ----------
const listeners = new Set();
export function subscribe(fn) { listeners.add(fn); return () => listeners.delete(fn); }
function emit(type, data) { for (const fn of listeners) { try { fn(type, data); } catch (e) { console.error(e); } } }

// ---------- 零件目录（懒加载；唯一数据源 /api/parts） ----------
let partsPromise = null;
export function getParts(force = false) {
  if (!partsPromise || force) {
    // 失败时保留 rejected promise（与迁移前一致）：零件页用 force=true 手动重试。
    partsPromise = api.parts().then(d => (d && d.parts) || []);
  }
  return partsPromise;
}

// ---------- 任务缓存与轮询 ----------
// 缓存条目：{ id, logs:[], status, result, live, desc, startedAt, seen(重绘游标), studio:{tab,step} }
const jobCache = new Map();
const pollers = new Map();
// 最近查看的任务（切换器保留 5 个；sessionStorage 持久化，刷新后仍可兜底选中）
const RECENT_KEY = 'legogod-recent-jobs';
let recentIds = [];
try { recentIds = JSON.parse(sessionStorage.getItem(RECENT_KEY)) || []; } catch (e) { recentIds = []; }

function cacheOf(id) { return jobCache.get(id); }

export function touchRecent(id) {
  const i = recentIds.indexOf(id);
  if (i >= 0) recentIds.splice(i, 1);
  recentIds.unshift(id);
  if (recentIds.length > 5) recentIds.length = 5;
  try { sessionStorage.setItem(RECENT_KEY, JSON.stringify(recentIds)); } catch (e) { /* 忽略 */ }
}

export function recentJobs() {
  // 整页刷新后 jobCache 还是空的：返回 id 存根即可（switchTo 会按 id 拉取任务）
  return recentIds.map(id => cacheOf(id) || { id, desc: '' });
}

// 产物相对路径必须按配置的 API Base URL 解析：服务端下发的评审图是
// /views/<name> 相对路径，独立部署时静态页所在源不提供产物，统一换成完整地址后 <img src>
// 才指向真实 API；已是绝对 URL 的值（历史/未来兼容）保持不变。
function resolveArtifact(value) {
  if (typeof value !== 'string' || !value) return value;
  return value.startsWith('/') ? apiUrl(value) : value;
}

function resolveViews(value) {
  if (!value || typeof value !== 'object') return value;
  const out = {};
  for (const [key, url] of Object.entries(value)) out[key] = resolveArtifact(url);
  return out;
}

function adopt(job) {
  // 服务端任务快照并入缓存：logs 只追加，其余字段覆盖
  let c = jobCache.get(job.id);
  if (!c) {
    c = { id: job.id, logs: [], status: job.status, result: job.result || null,
          live: job.live || null, desc: job.desc || '', startedAt: job.startedAt || null,
          mode: job.mode || null, retryOf: job.retryOf || null,
          design: null, progress: null, stage: null, views: null, thinking: null,
          studio: { tab: null, step: 0 } };
    jobCache.set(job.id, c);
  }
  if (Array.isArray(job.logs)) takeLogs(c, job.logs);
  c.status = job.status;
  c.result = job.result ?? c.result;
  c.live = job.live ?? null;
  if (job.desc) c.desc = job.desc;
  if (job.startedAt) c.startedAt = job.startedAt;
  if (job.mode) c.mode = job.mode;
  if (job.retryOf) c.retryOf = job.retryOf;
  if (job.design !== undefined) c.design = job.design;
  if (job.progress !== undefined) c.progress = job.progress;
  if (job.stage !== undefined) c.stage = job.stage;
  if (job.views !== undefined) c.views = resolveViews(job.views);
  if (job.thinking !== undefined) c.thinking = job.thinking;
  if (job.colors) c.colors = job.colors;
  if (job.grid) c.grid = job.grid;
  if (job.layers != null) c.layers = job.layers;
  if (job.pieces != null) c.pieces = job.pieces;
  return c;
}

function sameLog(a, b) {
  return !!a && !!b && a.ts === b.ts && a.kind === b.kind && a.text === b.text;
}

// 噪音淘汰会改写列表，不能再按「只在末尾追加」合并，否则会串行或漏掉关键事件。
function takeLogs(c, incoming) {
  const prev = c.logs;
  let prefix = incoming.length >= prev.length && prev.every((row, i) => sameLog(row, incoming[i]));
  if (prefix) {
    c.logsReset = false;
    for (let i = prev.length; i < incoming.length; i++) c.logs.push(incoming[i]);
    return;
  }
  c.logs = incoming.slice();
  c.logsReset = true;
}

// 拉取单个任务并入缓存（unknown job 抛错由调用方处理；错误信息取 ApiError.message）
export async function fetchJob(id) {
  return adopt(await api.job(id, { timeout: 10000 }));
}

// 每个任务一个轮询器：增量写自己的缓存并广播；连续失败 5 次停止（服务不可用）
function startPoller(id) {
  if (pollers.has(id)) return;
  pollers.set(id, true);
  (async () => {
    let fails = 0;
    for (;;) {
      let job;
      try {
        job = await api.job(id, { timeout: 10000 });
        fails = 0;
      } catch (e) {
        if (++fails >= 5) {
          pollers.delete(id);
          emit('job', { id, error: `与服务端通信失败 ${fails} 次，已停止轮询：${e.message || e}` });
          refreshList();
          return;
        }
        await sleep(1200); continue;
      }
      adopt(job);
      emit('job', { id });
      if (job.status !== 'running') { pollers.delete(id); refreshList(); return; }
      await sleep(900);
    }
  })();
}

export function ensurePoller(id) { startPoller(id); }

// ---------- 操作：发起 / 取消 / 重试 ----------
// Web 始终显式提交用户所见的模式：默认快速；API 省略 mode 的 fidelity 缺省语义
// 只服务于既有外部调用方，前端绝不依赖它。
export async function startJob(desc, mode) {
  const payload = buildJobPayload(desc, mode);
  const { id } = await api.build(payload.desc, payload.mode);
  jobCache.set(id, { id, logs: [], status: 'running', result: null, live: null,
                     desc, mode: payload.mode, startedAt: null, design: null, progress: null,
                     stage: null, views: null, thinking: null,
                     studio: { tab: null, step: 0 } });
  touchRecent(id);
  emit('job', { id });
  startPoller(id);
  refreshList();
  return id;
}

export async function cancelJob(id) {
  await api.cancel(id);
  const c = cacheOf(id);
  if (c && c.status === 'running') { c.status = 'cancelled'; c.live = null; }
  emit('job', { id });
  refreshList();
}

// 手动重试：新任务沿用原任务模式（服务端解析并返回），前端缓存用于即时展示。
export async function retryJob(id) {
  const { id: newId, mode: newMode } = await api.retry(id);
  const orig = cacheOf(id) || {};
  const mode = (newMode === 'fast' || newMode === 'fidelity') ? newMode : (orig.mode || null);
  jobCache.set(newId, { id: newId, logs: [], status: 'running', result: null, live: null,
                        desc: orig.desc || '', mode, startedAt: null, design: null, progress: null,
                        stage: null, views: null, thinking: null, retryOf: id,
                        studio: { tab: null, step: 0 } });
  touchRecent(newId);
  emit('job', { id: newId });
  startPoller(newId);
  refreshList();
  return newId;
}

// ---------- 进行中列表与总数（导航角标 / 切换器 / 历史进行中专区共用） ----------
let listState = { running: [], total: null };
export function listSnapshot() { return listState; }

export async function refreshList() {
  try {
    // 带最小分页参数：只取 running 数组与 total，不拉全量历史
    const d = await api.jobs({ page: 1, pageSize: 1 }, { timeout: 8000 });
    listState = { running: (d && d.running) || [], total: d ? (d.total ?? null) : null };
    emit('list', listState);
  } catch (e) { /* 服务不可用：保留上次快照 */ }
}

// ---------- 历史分页查询（历史页专用） ----------
export async function fetchJobsPage({ q = '', status = '', outcome = '', page = 1, pageSize = 20 } = {}) {
  // 非空 q/status/outcome 与 page/pageSize 由 api.jobs 统一拼查询串（数字字符串化）
  return api.jobs({ q, status, outcome, page, pageSize }, { timeout: 10000 });
}

// 首次进入时拉一份历史快照，供切换器「最近任务」兜底展示名称
export async function primeHistory() {
  try {
    const d = await fetchJobsPage({ page: 1, pageSize: 50 });
    for (const j of (d.jobs || [])) {
      if (!jobCache.has(j.id)) {
        jobCache.set(j.id, { id: j.id, logs: [], status: j.status, result: null, live: null,
                             desc: j.desc || '', startedAt: j.startedAt, name: j.name || '',
                             mode: j.mode || null,
                             colors: j.colors || null, grid: j.grid || null, layers: j.layers,
                             pieces: j.pieces, thinking: null, studio: { tab: null, step: 0 } });
      } else {
        const c = jobCache.get(j.id);
        if (j.name && !c.name) c.name = j.name;
        if (j.mode) c.mode = j.mode;
        if (j.colors) c.colors = j.colors;
      }
    }
  } catch (e) { /* 历史不可用不影响创作台 */ }
}

export function jobName(id) {
  const c = cacheOf(id);
  if (!c) return id;
  return (c.result && c.result.name) || c.name || c.desc || id;
}
