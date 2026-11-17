# -*- coding: utf-8 -*-
"""动态额度逻辑测试（class1/class2 交叉 +1，默认固定额度）。

覆盖：
  1. LEGOGOD_DYNAMIC_QUOTA 开关：默认 off、显式 off、cross、非法值按 off、大小写容忍；
  2. 固定模式 limit 恒等于 base（class1/class2/visual）；
  3. cross 模式交叉 +1 边界：另一类已接受 0 次→不加、≥1 次→+1、上限 base+1 不叠加；
  4. 取消/模型截止已置位时不发额外额度（既有取消/截止语义不变）；
  5. quota_state 纯读取快照（mode/limit/accepted/requests），requests 取真实记录并保证下界；
  6. BASE_REVISE_LIMITS 与 workflow.MAX_REVISE_CLASS1/MAX_REVISE_CLASS2 同步（防漂移）；
  7. LEGOGOD_DYNAMIC_DRAW_BUDGET 开关：默认开，off/0/false/no 关闭（与其它开关语义一致）。
"""
import os
import sys
import threading
import unittest
from contextlib import contextmanager
from unittest import mock

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from legogod import draw_budget  # noqa: E402


class _QuotaChain:
    """最小链路桩：只提供额度判定/快照需要的 counts、cancel、remaining_model。"""

    def __init__(self, counts=None, requests=None, remaining=100.0, cancel=None):
        self.counts = dict(counts or {"revise_class1": 0, "revise_class2": 0, "revise_visual": 0})
        self.quota_requests = dict(requests or {"class1": 0, "class2": 0})
        self.cancel = cancel if cancel is not None else threading.Event()
        self._remaining = remaining

    def remaining_model(self):
        return self._remaining


@contextmanager
def quota_env(value):
    """临时设置 LEGOGOD_DYNAMIC_QUOTA；value=None 表示删除该环境变量（默认 off 场景）。"""
    if value is None:
        patcher = mock.patch.dict(os.environ)
        patcher.start()
        try:
            os.environ.pop(draw_budget.ENV_DYNAMIC_QUOTA, None)
            yield
        finally:
            patcher.stop()
    else:
        with mock.patch.dict(os.environ, {draw_budget.ENV_DYNAMIC_QUOTA: value}):
            yield


class QuotaModeEnvTest(unittest.TestCase):
    """env 开关解析。"""

    def _mode(self, value):
        with quota_env(value):
            return draw_budget.dynamic_quota_mode()

    def test_default_off_when_env_absent(self):
        self.assertEqual(self._mode(None), "off")

    def test_explicit_off(self):
        self.assertEqual(self._mode("off"), "off")
        self.assertEqual(self._mode(" OFF "), "off")

    def test_cross_enabled(self):
        self.assertEqual(self._mode("cross"), "cross")
        self.assertEqual(self._mode("  Cross  "), "cross")

    def test_invalid_value_falls_back_to_off(self):
        for bad in ("on", "1", "true", "cross+", "dynamic", ""):
            self.assertEqual(self._mode(bad), "off", f"非法值 {bad!r} 必须按 off")


class FixedQuotaTest(unittest.TestCase):
    """默认固定额度：limit 与 base 一致，不被已接受修订数放大。"""

    def test_fixed_mode_returns_base_for_all_classes(self):
        with quota_env("off"):
            chain = _QuotaChain({"revise_class1": 2, "revise_class2": 2, "revise_visual": 0})
            for cls in ("class1", "class2", "visual"):
                self.assertEqual(draw_budget.quota_limit(chain, cls, 2), 2)

    def test_absent_env_is_fixed_mode(self):
        with quota_env(None):
            chain = _QuotaChain({"revise_class1": 1, "revise_class2": 0, "revise_visual": 0})
            self.assertEqual(draw_budget.quota_limit(chain, "class2", 2), 2)


class CrossQuotaTest(unittest.TestCase):
    """cross 模式：另一类已接受修订 ≥1 → 本类 +1，上限 base+1。"""

    def test_no_boost_when_other_class_zero_accepted(self):
        with quota_env("cross"):
            chain = _QuotaChain()
            self.assertEqual(draw_budget.quota_limit(chain, "class1", 2), 2)
            self.assertEqual(draw_budget.quota_limit(chain, "class2", 2), 2)

    def test_cross_boost_when_other_class_accepted_once(self):
        with quota_env("cross"):
            chain = _QuotaChain({"revise_class1": 1, "revise_class2": 0, "revise_visual": 0})
            self.assertEqual(draw_budget.quota_limit(chain, "class2", 2), 3,
                             "class1 已接受 1 次 → class2 额度 +1")
            self.assertEqual(draw_budget.quota_limit(chain, "class1", 2), 2,
                             "class2 尚未接受 → class1 不加")

    def test_boost_caps_at_base_plus_one(self):
        with quota_env("cross"):
            chain = _QuotaChain({"revise_class1": 5, "revise_class2": 5, "revise_visual": 0})
            self.assertEqual(draw_budget.quota_limit(chain, "class1", 2), 3)
            self.assertEqual(draw_budget.quota_limit(chain, "class2", 2), 3)
            self.assertLessEqual(draw_budget.quota_limit(chain, "class1", 2), 2 + 1)

    def test_boost_works_for_alternate_base(self):
        """base 非 2 时同样只 +1（不随 base 放大）。"""
        with quota_env("cross"):
            chain = _QuotaChain({"revise_class1": 1, "revise_class2": 0, "revise_visual": 0})
            self.assertEqual(draw_budget.quota_limit(chain, "class2", 1), 2)
            self.assertEqual(draw_budget.quota_limit(chain, "class2", 3), 4)

    def test_visual_class_never_boosted(self):
        with quota_env("cross"):
            chain = _QuotaChain({"revise_class1": 3, "revise_class2": 3, "revise_visual": 0})
            self.assertEqual(draw_budget.quota_limit(chain, "visual", 2), 2)

    def test_cancel_blocks_extra_quota(self):
        """取消已置位 → 不发额外额度（既有取消语义不变）。"""
        cancel = threading.Event()
        cancel.set()
        with quota_env("cross"):
            chain = _QuotaChain({"revise_class1": 1, "revise_class2": 0, "revise_visual": 0},
                                cancel=cancel)
            self.assertEqual(draw_budget.quota_limit(chain, "class2", 2), 2)

    def test_model_deadline_blocks_extra_quota(self):
        """剩余模型调用时间为 0 → 不发额外额度（墙钟语义不变）。"""
        with quota_env("cross"):
            chain = _QuotaChain({"revise_class1": 1, "revise_class2": 0, "revise_visual": 0},
                                remaining=0.0)
            self.assertEqual(draw_budget.quota_limit(chain, "class2", 2), 2)

    def test_quota_limit_is_pure_read(self):
        """额度判定纯读取：不修改 counts、不触发额外副作用，重复调用结果稳定。"""
        with quota_env("cross"):
            chain = _QuotaChain({"revise_class1": 1, "revise_class2": 0, "revise_visual": 0})
            before = dict(chain.counts)
            first = draw_budget.quota_limit(chain, "class2", 2)
            second = draw_budget.quota_limit(chain, "class2", 2)
            self.assertEqual(first, second)
            self.assertEqual(chain.counts, before)
            self.assertFalse(hasattr(chain, "revise_requests"))

    def test_missing_counts_is_treated_as_zero(self):
        with quota_env("cross"):
            chain = _QuotaChain()
            del chain.counts
            self.assertEqual(draw_budget.quota_limit(chain, "class2", 2), 2)


class QuotaStateTest(unittest.TestCase):
    """quota_state 审计快照（纯读取）。"""

    def test_fixed_state_shape(self):
        with quota_env("off"):
            chain = _QuotaChain({"revise_class1": 1, "revise_class2": 0, "revise_visual": 0})
            state = draw_budget.quota_state(chain)
        self.assertEqual(state["mode"], "off")
        self.assertEqual(set(state), {"mode", "class1", "class2"})
        for cls in ("class1", "class2"):
            self.assertEqual(set(state[cls]), {"limit", "accepted", "requests"})
            self.assertEqual(state[cls]["limit"], 2)
        self.assertEqual(state["class1"]["accepted"], 1)
        self.assertEqual(state["class2"]["accepted"], 0)
        self.assertEqual(state["class1"]["requests"], 1, "无请求记录时以已接受数作下界")

    def test_cross_state_limits_and_requests(self):
        with quota_env("cross"):
            chain = _QuotaChain({"revise_class1": 1, "revise_class2": 2, "revise_visual": 0},
                                requests={"class1": 2, "class2": 5})
            state = draw_budget.quota_state(chain)
        self.assertEqual(state["mode"], "cross")
        self.assertEqual(state["class1"]["limit"], 3, "class2 已接受≥1 → class1 +1")
        self.assertEqual(state["class2"]["limit"], 3, "class1 已接受≥1 → class2 +1")
        self.assertEqual(state["class1"]["requests"], 2)
        self.assertEqual(state["class2"]["requests"], 5)

    def test_requests_never_below_accepted(self):
        """真实请求数记录缺失/偏小时，至少等于已接受修订数（下界）。"""
        with quota_env("off"):
            chain = _QuotaChain({"revise_class1": 2, "revise_class2": 0, "revise_visual": 0},
                                requests={"class1": 1, "class2": 0})
            state = draw_budget.quota_state(chain)
        self.assertEqual(state["class1"]["requests"], 2)

    def test_quota_state_reads_quota_requests_field(self):
        """主链接线用 chain.quota_requests 记真实请求数时，quota_state 同样能读到。"""
        with quota_env("off"):
            chain = _QuotaChain({"revise_class1": 1, "revise_class2": 0, "revise_visual": 0})
            chain.quota_requests = {"class1": 4, "class2": 1}
            state = draw_budget.quota_state(chain)
        self.assertEqual(state["class1"]["requests"], 4)
        self.assertEqual(state["class2"]["requests"], 1)

    def test_state_does_not_mutate_chain(self):
        with quota_env("off"):
            chain = _QuotaChain({"revise_class1": 1, "revise_class2": 1, "revise_visual": 0})
            before = dict(chain.counts)
            draw_budget.quota_state(chain)
            draw_budget.quota_state(chain)
            self.assertEqual(chain.counts, before)


class DynamicDrawEnvTest(unittest.TestCase):
    """LEGOGOD_DYNAMIC_DRAW_BUDGET 开关：默认开，off/0/false/no 关闭（与其它开关语义一致）。"""

    def _enabled(self, value):
        if value is None:
            with mock.patch.dict(os.environ):
                os.environ.pop(draw_budget.ENV_DYNAMIC_DRAW, None)
                return draw_budget.dynamic_draw_enabled()
        with mock.patch.dict(os.environ, {draw_budget.ENV_DYNAMIC_DRAW: value}):
            return draw_budget.dynamic_draw_enabled()

    def test_default_enabled(self):
        self.assertTrue(self._enabled(None), "未设置时保持开（生产默认行为不变）")

    def test_disabled_values(self):
        for value in ("off", "0", "false", "no", "OFF", "False"):
            self.assertFalse(self._enabled(value), value)

    def test_other_values_keep_enabled(self):
        for value in ("on", "1", "true", "yes"):
            self.assertTrue(self._enabled(value), value)


class BaseLimitSyncTest(unittest.TestCase):
    """BASE_REVISE_LIMITS 必须与主链常量同步，防止两处漂移。"""

    def test_base_limits_match_workflow_constants(self):
        from legogod import workflow  # 延迟导入：避免测试收集期加载主链
        self.assertEqual(draw_budget.BASE_REVISE_LIMITS["class1"], workflow.MAX_REVISE_CLASS1)
        self.assertEqual(draw_budget.BASE_REVISE_LIMITS["class2"], workflow.MAX_REVISE_CLASS2)


if __name__ == "__main__":
    unittest.main()
