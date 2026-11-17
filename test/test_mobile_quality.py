"""真机质量断言脚本回归测试：冻结断言器为准，目标规模不得写死通过。

覆盖 tools/mobile_e2e/quality_check.py 的判定逻辑（不联网，均用替身）：
1) 冻结断言器 assertion_ok=False 时判定失败，并保留失败原因；
2) assertion_ok=True 但 target_blocks_ok=False 时判定失败（目标规模不达标）；
3) 两项都通过才判定通过。
"""
from unittest import mock

from tools.mobile_e2e import quality_check


def _job():
    return {
        "id": "j1",
        "status": "done",
        "mode": "fast",
        "outcome": "fast_success",
        "desc": "一只站着的小狗",
        "result": {"run_id": "run1"},
    }


def test_frozen_assertion_failure_propagates():
    metrics = {
        "assertion_ok": False,
        "assertion_errors": ["部位 ('耳') 未下垂"],
        "target_blocks_ok": True,
        "bricks": 55,
        "target_blocks": 80,
        "bricks_ratio": 0.69,
        "requirement_tier": {"ok": False},
    }
    with mock.patch.object(quality_check, "check_run_m", return_value=metrics):
        with mock.patch.object(quality_check, "find_m_case", return_value={"id": "M02"}):
            ok, info = quality_check.frozen_assertion(_job(), "M02")
    assert ok is False
    assert info["assertion_ok"] is False
    assert "未下垂" in " ".join(info["errors"])


def test_target_scale_failure_is_not_ignored():
    metrics = {
        "assertion_ok": True,
        "assertion_errors": [],
        "target_blocks_ok": False,
        "bricks": 30,
        "target_blocks": 80,
        "bricks_ratio": 0.375,
        "requirement_tier": {"ok": False},
    }
    with mock.patch.object(quality_check, "check_run_m", return_value=metrics):
        with mock.patch.object(quality_check, "find_m_case", return_value={"id": "M02"}):
            ok, info = quality_check.frozen_assertion(_job(), "M02")
    assert ok is False
    assert info["target_blocks_ok"] is False
    assert any("目标规模未达标" in e for e in info["errors"])


def test_frozen_pass_requires_assertion_and_scale():
    metrics = {
        "assertion_ok": True,
        "assertion_errors": [],
        "target_blocks_ok": True,
        "bricks": 55,
        "target_blocks": 80,
        "bricks_ratio": 0.69,
        "requirement_tier": {"ok": True},
    }
    with mock.patch.object(quality_check, "check_run_m", return_value=metrics):
        with mock.patch.object(quality_check, "find_m_case", return_value={"id": "M02"}):
            ok, info = quality_check.frozen_assertion(_job(), "M02")
    assert ok is True
    assert info["errors"] == []


def test_missing_run_id_is_failure():
    job = _job()
    job["result"] = {}
    ok, info = quality_check.frozen_assertion(job, "M02")
    assert ok is False
    assert "run" in " ".join(info["errors"]).lower()
