// ============================================================
// 真实阶段与求解进度。
// 阶段名来自后端上报，不从日志正文反推，也不画一条不存在的五步进度条。
// ============================================================
import { esc } from './ui.js';

export const PHASES = {
  plan: { icon: '📋', label: '规划', blurb: '正在确认规模、部位和造型计划' },
  draw: { icon: '🎨', label: '造型', blurb: '正在把计划编译成彩色体素设计稿' },
  label: { icon: '🏷️', label: '标注', blurb: '正在补齐部位标注' },
  review: { icon: '👁️', label: '评审', blurb: '正在对照多视角渲染做视觉评审' },
  revise: { icon: '🔧', label: '修订', blurb: '正在按评审或结构问题修订设计稿' },
  solve: { icon: '🧱', label: '求解', blurb: '正在把设计稿铺成可拼的零件' },
  final: { icon: '📦', label: '收尾', blurb: '正在做最后一次求解并写出产物' },
  artifacts: { icon: '📦', label: '产物', blurb: '正在写出步骤文档和独立 3D 页' },
};

export function phaseLabel(id) {
  if (!id) return '';
  return (PHASES[id] && PHASES[id].label) || String(id);
}

export function phaseBlurb(stage) {
  const id = stage && stage.current;
  if (!id) return '';
  return (PHASES[id] && PHASES[id].blurb) || '正在进行当前阶段';
}

// 只列出已经真实出现过的阶段。当前项高亮，修订带次数角标。图标和文字一起出现。
export function phaseBadgesHTML(stage) {
  const seen = (stage && Array.isArray(stage.seen)) ? stage.seen.slice() : [];
  const cur = stage && stage.current;
  if (cur && !seen.includes(cur)) seen.push(cur);
  if (!seen.length) return '';
  const items = seen.map(id => {
    const meta = PHASES[id] || { icon: '•', label: String(id) };
    const on = id === cur ? ' class="on"' : '';
    const cnt = id === 'revise' && stage && stage.revise
      ? `<span class="cnt" data-revise>${esc(String(stage.revise))}</span>` : '';
    return `<li${on} data-phase="${esc(id)}"><span class="ic" aria-hidden="true">${meta.icon}</span>${esc(meta.label)}${cnt}</li>`;
  }).join('');
  return `<ul class="phases" aria-label="阶段">${items}</ul>`;
}

// 求解器显式上报的一句进度。没有数据就不显示，也不拼百分比。
export function progressText(progress) {
  if (!progress || !progress.layer || !progress.total || !progress.round) return '';
  const y = progress.y != null && progress.y !== '' ? `（y=${progress.y}）` : '';
  return `正在铺第 ${progress.layer} 层${y}，共 ${progress.total} 层，第 ${progress.round} 轮`;
}

// 详情默认 Tab：进行中 → 复盘，完成 → 作品，失败 / 取消 / 中断 → 复盘。
export function defaultJobTab(job) {
  if (!job) return 'review';
  if (job.status === 'running') return 'review';
  if (job.status === 'done' && job.result && job.result.ok) return 'work';
  return 'review';
}

export const TAB_ALIAS = {
  overview: 'work', studio: 'work', work: 'work',
  steps: 'steps', logs: 'review', review: 'review',
};

export function canonicalTab(name, job) {
  if (name && TAB_ALIAS[name]) return TAB_ALIAS[name];
  return defaultJobTab(job);
}

// 失败 / 取消原因卡要用的三件事：原文、断点阶段、阶段中文名。
export function failureInfo(job) {
  const res = (job && job.result) || {};
  const stage = (res.failure && res.failure.stage) || (job && job.stage && job.stage.current) || '';
  let reason = res.error || '';
  if (!reason && job && job.status === 'cancelled') reason = '已由用户取消';
  if (!reason && job && job.status === 'interrupted') reason = '任务已中断（服务重启前未完成）';
  if (!reason) reason = '任务未完成';
  return { reason, stage, stageLabel: phaseLabel(stage) };
}
