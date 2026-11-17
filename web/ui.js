// ============================================================
// 共享 UI 工具：转义、格式化、统一状态标签
// 状态统一为「图标 + 文字」，进行中/降级/保底/失败在各页面使用同一套标签。
// 2026-11-14 双模式恢复：状态标签区分快速/高保真；快速成功明确标注“未进行视觉评审”，
// “未评审”不显示为 0 分，也不编造成高保真成功。
// ============================================================
import { modeBadgeText, modeLabel } from './modes.js';

export const esc = s => String(s ?? '').replace(/[&<>"']/g,
  c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));

export const sleep = ms => new Promise(r => setTimeout(r, ms));

export function debounce(fn, ms) {
  let t = null;
  return (...a) => { clearTimeout(t); t = setTimeout(() => fn(...a), ms); };
}

const fmtClock = secs => {
  const s = Math.max(0, Math.round(secs));
  return `${Math.floor(s / 60)}分${String(s % 60).padStart(2, '0')}秒`;
};

export const fmtTime = ts => new Date(ts * 1000).toLocaleTimeString('zh-CN', { hour12: false });

// 已运行时长（开始时间戳→现在）：创作台与历史任务共用同一格式
export const fmtElapsed = startedAt => fmtClock(Date.now() / 1000 - startedAt);
export const fmtDuration = secs => fmtClock(Number(secs) || 0);

export const fmtDateTime = ts => ts
  ? new Date(ts * 1000).toLocaleString('zh-CN', { hour12: false,
      month: '2-digit', day: '2-digit', hour: '2-digit', minute: '2-digit' })
  : '-';

export const shortDesc = (s, n = 40) => {
  const t = String(s || '').replace(/\s+/g, ' ').trim();
  return t.length > n ? t.slice(0, n) + '…' : t;
};

// 模式徽章（中文展示）。历史任务没有 mode 时不显示，避免错标。
export function modeBadge(mode) {
  const text = modeBadgeText(mode);
  return text ? `<span class="mode-chip" data-mode="${esc(text === '快速' ? 'fast' : 'fidelity')}">${esc(text)}</span>` : '';
}

// 结果状态四态：
// 高保真成功 / 降级交付 / 快速保底 / 快速成功 / 失败。
// 图标带 U+FE0F 变体选择符，保证 Windows 下渲染为彩色 emoji（⏹/⏸ 缺省是黑色单色方块）
const OUTCOME_TAG = {
  fidelity_success: { cls: 'ok',   icon: '✅', text: '高保真成功' },
  fidelity_degraded: { cls: 'warn', icon: '⚠️', text: '降级交付' },
  fast_fallback: { cls: 'fb',   icon: '🛟️', text: '快速保底' },
  fast_success: { cls: 'ok',   icon: '✅', text: '快速成功' },
  failed: { cls: 'bad',  icon: '❌', text: '生成失败' },
  cancelled: { cls: '',    icon: '⏹️', text: '已取消' },
  interrupted: { cls: 'warn', icon: '⏸️', text: '已中断' },
};

// 统一状态标签：优先按 result.outcome 命中四态，否则按执行状态。
// 旧任务没有 outcome 时用中性“生成成功”，不擅自归为快速或高保真。
export function statusTag(job) {
  const o = job && (job.outcome || (job.result && job.result.outcome));
  const status = job && job.status;
  let meta = OUTCOME_TAG[o];
  if (!meta) {
    meta = status === 'running' ? { cls: 'run', icon: '⏳', text: '进行中' }
      : status === 'cancelled' ? OUTCOME_TAG.cancelled
      : status === 'interrupted' ? OUTCOME_TAG.interrupted
      : status === 'error' ? OUTCOME_TAG.failed
      : status === 'done' ? { cls: 'ok', icon: '✅', text: '生成成功' }
      : { cls: '', icon: '•', text: status || '未知' };
  }
  return `<span class="tag ${meta.cls}"><span class="ic">${meta.icon}</span>${meta.text}</span>`;
}

const _FAST_OK_BANNER = '<div class="banner ok">✅ 快速生成成功：可拼初稿已交付' +
  '（快速生成，未进行视觉评审与视觉修订，因此不做视觉评分；结构与统一校验标准与高保真一致）</div>';

// 四态横幅（总览页；失败由错误卡展示，取消由 info 横幅展示）。
// mode 为任务真实模式：缺 outcome 的历史任务按它区分文案；完全未知时给中性文案。
export function outcomeBanner(res, mode) {
  const o = res.outcome;
  if (o === 'fidelity_success') return '<div class="banner ok">✅ 高保真成功：可拼方案 + 视觉评审达标</div>';
  if (o === 'fidelity_degraded') {
    return `<div class="banner warn">⚠️ 高保真产物已交付，但评审未完全通过（${esc(res.degraded_reason || '视觉评分不足或评审不可用')}）——按规则不重跑快速保底</div>`;
  }
  if (o === 'fast_fallback') {
    return `<div class="banner fb">🛟️ 高保真生成失败，已提供快速保底方案（不计高保真成功）` +
      `<span class="hint">高保真失败原因：${esc(res.fidelity_attempt_error || '-')}</span></div>`;
  }
  if (o === 'fast_success') return _FAST_OK_BANNER;
  if (o === 'cancelled') return '<div class="banner info">⏹️ 任务已取消：取消后不会再启动快速保底尝试</div>';
  if (o === 'failed') return '';
  if (!res.ok) return '';
  // 兼容旧任务：没有 outcome 时按持久化 mode 判断；完全未知不谎报高保真达标。
  if (modeBadgeText(mode) === '快速') return _FAST_OK_BANNER;
  if (modeBadgeText(mode) === '高保真') {
    return '<div class="banner ok">✅ 生成成功（历史任务未记录评审结论，不声称高保真达标）</div>';
  }
  return '<div class="banner ok">✅ 生成成功（历史任务未记录生成模式）</div>';
}

// 视觉评审分数徽章（整体 + 分项 + 最差部位；高保真任务展示）。
// 快速任务没有评审：不渲染评分，也不把“未评审”当 0 分；评审不可用/未通过如实标注。
export function reviewBadges(res) {
  const scores = (res.review && res.review.scores) || {};
  if (!Object.keys(scores).length) {
    if (res.review_unavailable || res.review_flag === 'review_unavailable') {
      return '<div class="hint">视觉评审不可用（如实标记：本次没有视觉评分，不属于 0 分）</div>';
    }
    if (res.review_failed || res.review_flag === 'review_failed') {
      return '<div class="hint">视觉评审未通过：本次没有可展示的有效评分（原因见降级说明）</div>';
    }
    return '';
  }
  const names = { proportion: '比例', features: '特征', color: '颜色', detail: '细节' };
  let html = `<span class="badge">视觉评审 overall <b>${esc(String(scores.overall ?? '-'))}</b>/10</span>`;
  for (const k of Object.keys(names)) {
    if (scores[k] !== undefined) html += `<span class="badge">${names[k]} <b>${esc(String(scores[k]))}</b></span>`;
  }
  const worst = (res.review && res.review.worst_parts) || [];
  if (worst.length) html += `<div class="hint">最差部位：${esc(worst.join('；'))}</div>`;
  return html;
}

// 两次尝试：分别展示模式、run_id、耗时、失败类别/原因与最终交付产物来源。
// 成功项不得再显示「未知原因」；失败项保留该次真实原因，空原因才写未知。
const _ATTEMPT_NAME = { fidelity: '高保真尝试', fast: '快速保底' };

function _attemptRow(a, isDelivered) {
  const name = _ATTEMPT_NAME[a.mode] || '尝试';
  const bits = [];
  bits.push(a.ok ? '成功' : '失败');
  if (a.run_id) bits.push(`run_id <span class="mono">${esc(a.run_id)}</span>`);
  if (a.elapsed_s !== undefined && a.elapsed_s !== null) bits.push(`耗时 ${esc(String(a.elapsed_s))}s`);
  if (!a.ok) {
    const failure = a.failure || {};
    const kind = failure.kind ? `失败类别 ${esc(String(failure.kind))}${failure.stage ? `（阶段 ${esc(String(failure.stage))}）` : ''}` : '失败类别未记录';
    const reason = a.error ? `：${esc(a.error)}` : '：未知原因';
    bits.push(kind + reason);
  }
  if (isDelivered && a.ok) bits.push('该次产物为最终交付产物');
  return `<div class="rv att-row">${a.ok ? '✅' : '❌'} <b>${name}</b>：${bits.join(' · ')}</div>`;
}

export function attemptsHTML(res) {
  const atts = res.attempts_detail || [];
  if (atts.length < 2) return '';
  // 最终交付产物来自最后一次成功的尝试（保底成功时即快速保底那次）。
  let lastOk = -1;
  atts.forEach((a, i) => { if (a.ok) lastOk = i; });
  const rows = atts.map((a, i) => _attemptRow(a, i === lastOk)).join('');
  return '<div class="section-title" style="margin-top:12px">两次尝试（分别保留）</div>' + rows;
}

// 重试相关页面的模式说明：快速不承诺继承评审意见。
export function modeRetryHint(mode) {
  return modeBadgeText(mode) === '快速'
    ? '快速任务没有视觉评审意见；重试按全新快速运行。'
    : '';
}

export { modeLabel };
