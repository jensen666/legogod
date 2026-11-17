# -*- coding: utf-8 -*-
"""前端双模式单测。

用 node 执行 web/modes.js 与 web/ui.js 的纯函数：
- Web 默认快速，API 缺省 fidelity，两者语义不可混用；
- 模式控件默认选中快速、切换后选中高保真、具备可访问名称；
- 提交参数始终显式携带模式；非法/缺失回退 Web 默认快速；
- 快速成功文案明确“未进行视觉评审”，不显示 0 分；
- 旧任务缺 outcome 时不谎报高保真达标；
- 双尝试展示 run_id/耗时/失败类别/最终交付产物来源。

未安装 node 时跳过（与 test_ui_frontend.py 同口径）。
"""
import os
import shutil
import subprocess
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

NODE_SOURCE = r"""
import { DEFAULT_MODE, API_DEFAULT_MODE, MODES, normalizeMode, modeLabel,
         modeBadgeText, buildJobPayload, retryLabel, modeSelectorHTML } from './web/modes.js';
import { outcomeBanner, attemptsHTML, statusTag, reviewBadges, modeBadge } from './web/ui.js';

const fail = (msg) => { console.error(msg); process.exit(1); };

// 1. Web 默认快速；API 缺省高保真（§二-7：两者不可混用）
if (DEFAULT_MODE !== 'fast') fail('Web 默认必须是快速');
if (API_DEFAULT_MODE !== 'fidelity') fail('API 缺省必须是 fidelity');
if (MODES.length !== 2) fail('必须恰好两档');

// 2. 模式控件：默认选中快速、可访问名称、切换后选中高保真
const html = modeSelectorHTML();
const fastChecked = /<input[^>]*id="mode-fast"[^>]*checked/.test(html);
const fidChecked = /<input[^>]*id="mode-fidelity"[^>]*checked/.test(html);
if (!fastChecked || fidChecked) fail('默认必须选中快速: ' + html);
if (!/role="radiogroup"/.test(html) || !/aria-label="生成模式"/.test(html)) fail('必须是 radiogroup 且有组名');
if (!/aria-label="快速"/.test(html) || !/aria-label="高保真"/.test(html)) fail('两档必须有可访问名称');
const alt = modeSelectorHTML('fidelity');
if (/<input[^>]*id="mode-fast"[^>]*checked/.test(alt)) fail('切换后快速不得仍选中');
if (!/<input[^>]*id="mode-fidelity"[^>]*checked/.test(alt)) fail('切换后必须选中高保真');
if (!/快速/.test(html) || !/高保真/.test(html)) fail('两档中文说明缺失');

// 3. 提交参数始终显式携带模式；非法/缺失回退 Web 默认快速
const pFast = buildJobPayload('塔', 'fast');
if (pFast.desc !== '塔' || pFast.mode !== 'fast') fail('快速提交参数错误');
if (buildJobPayload('塔', 'fidelity').mode !== 'fidelity') fail('高保真提交参数错误');
if (buildJobPayload('塔', 'bogus').mode !== 'fast') fail('非法模式必须回退 Web 默认快速');
if (buildJobPayload('塔').mode !== 'fast') fail('缺失模式必须回退 Web 默认快速');
if (normalizeMode('FIDELITY') !== 'fidelity') fail('模式大小写应规范化');

// 4. 中文标签与徽章
if (modeLabel('fast') !== '快速' || modeLabel('fidelity') !== '高保真') fail('模式中文标签错误');
if (modeLabel('') !== '未记录') fail('未记录模式不得冒充某一档');
if (modeBadgeText('') !== '') fail('未记录模式不得渲染徽章');
if (!modeBadge('fast').includes('快速')) fail('快速徽章缺失');
if (modeBadge('').includes('mode-chip')) fail('未记录模式不得渲染徽章 HTML');
if (retryLabel('fast').includes('评审')) fail('快速重试不得承诺携带评审意见');
if (!retryLabel('fidelity').includes('评审')) fail('高保真重试文案错误');

// 5. 快速成功横幅：明确未进行视觉评审，且不显示 0 分
const fastBanner = outcomeBanner({ outcome: 'fast_success', ok: true }, 'fast');
if (!fastBanner.includes('快速生成成功')) fail('快速成功横幅缺少明确结论: ' + fastBanner);
if (!fastBanner.includes('未进行视觉评审')) fail('快速成功必须明确未进行视觉评审: ' + fastBanner);
if (fastBanner.includes('0 分') || fastBanner.includes('0/10')) fail('快速不得显示虚构 0 分');
if (outcomeBanner({ outcome: 'fidelity_success', ok: true }, 'fidelity').includes('快速')) {
  fail('高保真成功不得显示快速文案');
}
if (outcomeBanner({ outcome: 'fast_fallback', ok: true }, 'fidelity').includes('banner ok')) {
  fail('快速保底不得冒充高保真成功');
}
// 旧任务缺 outcome：不得谎报高保真达标
const legacyFid = outcomeBanner({ ok: true }, 'fidelity');
if (legacyFid.includes('高保真成功')) fail('旧高保真记录不得声称高保真达标: ' + legacyFid);
if (outcomeBanner({ ok: true }, undefined).includes('高保真成功')) fail('模式未知时不得声称高保真成功');

// 6. 评审徽章：快速不显示评分；评审不可用如实标注
if (reviewBadges({ ok: true, mode: 'fast' }) !== '') fail('快速任务不得显示评审评分');
if (!reviewBadges({ review_unavailable: true, review_flag: 'review_unavailable' }).includes('不可用')) {
  fail('评审不可用必须如实标注');
}

// 7. 状态标签包含快速成功
if (!statusTag({ status: 'done', outcome: 'fast_success' }).includes('快速成功')) {
  fail('快速成功状态标签错误');
}

// 8. 双尝试展示：run_id/耗时/失败类别/最终交付产物来源
const att = attemptsHTML({ attempts_detail: [
  { mode: 'fidelity', ok: false, error: '门禁未过', run_id: 'aaa111', elapsed_s: 210.5,
    failure: { kind: 'gate', stage: 'solve' } },
  { mode: 'fast', ok: true, error: null, run_id: 'bbb222', elapsed_s: 95.2 },
]});
for (const token of ['高保真尝试', '快速保底', 'aaa111', 'bbb222', '210.5', '95.2',
                     '失败类别 gate', '最终交付产物']) {
  if (!att.includes(token)) fail('双尝试展示缺少 ' + token + ': ' + att);
}
if (att.includes('未知原因')) fail('有真实原因时不得显示未知原因');
if (attemptsHTML({ attempts_detail: [{ mode: 'fidelity', ok: true }] }) !== '') {
  fail('不足两次不得渲染两次尝试');
}
const bothFail = attemptsHTML({ attempts_detail: [
  { mode: 'fidelity', ok: false, error: '门禁未过' },
  { mode: 'fast', ok: false, error: '求解失败' },
]});
if (bothFail.includes('最终交付产物')) fail('双失败不得显示最终交付产物');
if (!bothFail.includes('门禁未过') || !bothFail.includes('求解失败')) fail('双失败原因必须保留');

console.log('ok');
"""


class WebModesTest(unittest.TestCase):
    def _run_node(self, source):
        node = shutil.which("node")
        if not node:
            self.skipTest("未安装 node，跳过前端双模式单测")
        proc = subprocess.run([node, "--input-type=module", "-e", source],
                              cwd=ROOT, capture_output=True, text=True,
                              encoding="utf-8", timeout=30)
        self.assertEqual(proc.returncode, 0, proc.stderr or proc.stdout)
        return proc

    def test_modes_and_banners(self):
        proc = self._run_node(NODE_SOURCE)
        self.assertIn("ok", proc.stdout)


if __name__ == "__main__":
    unittest.main()
