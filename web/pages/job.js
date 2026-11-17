// ============================================================
// 任务详情：作品 / 拼装步骤 / 复盘。
// - 旧链接 overview、studio → 作品；steps → 拼装步骤；logs → 复盘并锚定日志
// - 默认：进行中、失败、取消、中断 → 复盘；完成 → 作品。URL 指定的 Tab 优先
// - 3D 按需初始化、离开即销毁。创作台与复盘共用 tasks.js 的日志缓存，互不抢占
// ============================================================
import { mountLegoStudio } from '/web/viewer.js';
import { esc, statusTag, outcomeBanner, reviewBadges, attemptsHTML, fmtDateTime, shortDesc,
         modeBadge, modeLabel } from '../ui.js';
import { retryLabel } from '../modes.js';
import { createLogView, milestonesHTML, exportLogsMd } from '../logview.js';
import { fetchJob, cancelJob, retryJob, subscribe, getParts, touchRecent, ensurePoller } from '../tasks.js';
import { canonicalTab, defaultJobTab } from '../stage.js';
import { pickThinkingTurns, thinkingPanelHTML, liveTurn } from '../thinking.js';
// 产物 URL 统一由 web/api.js 解析：独立部署时 <img>/<a> 必须指向 API 源。
import { api, files, viz } from '../api.js';

const TABS = [
  { id: 'work', label: '作品' },
  { id: 'steps', label: '拼装步骤' },
  { id: 'review', label: '复盘' },
];

export async function mountJob(root, ctx) {
  const id = ctx.route.id;
  if (!id) {
    root.innerHTML = `<div class="page"><div class="empty"><div class="big">⚠️</div>
      <p>URL 缺少任务 ID。</p><div class="actions"><a class="btn btn-secondary btn-sm" href="/history">去历史任务</a></div></div></div>`;
    return;
  }
  let job;
  try {
    job = await fetchJob(id);
  } catch (e) {
    root.innerHTML = `<div class="page"><div class="empty"><div class="big">🧱</div>
      <p>任务 ${esc(id)} 不存在或加载失败：${esc(String(e.message || e))}</p>
      <div class="actions"><a class="btn btn-secondary btn-sm" href="/history">去历史任务</a></div></div></div>`;
    return;
  }
  touchRecent(id);
  if (job.status === 'running') ensurePoller(id);

  root.innerHTML = `
  <div class="page">
    <div class="job-head">
      <div class="title-row">
        <a class="backlink" href="/history" data-back>← 返回</a>
        <h1 data-title>…</h1>
        <span data-tag></span>
        <span style="flex:1 1 auto"></span>
        <span data-actions style="display:flex;gap:8px"></span>
      </div>
      <div class="jdesc" data-desc></div>
    </div>
    <div class="job-body">
      <div class="tabs" role="tablist" aria-label="任务视图" data-tabs></div>
      <div class="tabpanes"><div role="tabpanel" data-pane tabindex="-1"></div></div>
    </div>
  </div>`;

  const $ = s => root.querySelector(s);
  const paneEl = $('[data-pane]'), tabsEl = $('[data-tabs]');

  const srcFrom = history.state && history.state.from;
  // 来源按路径部分判断（创作台可能带 ?job= 查询参数）
  const fromPath = srcFrom ? srcFrom.split('?')[0] : '';
  const backTo = (srcFrom && (fromPath === '/' || fromPath === '/history' || fromPath === '/parts'))
    ? srcFrom : '/history';
  const backLabel = fromPath === '/' ? '返回创作台' : fromPath === '/parts' ? '返回零件目录' : '返回历史';
  const backBtn = $('[data-back]');
  backBtn.setAttribute('href', backTo);
  backBtn.textContent = '← ' + backLabel;

  // ---------- 产物加载（model/solution 文件为准，避免快照与最新文件不一致） ----------
  let artsPromise = null;
  // 工作室状态（内部 Tab + 拼装步数）：sessionStorage 持久化，SPA 与刷新后都保留
  const studioKey = 'legogod-studio-' + job.id;
  function loadStudioState() {
    if (job.studio && (job.studio.tab || job.studio.step)) return job.studio;
    try { return JSON.parse(sessionStorage.getItem(studioKey)) || null; }
    catch (e) { return null; }
  }
  function saveStudioState(s) {
    job.studio = { tab: s.tab, step: s.step };
    try { sessionStorage.setItem(studioKey, JSON.stringify(job.studio)); } catch (e) { /* 忽略 */ }
  }
  function loadArtifacts() {
    const res = job.result || {};
    if (!res.model_path || !res.solution_path) return Promise.resolve(null);
    if (!artsPromise) {
      artsPromise = (async () => {
        const parts = await getParts();
        if (!parts.length) throw new Error('零件目录为空：/api/parts 不可用');
        const model = await api.getJson(files(res.model_path));
        const sol = await api.getJson(files(res.solution_path));
        return { parts, model, sol };
      })();
      artsPromise.catch(() => { artsPromise = null; });  // 失败允许重试
    }
    return artsPromise;
  }

  // ---------- 页头与操作 ----------
  // 模式中文展示：优先任务持久化 mode；旧记录从结果补取；完全缺失如实标注回退约定。
  function modeText() {
    const m = job.mode || (job.result || {}).mode || '';
    return m ? modeLabel(m) : '未记录（重试按高保真处理）';
  }

  function paintHeader() {
    const res = job.result || {};
    $('[data-title]').textContent = res.name || shortDesc(job.desc || job.id, 30);
    $('[data-tag]').innerHTML = statusTag({ status: job.status, outcome: res.outcome }) + modeBadge(job.mode);
    const desc = job.desc || '';
    const from = job.retryOf ? `  ·  重试自 ${job.retryOf}` : '';
    $('[data-desc]').textContent = desc + from;
    $('[data-desc]').title = desc + from;
    const acts = $('[data-actions]');
    if (job.status === 'running') {
      acts.innerHTML = '<button class="btn btn-danger btn-sm" data-cancel>✕ 取消任务</button>';
      acts.querySelector('[data-cancel]').addEventListener('click', () => cancelJob(job.id));
    } else if (job.desc || (res.run_record || {}).desc) {
      acts.innerHTML = `<button class="btn btn-secondary btn-sm" data-retry>${esc(retryLabel(job.mode))}</button>`;
      acts.querySelector('[data-retry]').addEventListener('click', doRetry);
    }
  }

  async function doRetry() {
    try {
      const newId = await retryJob(job.id);
      history.pushState({ from: location.pathname + location.search }, '',
        '/?job=' + encodeURIComponent(newId));  // 新任务回到创作台，才能看到阶段和预览
      window.dispatchEvent(new PopStateEvent('popstate'));
    } catch (e) {
      paneEl.insertAdjacentHTML('afterbegin',
        `<div class="banner warn">重试失败：${esc(String(e.message || e))}</div>`);
    }
  }

  // ---------- Tab 骨架（role=tablist，支持左右方向键切换） ----------
  let curTab = null;
  function paintTabs() {
    tabsEl.innerHTML = TABS.map(t =>
      `<button role="tab" type="button" data-tab="${t.id}" aria-selected="false" aria-controls="job-pane">
        ${t.label}</button>`).join('');
    tabsEl.addEventListener('click', e => {
      const b = e.target.closest('[data-tab]');
      if (b) activateTab(b.dataset.tab);
    });
    tabsEl.addEventListener('keydown', e => {
      if (e.key !== 'ArrowLeft' && e.key !== 'ArrowRight') return;
      const ids = TABS.map(t => t.id);
      const i = ids.indexOf(curTab);
      const next = ids[(i + (e.key === 'ArrowRight' ? 1 : ids.length - 1)) % ids.length];
      activateTab(next);
      tabsEl.querySelector(`[data-tab="${next}"]`).focus();
    });
  }

  function activateTab(name, { push = true } = {}) {
    const requested = name;
    name = canonicalTab(name, job);
    curTab = name;
    for (const b of tabsEl.querySelectorAll('[role="tab"]')) {
      b.setAttribute('aria-selected', String(b.dataset.tab === name));
    }
    if (push) {
      const url = `/jobs/${encodeURIComponent(job.id)}?tab=${name}`;
      history.pushState({ from: history.state && history.state.from }, '', url);
    }
    renderPane(name);
    if (requested === 'logs') {
      requestAnimationFrame(() => paneEl.querySelector('[data-log]')?.scrollIntoView({ block: 'nearest' }));
    }
  }

  // ---------- 各 Tab 渲染 ----------
  let studio = null, logview = null, logSeen = 0, lastStatus = null;

  function paneLoading(text = '加载中……') {
    paneEl.innerHTML = `<div class="empty"><span class="spin">⏳</span><p>${esc(text)}</p></div>`;
  }

  function destroyStudio() {
    if (studio) { studio.destroy(); studio = null; }
  }

  function renderOverview() {
    const res = job.result || {};
    if (job.status === 'running') {
      paneEl.innerHTML = `
        <div class="banner info">⏳ 任务进行中。阶段、进度和设计稿在 <a href="/?job=${encodeURIComponent(job.id)}">创作台</a>，这里是复盘用的日志。</div>
        <div class="kv" style="margin-top:12px">
          <span class="kvp"><span class="k">任务 ID</span><span class="mono">${esc(job.id)}</span></span>
          <span class="kvp"><span class="k">需求</span><span>${esc(shortDesc(job.desc || '-', 60))}</span></span>
          <span class="kvp"><span class="k">模式</span><span>${esc(modeText())}</span></span>
        </div>
        <div class="links" style="margin-top:12px">
          <button class="btn btn-secondary btn-sm" data-export>⬇ 下载运行日志.md</button>
          <span class="hint" data-logcount></span>
        </div>
        <div data-thinkzone></div>
        <div data-wblog style="height:min(46vh,420px);border:1px solid var(--border-soft);border-radius:10px;overflow:hidden">
          <div data-log></div>
        </div>
        <div class="section-title" style="margin-top:16px">运行复盘</div>
        <div data-review><div data-miles></div></div>`;
      wireLogs();
      return;
    }
    const cancelled = job.status === 'cancelled' || res.outcome === 'cancelled';
    const interrupted = job.status === 'interrupted';
    const failed = !cancelled && !interrupted && !(job.status === 'done' && res.ok);
    paneEl.innerHTML = `
      <div class="ovw-grid">
        <div>
          ${outcomeBanner(cancelled ? { ...res, outcome: 'cancelled' } : res, job.mode)}
          ${interrupted ? '<div class="banner info">⏸️ 任务已中断：服务重启前没有跑完，可以回看日志或重试</div>' : ''}
          ${failed ? `<div class="banner warn">❌ ${esc(res.error || '生成失败')}</div>` : ''}
          ${attemptsHTML(res)}
          <div data-facts class="facts" style="margin:12px 0"></div>
          <div data-fbnote></div>
          <div data-scores>${reviewBadges(res)}</div>
          <div class="links" style="margin-top:12px">
            ${(job.desc || (res.run_record || {}).desc)
              ? `<button class="btn btn-secondary btn-sm" data-retry>${esc(retryLabel(job.mode))}</button>` : ''}
            <button class="btn btn-secondary btn-sm" data-export>⬇ 下载运行日志.md</button>
          </div>
          <p class="hint" data-mismatch style="margin-top:8px"></p>
        </div>
        <div>
          <div class="section-title">产物下载</div>
          <div class="links" data-files></div>
          <div class="section-title" style="margin-top:16px">运行信息</div>
          <div class="kv">
            <span class="kvp"><span class="k">任务 ID</span><span class="mono">${esc(job.id)}</span></span>
            ${res.run_id ? `<span class="kvp"><span class="k">run_id</span><span class="mono">${esc(res.run_id)}</span></span>` : ''}
            <span class="kvp"><span class="k">模式</span><span>${esc(modeText())}</span></span>
            ${job.retryOf ? `<span class="kvp"><span class="k">重试自</span><a href="/jobs/${esc(job.retryOf)}" class="mono">${esc(job.retryOf)}</a></span>` : ''}
            <span class="kvp"><span class="k">发起时间</span><span>${fmtDateTime(job.startedAt || ((job.logs || [])[0] || {}).ts)}</span></span>
            ${res.elapsed_s !== undefined ? `<span class="kvp"><span class="k">总耗时</span><span>${esc(String(res.elapsed_s))}s</span></span>` : ''}
          </div>
        </div>
      </div>
      <div class="section-title" style="margin-top:16px">评审渲染图</div>
      <div class="viewstrip" data-viewstrip></div>
      <div class="section-title">运行复盘（设计版本与求解轨迹）</div>
      <div data-review><div data-miles></div></div>
      <div data-thinkzone></div>
      <div class="links" style="margin-top:12px"><span class="hint" data-logcount></span></div>
      <div data-wblog style="height:min(46vh,420px);border:1px solid var(--border-soft);border-radius:10px;overflow:hidden">
        <div data-log></div>
      </div>`;
    const factsEl = paneEl.querySelector('[data-facts]');
    const paintFileFacts = ({ model, sol }) => {
      const colorNames = Object.keys(sol.colors || {});
      factsEl.innerHTML =
        `<span class="badge">体素 <b>${model.totalVoxels ?? '-'}</b></span>` +
        `<span class="badge">层数 <b>${model.layers.length}</b></span>` +
        `<span class="badge">占地 <b>${model.grid.w}×${model.grid.d}</b></span>` +
        `<span class="badge">零件 <b>${sol.steps.length}</b> 块</span>` +
        `<span class="badge">求解尝试 <b>${sol.attempts ?? res.attempts ?? '-'}</b> 次</span>` +
        (colorNames.length ? `<span class="badge">配色 <b>${colorNames.length}</b> 种（${esc(colorNames.join('、'))}）</span>` : '');
      const fb = sol.colorFallbacks || [];
      paneEl.querySelector('[data-fbnote]').innerHTML = fb.length
        ? `<p class="err-text">注意：${fb.map(f => `y=${f.layer} 层设计色「${esc(f.target)}」库存不足，回退使用 ${esc(Object.entries(f.used).map(([c, n]) => `${c}×${n}`).join('、'))}`).join('；')}</p>`
        : '';
      // 产物文件可能已被之后的重新生成覆盖：统计以文件为准并说明（原结果卡语义）
      if (res.pieces !== undefined && (res.pieces !== sol.steps.length || res.voxels !== model.totalVoxels)) {
        paneEl.querySelector('[data-mismatch]').textContent =
          '注意：该任务的产物文件已在之后重新生成，上方统计与 3D 以最新文件为准；运行记录是任务当时的日志。';
      }
    };
    paneEl.querySelectorAll('[data-retry]').forEach(b => b.addEventListener('click', doRetry));
    const downloads = [];
    if (res.md_path) downloads.push(`<a href="${esc(files(res.md_path))}" target="_blank" data-ext>拼装步骤.md</a>`);
    if (res.viz_file) downloads.push(`<a href="${esc(viz(res.viz_file))}" target="_blank" data-ext>独立 3D 页</a>`);
    if (res.model_path) downloads.push(`<a href="${esc(files(res.model_path))}" target="_blank" data-ext>设计.json</a>`);
    if (res.solution_path) downloads.push(`<a href="${esc(files(res.solution_path))}" target="_blank" data-ext>方案.json</a>`);
    paneEl.querySelector('[data-files]').innerHTML = downloads.join(' · ') || '<span class="hint">—（失败任务无产物）</span>';
    if (!failed && !cancelled) {
      loadArtifacts().then(a => { if (a && curTab === 'review') paintFileFacts(a); })
        .catch(e => { factsEl.innerHTML = `<span class="hint">产物统计加载失败：${esc(String(e.message || e))}</span>`; });
    } else {
      // 快照统计兜底（失败任务没有产物文件）
      factsEl.innerHTML = res.pieces !== undefined
        ? `<span class="badge">零件 <b>${esc(String(res.pieces))}</b> 块</span>` : '';
    }
    paintViews();
    wireLogs();
  }

  function paintViews() {
    const box = paneEl.querySelector('[data-viewstrip]');
    if (!box) return;
    const views = job.views || {};  // tasks.js 已按 API Base URL 解析成完整地址
    const order = [['front', '正视'], ['side', '侧视'], ['top', '俯视'], ['iso', '轴测']];
    const imgs = order.filter(([k]) => views[k]).map(([k, label]) =>
      `<figure><img alt="${label}" src="${esc(views[k])}"><figcaption>${label}</figcaption></figure>`).join('');
    box.innerHTML = imgs || '<span class="hint">评审图还没有，或这次运行没有渲染。</span>';
  }

  // 思考过程区块：已完成任务默认折叠，可逐轮展开；进行中显示实时通道。
  function paintThinkingSection() {
    const zone = paneEl.querySelector('[data-thinkzone]');
    if (!zone) return;
    const turns = pickThinkingTurns(job.logs);
    const live = liveTurn(job.thinking);
    if (!turns.length && !live) {
      if (zone.innerHTML) zone.innerHTML = '';
      return;
    }
    // 重绘时保留用户已展开的思考块（按 data-key，与日志视图同一机制）
    const open = new Set([...zone.querySelectorAll('details[open][data-key]')].map(d => d.dataset.key));
    const parts = [];
    if (live) parts.push(thinkingPanelHTML(live, { open: true, live: true }));
    for (const turn of turns) parts.push(thinkingPanelHTML(turn, { open: false }));
    zone.innerHTML = `<div class="section-title">思考过程 · ${parts.length} 轮</div>` + parts.join('');
    for (const det of zone.querySelectorAll('details[data-key]')) {
      if (open.has(det.dataset.key)) det.open = true;
    }
  }

  function wireLogs() {
    const box = paneEl.querySelector('[data-log]');
    if (!box) return;
    logview = createLogView(box);
    logSeen = 0;
    appendLogs();
    const miles = paneEl.querySelector('[data-miles]');
    if (miles) miles.innerHTML = milestonesHTML(job.logs);
    const exp = paneEl.querySelector('[data-export]');
    if (exp && !exp.dataset.bound) {
      exp.dataset.bound = '1';
      exp.addEventListener('click', () => exportLogsMd(job.result || {}, job.logs));
    }
  }

  function renderSteps() {
    const res = job.result || {};
    if (job.status !== 'done' || !res.ok) {
      paneEl.innerHTML = '<div class="empty"><div class="big">🧩</div><p>还没有拼装步骤。失败或未完成的任务，原因在「复盘」。</p></div>';
      return;
    }
    paneLoading('加载拼装步骤……');
    loadArtifacts().then(({ model, sol }) => {
      if (curTab !== 'steps') return;
      let html = `<div class="links" style="margin-bottom:12px">
          ${res.md_path ? `<a href="${esc(files(res.md_path))}" target="_blank" data-ext>⬇ 下载拼装步骤.md</a>` : ''}
          <span class="hint">共 ${sol.steps.length} 块零件 · ${model.layers.length} 层</span>
        </div><div class="steps-list">`;
      for (const l of model.layers) {
        const ss = sol.steps.filter(s => s.layer === l.y);
        if (!ss.length) continue;
        html += `<details ${l.y === 0 ? 'open' : ''}><summary><b>y=${l.y}</b> ${esc(l.module.join('·'))} · ${ss.length} 块</summary><ol>` +
          ss.map(s => {
            return `<li data-piece="${esc(s.piece)}" data-x="${s.x}" data-w="${s.w}" data-z="${s.z}" data-d="${s.d}" data-rot="${s.rotate ? 1 : 0}"></li>`;
          }).join('') + '</ol></details>';
      }
      html += '</div>';
      paneEl.innerHTML = html;
      // 零件名与颜色在 parts 就绪后填充（目录失败时显示零件 id 兜底）
      getParts().then(parts => {
        const byId = new Map(parts.map(p => [p.id, p]));
        for (const li of paneEl.querySelectorAll('li[data-piece]')) {
          const p = byId.get(li.dataset.piece);
          if (!p) {
            li.innerHTML = `<span class="err-text">未知零件 ${esc(li.dataset.piece)}（零件目录未同步）</span> → x=${li.dataset.x}..${+li.dataset.x + +li.dataset.w - 1}, z=${li.dataset.z}..${+li.dataset.z + +li.dataset.d - 1}`;
            continue;
          }
          li.innerHTML = `<span class="dot" style="background:${esc(p.color)}"></span>${esc(p.name)} → ` +
            `x=${li.dataset.x}..${+li.dataset.x + +li.dataset.w - 1}, z=${li.dataset.z}..${+li.dataset.z + +li.dataset.d - 1}` +
            (li.dataset.rot === '1' ? '（旋转90°）' : '');
        }
      }).catch(e => {
        paneEl.insertAdjacentHTML('beforeend', `<p class="err-text">零件目录加载失败：${esc(String(e.message || e))}</p>`);
      });
    }).catch(e => {
      paneEl.innerHTML = `<div class="empty"><p class="err-text">拼装步骤加载失败：${esc(String(e.message || e))}</p></div>`;
    });
  }

  function renderStudio() {
    const res = job.result || {};
    if (job.status !== 'done' || !res.ok) {
      paneEl.innerHTML = '<div class="empty"><div class="big">🎬</div><p>还没有成品。失败或未完成的任务，原因在「复盘」。</p></div>';
      return;
    }
    paneLoading('加载 3D 工作室……');
    loadArtifacts().then(({ parts, model, sol }) => {
      if (curTab !== 'work') return;
      destroyStudio();
      const colorNames = Object.keys(sol.colors || {});
      paneEl.innerHTML = `<div data-facts class="facts" style="margin-bottom:12px">` +
        `<span class="badge">体素 <b>${model.totalVoxels ?? '-'}</b></span>` +
        `<span class="badge">层数 <b>${model.layers.length}</b></span>` +
        `<span class="badge">占地 <b>${model.grid.w}×${model.grid.d}</b></span>` +
        `<span class="badge">零件 <b>${sol.steps.length}</b> 块</span>` +
        (colorNames.length ? `<span class="badge">配色 <b>${colorNames.length}</b> 种</span>` : '') +
        `</div><div data-studio></div>`;
      const host = paneEl.querySelector('[data-studio]');
      const saved = loadStudioState() || { tab: null, step: 0 };
      studio = mountLegoStudio(host, {
        name: res.name, grid: model.grid, layers: model.layers, parts,
        steps: sol.steps, usage: sol.usage, strategy: sol.strategy,
        valid: sol.valid, attempts: sol.attempts, model: res.model || 'AI',
        subassemblies: sol.subassemblies || [],
      }, {
        height: Math.max(380, Math.min(560, window.innerHeight - 320)),
        initial: { tab: saved.tab, step: saved.step | 0 },
        // 工作室内 Tab 与拼装步数跨离开保留
        onState: saveStudioState,
      });
    }).catch(e => {
      paneEl.innerHTML = `<div class="empty"><p class="err-text">3D 视图加载失败：${esc(String(e.message || e))}</p></div>`;
    });
  }

  function appendLogs() {
    if (!logview) return;
    if (job.logsReset) {
      job.logsReset = false;
      logview.load(job.logs || []);
      logSeen = job.logs.length;
    } else {
      for (; logSeen < job.logs.length; logSeen++) {
        const l = job.logs[logSeen];
        logview.append(l.kind, l.text, l);
      }
    }
    const count = paneEl.querySelector('[data-logcount]');
    if (count) count.textContent = `${job.logs.length} 条日志`;
    logview.live(paneEl.querySelector('[data-wblog]'), job.status === 'running' ? job.live : null);
    const miles = paneEl.querySelector('[data-miles]');
    if (miles) miles.innerHTML = milestonesHTML(job.logs);
    paintThinkingSection();
  }

  function renderPane(name) {
    // 离开作品页就销毁 3D，避免 WebGL 上下文堆到浏览器上限。
    destroyStudio();
    logview = null;
    if (name === 'work') renderStudio();
    else if (name === 'steps') renderSteps();
    else renderOverview();
  }

  // ---------- 订阅任务更新：只重绘页头与当前 Tab（后台完成不强制跳转） ----------
  const unsub = subscribe((type, data) => {
    if (type !== 'job' || data.id !== job.id) return;
    if (data.error) {
      if (curTab === 'review') appendLogs();
      return;
    }
    paintHeader();
    if (job.status !== lastStatus) {
      lastStatus = job.status;
      renderPane(curTab);
      return;
    }
    if (curTab === 'review') {
      appendLogs();
      paintViews();
    }
  });

  // ---------- 启动 ----------
  paintHeader();
  paintTabs();
  lastStatus = job.status;
  const urlTab = ctx.query.get('tab');
  activateTab(urlTab || defaultJobTab(job), { push: false });

  return () => {
    unsub();
    destroyStudio();  // 离开详情销毁 3D
  };
}
