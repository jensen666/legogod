# -*- coding: utf-8 -*-
"""创作台阶段徽标、进度句、详情 Tab 与日志分组的前端单测。未安装 node 时跳过。"""
import os
import shutil
import subprocess
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

NODE_SOURCE = r"""
import { phaseBadgesHTML, progressText, defaultJobTab, canonicalTab, failureInfo } from './web/stage.js';
import { paletteHTML } from './web/palette.js';
import { presentLogs, milestonesHTML } from './web/logview.js';

const fail = (msg) => { console.error(msg); process.exit(1); };

const badges = phaseBadgesHTML({ current: 'revise', seen: ['plan', 'draw', 'revise'], revise: 2 });
if (!badges.includes('规划') || !badges.includes('造型') || !badges.includes('修订')) fail('阶段名缺失 ' + badges);
if (!badges.includes('data-phase="revise"') || !badges.includes('data-revise')) fail('修订角标缺失 ' + badges);
if (badges.includes('求解')) fail('没发生的阶段不能出现 ' + badges);
if (!badges.includes('class="on"')) fail('当前阶段要高亮 ' + badges);

const sentence = progressText({ layer: 3, total: 12, round: 2, y: 2 });
if (sentence !== '正在铺第 3 层（y=2），共 12 层，第 2 轮') fail('进度句不对 ' + sentence);
if (sentence.includes('%') || progressText(null) !== '') fail('不许伪进度');

if (defaultJobTab({ status: 'running' }) !== 'review') fail('进行中应进复盘');
if (defaultJobTab({ status: 'done', result: { ok: true } }) !== 'work') fail('完成应进作品');
if (defaultJobTab({ status: 'error', result: { ok: false } }) !== 'review') fail('失败应进复盘');
if (defaultJobTab({ status: 'cancelled' }) !== 'review') fail('取消应进复盘');
if (canonicalTab('overview') !== 'work' || canonicalTab('studio') !== 'work') fail('旧作品链接');
if (canonicalTab('steps') !== 'steps' || canonicalTab('logs') !== 'review') fail('旧步骤/日志链接');

const info = failureInfo({ status: 'error', result: { error: 'y=7 层支撑不可行', failure: { stage: 'solve' } }, stage: { current: 'draw' } });
if (info.reason !== 'y=7 层支撑不可行' || info.stage !== 'solve' || info.stageLabel !== '求解') fail(JSON.stringify(info));

const emptyBar = paletteHTML(null);
if (!emptyBar.includes('—')) fail('无颜色要留空');
const bar = paletteHTML([{ name: '红色', hex: '#C4281B', share: 0.5 }]);
if (!bar.includes('#C4281B') || !bar.includes('红色')) fail(bar);

const grouped = presentLogs([
  { kind: 'phase', phase: 'solve', text: '—— 阶段：solve ——' },
  { kind: 'solver', text: 'y=0' },
  { kind: 'solver', text: 'y=1' },
  { kind: 'result', text: '完成' },
]);
if (grouped.length !== 3) fail('分组数量 ' + grouped.length);
if (grouped[0].type !== 'phase' || grouped[1].type !== 'solver' || grouped[1].items.length !== 2) fail(JSON.stringify(grouped));
if (grouped[2].type !== 'line') fail('结果应单独成行');

// 思考块与 thought 的配对（真实任务验收发现：修订轮 thought 为空应整行消失，
// 有摘要的 thought 应被吸收进思考块标题，不重复占行）
const withThinking = presentLogs([
  { kind: 'phase', phase: 'plan', text: '阶段' },
  { kind: 'thinking', phase: 'plan', text: '推理原文', ts: 1, chars: 4 },
  { kind: 'thought', phase: 'plan', text: '规划摘要', ts: 2 },
  { kind: 'thinking', phase: 'revise', text: '第二轮', ts: 3, chars: 3 },
  { kind: 'thought', phase: 'revise', text: '', ts: 4 },
]);
const kinds = withThinking.map(b => (b.type === 'phase' ? 'phase' : b.entry.kind));
if (kinds.join(',') !== 'phase,thinking,thinking') {
  fail('有摘要的 thought 应被吸收、空 thought 应整行消失：' + kinds.join(','));
}
if (withThinking[1].thought !== '规划摘要') fail('思考块必须带上配对摘要');
if (withThinking[2].thought) fail('空 thought 不得配成摘要');

const miles = milestonesHTML([{ kind: 'phase', phase: 'plan', text: '—— 阶段：plan ——' }]);
if (!miles.includes('阶段 · 规划') || miles.includes('阶段：plan')) fail('里程碑阶段名 ' + miles);

const banner = (await import('./web/ui.js')).outcomeBanner;
const degraded = banner({ outcome: 'fidelity_degraded', degraded_reason: '视觉评分不足' }, 'fidelity');
if (!degraded.includes('高保真产物已交付，但评审未完全通过（视觉评分不足）——按规则不重跑快速保底')) {
  fail('降级横幅被改写 ' + degraded);
}
console.log('ok');
"""


class StageUiTest(unittest.TestCase):
    def test_stage_progress_tabs_and_log_groups(self):
        node = shutil.which("node")
        if not node:
            self.skipTest("未安装 node，跳过前端单测")
        proc = subprocess.run([node, "--input-type=module", "-e", NODE_SOURCE],
                              cwd=ROOT, capture_output=True, text=True,
                              encoding="utf-8", timeout=30)
        self.assertEqual(proc.returncode, 0, proc.stderr or proc.stdout)
        self.assertIn("ok", proc.stdout)


if __name__ == "__main__":
    unittest.main()
