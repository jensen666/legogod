# -*- coding: utf-8 -*-
"""思考过程流式展示前端纯函数单测。

用 node 执行 web/thinking.js：配对方向、折叠面板转义、空推理返回空串。
未安装 node 时跳过（与 test_ui_frontend.py 同一策略）。
"""
import os
import shutil
import subprocess
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

NODE_SOURCE = r"""
import {
  pickThinkingTurns, pairThoughtEntries, thinkingPanelHTML, thinkingStateHTML,
  thinkingTurnHTML, liveTurn, thinkingMeta,
} from './web/thinking.js';

const fail = (msg) => { console.error(msg); process.exit(1); };
const eq = (a, b, msg) => {
  if (JSON.stringify(a) !== JSON.stringify(b)) fail(`${msg}: ${JSON.stringify(a)} != ${JSON.stringify(b)}`);
};

// ① 配对方向：真实顺序是先落 thinking 再发 thought；只有同 phase 才配对
const logs = [
  { kind: 'phase', text: '阶段', phase: 'plan', ts: 1 },
  { kind: 'thinking', text: '第一轮推理', phase: 'plan', chars: 5, elapsed: 3, ts: 2 },
  { kind: 'thought', text: '先规划规模', phase: 'plan', ts: 3 },
  { kind: 'thinking', text: '第二轮推理', phase: 'plan', chars: 5, elapsed: 2, ts: 4 },
  { kind: 'thought', text: '跨阶段摘要', phase: 'draw', ts: 5 },
  { kind: 'thought', text: '造型完成', phase: 'draw', ts: 6 },
  { kind: 'thinking', text: '第三轮推理', phase: 'draw', chars: 5, elapsed: 1, ts: 7 },
];
const turns = pickThinkingTurns(logs);
eq(turns.length, 3, '应抽出 3 个思考回合');
eq(turns.map(t => t.thought), ['先规划规模', '', ''], '只有相邻同 phase 的 thought 才配对');
eq(turns.map(t => t.phase), ['plan', 'plan', 'draw'], '阶段顺序保持日志顺序');
const paired = pairThoughtEntries(logs);
eq(paired.length, 3, 'pairThoughtEntries 条数');
if (paired[0].thoughtEntry.ts !== 3) fail('摘要应指回原始 thought 条目');
if (paired[1].thoughtEntry !== null) fail('跨阶段 thought 不得认领');

// ② 转义：推理原文含 HTML/脚本不得原样出现
const evil = { kind: 'thinking', text: '<script>alert(1)</script>', phase: 'plan', chars: 30, elapsed: 1 };
const evilHTML = thinkingPanelHTML(evil, { open: false });
if (evilHTML.includes('<script>')) fail('推理原文不得原样进 innerHTML');
if (!evilHTML.includes('&lt;script&gt;')) fail('推理原文必须经 esc()');

// 摘要同样要转义
const evilIdea = thinkingPanelHTML({ ...evil, thought: '<img src=x onerror=alert(1)>' });
if (evilIdea.includes('<img')) fail('摘要不得原样进 innerHTML');

// ③ 空推理返回空串
eq(thinkingPanelHTML(null), '', '空 turn 返回空串');
eq(thinkingPanelHTML({ text: '' }), '', '空文本返回空串');
eq(thinkingStateHTML({ logs: [] }), '', '没有思考时不渲染');
eq(thinkingTurnHTML({ kind: 'thinking', text: '' }, '', 'k'), '', '空日志条目不渲染');
eq(liveTurn(null), null, 'null 实时通道');

// ④ 标题元信息：阶段 · 耗时 · 字数 · 标记
const meta = thinkingMeta({ phaseLabel: '造型', elapsed: 42.4, chars: 3210, partial: false, truncated: true });
if (!meta.includes('造型') || !meta.includes('42s') || !meta.includes('3,210 字') || !meta.includes('已截断')) {
  fail('标题元信息不完整: ' + meta);
}
const partialMeta = thinkingMeta({ phaseLabel: '规划', elapsed: null, chars: 10, partial: true });
if (!partialMeta.includes('未完成') || partialMeta.includes('s ·')) fail('半截标记: ' + partialMeta);

// ⑤ 实时通道优先：有 job.thinking 就显示实时，忽略已落盘回合
const liveHTML = thinkingStateHTML({
  thinking: { phase: 'draw', text: '正在推理', chars: 4, elapsed: 1 },
  logs: [{ kind: 'thinking', text: '旧回合', phase: 'plan', chars: 3, ts: 9 }],
});
if (!liveHTML.includes('think-live') || !liveHTML.includes('正在推理')) fail('实时通道必须优先: ' + liveHTML);
if (liveHTML.includes('旧回合')) fail('实时进行中不得混入旧回合');

// ⑤b live 选项必须直接生效（真实任务验收发现：workbench 漏传 live，实时样式从未出现）
const explicitLive = thinkingPanelHTML({ phase: 'draw', text: 'x', phaseLabel: '造型', chars: 1 }, { live: true });
if (!explicitLive.includes('think-live')) fail('live:true 必须带 think-live 类');
const explicitStatic = thinkingPanelHTML({ phase: 'draw', text: 'x', phaseLabel: '造型', chars: 1 }, { live: false });
if (explicitStatic.includes('think-live')) fail('live:false 不得带 think-live 类');

// ⑥ 已结束取最后一条且默认折叠
const doneHTML = thinkingStateHTML({ logs }, { open: false });
if (!doneHTML.includes('第三轮推理')) fail('已结束应显示最后一条');
if (doneHTML.includes(' open')) fail('已结束默认折叠');

// ⑦ 折叠块带 data-key，便于日志视图保留展开状态
const keyed = thinkingTurnHTML({ kind: 'thinking', text: 'x', phase: 'plan', chars: 1 }, '', 'k1');
if (!keyed.includes('data-key="k1"')) fail('日志视图折叠块需要 data-key');

console.log('ok');
"""


class ThinkingUiTest(unittest.TestCase):
    def test_thinking_ui_pure_functions(self):
        node = shutil.which("node")
        if not node:
            self.skipTest("未安装 node，跳过 web/thinking.js 前端单测")
        proc = subprocess.run([node, "--input-type=module", "-e", NODE_SOURCE],
                              cwd=ROOT, capture_output=True, text=True, timeout=30)
        self.assertEqual(proc.returncode, 0, proc.stderr or proc.stdout)
        self.assertIn("ok", proc.stdout)

    def test_workbench_passes_live_flag_to_panel(self):
        """创作台渲染实时面板必须把 live 传下去（真实任务验收发现的接线漏洞）。

        纯函数单测覆盖不到「调用方漏传参数」：thinkingPanelHTML 本身支持 live，
        但 workbench 曾只传 open，导致进行中的实时样式从来不出现。
        """
        src = open(os.path.join(ROOT, "web", "pages", "workbench.js"), encoding="utf-8").read()
        self.assertIn("thinkingPanelHTML(now.turn, { open, live: now.live })", src,
                      "workbench 必须把 now.live 传给 thinkingPanelHTML")


if __name__ == "__main__":
    unittest.main()
