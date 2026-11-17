// ============================================================
// 配色条：按颜色占比分段。没有颜色数据时留空，不编造色块。
// ============================================================
import { esc } from './ui.js';

export function paletteHTML(colors) {
  if (!Array.isArray(colors) || !colors.length) {
    return '<span class="palette-empty">—</span>';
  }
  const segs = colors.map(c => {
    const share = Number(c.share) || 0;
    const width = Math.max(4, Math.round(share * 100));
    const hex = c.hex || '#6b7480';
    return `<i style="width:${width}%;background:${esc(hex)}" title="${esc(c.name || '')}"></i>`;
  }).join('');
  return `<span class="palette" role="img" aria-label="配色">${segs}</span>`;
}
