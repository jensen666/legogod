# -*- coding: utf-8 -*-
"""R01–R10 冻结新例的「结果正确性」硬断言（tools/e2e_cases_r.py 的检查器实现）。

用法：
    python -m tools.e2e_assert_r <run_id>                 # 按运行记录 desc 自动匹配 R 案例
    python -m tools.e2e_assert_r <run_id> --case R01
    python -m tools.e2e_assert_r <run_id> --json out.json

口径（与 P 组沿用同一套 E2E 断言语义，R 组单独成模块）：
  两层结构：
    1) generic_tier（可信底线，任何一项失败即断言失败）：
       - 任务成功（record.ok）；
       - 最终门禁 replay（record["finalGateReplay"]，旧记录兼容退回 gateFailed）；
       - 统一物理校验按**同一模型**重算全绿（assert_generic 内 validate_solution）；
       - 最终版本产物齐全（model_/solution_/md_ 与 record.revision 对应）；
       - 无版本覆盖（record.versionOverwriteCount > 0 判失败）；
       - 评审不过期（record.reviewStale=true 判失败）。
    2) requirement_tier（真实用户任务的结果正确性，硬失败）：
       - 目标块数比 bricks/target >= R_TARGET_TOLERANCE(0.5)；
       - require_parts 部位存在且未被删空/退化成贴花；
       - 本组冻结的 feature checks（部位几何/结构关系/配色）；
       - min_parts / min_solid_parts 复杂度设计下限。
    errors = generic_tier + requirement_tier。

复用而非复制（只读导入现有模块，不修改任何现有文件）：
  - tools.e2e_assert.resolve_check 的注册链：R 案例 checks 统一由
    tools.e2e_assert_new20.resolve_check 解析（N 新检查器 → G 组注册表 →
    20 例通用检查器），检查器实现全部复用，R 组不新增检查器；
  - tools.e2e_assert.assert_generic / final_gate_state / load_run / review_with_source /
    draw_request_count：通用底线、最终门禁、运行记录读取、评审补入与 draw 请求数
    （最大值语义）全部走既有单源；
  - tools.e2e_assert_20._part_counts / _require_parts / _slope_count、
    tools.e2e_assert_g._final_gate_replay_errors / _solid_cells：部位统计与门禁重放判据。

评审补入口径：新 run 记录自带 review；旧记录没有 review 字段时用任务
result.review 通过 review_fallback 补入；两者都空时保持空 dict、review_overall=None，
不猜测、不伪造分数。
"""
import json
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from tools.e2e_assert import (  # noqa: E402
    _colored_cells, assert_generic, draw_request_count, final_gate_state, load_run,
    review_with_source,
)
from tools.e2e_assert_20 import _part_counts, _require_parts, _slope_count  # noqa: E402
from tools.e2e_assert_g import _final_gate_replay_errors, _solid_cells  # noqa: E402
from tools.e2e_assert_new20 import resolve_check  # noqa: E402
from tools.e2e_cases_r import (  # noqa: E402
    R_TARGET_TOLERANCE, find_r_case, parse_target_blocks,
)


def _as_dict(value):
    """把输入统一成 dict（None/异常类型给空 dict，断言模块不抛未捕获异常）。"""
    return value if isinstance(value, dict) else {}


def _generic_errors(record, model, solution):
    """通用可信底线断言，返回 (errors, review_stale, version_overwrites)。

    复用 assert_generic（任务成功/最终门禁/统一校验/产物齐全）并补最终门禁 replay 的
    独立判据（与 G/N 组同口径）；再补版本覆盖与评审过期两条可信底线。
    字段缺失记 None（未知，不误判），显式 True/正数才判失败。
    """
    errors = []
    try:
        assert_generic(record, model, solution, errors)
        errors.extend(_final_gate_replay_errors(record))
    except SystemExit as exc:  # 数据异常被以 SystemExit 抛出时也转可读失败
        errors.append(f"通用底线断言数据异常：{exc}")
    except Exception as exc:  # noqa: BLE001 - 断言模块必须可读失败、不静默通过
        errors.append(f"通用底线断言执行失败：{exc.__class__.__name__}: {exc}")

    review_stale = record.get("reviewStale") if "reviewStale" in record else None
    if review_stale is True:
        errors.append("最终产物评审已过期（reviewStale=true，评审稿与最终模型哈希不一致）："
                      "不得判成功")
    overwrites = record.get("versionOverwriteCount") \
        if "versionOverwriteCount" in record else None
    if isinstance(overwrites, int) and not isinstance(overwrites, bool) and overwrites > 0:
        errors.append(f"版本覆盖 {overwrites} 次（最终版本之外的补稿覆盖了产物）："
                      "版本/哈希一致性退化")
    return errors, review_stale, overwrites


def check_objects_r(record, model, solution, case, review_fallback=None):
    """对 R 组单个案例执行两层断言，返回 (errors, metrics)。

    errors = generic_tier + requirement_tier（任何一项即断言失败）。
    metrics 里 requirement_tier / generic_tier 各自保留失败项列表；assertion_ok 为总判定。
    review_fallback：旧 run 记录没有 review 字段时用任务 result.review 补入
    （新记录由主链在 run 记录里落盘 review，优先使用 run 记录）。
    """
    record = _as_dict(record)
    model = _as_dict(model)
    solution = _as_dict(solution)
    case = _as_dict(case)

    generic_errors, review_stale, version_overwrites = _generic_errors(
        record, model, solution)

    ctx = {"model": model, "solution": solution,
           "counts": _part_counts(model),
           "colored": _colored_cells(model),
           "solid": _solid_cells(model)}
    label = f"{case.get('id', 'R??')} {case.get('name', '')}".strip()
    target = case.get("target_blocks")
    if target is None:
        target = parse_target_blocks(case.get("desc") or record.get("desc"))
    bricks = len(solution.get("steps") or [])

    requirement_errors = []
    feature_checks = []
    # 冻结口径守卫：运行记录的需求原文必须与 R 组冻结原文逐字一致（desc_sha256 冻结）。
    frozen_desc = case.get("desc")
    record_desc = record.get("desc")
    if frozen_desc and record_desc and record_desc != frozen_desc:
        requirement_errors.append(
            "运行记录需求原文与 R 组冻结原文不一致：冻结口径被破坏"
            f"（记录 {str(record_desc)[:24]!r}… 冻结哈希 {str(case.get('desc_sha256'))[:12]}…）")
    if record.get("ok"):
        # 部位存在性（未删空、未退化成贴花）
        _require_parts(model, requirement_errors, label, case.get("require_parts") or [])
        # 本组冻结的特征检查（统一走 resolve_check 注册链，不复制检查器实现）
        for spec in case.get("checks") or []:
            name, args = spec[0], spec[1:]
            fn = resolve_check(name)
            if fn is None:
                check_errors = [f"断言配置错误：未知检查 {name}"]
            else:
                try:
                    check_errors = list(fn(ctx, *args) or [])
                except Exception as exc:  # noqa: BLE001 - 产物异常时必须可读失败
                    check_errors = [f"检查 {name} 执行失败：{exc.__class__.__name__}: {exc}"]
            feature_checks.append({"name": name, "ok": not check_errors,
                                   "errors": check_errors})
            requirement_errors.extend(check_errors)
        # 复杂度设计下限
        total, solid_count, _surface = ctx["counts"]
        min_parts = int(case.get("min_parts") or 0)
        min_solid_parts = int(case.get("min_solid_parts") or 0)
        if total < min_parts:
            requirement_errors.append(f"复杂度未达设计下限：部位数 {total} < {min_parts}")
        if solid_count < min_solid_parts:
            requirement_errors.append(
                f"复杂度未达设计下限：立体部位数 {solid_count} < {min_solid_parts}")
        # 目标块数统一容差（逐例 bricks/target >= 0.5）
        if target:
            ratio = bricks / float(target)
            if ratio < R_TARGET_TOLERANCE:
                requirement_errors.append(
                    f"目标块数未达标：实际零件 {bricks}/{target} = {ratio:.2%} < "
                    f"{R_TARGET_TOLERANCE:.0%}（方案 12.4 统一容差）")
    errors = generic_errors + requirement_errors

    # 评审：run 记录优先，旧记录用任务 result.review 补入
    review, review_source = review_with_source(record, review_fallback)
    scores = review.get("scores") if isinstance(review.get("scores"), dict) else {}
    attempts = record.get("drawAttempts") or []
    voxels = int(model.get("totalVoxels") or 0)
    ops = len(model.get("ops") or [])
    min_voxels = int(case.get("min_voxels") or 0)
    min_ops = int(case.get("min_ops") or 0)
    bricks_ratio = round(bricks / float(target), 4) if target else None
    gate_source, gate_ok, _gate_errors = final_gate_state(record)
    replay = record.get("finalGateReplay") or record.get("final_gate_replay")
    metrics = {
        "suite": "R",
        "case": case.get("id"), "name": case.get("name"), "run_id": record.get("runId"),
        "desc": record.get("desc"),
        "stress": list(case.get("stress") or []),
        "historical_failure_hint": case.get("historical_failure_hint"),
        "task_ok": bool(record.get("ok")), "error": record.get("error"),
        "mode": record.get("mode"), "track": model.get("track"),
        "parts": ctx["counts"][0], "solid_parts": ctx["counts"][1],
        "surface_parts": ctx["counts"][2],
        "voxels": voxels, "ops": ops,
        "slope_voxels": _slope_count(model),
        "layers": len(model.get("layers") or []),
        "grid": model.get("grid"),
        "pieces": bricks, "bricks": bricks,
        "target_blocks": target,
        "bricks_ratio": bricks_ratio,
        "target_blocks_ok": (bricks_ratio is not None
                             and bricks_ratio >= R_TARGET_TOLERANCE),
        "colors": len(set(ctx["colored"].values())),
        "gate_failed": bool(record.get("gateFailed") or record.get("gate_failed")),
        "gate_errors": record.get("gateErrors") or record.get("gate_errors") or [],
        "final_gate_replay": replay,
        "final_gate_source": gate_source,
        "final_gate_ok": gate_ok,
        "validation_ok": solution.get("validation", {}).get("ok")
        if isinstance(solution.get("validation"), dict) else None,
        "review_overall": scores.get("overall"),
        "review_flag": record.get("reviewFlag"),
        "review_stale": review_stale,
        "version_overwrites": version_overwrites,
        "draw_attempts": len(attempts),
        # 累计请求编号的最大值（不得对累计编号求和）；空列表为 0
        "draw_requests": draw_request_count(attempts),
        "review": review,
        "review_source": review_source,
        "feature_checks": feature_checks,
        "requirement_tier": requirement_errors,
        "generic_tier": generic_errors,
        "regression_tier": {
            "voxels": voxels,
            "actual_voxels": voxels,
            "actual_bricks": bricks,
            "actual_voxels_per_piece": (round(voxels / float(bricks), 2) if bricks else None),
            "voxels_per_target_block": round(voxels / float(target), 2) if target else None,
            "design_min_voxels": min_voxels,
            "voxels_below_design_floor": voxels < min_voxels if min_voxels else None,
            "ops": ops,
            "design_min_ops": min_ops,
            "ops_below_design_floor": ops < min_ops if min_ops else None,
            "layers": len(model.get("layers") or []),
            "colors": len(set(ctx["colored"].values())),
            "parts": ctx["counts"][0],
        },
        "assertion_errors": errors,
        "assertion_ok": not errors,
    }
    return errors, metrics


def check_run_r(run_id, case_id=None, review_fallback=None):
    """读取 run 记录与最终产物执行 R 组断言，返回 metrics dict。

    运行记录缺失/损坏时以可读 SystemExit 结束 CLI，不输出裸 traceback。
    """
    try:
        record, model, solution = load_run(run_id)
    except (OSError, ValueError) as exc:
        raise SystemExit(f"读取 run {run_id} 失败：{exc}") from exc
    case = find_r_case(case_id, desc=record.get("desc"))
    if case is None:
        raise SystemExit(f"无法匹配 R 组案例：case_id={case_id!r} "
                         f"desc={str(record.get('desc'))[:60]!r}"
                         "（请显式给 --case，或确认需求原文与 tools/e2e_cases_r.py 一致）")
    _errors, metrics = check_objects_r(record, model, solution, case,
                                       review_fallback=review_fallback)
    return metrics


def main(argv=None):
    """CLI：`<run_id> [--case R01] [--json out.json]`，与 N/G 组断言入口同构。"""
    # Windows GBK 控制台兼容：CLI 打印不能因编码崩溃。
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except (AttributeError, ValueError):  # 老 Python / 非文本 stdout
        pass
    argv = list(sys.argv[1:] if argv is None else argv)
    json_out, case_id, positional = None, None, []
    i = 0
    while i < len(argv):
        a = argv[i]
        if a == "--case":
            i += 1
            case_id = argv[i] if i < len(argv) else None
        elif a == "--json":
            i += 1
            json_out = argv[i] if i < len(argv) else None
        else:
            positional.append(a)
        i += 1
    if len(positional) != 1:
        print("用法: python -m tools.e2e_assert_r <run_id> [--case R01] [--json out.json]")
        return 2
    metrics = check_run_r(positional[0], case_id)
    if json_out:
        with open(json_out, "w", encoding="utf-8") as f:
            json.dump(metrics, f, ensure_ascii=False, indent=2)
    print(f"案例 {metrics['case']} {metrics['name']} · run {metrics['run_id']} · "
          f"{'断言通过' if metrics['assertion_ok'] else '断言未通过'}")
    print(f"  目标块数={metrics['target_blocks']} 实际零件={metrics['bricks']} "
          f"比值={metrics['bricks_ratio']} 达标={metrics['target_blocks_ok']}")
    print(f"  任务成功={metrics['task_ok']} 轨道={metrics['track']} 部位={metrics['parts']}"
          f"(立体{metrics['solid_parts']}/涂装{metrics['surface_parts']}) "
          f"体素={metrics['voxels']} 算子={metrics['ops']} 层={metrics['layers']} "
          f"颜色={metrics['colors']}")
    print(f"  门禁来源={metrics['final_gate_source']} 门禁={metrics['final_gate_ok']} "
          f"统一校验={metrics['validation_ok']} 评审={metrics['review_overall']}"
          f"（{metrics['review_source']}） draw请求={metrics['draw_requests']}")
    if metrics["assertion_errors"]:
        print("断言未通过项：")
        for e in metrics["assertion_errors"]:
            print(" -", e)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
