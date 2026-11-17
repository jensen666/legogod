// ============================================================
// 创作台右栏：空态 / 进行中 / 完成 / 失败。作品是主视觉，日志是浮层抽屉。
// 抽屉展开盖住舞台下沿，不增加文档高度（1280×720 不得出现页面级滚动）。
// ============================================================
import { esc, statusTag, outcomeBanner, modeBadge } from '../ui.js';
import { retryLabel } from '../modes.js';
import { createLogView, exportLogsMd } from '../logview.js';
import { paletteHTML } from '../palette.js';
import { phaseBadgesHTML, phaseBlurb, progressText, failureInfo } from '../stage.js';
import { liveTurn, thinkingPanelHTML, thinkingMeta, pickThinkingTurns } from '../thinking.js';
import { getParts } from '../tasks.js';
// 产物 URL 统一由 web/api.js 解析：独立部署时链接必须指向 API 源。
// mountWorkbench 的第二个参数也叫 api（页面回调集合），这里用别名避免遮蔽。
import { api as apiClient, files, viz } from '../api.js';

function logDrawer(count) {
  return `<div class="log-drawer" data-drawer>
    <div class="log-drawer-bar">
      <button type="button" class="log-toggle" data-drawer-toggle aria-expanded="false">▸ 运行日志</button>
      <span class="hint" data-logcount>${count} 条</span>
      <span style="flex:1 1 auto"></span>
      <button type="button" class="btn btn-secondary btn-sm" data-export>导出 Markdown</button>
    </div>
    <div class="log-drawer-body wb-log" data-wblog hidden><div data-log></div></div>
  </div>`;
}

function statusRow(job, running) {
  const res = job.result || {};
  const name = res.name || job.desc || job.id;
  const from = job.retryOf ? `<span class="hint">重试自 ${esc(job.retryOf)}</span>` : '';
  return `<div class="wb-status" data-wbmark="${esc(job.id)}:${esc(job.status)}">
    <span class="wb-name" title="${esc(job.desc || '')}">${esc(name)}</span>
    <span data-tag>${statusTag(job)}</span>
    ${modeBadge(job.mode)}
    <span class="hint" data-elapsed></span>
    ${from}
    <span style="flex:1 1 auto"></span>
    ${running ? '<button class="btn btn-danger btn-sm" type="button" data-cancel>✕ 取消该任务</button>' : ''}
  </div>`;
}

function factsHTML(res) {
  const colors = res.colors && typeof res.colors === 'object' ? Object.keys(res.colors) : [];
  const grid = res.grid || {};
  const score = res.review && res.review.scores && res.review.scores.overall;
  const bits = [
    res.pieces != null ? `<span class="badge">零件 <b>${esc(String(res.pieces))}</b></span>` : '',
    res.voxels != null ? `<span class="badge">体素 <b>${esc(String(res.voxels))}</b></span>` : '',
    res.layers != null ? `<span class="badge">层数 <b>${esc(String(res.layers))}</b></span>` : '',
    grid.w && grid.d ? `<span class="badge">占地 <b>${esc(grid.w)}×${esc(grid.d)}</b></span>` : '',
    colors.length ? `<span class="badge">配色 <b>${colors.length}</b> 种</span>` : '',
    score != null ? `<span class="badge badge-hot">视觉评审 <b>${esc(String(score))}</b>/10</span>` : '',
  ];
  return `<div class="wb-facts" data-facts>${bits.join('')}</div>`;
}

function retryButton(job) {
  const res = job.result || {};
  return (job.desc || (res.run_record || {}).desc)
    ? `<button class="btn btn-secondary btn-sm" type="button" data-retry>${esc(retryLabel(job.mode))}</button>` : '';
}

function doneActions(job) {
  const res = job.result || {};
  const id = encodeURIComponent(job.id);
  // 变量名不能叫 viz/files：会遮蔽 api.js 的产物 URL 助手（或与其同名）。
  const mdLink = res.md_path
    ? `<a class="btn btn-secondary btn-sm" data-ext href="${esc(files(res.md_path))}" target="_blank">下载步骤文档</a>` : '';
  const vizLink = res.viz_file
    ? `<a class="btn btn-secondary btn-sm" data-ext href="${esc(viz(res.viz_file))}" target="_blank">独立 3D 页</a>` : '';
  return `<a class="btn btn-secondary btn-sm" href="/jobs/${id}?tab=work">3D 工作室</a>
    <a class="btn btn-secondary btn-sm" href="/jobs/${id}?tab=steps">拼装步骤</a>
    <a class="btn btn-secondary btn-sm" href="/jobs/${id}?tab=review">复盘</a>
    ${mdLink}${vizLink}${retryButton(job)}`;
}

function stopActions(job) {
  const id = encodeURIComponent(job.id);
  return `<a class="btn btn-secondary btn-sm" href="/jobs/${id}?tab=review">查看原因</a>${retryButton(job)}`;
}

// 完成态结果横幅：四态 + 快速成功“未进行视觉评审”的明确提示。
function deliveryBanner(res, mode) {
  return outcomeBanner(res || {}, mode);
}

function viewsHTML(views) {
  if (!views) return '';
  // tasks.js 已把 /views/<name> 解析成按 API Base URL 的完整地址。
  const order = [['front', '正视'], ['side', '侧视'], ['top', '俯视'], ['iso', '轴测']];
  const imgs = order.filter(([k]) => views[k]).map(([k, label]) =>
    `<figure><img alt="${label}" src="${esc(views[k])}"><figcaption>${label}</figcaption></figure>`).join('');
  if (!imgs) return '';
  return `<div class="viewstrip" data-views>${imgs}</div>`;
}

// 当前该展示的思考：进行中有实时通道用实时，否则取最后一条落盘回合。
function thinkingNow(job) {
  const live = liveTurn(job.thinking);
  if (live) return { turn: live, live: true, sig: `L|${live.phase}` };
  const turns = pickThinkingTurns(job.logs || []);
  const last = turns[turns.length - 1];
  if (!last) return null;
  return { turn: last, live: false, sig: `D|${last.ts ?? ''}|${last.phase}|${last.chars}` };
}

export function mountWorkbench(host, api) {
  let gen = 0;
  let current = null;
  let snap = { id: null, status: null };
  let preview = null;
  let studio = null;
  let logview = null;
  let seen = 0;
  let previewStamp = '';
  let shownViews = '';
  let previewReq = 0;
  // 思考面板折叠状态：按轮次记 userToggled，用户手动展开后不被自动折叠覆盖
  let thinkSig = '';
  let thinkUserToggled = false;
  let thinkPhase = '';

  function kill3d() {
    if (preview) { preview.destroy(); preview = null; }
    if (studio) { studio.destroy(); studio = null; }
  }

  function bindDrawer() {
    const toggle = host.querySelector('[data-drawer-toggle]');
    const body = host.querySelector('[data-wblog]');
    if (!toggle || !body) return;
    toggle.addEventListener('click', () => {
      const open = body.hasAttribute('hidden');
      if (open) body.removeAttribute('hidden');
      else body.setAttribute('hidden', '');
      toggle.setAttribute('aria-expanded', String(open));
      toggle.textContent = (open ? '▾' : '▸') + ' 运行日志';
    });
    const exp = host.querySelector('[data-export]');
    if (exp) exp.addEventListener('click', () => exportLogsMd((current && current.result) || {}, (current && current.logs) || []));
  }

  function notice(text) {
    let el = host.querySelector('[data-notice]');
    if (!el) {
      host.insertAdjacentHTML('afterbegin', '<div class="banner warn" data-notice></div>');
      el = host.querySelector('[data-notice]');
    }
    if (el) el.textContent = text;
    console.info('[workbench]', text);
  }

  function bindActions(job) {
    const cancel = host.querySelector('[data-cancel]');
    if (cancel) cancel.addEventListener('click', () => {
      Promise.resolve(api.onCancel(job.id)).catch(e => notice('取消失败：' + (e.message || e)));
    });
    host.querySelectorAll('[data-retry]').forEach(btn => {
      btn.addEventListener('click', () => {
        btn.disabled = true;
        Promise.resolve(api.onRetry(job.id)).catch(e => {
          btn.disabled = false;
          notice('重试失败：' + (e.message || e));
        });
      });
    });
  }

  function fillLogs(job) {
    const box = host.querySelector('[data-log]');
    if (!box) return;
    logview = createLogView(box);
    logview.load(job.logs || []);
    seen = (job.logs || []).length;
    const count = host.querySelector('[data-logcount]');
    if (count) count.textContent = `${seen} 条`;
    paintLive(job);
  }

  function paintLive(job) {
    const el = host.querySelector('[data-live]');
    if (!el) return;
    const text = job.status === 'running' ? (job.live || '') : '';
    el.textContent = text;
    el.hidden = !text;
  }

  // 思考面板：进行中默认展开、新内容贴底；回合结束或阶段切换自动折叠；
  // 用户手动展开过的轮次保留其选择。
  function paintThinking(job) {
    const box = host.querySelector('[data-think]');
    if (!box) return;
    const now = thinkingNow(job);
    if (!now) {
      if (box.innerHTML) box.innerHTML = '';
      thinkSig = '';
      thinkPhase = '';
      thinkUserToggled = false;
      return;
    }
    if (now.sig !== thinkSig) {
      // 同一阶段的「实时 → 落盘」切换不算新轮次：保留用户手动展开的选择
      const sameTurn = now.turn.phase === thinkPhase;
      if (!sameTurn) { thinkUserToggled = false; thinkPhase = now.turn.phase || ''; }
      thinkSig = now.sig;
      const open = now.live || thinkUserToggled;
      // live 必须传给面板：进行中要带 think-live 样式（等宽呼吸高亮），
      // 否则实时与已落盘的历史思考看起来完全一样（真实任务验收发现）。
      box.innerHTML = thinkingPanelHTML(now.turn, { open, live: now.live });
      const det = box.querySelector('details');
      if (det) {
        det.addEventListener('toggle', () => { thinkUserToggled = true; });
        const body = det.querySelector('.think-body');
        if (body) body.scrollTop = body.scrollHeight;
      }
      return;
    }
    // 同一轮：实时内容增长时只更新正文，不重绘整个面板（避免抢走焦点）
    if (!now.live) return;
    const det = box.querySelector('details');
    const body = det && det.querySelector('.think-body');
    if (!body) return;
    const nearBottom = body.scrollHeight - body.scrollTop - body.clientHeight < 24;
    body.textContent = now.turn.text;
    const meta = det.querySelector('.think-meta');
    if (meta) meta.textContent = thinkingMeta(now.turn);
    if (nearBottom) body.scrollTop = body.scrollHeight;
  }

  async function showDesign(job, token) {
    const canvas = host.querySelector('[data-canvas]');
    if (!canvas || !job.design) {
      if (canvas && !job.design) {
        canvas.innerHTML = '<div class="preview-wait"><p>造型完成后，彩色设计稿会出现在这里。</p></div>';
      }
      return;
    }
    if (preview && preview.update) {
      preview.update(job.design);
      return;
    }
    const req = ++previewReq;
    const { mountPreview } = await import('../preview.js');
    if (token !== gen || req !== previewReq) return;
    const handle = await mountPreview(canvas, job.design);
    if (token !== gen || req !== previewReq) { handle.destroy(); return; }
    preview = handle;
  }

  async function showStudio(job, token) {
    const canvas = host.querySelector('[data-canvas]');
    const res = job.result || {};
    if (!canvas || !res.model_path || !res.solution_path) return;
    try {
      const { mountLegoStudio } = await import('../viewer.js');
      const parts = await getParts();
      const model = await apiClient.getJson(files(res.model_path));
      const sol = await apiClient.getJson(files(res.solution_path));
      if (token !== gen) return;
      // 工作室自己还有页签和控制条，画布不能占满整个舞台，否则播放按钮被裁掉。
      const height = Math.max(140, (canvas.clientHeight || 320) - 168);
      studio = mountLegoStudio(canvas, {
        name: res.name, grid: model.grid, layers: model.layers, parts,
        steps: sol.steps, usage: sol.usage, strategy: sol.strategy,
        valid: sol.valid, attempts: sol.attempts, model: 'AI',
        subassemblies: sol.subassemblies || [],
      }, { height });
    } catch (e) {
      if (token === gen && canvas) {
        canvas.innerHTML = `<p class="err-text">成品加载失败：${esc(String(e.message || e))}</p>`;
      }
    }
  }

  function showEmpty() {
    gen += 1;
    kill3d();
    current = null;
    snap = { id: null, status: null };
    logview = null;
    seen = 0;
    previewStamp = '';
    shownViews = '';
    thinkSig = '';
    thinkUserToggled = false;
    thinkPhase = '';
    host.innerHTML = `<div class="wb-empty">
      <div class="big">🧱</div>
      <p>左侧描述需求，点击「开始拼装」。<br>生成过程与成品都会出现在这里。</p>
      <div class="recent-works" data-recent></div>
    </div>`;
    api.loadRecent().then(rows => {
      const box = host.querySelector('[data-recent]');
      if (!box || current) return;
      if (!rows.length) {
        box.innerHTML = '<p class="hint">还没有完成的作品。历史任务页可以检索全部记录。</p>';
        return;
      }
      box.innerHTML = '<div class="section-title">最近的作品</div>' + rows.map(j =>
        `<button type="button" class="recent-card" data-open="${esc(j.id)}">
          <span class="n">${esc(j.name || j.desc || j.id)}</span>${paletteHTML(j.colors)}
        </button>`).join('');
      box.addEventListener('click', e => {
        const btn = e.target.closest('[data-open]');
        if (btn) api.onOpen(btn.dataset.open);
      });
    }).catch(() => { /* 最近作品加载失败时保留引导文案 */ });
  }

  function show(job) {
    const token = ++gen;
    kill3d();
    current = job;
    if (!job) { showEmpty(); return; }
    const running = job.status === 'running';
    const done = job.status === 'done' && job.result && job.result.ok;
    snap = { id: job.id, status: job.status };
    previewStamp = (job.design && job.design.stamp) || '';
    shownViews = JSON.stringify(job.views || {});
    host.dataset.stamp = previewStamp;
    if (running) {
      host.innerHTML = statusRow(job, true) +
        `<div data-phases>${phaseBadgesHTML(job.stage)}</div>` +
        `<p class="wb-narr" data-narr>${esc(phaseBlurb(job.stage))}</p>` +
        `<div class="think-host" data-think></div>` +
        `<p class="wb-live" data-live hidden></p>` +
        `<p class="wb-progress" data-progress>${esc(progressText(job.progress))}</p>` +
        `<div class="stagewrap"><div class="stage-canvas" data-canvas></div>` +
        viewsHTML(job.views) + logDrawer((job.logs || []).length) + `</div>`;
      showDesign(job, token);
    } else if (done) {
      host.innerHTML = statusRow(job, false) +
        `<div class="stagewrap"><div class="stage-canvas" data-canvas></div>` +
        logDrawer((job.logs || []).length) + `</div>` +
        deliveryBanner(job.result || {}, job.mode) +
        factsHTML(job.result || {}) +
        `<div class="think-host" data-think></div>` +
        `<div class="wb-result"><div class="wb-actions">${doneActions(job)}</div></div>`;
      showStudio(job, token);
    } else {
      const info = failureInfo(job);
      const res = job.result || {};
      const cancelled = job.status === 'cancelled' || res.outcome === 'cancelled';
      const interrupted = job.status === 'interrupted';
      const where = info.stageLabel ? `断在「${info.stageLabel}」阶段` : '没有记录到阶段';
      const card = (cancelled || interrupted)
        ? `<div class="infocard" data-reason>
            ${cancelled ? outcomeBanner({ outcome: 'cancelled' }) : '<div class="banner info">⏸️ 任务已中断：服务重启前没有跑完</div>'}
            <p data-stage="${esc(info.stage)}">${esc(where)}${interrupted ? '。' + esc(info.reason) : ''}</p>
            <div class="wb-actions">${stopActions(job)}</div>
          </div>`
        : `<div class="failcard" data-reason>
            <h3>生成未完成 —— ${esc(where)}</h3>
            <p data-stage="${esc(info.stage)}">${esc(info.reason)}</p>
            <div class="wb-actions">${stopActions(job)}</div>
          </div>`;
      host.innerHTML = statusRow(job, false) +
        `<div class="wb-result">${card}</div>` +
        `<div class="stagewrap stage-slim">${logDrawer((job.logs || []).length)}</div>`;
    }
    fillLogs(job);
    paintThinking(job);
    bindDrawer();
    bindActions(job);
  }

  function patch(job) {
    current = job;
    const phases = host.querySelector('[data-phases]');
    if (phases) phases.innerHTML = phaseBadgesHTML(job.stage);
    const narr = host.querySelector('[data-narr]');
    if (narr) narr.textContent = phaseBlurb(job.stage);
    const prog = host.querySelector('[data-progress]');
    if (prog) prog.textContent = progressText(job.progress);
    const tag = host.querySelector('[data-tag]');
    if (tag) tag.innerHTML = statusTag(job);
    const name = host.querySelector('.wb-name');
    if (name) name.textContent = (job.result && job.result.name) || job.desc || job.id;
    // 修订会换稿。stamp 变了才拆掉旧画布，进行中的第一次挂载不重复创建。
    const stamp = (job.design && job.design.stamp) || '';
    if (job.status === 'running' && stamp && stamp !== previewStamp) {
      previewStamp = stamp;
      host.dataset.stamp = stamp;
      showDesign(job, gen);
    }
    const viewKey = JSON.stringify(job.views || {});
    if (viewKey !== shownViews) {
      shownViews = viewKey;
      const html = viewsHTML(job.views);
      const old = host.querySelector('[data-views]');
      if (old) old.remove();
      const canvas = host.querySelector('[data-canvas]');
      if (html && canvas) canvas.insertAdjacentHTML('afterend', html);
    }
    if (!logview) return;
    if (job.logsReset) {
      job.logsReset = false;
      logview.load(job.logs || []);
      seen = (job.logs || []).length;
    } else {
      for (; seen < (job.logs || []).length; seen++) {
        const line = job.logs[seen];
        logview.append(line.kind, line.text, line);
      }
    }
    const count = host.querySelector('[data-logcount]');
    if (count) count.textContent = `${(job.logs || []).length} 条`;
    paintThinking(job);
    paintLive(job);
  }

  return {
    show(job) {
      if (!job) { showEmpty(); return; }
      const marker = host.querySelector('[data-wbmark]');
      const key = `${job.id}:${job.status}`;
      if (marker && marker.dataset.wbmark === key) { patch(job); return; }
      show(job);
    },
    notice,
    destroy() { gen += 1; previewReq += 1; kill3d(); host.innerHTML = ''; current = null; },
  };
}
