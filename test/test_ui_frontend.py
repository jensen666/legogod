# -*- coding: utf-8 -*-
"""web/ui.js::attemptsHTML 前端单测（双尝试展示）。

用 node 执行 web/ui.js 的 attemptsHTML。成功项不得出现「未知原因」，失败项保留真实原因。
未安装 node 时跳过（CI 无 node 环境不应误报为失败）。
"""
import os
import shutil
import subprocess
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

NODE_SOURCE = r"""
import { attemptsHTML } from './web/ui.js';

const fail = (msg) => { console.error(msg); process.exit(1); };

if (attemptsHTML({ attempts_detail: [{ mode: 'fidelity', ok: false, error: '只有一次' }] }) !== '') {
  fail('不足两次不得渲染');
}

const fastOk = attemptsHTML({ attempts_detail: [
  { mode: 'fidelity', ok: false, error: '高保真断连' },
  { mode: 'fast', ok: true, error: null },
]});
if (!fastOk.includes('高保真断连')) fail('失败项必须保留真实原因: ' + fastOk);
if (!fastOk.includes('成功')) fail('成功极速必须显示成功: ' + fastOk);
if (fastOk.includes('未知原因')) fail('成功极速不得显示未知原因: ' + fastOk);
if (fastOk.includes('❌ <b>快速保底</b>')) fail('成功极速不得标成失败: ' + fastOk);

const bothBad = attemptsHTML({ attempts_detail: [
  { mode: 'fidelity', ok: false, error: '门禁未过' },
  { mode: 'fast', ok: false, error: '求解覆盖不足' },
]});
if (!bothBad.includes('门禁未过') || !bothBad.includes('求解覆盖不足')) {
  fail('两次失败都要保留原因: ' + bothBad);
}
if (bothBad.includes('未知原因') || bothBad.includes('成功')) fail('双失败不得冒充成功或未知: ' + bothBad);

const emptyReason = attemptsHTML({ attempts_detail: [
  { mode: 'fidelity', ok: false, error: '' },
  { mode: 'fast', ok: false, error: null },
]});
if (!emptyReason.includes('未知原因')) fail('失败且没有原因时才允许未知原因: ' + emptyReason);
if (emptyReason.includes('成功')) fail('失败项不得显示成功');

console.log('ok');
"""


class AttemptsHtmlTest(unittest.TestCase):
    def test_attempts_html_by_ok(self):
        node = shutil.which("node")
        if not node:
            self.skipTest("未安装 node，跳过 web/ui.js 前端单测")
        proc = subprocess.run([node, "--input-type=module", "-e", NODE_SOURCE],
                              cwd=ROOT, capture_output=True, text=True, timeout=30)
        self.assertEqual(proc.returncode, 0, proc.stderr or proc.stdout)
        self.assertIn("ok", proc.stdout)
