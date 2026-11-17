# -*- coding: utf-8 -*-
"""设计阶段支撑校验回归测试。

口径：早期 save_design 用「正下方无实体」的体素数当悬空统计，天井/出檐等结构会天然
产生大量这种体素，误判设计不可行。现在改用与求解器同一套判断：只有「找不到任何一块
能覆盖它、且至少一格着地的砖」才算不可行。

夹具：两份「项目自造」公开测试模型，登记在 `test/fixtures/public-fixtures.json`，
文件位于 `test/fixtures/public/design/`。夹具缺失、哈希不符或数量不对一律硬失败，
不允许 skip（公开 CI 禁止以缺语料静默跳过核心用例）。
"""
import os
import sys
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
# 测试侧共享装置：test/ 目录也加入导入路径（test 是 stdlib 包名，不能写成 from test.xxx）
sys.path.insert(0, os.path.join(ROOT, "test"))

from _helpers import validate_plan  # noqa: E402
from _public_fixtures import fixture_entries, get_fixture, read_json  # noqa: E402

CONSUMER = "test/test_design_support.py"
EAVE_FIXTURE_ID = "design-eave-overhang-ok"
UNSUPPORTED_FIXTURE_ID = "design-overhang-unsupported"


class DesignSupportCheckTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        """本文件必须消费清单中恰 2 份必需 design 夹具；数量不符直接失败。"""
        cls.entries = fixture_entries(type="design-plan", required_only=True,
                                      consumer=CONSUMER)
        if len(cls.entries) != 2:
            raise AssertionError(
                "公开清单中 test_design_support 的必需 design 夹具应为 2 份，实际 %d 份：%r"
                % (len(cls.entries), [e["id"] for e in cls.entries]))

    def test_eave_overhang_design_is_accepted(self):
        """公开夹具「平台出檐」：出檐天然悬空但可搭接 → 通过且无法铺砖数为 0。"""
        plan = read_json(get_fixture(EAVE_FIXTURE_ID))
        errs, model, _warns = validate_plan(plan)
        self.assertEqual(errs, [])
        self.assertIsNotNone(model, "可搭接出檐设计不应被预检拒绝")
        self.assertEqual(model["floatingVoxels"], 14,
                         "该设计应存在天然悬空体素（出檐）")
        self.assertEqual(model["unsupportedVoxels"], 0,
                         "天然悬空但可搭接的体素不应被判为不可铺砖")

    def test_unsupported_overhang_design_is_rejected_early(self):
        """公开夹具「孤立柱大悬挑」：四周悬挑无法被任何砖覆盖 → 设计阶段拒绝。"""
        plan = read_json(get_fixture(UNSUPPORTED_FIXTURE_ID))
        errs, model, _warns = validate_plan(plan)
        self.assertIsNone(model, "大悬挑设计必须在设计预检阶段被拒绝")
        self.assertTrue(any("得不到支撑" in e for e in errs), f"实际错误：{errs}")

    def test_impossible_overhang_is_rejected(self):
        """孤立柱顶盖满平板：离支撑太远的体素无法被任何砖覆盖 → 设计阶段直接拒绝。"""
        plan = {
            "name": "悬空测试",
            "slug": "overhang-test",
            "features": ["测试悬空"],
            "layers": [
                {"module": "柱", "color": "浅灰", "rows": [".......",
                                                          ".......",
                                                          ".......",
                                                          "...#...",
                                                          ".......",
                                                          ".......",
                                                          "......."]},
                {"module": "平板", "color": "白色", "rows": ["#######"] * 7},
            ],
        }
        errs, model, _warns = validate_plan(plan)
        self.assertIsNone(model)
        self.assertTrue(any("得不到支撑" in e for e in errs), f"实际错误：{errs}")

    def test_one_step_overhang_is_accepted(self):
        """出檐 1 格（可被砖搭接）不应误报。"""
        plan = {
            "name": "出檐测试",
            "slug": "overhang-ok",
            "features": ["测试出檐"],
            "layers": [
                {"module": "地", "color": "浅灰",
                 "rows": [".......",
                          ".#####.",
                          ".#####.",
                          ".#####.",
                          ".#####.",
                          ".#####.",
                          "......."]},
                {"module": "檐", "color": "白色",
                 "rows": ["#######"] * 7},
            ],
        }
        errs, model, _warns = validate_plan(plan)
        self.assertEqual(errs, [])
        self.assertEqual(model["unsupportedVoxels"], 0)


if __name__ == "__main__":
    unittest.main()
