# -*- coding: utf-8 -*-
"""E2E 结果正确性硬断言通用核心。

本文件只保留**通用底线**与共享读取工具：
  - load_run / _check_artifact_pair：按 run 记录取「最终版本」model/solution 并强制版本与哈希一致；
  - final_gate_state / assert_generic：运行成功、最终门禁重放、统一校验、产物齐全；
  - 各案例族共用的几何/配色小工具（_layer_solid / _part_cells_from_boxes / _2d_components /
    _enclosed_or_walled_interior / _spans_both_sides / _colored_cells）。

逐案例专项断言不在这里：C/H 案例见 tools/e2e_assert_20.py，G 组见 tools/e2e_assert_g.py，
N 组见 tools/e2e_assert_new20.py。本模块的 CLI 只做通用底线校验。
"""
import json
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from legogod.geometry import solid_cells_of_model  # noqa: E402
from legogod.validate import validate_solution  # noqa: E402
from legogod.workflow_artifacts import model_hash  # noqa: E402


def _rev_id(value):
    """把记录里的版本号统一成 rNNN（兼容 int / 'r003' / 'r3'）。"""
    if isinstance(value, int):
        return f"r{value:03d}"
    text = str(value or "").strip()
    if text.startswith("r") and text[1:].isdigit():
        return f"r{int(text[1:]):03d}"
    return text


def _check_artifact_pair(record, model, solution, rid):
    """强制 model/solution/记录三者版本与哈希一致；不一致即数据异常（不混用、不猜测）。"""
    run_id = record.get("runId") or record.get("run_id") or "?"
    if _rev_id(model.get("revision")) != rid:
        raise SystemExit(f"run {run_id} 数据异常：模型版本 {model.get('revision')!r} != 记录最终版本 {rid}"
                         "（疑似读到被废弃的更高版本补丁稿）")
    if _rev_id(solution.get("revision")) != rid:
        raise SystemExit(f"run {run_id} 数据异常：方案版本 {solution.get('revision')!r} != 记录最终版本 {rid}"
                         "（模型与方案版本不一致）")
    digest = model_hash(model)
    if solution.get("modelHash") != digest:
        raise SystemExit(f"run {run_id} 数据异常：方案 modelHash 与模型内容不一致"
                         f"（方案 {str(solution.get('modelHash'))[:16]}…，实测 {digest[:16]}…）")


def load_run(run_id):
    """按 run_id 读取运行记录及**记录最终版本**的 model 与 solution。

    2026-11-03 复核修正：视觉回滚后 artifacts 里会留下被废弃的更高版本补丁（如 r004/r005），
    最终产物是 record["revision"] 指向的那一版（如 r003）。旧实现取排序最后的版本，会把
    废弃稿当最终稿（H02/H04/G03/G05 曾因此版本错配）。现在：
      - 按 record["revision"] 精确取 model_rNNN / solution_rNNN；
      - 强制 model.revision == solution.revision == record.revision；
      - 强制 solution.modelHash == model 内容哈希。
    任何不一致直接判数据异常（SystemExit），绝不在不同版本之间拼指标。
    """
    base = os.path.join(ROOT, "artifacts")
    with open(os.path.join(base, f"run_{run_id}.json"), encoding="utf-8") as f:
        record = json.load(f)
    rid = _rev_id(record.get("revision"))
    if not rid or rid == "r000" or not (len(rid) == 4 and rid[1:].isdigit()):
        raise SystemExit(f"run {run_id} 数据异常：记录缺少合法 revision（{record.get('revision')!r}）")
    arts = record.get("artifacts") or {}
    mkey, skey = f"model_{rid}", f"solution_{rid}"
    if mkey not in arts or skey not in arts:
        have = sorted(k for k in arts if k.startswith(("model_", "solution_")))
        raise SystemExit(f"run {run_id} 数据异常：缺少最终版本 {rid} 的 model/solution 产物（已有 {have}）")
    with open(os.path.join(base, arts[mkey]), encoding="utf-8") as f:
        model = json.load(f)
    with open(os.path.join(base, arts[skey]), encoding="utf-8") as f:
        solution = json.load(f)
    _check_artifact_pair(record, model, solution, rid)
    return record, model, solution


def _layer_solid(model, y):
    for L in model["layers"]:
        if L["y"] == y:
            return {(x, z) for z, r in enumerate(L["rows"]) for x, c in enumerate(r) if c != "."}
    return set()


def _part_cells_from_boxes(part_entry):
    cells = set()
    for b in (part_entry.get("boxes") or []):
        for y in range(b["y1"], b["y2"] + 1):
            for x in range(b["x1"], b["x2"] + 1):
                for z in range(b["z1"], b["z2"] + 1):
                    cells.add((x, y, z))
    return cells


def _2d_components(cells_xz):
    seen, comps = set(), 0
    for c in cells_xz:
        if c in seen:
            continue
        comps += 1
        stack = [c]
        seen.add(c)
        while stack:
            x, z = stack.pop()
            for nb in ((x + 1, z), (x - 1, z), (x, z + 1), (x, z - 1)):
                if nb in cells_xz and nb not in seen:
                    seen.add(nb)
                    stack.append(nb)
    return comps


def final_gate_state(record):
    """读取最终门禁结论：返回 (source, ok, errors)。

    最终门禁以对最终模型的重放结果（record["finalGateReplay"]）为准，
    gateDegraded/gateFailed 只是过程标记，不得单独决定最终失败。兼容口径：
      - 有 finalGateReplay 且为 dict：source="replay"；ok=True/False 按重放结论；
        ok=None（重放不可用）返回 ok=None（未知，不判失败），错误列表为空；
      - 字段为显式 null：source="replay"，ok=None（未知，不判失败）；
      - 旧记录没有该字段：source="legacy"，退回 gateFailed 过程标记（不得因字段缺失误判）。
    """
    if "finalGateReplay" in record:
        replay = record.get("finalGateReplay")
        if isinstance(replay, dict):
            ok = replay.get("ok")
            if ok is True:
                return "replay", True, []
            if ok is False:
                return "replay", False, [str(e) for e in (replay.get("errors") or [])]
            return "replay", None, []
        return "replay", None, []
    if record.get("gateFailed") or record.get("gate_failed"):
        return "legacy", False, record.get("gateErrors") or record.get("gate_errors") or []
    return "legacy", True, []


def review_with_source(record, review_fallback=None):
    """取最终评审与其来源：run 记录 review 优先，缺失时用任务 result.review 补入。

    返回 (review_dict, source)，source ∈ {"run_record", "task_result", None}。
    冻结口径：新 run 记录自带 review（review_state.parsed）；
    历史记录没有该字段，浏览器断言可从任务结果 result.review 补入恢复真实视觉分；
    两者都没有则保持空 dict（不猜测、不伪造分数）。
    """
    review = record.get("review")
    if isinstance(review, dict) and review:
        return review, "run_record"
    if isinstance(review_fallback, dict) and review_fallback:
        return review_fallback, "task_result"
    return {}, None


def draw_request_count(attempts):
    """draw 请求数 = drawAttempts[].request 累计编号的**最大值**（空/非法为 0）。

    冻结口径：drawAttempts[].request 是「这是第几次 HTTP
    draw 请求」的累计值（1,2,3…），不是每次的增量；对累计编号求和会把 3 次请求
    算成 1+2+3=6，导致请求成本与重试次数严重高估。旧记录没有该字段的条目按 0 计。
    """
    best = 0
    for attempt in attempts or []:
        if not isinstance(attempt, dict):
            continue
        try:
            value = int(attempt.get("request") or 0)
        except (TypeError, ValueError):
            continue
        if value > best:
            best = value
    return best


def assert_generic(record, model, solution, errors):
    """通用底线断言：运行成功、最终门禁通过、统一校验全绿、核心产物齐全。

    门禁口径见 final_gate_state：有最终重放时只认重放；过程 gateDegraded 只记录；
    旧记录缺字段时退回 gateFailed 过程标记（兼容降级，不因缺失误判）。
    """
    if not record.get("ok"):
        errors.append(f"运行未成功：{record.get('error')}")
        return
    source, gate_ok, gate_errors = final_gate_state(record)
    if gate_ok is False:
        if source == "replay":
            replay = record.get("finalGateReplay") or {}
            errors.append(f"最终门禁重放未通过（受影响部位 {replay.get('affectedPartCount')}，"
                          f"错误格 {replay.get('errorCellCount')}）：{gate_errors[:2]}")
        else:
            errors.append(f"突显门禁带记录降级（伪部位未修复）：{gate_errors[:2]}")
    # 统一校验按**同一模型**重算（不信任 solution 里缓存的 validation，防止模型/方案版本错配时
    # 用旧模型算出的缓存结论冒充当前模型通过；断言口径与生产 validate_solution 完全一致）。
    report = validate_solution(model, solution)
    if not report.get("ok"):
        errors.append(f"统一校验未通过：{(report.get('errors') or [])[:3]}")
    rev = f"r{record.get('revision', 1):03d}"
    arts = record.get("artifacts") or {}
    if arts:
        for prefix in ("model_", "solution_", "md_"):
            if f"{prefix}{rev}" not in arts:
                errors.append(f"最终版本产物缺失：{prefix}{rev}")


def _enclosed_or_walled_interior(model):
    """统计被四周墙体围合的内部空腔格数（封闭室内空腔或四面围合内院）。"""
    solid = solid_cells_of_model(model)
    w, d, h = model["grid"]["w"], model["grid"]["d"], len(model["layers"])
    walled = 0
    for y in range(h):
        plane = {(x, z) for (x, yy, z) in solid if yy == y}
        if not plane:
            continue
        outside = set()
        stack = [(x, z) for x in range(-1, w + 1) for z in (-1, d)] + [
            (x, z) for x in (-1, w) for z in range(d)
        ]
        while stack:
            c = stack.pop()
            if c in outside or c in plane:
                continue
            if not (-1 <= c[0] <= w and -1 <= c[1] <= d):
                continue
            outside.add(c)
            stack += [(c[0] + 1, c[1]), (c[0] - 1, c[1]), (c[0], c[1] + 1), (c[0], c[1] - 1)]
        for x in range(w):
            for z in range(d):
                if (x, z) not in plane and (x, z) not in outside:
                    walled += 1
    return walled


def _spans_both_sides(model, cells):
    """部位实体是否横跨网格左右两半（镜像/成对部件的几何证据）。"""
    if not cells:
        return False
    w = model["grid"]["w"]
    mid = (w - 1) / 2.0
    xs = [c[0] for c in cells]
    return min(xs) <= mid - 0.5 and max(xs) >= mid + 0.5


def _colored_cells(model):
    """全部 colorRows 非空格 {(x,y,z): 颜色字符}。"""
    out = {}
    for L in model.get("layers") or []:
        rows = L.get("colorRows") or []
        for z, row in enumerate(rows):
            for x, ch in enumerate(row):
                if ch and ch != ".":
                    out[(x, L["y"], z)] = ch
    return out


def main(argv=None):
    """通用底线断言入口：`<run_id>` 或 `<model.json> <solution.json>`。

    逐案例专项断言已迁到 e2e_assert_20/g/new20（C/H/G/N 案例族）；本入口只跑
    assert_generic（运行成功 / 最终门禁重放 / 统一校验 / 产物齐全）。
    """
    argv = list(sys.argv[1:] if argv is None else argv)
    if len(argv) == 2 and argv[0].endswith(".json"):
        with open(argv[0], encoding="utf-8") as f:
            model = json.load(f)
        with open(argv[1], encoding="utf-8") as f:
            solution = json.load(f)
        record = {"ok": solution.get("valid"), "artifacts": {}, "error": None}
    elif len(argv) == 1:
        record, model, solution = load_run(argv[0])
    else:
        print("用法: python -m tools.e2e_assert <run_id | model.json solution.json>")
        return 2
    errors = []
    assert_generic(record, model, solution, errors)
    if errors:
        print("E2E 通用底线断言未通过：")
        for e in errors:
            print(" -", e)
        return 1
    print(f"E2E 通用底线断言全部通过：{model.get('name')}，"
          f"{len(solution.get('steps') or [])} 块零件")
    return 0


if __name__ == "__main__":
    sys.exit(main())
