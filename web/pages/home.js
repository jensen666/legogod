// ============================================================
// 创作台：左侧需求栏不动，右侧是作品舞台。
// 只渲染当前选中的任务；后台任务只更新自己的缓存，不抢占这块视图。
// 2026-11-14：恢复「快速 / 高保真」两档选择，默认快速；模式只影响下一次新任务。
// ============================================================
import { esc, fmtElapsed, fmtDuration, shortDesc, modeBadge } from '../ui.js';
import { modeSelectorHTML, DEFAULT_MODE } from '../modes.js';
import { startJob, cancelJob, retryJob, subscribe, fetchJob, ensurePoller, touchRecent,
         listSnapshot, recentJobs, jobName, fetchJobsPage } from '../tasks.js';
import { mountWorkbench } from './workbench.js';

const CHIPS = [
  { label: '中世纪城堡', desc: '一座中世纪城堡：四座角楼、城墙带垛口、正面大门，目标 300 块积木' },
  { label: '三桅大帆船', desc: '一艘大帆船：船身、三根桅杆挂帆，目标 200 块积木' },
  { label: '垂耳小狗', desc: '一只站着的小狗：垂耳、黑鼻子、眼睛、短腿' },
];

const RULES = '两档生成模式：快速跳过视觉评审和视觉修订，优先生成可拼初稿；高保真追加多视角视觉评审与有界外观修订，' +
  '通常耗时更长，硬失败时自动快速保底一次（计为同一任务的第二次尝试）。两档都完整保留原始需求，' +
  '部位绑定、设计预检、结构修订、精确求解与统一校验执行同一标准。任务运行期间可继续发起新任务并独立取消，互不影响；' +
  '手动重试沿用原任务模式。Agent 可用零件与库存以「零件目录」为准。';

export async function mountHome(root, ctx) {
  root.innerHTML = `
  <div class="page"><div class="home">
    <aside class="req-side">
      <h1 class="page-title">创作台</h1>
      <textarea id="desc" aria-label="需求描述"
        placeholder="描述你想要拼的作品，例如：一座中世纪城堡，四座角楼，目标 300 块积木"></textarea>
      <div data-mode-host>${modeSelectorHTML(DEFAULT_MODE)}</div>
      <div class="chips" id="chips" aria-label="示例需求"></div>
      <button class="btn btn-block" id="go">开始拼装 ▶</button>
      <details class="help-fold"><summary>生成规则</summary><p class="hint">${esc(RULES)}</p></details>
    </aside>
    <section class="workbench" aria-label="作品舞台">
      <div class="wb-head">
        <h2>作品</h2>
        <div class="switcher" id="switcher"></div>
      </div>
      <div id="wb-body"></div>
    </section>
  </div></div>`;

  const $ = s => root.querySelector(s);
  const descEl = $('#desc'), goEl = $('#go'), bodyEl = $('#wb-body'), switcherEl = $('#switcher');

  // ---------- 模式选择：读取当前选中档位；E2E 用同一 DOM 回读 ----------
  const currentMode = () => {
    const checked = root.querySelector('[data-mode-group] input[name="mode"]:checked');
    return checked ? checked.value : DEFAULT_MODE;
  };
  $('#chips').innerHTML = CHIPS.map((c, i) =>
    `<button class="chip" type="button" data-i="${i}">${esc(c.label)}</button>`).join('');
  $('#chips').addEventListener('click', e => {
    const b = e.target.closest('.chip');
    if (b) descEl.value = CHIPS[+b.dataset.i].desc;
  });
  root.querySelector('[data-mode-group]').addEventListener('change', e => {
    const input = e.target.closest('input[name="mode"]');
    if (!input) return;
    for (const opt of root.querySelectorAll('[data-mode-option]')) {
      opt.classList.toggle('selected', opt.dataset.modeOption === input.value);
    }
  });

  let cur = null, curJob = null, submitting = false;

  const bench = mountWorkbench(bodyEl, {
    onCancel: id => cancelJob(id),
    onRetry: async id => {
      const newId = await retryJob(id);
      await switchTo(newId);
    },
    onOpen: id => switchTo(id),
    loadRecent: async () => {
      const page = await fetchJobsPage({ status: 'done', page: 1, pageSize: 3 });
      return page.jobs || [];
    },
  });

  function paintElapsed() {
    const el = bodyEl.querySelector('[data-elapsed]');
    if (!el || !curJob) return;
    if (curJob.status === 'running' && curJob.startedAt) {
      el.textContent = `耗时 ${fmtElapsed(curJob.startedAt)}`;
      return;
    }
    const secs = curJob.result && curJob.result.elapsed_s;
    el.textContent = (secs !== undefined && secs !== null) ? `耗时 ${fmtDuration(secs)}` : '';
  }

  async function switchTo(id, { updateUrl = true } = {}) {
    if (!id) { cur = null; curJob = null; bench.show(null); renderSwitcher(); return; }
    let job;
    try {
      job = await fetchJob(id);
    } catch (e) {
      cur = null; curJob = null;
      bodyEl.innerHTML = `<div class="wb-empty"><div class="big">⚠️</div>
        <p>加载任务 ${esc(id)} 失败：${esc(String(e.message || e))}</p></div>`;
      return;
    }
    cur = id; curJob = job;
    touchRecent(id);
    if (updateUrl) history.replaceState(history.state, '', '/?job=' + encodeURIComponent(id));
    bench.show(job);
    paintElapsed();
    if (job.status === 'running') ensurePoller(id);
    renderSwitcher();
  }

  function switcherHTML() {
    const running = listSnapshot().running;
    const runIds = new Set(running.map(j => j.id));
    const recent = recentJobs().filter(j => !runIds.has(j.id));
    if (cur && !runIds.has(cur) && !recent.some(j => j.id === cur)) recent.unshift({ id: cur, desc: '' });
    const item = (j, icon) => `<button class="sw-item${j.id === cur ? ' current' : ''}" type="button" data-id="${esc(j.id)}">
      <span>${icon}</span><span class="nm" title="${esc(jobName(j.id))}">${esc(shortDesc(jobName(j.id), 24))}</span></button>`;
    return `
      ${running.length ? '<div class="sw-group">进行中</div>' + running.map(j => item(j, '⏳')).join('') : ''}
      ${recent.length ? (running.length ? '<hr>' : '') + '<div class="sw-group">最近查看</div>' + recent.slice(0, 5).map(j => item(j, '🧱')).join('') : ''}
      <hr><a class="sw-item" href="/history"><span>📜</span><span class="nm">查看全部历史</span></a>`;
  }

  function renderSwitcher() {
    const label = cur ? shortDesc(jobName(cur), 16) : '切换任务';
    const wasOpen = switcherEl.querySelector('.switcher-menu')?.classList.contains('open') ?? false;
    switcherEl.innerHTML = `
      <button type="button" aria-haspopup="true" aria-expanded="false">
        <span class="sw-label">${esc(label)}</span><span>▾</span>
      </button>
      <div class="switcher-menu" role="menu">${switcherHTML()}</div>`;
    const btn = switcherEl.querySelector('button');
    const menu = switcherEl.querySelector('.switcher-menu');
    if (wasOpen) menu.classList.add('open');
    btn.setAttribute('aria-expanded', String(wasOpen));
    btn.addEventListener('click', () => {
      const open = menu.classList.toggle('open');
      btn.setAttribute('aria-expanded', String(open));
    });
    menu.addEventListener('click', e => {
      const it = e.target.closest('.sw-item[data-id]');
      if (!it) return;
      menu.classList.remove('open');
      switchTo(it.dataset.id);
    });
  }

  const docClickHandler = e => {
    const menu = switcherEl.querySelector('.switcher-menu');
    if (menu && !switcherEl.contains(e.target)) menu.classList.remove('open');
  };
  document.addEventListener('click', docClickHandler, { capture: true });

  goEl.addEventListener('click', async () => {
    const desc = descEl.value.trim();
    if (!desc || submitting) return;
    const mode = currentMode();
    submitting = true; goEl.disabled = true;
    cur = null; curJob = null;
    bodyEl.innerHTML = `<div class="wb-status"><span class="wb-name">${esc(shortDesc(desc, 40))}</span>` +
      `<span class="tag run"><span class="ic">⏳</span>启动中</span>${modeBadge(mode)}` +
      `<span class="hint" data-elapsed></span></div>`;
    try {
      const id = await startJob(desc, mode);
      await switchTo(id);
    } catch (e) {
      bodyEl.innerHTML = `<div class="wb-empty"><div class="big">⚠️</div><p>启动失败：${esc(String(e.message || e))}</p></div>`;
    } finally {
      submitting = false; goEl.disabled = false;
    }
  });
  descEl.addEventListener('keydown', e => {
    if (e.key === 'Enter' && (e.ctrlKey || e.metaKey)) goEl.click();
  });

  const unsub = subscribe((type, data) => {
    if (type === 'list') { renderSwitcher(); return; }
    if (type !== 'job' || data.id !== cur || !curJob) return;
    if (data.error) { bench.notice(data.error); return; }
    bench.show(curJob);
    paintElapsed();
  });

  const elapsedTimer = setInterval(paintElapsed, 1000);
  const wanted = ctx.query.get('job');
  const running = listSnapshot().running;
  // 只自动接上地址栏指定的任务或仍在跑的任务。已完成的作品留在空态卡片里，点了再回看。
  const initId = wanted || (running.length ? running[0].id : '');
  await switchTo(initId, { updateUrl: false });

  return () => {
    unsub();
    clearInterval(elapsedTimer);
    bench.destroy();
    document.removeEventListener('click', docClickHandler, { capture: true });
  };
}
