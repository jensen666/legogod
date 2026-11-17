"""真机 E2E 交付质量断言脚本（真实服务端数据，冻结 M 组断言器为准）。

用法：
    python tools/mobile_e2e/quality_check.py --token-file artifacts/e2e-mobile/<stamp>/token.txt \
        --out-dir artifacts/e2e-mobile/<stamp>/quality

判定分层（不互相替代）：
1. **冻结断言器（硬门槛）**：直接调用 `tools.e2e_assert_mode20.check_run_m`，用仓库现有
   M 组断言器（通用可信底线 + 需求达标档 + 模式事实 + 回归档）重算 run/model/solution，
   断言失败即质量失败。目标规模以断言器的 `target_blocks_ok`/`bricks_ratio` 为准，
   不再写死通过。
2. **结构一致性（硬门槛）**：模型体素 = 结果 voxels；步骤数 = 零件数 = usage 合计；
   每步覆盖属于模型体素、步骤不重复覆盖、最终覆盖完整；用量零件来自零件目录。
3. **启发式需求特征**：仅作为辅助证据输出，不参与通过判定（避免以宽松启发式冒充冻结断言）。
4. 非交付记录（取消/失败/中断）：核对 status/outcome/outcomeSource 且无假产物。

退出码：全部冻结案例断言通过才 0；否则 1（本脚本不会为了通过而放宽断言）。
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import urllib.request
from datetime import datetime

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from tools.e2e_assert_mode20 import TARGET_RATIO_MIN, check_run_m  # noqa: E402
from tools.e2e_cases_mode20 import find_m_case  # noqa: E402

BASE = "http://127.0.0.1:8600"


def http_json(path: str, token: str):
    request = urllib.request.Request(
        BASE + path, headers={"Authorization": "Bearer " + token}
    )
    with urllib.request.urlopen(request, timeout=30) as response:
        return json.load(response)


def http_bytes(path: str, token: str) -> bytes:
    request = urllib.request.Request(
        BASE + path, headers={"Authorization": "Bearer " + token}
    )
    with urllib.request.urlopen(request, timeout=60) as response:
        return response.read()


def fetch_file(name: str, token: str, out_dir: str):
    if not name:
        return None
    data = http_bytes("/files/" + name.lstrip("/"), token)
    artifact_dir = os.path.join(out_dir, "artifacts")
    os.makedirs(artifact_dir, exist_ok=True)
    with open(os.path.join(artifact_dir, os.path.basename(name)), "wb") as handle:
        handle.write(data)
    return json.loads(data.decode("utf-8"))


# ---------------------------------------------------------------- 结构一致性
def model_voxel_count(model: dict) -> int:
    return sum(len(layer.get("cells") or []) for layer in model.get("layers") or [])


def step_footprints(solution: dict, model: dict):
    """展开方案步骤：覆盖体素数、层序、重复覆盖、越界列表。"""
    covered = set()
    duplicated = []
    step_layers = []
    for step in solution.get("steps") or []:
        layer = step["layer"]
        step_layers.append((step.get("step"), layer))
        width = step.get("w") or 1
        depth = step.get("d") or 1
        for dx in range(width):
            for dz in range(depth):
                key = (step["x"] + dx, layer, step["z"] + dz)
                if key in covered:
                    duplicated.append({"step": step.get("step"), "voxel": key})
                covered.add(key)
    model_voxels = {
        (cell[0], layer["y"], cell[1])
        for layer in model.get("layers") or []
        for cell in layer.get("cells") or []
    }
    outside = [item for item in covered if item not in model_voxels]
    return len(covered), step_layers, duplicated, outside, len(model_voxels)


def structural_checks(result: dict, model: dict, solution: dict) -> list:
    checks = []

    def record(name: str, ok: bool, detail):
        checks.append({"check": name, "ok": bool(ok), "detail": detail})

    validation = result.get("validation") or {}
    record("result_validation_ok", validation.get("ok") is True, {
        "ok": validation.get("ok"),
        "errors": (validation.get("errors") or [])[:3],
    })
    record(
        "solution_validation_ok",
        (solution.get("validation") or {}).get("ok") is True,
        (solution.get("validation") or {}).get("ok"),
    )
    steps = solution.get("steps") or []
    record(
        "pieces_match_steps",
        result.get("pieces") == len(steps),
        {"pieces": result.get("pieces"), "steps": len(steps)},
    )
    covered, step_layers, duplicated, outside, model_total = step_footprints(
        solution, model
    )
    record(
        "voxels_match_model_cells",
        result.get("voxels") == model_total,
        {"voxels": result.get("voxels"), "modelCells": model_total},
    )
    record(
        "steps_cover_all_voxels",
        covered == model_total and not outside,
        {"covered": covered, "modelCells": model_total, "outside": outside[:3]},
    )
    record("steps_no_duplicate_target", not duplicated, duplicated[:3])
    # 预拼子模块整组扣入允许回到低层，其余层序不得倒退。
    subassembly_steps = {
        step_no
        for group in solution.get("subassemblies") or []
        for step_no in (group.get("steps") or [])
    }
    drops = []
    for (prev_step, prev_layer), (cur_step, cur_layer) in zip(
        step_layers, step_layers[1:]
    ):
        del prev_step
        if cur_layer < prev_layer and cur_step not in subassembly_steps:
            drops.append({"step": cur_step, "from": prev_layer, "to": cur_layer})
    record("layer_order_monotonic", not drops, {"drops": drops[:5]})
    usage = result.get("usage") or {}
    record(
        "usage_sum_matches_pieces",
        sum(usage.values()) == result.get("pieces"),
        {"usageSum": sum(usage.values()), "pieces": result.get("pieces")},
    )
    return checks


def heuristic_checks(result: dict, model: dict, spec: dict) -> list:
    """辅助启发式（不参与通过判定，仅输出观察项）。"""
    notes = []
    heuristics = spec.get("heuristics") or {}
    colors = result.get("colors") or {}
    if "required_colors" in heuristics:
        matched = [c for c in heuristics["required_colors"] if c in colors]
        notes.append(
            {
                "note": "required_colors_heuristic",
                "ok": len(matched) >= heuristics.get("min_required_colors", 1),
                "detail": {"matched": matched, "all": list(colors.keys())},
            }
        )
    if "pieces_range" in heuristics:
        low, high = heuristics["pieces_range"]
        pieces = result.get("pieces") or 0
        notes.append(
            {
                "note": "pieces_range_heuristic",
                "ok": low <= pieces <= high,
                "detail": {"pieces": pieces, "range": [low, high]},
            }
        )
    return notes


# ---------------------------------------------------------------- 冻结断言
def frozen_assertion(job: dict, case_id: str):
    """调用冻结 M 组断言器；返回 (ok, metrics/errors) 与可读失败项。"""
    result = job.get("result") or {}
    run_id = result.get("run_id") or job.get("run_id")
    if not run_id:
        return False, {
            "run_id": None,
            "errors": ["任务结果缺少 run_id，无法调用冻结断言器"],
        }
    try:
        case = find_m_case(case_id, desc=job.get("desc"))
        if case is None:
            return False, {
                "run_id": run_id,
                "errors": [f"无法匹配冻结 M 组案例 {case_id}（需求原文不一致）"],
            }
        metrics = check_run_m(run_id, case_id=case_id)
    except SystemExit as exc:
        return False, {"run_id": run_id, "errors": [f"冻结断言器读取 run 失败：{exc}"]}
    except Exception as exc:  # noqa: BLE001 - 断言必须可读失败，不得静默通过
        return False, {
            "run_id": run_id,
            "errors": [f"冻结断言器执行异常：{exc.__class__.__name__}: {exc}"],
        }
    errors = [str(item) for item in (metrics.get("assertion_errors") or [])]
    ok = bool(metrics.get("assertion_ok")) and bool(metrics.get("target_blocks_ok"))
    if bool(metrics.get("assertion_ok")) and not metrics.get("target_blocks_ok"):
        errors = list(errors) + [
            f"目标规模未达标：bricks={metrics.get('bricks')} "
            f"target={metrics.get('target_blocks')} ratio={metrics.get('bricks_ratio')} "
            f"（下限 {TARGET_RATIO_MIN}）"
        ]
    return ok, {
        "run_id": run_id,
        "case": case_id,
        "assertion_ok": bool(metrics.get("assertion_ok")),
        "target_blocks_ok": bool(metrics.get("target_blocks_ok")),
        "bricks": metrics.get("bricks"),
        "target_blocks": metrics.get("target_blocks"),
        "bricks_ratio": metrics.get("bricks_ratio"),
        "requirement_tier_ok": (metrics.get("requirement_tier") or {}).get("ok"),
        "errors": errors,
    }


def check_deliverable(job_id: str, spec: dict, token: str, out_dir: str, frozen: bool):
    job = http_json(f"/api/job/{job_id}", token)
    case_dir = os.path.join(out_dir, job_id)
    os.makedirs(case_dir, exist_ok=True)
    with open(os.path.join(case_dir, "job.json"), "w", encoding="utf-8") as handle:
        json.dump(job, handle, ensure_ascii=False, indent=2)

    checks = []

    def record(name: str, ok: bool, detail):
        checks.append({"check": name, "ok": bool(ok), "detail": detail})

    record("status_done", job.get("status") == "done", job.get("status"))
    record("outcome_expected", job.get("outcome") == spec["outcome"], job.get("outcome"))
    record("mode_expected", job.get("mode") == spec["mode"], job.get("mode"))

    result = job.get("result") or {}
    model = fetch_file(result.get("model_path"), token, case_dir)
    solution = fetch_file(result.get("solution_path"), token, case_dir)
    record("model_loaded", bool(model), result.get("model_path"))
    record("solution_loaded", bool(solution), result.get("solution_path"))

    frozen_info = None
    if frozen:
        if not model or not solution:
            record("frozen_assertion_ok", False, {"errors": ["产物缺失，无法断言"]})
        else:
            ok, info = frozen_assertion(job, spec["frozen_case"])
            frozen_info = info
            record("frozen_assertion_ok", ok, info)
            record(
                "frozen_target_blocks_ok",
                bool(info.get("target_blocks_ok")),
                {
                    "bricks": info.get("bricks"),
                    "target": info.get("target_blocks"),
                    "ratio": info.get("bricks_ratio"),
                    "min": TARGET_RATIO_MIN,
                },
            )

    if model and solution:
        checks.extend(structural_checks(result, model, solution))
    else:
        record("structural_checks", False, {"reason": "产物缺失"})

    heuristics = heuristic_checks(result, model or {"layers": []}, spec)

    return {
        "id": job_id,
        "title": spec.get("title"),
        "frozen_case": spec.get("frozen_case"),
        "desc": job.get("desc"),
        "mode": job.get("mode"),
        "outcome": job.get("outcome"),
        "summary": {
            "pieces": result.get("pieces"),
            "voxels": result.get("voxels"),
            "layers": result.get("layers"),
            "grid": result.get("grid"),
            "colors": list((result.get("colors") or {}).keys()),
        },
        "frozen": frozen_info,
        "checks": checks,
        "heuristics": heuristics,
        "passed": all(item["ok"] for item in checks),
    }


def check_non_done(job_id: str, expect: dict, token: str, out_dir: str):
    job = http_json(f"/api/job/{job_id}", token)
    case_dir = os.path.join(out_dir, job_id)
    os.makedirs(case_dir, exist_ok=True)
    with open(os.path.join(case_dir, "job.json"), "w", encoding="utf-8") as handle:
        json.dump(job, handle, ensure_ascii=False, indent=2)
    checks = [
        {
            "check": "status_expected",
            "ok": job.get("status") == expect["status"],
            "detail": job.get("status"),
        },
        {
            "check": "outcome_expected",
            "ok": job.get("outcome") == expect.get("outcome"),
            "detail": job.get("outcome"),
        },
        {
            "check": "outcome_source_expected",
            "ok": job.get("outcomeSource") == expect.get("outcomeSource"),
            "detail": job.get("outcomeSource"),
        },
        {
            "check": "no_fake_artifacts",
            "ok": not (job.get("result") or {}).get("model_path"),
            "detail": (job.get("result") or {}).get("model_path"),
        },
    ]
    return {
        "id": job_id,
        "status": job.get("status"),
        "outcome": job.get("outcome"),
        "outcomeSource": job.get("outcomeSource"),
        "mode": job.get("mode"),
        "checks": checks,
        "passed": all(item["ok"] for item in checks),
    }


# 公开版不含任何历史验收任务映射：默认值原本是本地真机验收轮的真实任务 ID 与结论，
# 不随仓库发布。需要校验自己的任务时，用同目录 quality_check_round.py 按映射文件提供，
# 或按下面结构自行补充：
#   SPECS = {"<job_id>": {"title": "...", "mode": "fast|fidelity", "outcome": "...",
#                          "frozen_case": "M01" 或 None, "heuristics": {"pieces_range": [min, max]}}}
# 断言器（check_run_m）本身不做任何放宽或改动。
RETRY_LINEAGE = ()

FIDELITY_EXPECT = ()

SPECS = {}

NON_DONE_SPECS = {}


def main():
    if not SPECS and not NON_DONE_SPECS:
        print("未配置验收任务映射：请用 quality_check_round.py 的映射文件提供任务 ID，"
              "或按 quality_check.py 注释中的结构补充 SPECS；空集不会判定为通过。")
        return 2

    parser = argparse.ArgumentParser()
    parser.add_argument("--token-file", required=True)
    parser.add_argument("--out-dir", required=True)
    args = parser.parse_args()
    token = open(args.token_file, encoding="utf-8").read().strip()
    os.makedirs(args.out_dir, exist_ok=True)

    report = {
        "generatedAt": datetime.now().isoformat(),
        "note": "质量判定以冻结 M 组断言器 check_run_m 为准；启发式仅辅助、不参与通过判定。",
        "cases": [],
    }

    frozen_cases = []
    for job_id, spec in SPECS.items():
        frozen = spec.get("frozen_case") is not None
        result = check_deliverable(job_id, spec, token, args.out_dir, frozen)
        report["cases"].append(result)
        if frozen:
            frozen_cases.append(result)
        print(f"[{'PASS' if result['passed'] else 'FAIL'}] {job_id} {spec['title']}")

    for job_id, expect in NON_DONE_SPECS.items():
        result = check_non_done(job_id, expect, token, args.out_dir)
        report["cases"].append(result)
        print(f"[{'PASS' if result['passed'] else 'FAIL'}] {job_id} 非交付记录")

    frozen_pass = [case for case in frozen_cases if case["passed"]]
    report["frozenSummary"] = {
        "total": len(frozen_cases),
        "passed": len(frozen_pass),
        "failed": [
            {
                "id": case["id"],
                "case": case.get("frozen_case"),
                "errors": (case.get("frozen") or {}).get("errors") or [],
            }
            for case in frozen_cases
            if not case["passed"]
        ],
        "ok": len(frozen_pass) == len(frozen_cases),
    }
    print(
        f"冻结 M 组断言：{len(frozen_pass)}/{len(frozen_cases)} 通过"
        f"（{'全部通过' if report['frozenSummary']['ok'] else '存在失败，质量未达标'}）"
    )

    # 重试血缘与高保真评审链（事实核对，不改变冻结断言结论）。
    retry_checks = []
    for child, parent in RETRY_LINEAGE:
        try:
            child_job = http_json(f"/api/job/{child}", token)
            ok = child_job.get("retryOf") == parent
            retry_checks.append(
                {"job": child, "retryOf": child_job.get("retryOf"), "expected": parent, "ok": ok}
            )
        except Exception as exc:  # noqa: BLE001
            retry_checks.append({"job": child, "error": str(exc), "ok": False})
    report["retryLineage"] = retry_checks
    report["retryLineageOk"] = all(item["ok"] for item in retry_checks)

    fidelity_details = []
    for job_id, expect_outcome in FIDELITY_EXPECT:
        job = http_json(f"/api/job/{job_id}", token)
        result = job.get("result") or {}
        review = result.get("review") or {}
        chain = result.get("revisionChain") or []
        fidelity_details.append(
            {
                "job": job_id,
                "outcome": job.get("outcome"),
                "reviewPresent": bool(review),
                "revisionChainLen": len(chain),
                "ok": bool(review) and job.get("outcome") == expect_outcome,
            }
        )
    report["fidelity"] = {
        "details": fidelity_details,
        "ok": all(item["ok"] for item in fidelity_details),
    }

    all_ok = report["frozenSummary"]["ok"]
    report["passed"] = all_ok
    with open(os.path.join(args.out_dir, "quality-report.json"), "w", encoding="utf-8") as handle:
        json.dump(report, handle, ensure_ascii=False, indent=2)

    lines = [
        "# 交付质量断言（真实服务端数据，冻结 M 组断言器为准）",
        "",
        f"生成时间：{report['generatedAt']}",
        "",
        f"**冻结 M 组断言结果：{len(frozen_pass)}/{len(frozen_cases)} 通过**",
        "",
    ]
    for case in report["cases"]:
        lines.append(
            f"## {'✅' if case['passed'] else '❌'} {case['id']} "
            f"{case.get('title', case.get('status', ''))}"
        )
        if case.get("summary"):
            lines.append("```")
            lines.append(json.dumps(case["summary"], ensure_ascii=False))
            lines.append("```")
        if case.get("frozen_case"):
            frozen = case.get("frozen") or {}
            lines.append(
                f"- 冻结断言：{'✅ 通过' if frozen.get('assertion_ok') and frozen.get('target_blocks_ok') else '❌ 未通过'} "
                f"（case={case['frozen_case']} run={frozen.get('run_id')} "
                f"bricks={frozen.get('bricks')}/{frozen.get('target_blocks')} "
                f"ratio={frozen.get('bricks_ratio')}）"
            )
            for error in frozen.get("errors") or []:
                lines.append(f"  - ❌ {error}")
        for item in case["checks"]:
            if item["check"].startswith("frozen_"):
                continue
            lines.append(
                f"- {'✓' if item['ok'] else '✗'} {item['check']}: "
                f"{json.dumps(item['detail'], ensure_ascii=False)[:240]}"
            )
        for note in case.get("heuristics") or []:
            lines.append(
                f"- （辅助，不计入判定）{note['note']}: {'✓' if note['ok'] else '✗'} "
                f"{json.dumps(note['detail'], ensure_ascii=False)[:200]}"
            )
        lines.append("")
    for item in report["retryLineage"]:
        lines.append(
            f"- 重试血缘 {item.get('job')} -> {item.get('retryOf')}"
            f"（期望 {item.get('expected')}）：{'✅' if item['ok'] else '❌'}"
        )
    lines.append("")
    lines.append(f"高保真评审链：{'✅' if report['fidelity']['ok'] else '❌'}")
    for item in report["fidelity"]["details"]:
        lines.append(
            f"- {item['job']} outcome={item['outcome']} "
            f"review={item['reviewPresent']} revisions={item['revisionChainLen']} "
            f"{'✅' if item['ok'] else '❌'}"
        )
    with open(os.path.join(args.out_dir, "quality-report.md"), "w", encoding="utf-8") as handle:
        handle.write("\n".join(lines))
    print("整体结果:", "PASS" if all_ok else "FAIL")
    return 0 if all_ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
