// ============================================================
// 历史任务：
// - 进行中专区置顶（耗时、查看进度、独立取消），无进行中任务不占空间
// - 紧凑行列表：状态、名称/需求（最多两行）、发起时间、零件数、≤2 个高频操作
// - 按名称/需求/任务 ID 搜索，按执行状态与交付结果筛选，默认最新在前
// - 服务端分页每页 20 条；搜索、筛选、分页状态写入 URL（刷新可恢复）
// - 三种空态：尚无历史 / 筛选无结果 / 加载失败；interrupted 可回看
// ============================================================
import { esc, statusTag, fmtDateTime, fmtElapsed, debounce, modeBadge } from '../ui.js';
import { paletteHTML } from '../palette.js';
import { fetchJobsPage, cancelJob, retryJob, subscribe, listSnapshot } from '../tasks.js';

const PAGE_SIZE = 20;
const STATUS_OPTS = [
  ['', '全部状态'], ['running', '进行中'], ['done', '已完成'],
  ['error', '失败'], ['cancelled', '已取消'], ['interrupted', '已中断'],
];
const OUTCOME_OPTS = [
  ['', '全部交付结果'], ['fidelity_success', '高保真成功'], ['fidelity_degraded', '降级交付'],
  ['fast_fallback', '快速保底'], ['fast_success', '快速成功'], ['failed', '生成失败'],
  ['cancelled', '已取消'],
];

export async function mountHistory(root, ctx) {
  const q0 = ctx.query;
  const state = {
    q: q0.get('q') || '', status: q0.get('status') || '',
    outcome: q0.get('outcome') || '', page: Math.max(1, parseInt(q0.get('page'), 10) || 1),
  };

  root.innerHTML = `
  <div class="page">
    <div class="page-head">
      <h1 class="page-title">历史任务</h1>
      <span class="hint" data-total></span>
    </div>
    <div class="filters">
      <input type="search" data-q placeholder="搜索名称、需求或任务 ID" aria-label="搜索历史任务">
      <select data-status aria-label="按执行状态筛选"></select>
      <select data-outcome aria-label="按交付结果筛选"></select>
      <button class="btn btn-secondary btn-sm" type="button" data-reset>重置</button>
    </div>
    <div class="runzone" data-runzone></div>
    <div class="panel"><div class="rowlist" data-list></div></div>
    <div class="pager" data-pager></div>
  </div>`;

  const $ = s => root.querySelector(s);
  const listEl = $('[data-list]'), runzoneEl = $('[data-runzone]'),
        pagerEl = $('[data-pager]'), totalEl = $('[data-total]');

  $('[data-status]').innerHTML = STATUS_OPTS.map(([v, t]) =>
    `<option value="${v}">${t}</option>`).join('');
  $('[data-outcome]').innerHTML = OUTCOME_OPTS.map(([v, t]) =>
    `<option value="${v}">${t}</option>`).join('');
  $('[data-q]').value = state.q;
  $('[data-status]').value = state.status;
  $('[data-outcome]').value = state.outcome;

  // ---------- URL 同步：筛选/分页写入 URL ----------
  function syncUrl(push) {
    const qs = new URLSearchParams();
    if (state.q) qs.set('q', state.q);
    if (state.status) qs.set('status', state.status);
    if (state.outcome) qs.set('outcome', state.outcome);
    if (state.page > 1) qs.set('page', String(state.page));
    const url = '/history' + (qs.toString() ? '?' + qs.toString() : '');
    history[push ? 'pushState' : 'replaceState']({ from: history.state && history.state.from }, '', url);
  }

  // ---------- 行渲染 ----------
  // 每行最多两个高频操作：done 一律视为可回看成果（存量任务可能没有 outcome，
  // outcome 只用于状态标签与筛选）；失败→查看原因+重试；取消/中断→查看详情+重试
  function actionsOf(j) {
    if (j.status === 'done') {
      return `<a class="btn btn-secondary btn-sm" href="/jobs/${encodeURIComponent(j.id)}">查看作品</a>` +
             `<a class="btn btn-secondary btn-sm" href="/jobs/${encodeURIComponent(j.id)}?tab=steps">拼装步骤</a>`;
    }
    if (j.status === 'error') {
      return `<a class="btn btn-secondary btn-sm" href="/jobs/${encodeURIComponent(j.id)}?tab=review">查看原因</a>` +
             `<button class="btn btn-secondary btn-sm" type="button" data-retry="${esc(j.id)}">重试</button>`;
    }
    if (j.status === 'cancelled' || j.status === 'interrupted') {
      return `<a class="btn btn-secondary btn-sm" href="/jobs/${encodeURIComponent(j.id)}?tab=review">查看详情</a>` +
             (j.desc ? `<button class="btn btn-secondary btn-sm" type="button" data-retry="${esc(j.id)}">重试</button>` : '');
    }
    if (j.status === 'running') {
      return `<a class="btn btn-secondary btn-sm" href="/?job=${encodeURIComponent(j.id)}">查看进度</a>` +
             `<button class="btn btn-danger btn-sm" type="button" data-cancel="${esc(j.id)}">✕ 取消</button>`;
    }
    return '';
  }

  function specOf(j) {
    const bits = [];
    if (j.grid && j.grid.w && j.grid.d) bits.push(`${j.grid.w}×${j.grid.d}`);
    if (j.pieces !== undefined && j.pieces !== null) bits.push(`${j.pieces} 块`);
    if (typeof j.layers === 'number') bits.push(`${j.layers} 层`);
    return bits.join(' · ');
  }

  function rowHTML(j) {
    const name = j.name || j.desc || j.id;
    const desc = j.desc && j.name ? j.desc : '';
    const spec = specOf(j);
    return `<div class="rowitem">
      <span data-tag>${statusTag(j)}</span>
      <div class="rdesc" style="min-width:0">
        <div class="rname" title="${esc(name)}">${esc(name)}${modeBadge(j.mode)}<span class="jid">${esc(j.id)}</span></div>
        ${desc ? `<div class="clamp2" title="${esc(desc)}">${esc(desc)}</div>` : ''}
        ${j.status === 'error' && j.error ? `<div class="hint clamp2 err-text" title="${esc(j.error)}">${esc(j.error)}</div>` : ''}
      </div>
      <span class="rpalette">${paletteHTML(j.colors)}</span>
      <span class="rpieces">${spec ? esc(spec) : '—'}</span>
      <span class="rtime">${fmtDateTime(j.startedAt)}</span>
      <span class="ractions">${actionsOf(j)}</span>
    </div>`;
  }

  // ---------- 进行中专区（独立取消；无进行中不占空间） ----------
  // 用户筛选 status=running 时主列表本身就是进行中任务，隐藏专区避免同一任务出现两次
  function renderRunzone() {
    const running = listSnapshot().running;
    if (!running.length || state.status === 'running') {
      runzoneEl.innerHTML = ''; runzoneEl.style.display = 'none'; return;
    }
    runzoneEl.style.display = '';
    runzoneEl.innerHTML = '<div class="section-title">进行中</div>' + running.map(j => `
      <div class="runrow">
        <span class="ic">⏳</span>
        <span class="nm" title="${esc(j.desc || j.name || j.id)}">${esc((j.name || j.desc || j.id).slice(0, 40))}</span>
        <span class="elapsed" data-started="${j.startedAt || ''}">耗时 —</span>
        <span style="flex:1 1 auto"></span>
        <a class="btn btn-secondary btn-sm" href="/?job=${encodeURIComponent(j.id)}">查看进度</a>
        <button class="btn btn-danger btn-sm" type="button" data-cancel="${esc(j.id)}">✕ 取消</button>
      </div>`).join('');
    tickElapsed();
  }

  function tickElapsed() {
    for (const el of runzoneEl.querySelectorAll('.elapsed')) {
      const t = parseFloat(el.dataset.started);
      el.textContent = t ? `耗时 ${fmtElapsed(t)}` : '耗时 —';
    }
  }
  const elapsedTimer = setInterval(tickElapsed, 1000);

  // ---------- 主列表加载与空态 ----------
  // 首次/用户主动筛选才显示加载态；周期性后台刷新静默进行：数据没变不重绘（避免 8s 闪屏
  // 与焦点丢失），请求失败保留旧列表
  let hasLoaded = false, lastSig = null;
  async function load({ silent = false } = {}) {
    if (!silent || !hasLoaded) {
      listEl.innerHTML = '<div class="empty"><span class="spin">⏳</span><p>加载中……</p></div>';
      pagerEl.innerHTML = '';
    }
    try {
      const d = await fetchJobsPage(state);
      const sig = JSON.stringify([d.jobs, d.total, d.page, d.pages]);
      if (silent && hasLoaded && sig === lastSig) return;  // 数据没变：不动 DOM
      lastSig = sig;
      hasLoaded = true;
      const n = (d.jobs || []).length;
      totalEl.textContent = d.total === null ? '' : `共 ${d.total} 条`;
      if (!n && d.total === 0 && !state.q && !state.status && !state.outcome) {
        listEl.innerHTML = `<div class="empty"><div class="big">🧱</div>
          <p>还没有历史任务。</p>
          <div class="actions"><a class="btn btn-sm" href="/">去创作台开始第一次拼装</a></div></div>`;
        pagerEl.innerHTML = '';
        return;
      }
      if (!n) {
        listEl.innerHTML = `<div class="empty"><div class="big">🔍</div>
          <p>没有匹配的任务。</p>
          <div class="actions"><button class="btn btn-secondary btn-sm" type="button" data-clear>清除搜索与筛选</button></div></div>`;
        listEl.querySelector('[data-clear]').addEventListener('click', clearFilters);
        pagerEl.innerHTML = '';
        return;
      }
      listEl.innerHTML = `<div class="rowhead"><span>状态</span><span>作品</span><span>配色</span><span>规格</span><span>时间</span><span></span></div>` +
        d.jobs.map(rowHTML).join('');
      const pages = d.pages || 1;
      pagerEl.innerHTML = `
        <span class="pginfo">第 ${d.page} / ${pages} 页 · 共 ${d.total} 条</span>
        <button class="btn btn-secondary btn-sm" type="button" data-prev ${d.page <= 1 ? 'disabled' : ''}>← 上一页</button>
        <button class="btn btn-secondary btn-sm" type="button" data-next ${d.page >= pages ? 'disabled' : ''}>下一页 →</button>`;
      pagerEl.querySelector('[data-prev]').addEventListener('click', () => { state.page--; syncUrl(true); load(); });
      pagerEl.querySelector('[data-next]').addEventListener('click', () => { state.page++; syncUrl(true); load(); });
    } catch (e) {
      if (silent && hasLoaded) return;  // 后台刷新失败：保留旧列表，不打断浏览
      const msg = String(e.message || e);
      listEl.innerHTML = `<div class="empty"><div class="big">⚠️</div>
        <p class="err-text">历史任务加载失败：${esc(msg)}</p>
        <div class="actions"><button class="btn btn-secondary btn-sm" type="button" data-reload>重试</button></div></div>`;
      listEl.querySelector('[data-reload]').addEventListener('click', load);
      pagerEl.innerHTML = '';
    }
  }

  function clearFilters() {
    state.q = ''; state.status = ''; state.outcome = ''; state.page = 1;
    $('[data-q]').value = ''; $('[data-status]').value = ''; $('[data-outcome]').value = '';
    renderRunzone(); syncUrl(false); load();
  }

  $('[data-reset]').addEventListener('click', clearFilters);
  const onSearch = debounce(() => {
    state.q = $('[data-q]').value.trim();
    state.page = 1; syncUrl(false); load();
  }, 350);
  $('[data-q]').addEventListener('input', onSearch);
  $('[data-status]').addEventListener('change', () => {
    state.status = $('[data-status]').value; state.page = 1; syncUrl(true);
    renderRunzone(); load();
  });
  $('[data-outcome]').addEventListener('change', () => {
    state.outcome = $('[data-outcome]').value; state.page = 1; syncUrl(true); load();
  });

  // 行内操作（重试 / 取消）
  listEl.addEventListener('click', async e => {
    const r = e.target.closest('[data-retry]');
    if (r) {
      r.disabled = true;
      try {
        const newId = await retryJob(r.dataset.retry);
        history.pushState({ from: location.pathname + location.search }, '', '/?job=' + encodeURIComponent(newId));
        window.dispatchEvent(new PopStateEvent('popstate'));  // 重试直达新任务运行记录
      } catch (err) {
        r.disabled = false;
        listEl.dispatchEvent(new CustomEvent('retry-failed', { detail: '重试失败：' + String(err.message || err) }));
      }
      return;
    }
    const c = e.target.closest('[data-cancel]');
    if (c) { c.disabled = true; cancelJob(c.dataset.cancel); }
  });
  runzoneEl.addEventListener('click', e => {
    const c = e.target.closest('[data-cancel]');
    if (c) { c.disabled = true; cancelJob(c.dataset.cancel); }
  });

  // 重试失败等页内提示（不用 alert：自动化与读屏都不友好）
  function notice(text) {
    root.querySelector('.page-head').insertAdjacentHTML('afterend',
      `<div class="banner warn" data-notice>${esc(text)}</div>`);
    setTimeout(() => { root.querySelector('[data-notice]')?.remove(); }, 6000);
  }
  listEl.addEventListener('retry-failed', e => notice(e.detail));

  // ---------- 订阅：任务列表变化时刷新进行中专区与当前页数据 ----------
  const reloadSoon = debounce(() => load(), 500);
  const unsub = subscribe(type => {
    if (type !== 'list') return;
    renderRunzone();
    // 有任务进入终态（或新任务发起）时，当前页数据可能在服务端已变化
    reloadSoon();
  });

  renderRunzone();
  await load();

  return () => {
    unsub();
    clearInterval(elapsedTimer);
  };
}
