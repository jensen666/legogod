// ============================================================
// 思考过程展示：纯函数，可在 node 里单测。
// - pickThinkingTurns：从日志里抽出所有 thinking 条目，并按「同一 phase 下、
//   下一条 thinking 之前最近的 thought」配对中文摘要
// - thinkingPanelHTML：生成 <details class="think-panel">，标题 = 阶段 + 耗时 + 字数 + 摘要
// - thinkingStateHTML：进行中取实时通道，已结束取最后一条落盘条目
// 模型输出是不可信内容：所有推理原文一律经 esc()，绝不直接拼进 innerHTML。
// ============================================================
import { esc } from './ui.js';
import { phaseLabel } from './stage.js';

// 一条 thinking 日志条目 → 统一形状。非法条目返回 null。
// key：日志视图里用于保留展开状态（details[data-key]），与其它折叠块同一机制。
function toTurn(entry, thought = '', key = '') {
  if (!entry || entry.kind !== 'thinking') return null;
  const text = String(entry.text ?? '');
  if (!text) return null;
  const chars = Number.isFinite(entry.chars) ? entry.chars : text.length;
  return {
    phase: entry.phase || '',
    phaseLabel: phaseLabel(entry.phase) || entry.phase || '思考',
    text,
    chars,
    truncated: !!entry.truncated,
    partial: !!entry.partial,
    elapsed: Number.isFinite(entry.elapsed) ? entry.elapsed : null,
    thought: thought || '',
    ts: entry.ts != null ? entry.ts : null,
    key: key || '',
  };
}

// 从日志里抽出所有思考回合，并配对摘要。
// 真实发出顺序（workflow.model_turn）：thinking 回合结束先落盘，解析成功后才有 thought。
// 配对规则：同一 phase 下、下一条 thinking 之前最近的 thought 归前一条 thinking。
// 返回 [{ entry, thoughtEntry, thought }]，顺序与日志一致；entry 仍是原始日志对象。
export function pairThoughtEntries(logs) {
  const out = [];
  let last = null;   // 最近一条、尚未配上摘要的 thinking 记录
  for (const entry of (Array.isArray(logs) ? logs : [])) {
    if (!entry || typeof entry !== 'object') continue;
    if (entry.kind === 'thinking') {
      last = { entry, phase: entry.phase || '', thoughtEntry: null, thought: '' };
      out.push(last);
      continue;
    }
    if (entry.kind !== 'thought' || !last || last.thoughtEntry) continue;
    if (last.phase !== (entry.phase || '')) continue;
    const text = String(entry.text ?? '').trim();
    if (!text) continue;
    last.thoughtEntry = entry;
    last.thought = text;
  }
  return out;
}

export function pickThinkingTurns(logs) {
  return pairThoughtEntries(logs)
    .map(({ entry, thought }, i) => toTurn(entry, thought, 'tk' + i))
    .filter(Boolean);
}

export function fmtThinkingElapsed(sec) {
  if (!Number.isFinite(sec) || sec <= 0) return '';
  return `${Math.round(sec)}s`;
}

// 标题右侧的一行元信息：阶段 · 耗时 · 字数，以及被截断 / 半截标记。
export function thinkingMeta(turn) {
  const bits = [turn.phaseLabel || '思考'];
  const el = fmtThinkingElapsed(turn.elapsed);
  if (el) bits.push(el);
  bits.push(`${Number(turn.chars || 0).toLocaleString('zh-CN')} 字`);
  if (turn.partial) bits.push('未完成');
  if (turn.truncated) bits.push('已截断');
  return bits.join(' · ');
}

// <details class="think-panel">；open 决定初始展开，live=true 时加进行中样式。
export function thinkingPanelHTML(turn, { open = false, live = false } = {}) {
  if (!turn || !turn.text) return '';
  const cls = 'think-panel' + (live ? ' think-live' : '');
  const summary = turn.thought
    ? `<span class="think-idea">${esc(turn.thought)}</span>`
    : '';
  return `<details class="${cls}"${open ? ' open' : ''}` +
    ` data-think-phase="${esc(turn.phase || '')}"` +
    (turn.key ? ` data-key="${esc(turn.key)}"` : '') + '>' +
    `<summary><span class="think-tag">💭 思考</span>` +
    `<span class="think-meta">${esc(thinkingMeta(turn))}</span>${summary}</summary>` +
    `<pre class="think-body">${esc(turn.text)}</pre></details>`;
}

// 日志条目 → 折叠面板 HTML（logview 用：默认折叠，展开状态按 data-key 保留）。
export function thinkingTurnHTML(entry, thought, key) {
  return thinkingPanelHTML(toTurn(entry, thought, key), { open: false });
}

// 进行中的实时通道 → turn（job.thinking 由 /api/job 下发，重启后为 null）。
export function liveTurn(live) {
  if (!live || typeof live !== 'object') return null;
  const text = String(live.text ?? '');
  if (!text) return null;
  const chars = Number.isFinite(live.chars) ? live.chars : text.length;
  return {
    phase: live.phase || '', phaseLabel: phaseLabel(live.phase) || live.phase || '思考',
    text, chars, truncated: false, partial: !!live.partial,
    elapsed: Number.isFinite(live.elapsed) ? live.elapsed : null,
    thought: '', ts: null, live: true,
  };
}

// 状态选择：进行中有实时通道就用实时，否则取已落盘的最后一条思考。
export function thinkingStateHTML(job, { open = false } = {}) {
  if (!job) return '';
  const live = liveTurn(job.thinking);
  if (live) return thinkingPanelHTML(live, { open: true, live: true });
  const turns = pickThinkingTurns(job.logs);
  if (!turns.length) return '';
  return thinkingPanelHTML(turns[turns.length - 1], { open });
}
