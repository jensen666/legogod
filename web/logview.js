// ============================================================
// 日志视图：阶段事件做成分隔条，求解器明细合并成可折叠分组。
// 创作台抽屉和详情「复盘」共用。导出仍走原始日志条目，不丢关键事件。
// ============================================================
import { esc, fmtTime } from './ui.js';
import { phaseLabel } from './stage.js';
import { thinkingTurnHTML, pairThoughtEntries } from './thinking.js';

export function presentLogs(logs) {
  const out = [];
  let bucket = null;
  const flush = () => { if (bucket) { out.push(bucket); bucket = null; } };
  const thoughts = pairThoughtEntries(logs);
  const byEntry = new Map(thoughts.map(p => [p.entry, p.thought]));
  // 有摘要的 thought 已被吸收进思考块标题；空 thought 没有信息量，也不单独占一行。
  const absorbed = new Set(thoughts.filter(p => p.thoughtEntry).map(p => p.thoughtEntry));
  for (const entry of logs || []) {
    if (absorbed.has(entry)) continue;
    if (entry && entry.kind === 'thought' && !String(entry.text || '').trim()) continue;
    if (entry && entry.kind === 'solver') {
      if (!bucket) bucket = { type: 'solver', items: [] };
      bucket.items.push(entry);
      continue;
    }
    flush();
    if (entry && entry.kind === 'phase') out.push({ type: 'phase', entry });
    else out.push({ type: 'line', entry, thought: byEntry.get(entry) || '' });
  }
  flush();
  return out;
}

function entryKey(entry, index) {
  return `${entry && entry.ts != null ? entry.ts : 'i' + index}-${entry && entry.kind || ''}`;
}

function lineHTML(entry, key, thought = '') {
  const kind = entry.kind || 'info';
  const t = entry.ts ? fmtTime(entry.ts) : '';
  const step = entry.step != null ? `<span class="rv-s">S${esc(String(entry.step))}</span>` : '';
  if (kind === 'thinking') return thinkingTurnHTML(entry, thought, key);
  const head = `<span class="t">${esc(t)}</span>${step}<span class="k-${esc(kind)}">[${esc(kind)}]</span> `;
  const text = String(entry.text || '');
  if (text.length > 260) {
    return `<div class="ln">${head}<details data-key="${esc(key)}"><summary>${esc(text.slice(0, 240))} ……（点击展开全部 ${text.length} 字）</summary><pre>${esc(text)}</pre></details></div>`;
  }
  return `<div class="ln">${head}${esc(text)}</div>`;
}

function blockHTML(block, index) {
  if (block.type === 'phase') {
    const id = block.entry && (block.entry.phase || '');
    const label = phaseLabel(id) || String((block.entry && block.entry.text) || '阶段');
    return `<div class="phasebar" data-phase="${esc(id)}">◆ 阶段 · ${esc(label)}</div>`;
  }
  if (block.type === 'solver') {
    const n = block.items.length;
    const key = entryKey(block.items[0], index);
    const body = block.items.map((item, i) => lineHTML(item, entryKey(item, i))).join('');
    return `<details class="solver-group" data-key="${esc(key)}"><summary>求解器明细 · ${n} 条</summary>${body}</details>`;
  }
  return lineHTML(block.entry || {}, entryKey(block.entry, index), block.thought);
}

export function createLogView(container) {
  container.classList.add('logbox');
  container.setAttribute('role', 'log');
  container.setAttribute('aria-live', 'off');
  const entries = [];

  function render() {
    const near = container.scrollHeight - container.scrollTop - container.clientHeight < 60;
    const open = new Set([...container.querySelectorAll('details[open][data-key]')].map(d => d.dataset.key));
    container.innerHTML = presentLogs(entries).map(blockHTML).join('');
    for (const det of container.querySelectorAll('details[data-key]')) {
      if (open.has(det.dataset.key)) det.open = true;
    }
    if (near) container.scrollTop = container.scrollHeight;
  }

  return {
    reset() { entries.length = 0; container.innerHTML = ''; },
    load(list) {
      entries.length = 0;
      for (const item of list || []) entries.push({ kind: item.kind, text: item.text, ...item });
      render();
    },
    append(kind, text, meta = {}) {
      entries.push({ kind, text, ...meta });
      render();
    },
    live(host, text) {
      let bar = host.querySelector('.livebar');
      if (!bar) {
        bar = document.createElement('div');
        bar.className = 'livebar';
        host.appendChild(bar);
      }
      if (text) { bar.textContent = text; bar.classList.add('on'); }
      else { bar.classList.remove('on'); bar.textContent = ''; }
    },
  };
}

export function milestonesHTML(logs) {
  const miles = (logs || []).filter(l =>
    l.kind === 'phase' || l.kind === 'review' || l.kind === 'result' || l.kind === 'error' ||
    l.kind === 'version' || l.kind === 'revise' || l.kind === 'plan' ||
    (l.kind === 'tool' && /求解成功|求解结束：失败|校验未通过|设计已保存|求解失败/.test(l.text || '')));
  if (!miles.length) return '<div class="hint">该任务没有可复盘的里程碑。</div>';
  return miles.map(l => {
    const label = l.kind === 'phase' ? phaseLabel(l.phase) : '';
    const shown = label ? `阶段 · ${label}` : String(l.text || '');
    const first = shown.split('\n')[0].slice(0, 120);
    const bad = l.kind === 'error' || /失败|未通过/.test(shown);
    const okMark = /成功|已保存|达标/.test(shown) && l.kind !== 'error';
    const icon = l.kind === 'phase' ? '◆' : l.kind === 'review' ? '👁️' : bad ? '❌' : okMark ? '✅' : '🛠';
    const body = shown.length > 130
      ? `<details><summary>${esc(first)}……</summary><pre>${esc(shown)}</pre></details>`
      : esc(first);
    const step = l.step != null ? `<span class="rv-s">S${l.step}</span>` : '';
    return `<div class="rv">${step}${icon} ${body}</div>`;
  }).join('');
}

export function exportLogsMd(res, logs) {
  const out = [`# LEGOGOD 运行日志 · ${res.name || ''}`, '',
    `- 结论：${res.ok ? '拼装成功' : '未完成'}；体素 ${res.voxels ?? '-'}；零件 ${res.pieces ?? '-'}；求解尝试 ${res.attempts ?? '-'} 次`,
    '', '## 时间线', ''];
  for (const l of (logs || [])) {
    const t = l.ts ? fmtTime(l.ts) : '-';
    out.push(`### [${t}] S${l.step ?? '-'} · ${l.kind}`);
    out.push('```');
    out.push(l.text);
    out.push('```');
  }
  const blob = new Blob([out.join('\n')], { type: 'text/markdown;charset=utf-8' });
  const a = document.createElement('a');
  a.href = URL.createObjectURL(blob);
  a.download = `运行日志_${res.slug || res.name || 'job'}.md`;
  a.click();
  URL.revokeObjectURL(a.href);
}
