// ============================================================
// 生成模式：
// Web 恢复「快速 / 高保真」两档选择，默认快速。两档是生成策略与视觉闭环差异，
// 不是“简单作品/复杂作品”两套模型，也不做自动复杂度分类。
//
// 本模块只放可单测的纯函数与控件模板：值规范化、中文标签、辅助说明、提交参数、
// 重试按钮文案。页面 DOM 绑定留在页面模块里，node 单测可以直接 import 本文件。
// ============================================================

// Web 默认档位。只影响新任务：修改选择不得改变已运行或历史任务的模式。
export const DEFAULT_MODE = 'fast';

// API 缺省语义：POST /api/build 省略 mode 时仍按 fidelity 处理（兼容既有调用方）。
// Web 必须始终显式提交用户所见模式，绝不依赖服务端缺省值。
export const API_DEFAULT_MODE = 'fidelity';

export const MODES = [
  {
    id: 'fast',
    label: '快速',
    short: '快速',
    desc: '跳过视觉评审和视觉修订，优先生成可拼初稿；仍需完成结构与统一校验。',
    hint: '通常更快；不进行视觉评审，因此不提供视觉评分。',
  },
  {
    id: 'fidelity',
    label: '高保真',
    short: '高保真',
    desc: '增加多视角视觉评审与有界外观修订，通常耗时更长；硬失败时自动快速保底一次。',
    hint: '外观精修优先；硬失败时可能自动快速保底（计为同一任务的第二次尝试）。',
  },
];

const MODE_IDS = MODES.map(m => m.id);
const MODE_SET = new Set(MODE_IDS);

function clean(mode) {
  return String(mode ?? '').trim().toLowerCase();
}

// 把任意输入规范成合法模式；非法/缺失回退 fallback（默认 Web 快速）。
// 注意：服务端 /api/build 的缺省值是 fidelity，和这里的 Web 缺省语义不同，不要混用。
export function normalizeMode(mode, fallback = DEFAULT_MODE) {
  const m = clean(mode);
  if (MODE_SET.has(m)) return m;
  const f = clean(fallback);
  return MODE_SET.has(f) ? f : DEFAULT_MODE;
}

// 中文展示名：快速 / 高保真；完全未记录时显示“未记录”，不擅自改写成某一档。
export function modeLabel(mode) {
  const m = clean(mode);
  return m === 'fast' ? '快速' : m === 'fidelity' ? '高保真' : '未记录';
}

// 模式徽章文案：历史任务没有 mode 时不显示徽章，避免把旧任务错标成某一档。
export function modeBadgeText(mode) {
  const m = clean(mode);
  return m === 'fast' || m === 'fidelity' ? modeLabel(m) : '';
}

// 提交参数：Web 始终显式携带 mode。
export function buildJobPayload(desc, mode) {
  return { desc: String(desc ?? ''), mode: normalizeMode(mode) };
}

// 手动重试按钮文案：快速任务没有视觉评审可继承，不能承诺“携带评审意见”。
export function retryLabel(mode) {
  return normalizeMode(mode) === 'fast' ? '🔁 按快速模式重试' : '🔁 携带评审意见重试';
}

// 模式选择控件：两档清晰可选、默认选中快速、带可访问名称。
// E2E 通过 [data-mode-group] input[name="mode"]:checked 读取当前档位，
// 通过 #mode-fast / #mode-fidelity 点击切换。
export function modeSelectorHTML(selected = DEFAULT_MODE) {
  const cur = normalizeMode(selected);
  const items = MODES.map(m => {
    const checked = m.id === cur;
    return `<label class="mode-opt${checked ? ' selected' : ''}" data-mode-option="${m.id}">
        <input type="radio" name="mode" value="${m.id}" id="mode-${m.id}" data-mode="${m.id}"
          aria-label="${m.label}"${checked ? ' checked' : ''}>
        <span class="mode-body">
          <span class="mode-name">${m.label}</span>
          <span class="mode-desc">${m.desc}</span>
        </span>
      </label>`;
  }).join('');
  return `<fieldset class="modes" data-mode-group role="radiogroup" aria-label="生成模式">
      <legend class="modes-title">生成模式 <span class="hint">默认快速 · 只影响新任务</span></legend>
      ${items}
    </fieldset>`;
}
