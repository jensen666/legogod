// ============================================================
// 零件目录：完整库存独立成页，不再占用创作页。
// 唯一数据源 /api/parts：按形状分组展示全部「形状 × 颜色」变体，含加载/失败/空态。
// ============================================================
import { esc } from '../ui.js';
import { getParts } from '../tasks.js';

export async function mountParts(root) {
  root.innerHTML = `
  <div class="page">
    <div class="page-head">
      <h1 class="page-title">零件目录</h1>
      <span class="hint" data-meta></span>
    </div>
    <p class="hint" style="margin:-8px 0 16px">由服务端 /api/parts 统一提供（唯一数据源）：按形状分组展示全部「形状 × 颜色」变体，
      含色块、颜色名、尺寸、库存与零件 id；零件库扩库后新变体会自动出现，前端不硬编码零件清单。</p>
    <div id="catalog"><div class="empty"><span class="spin">⏳</span><p>零件目录加载中……</p></div></div>
  </div>`;

  const catalogEl = root.querySelector('#catalog');
  const metaEl = root.querySelector('[data-meta]');

  function renderCatalog(parts) {
    if (!parts.length) {
      catalogEl.innerHTML = '<p class="hint" style="margin:0">零件目录为空：服务端没有返回任何零件（请检查 parts_library）。</p>';
      metaEl.textContent = '';
      return;
    }
    const byShape = new Map();
    for (const p of parts) {
      const k = p.shape || p.id;
      if (!byShape.has(k)) byShape.set(k, []);
      byShape.get(k).push(p);
    }
    const shapes = [...byShape.values()];
    metaEl.textContent = `${shapes.length} 种形状 · ${parts.length} 个「形状×颜色」变体`;
    catalogEl.innerHTML = shapes.map(list => {
      const p0 = list[0];
      const slopes = p0.slope ? ` · 坡向 ${esc(p0.slope)}` : '';
      const variants = list.map(p =>
        `<span class="cat-variant" title="${esc(p.id)} · 库存 ${p.count}">` +
        `<span class="dot" style="background:${esc(p.color)}"></span>${esc(p.colorName)} × ${p.count}` +
        `<code>${esc(p.id)}</code></span>`).join('');
      return `<details class="cat-shape" ${p0.slope ? '' : 'open'}>` +
        `<summary><b>${esc(p0.name)}</b> · ${p0.w}×${p0.d}${slopes} · ${list.length} 色变体</summary>` +
        `<div class="cat-variants">${variants}</div></details>`;
    }).join('');
  }

  async function load(force = false) {
    catalogEl.innerHTML = '<div class="empty"><span class="spin">⏳</span><p>零件目录加载中……</p></div>';
    try {
      renderCatalog(await getParts(force));
    } catch (e) {
      catalogEl.innerHTML =
        `<div class="empty"><p class="err-text">零件目录加载失败：${esc(String(e.message || e))}。</p>` +
        `<div class="actions"><button class="btn btn-secondary btn-sm" type="button" data-retry>重试</button></div></div>`;
      catalogEl.querySelector('[data-retry]').addEventListener('click', () => load(true));
    }
  }

  await load();
  return () => {};
}
