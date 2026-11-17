# ============================================================
# 工作包 B：结构候选完整验收
#
# 本模块是 workflow_phases.try_structural_candidates 的实现体：
#   1. 结构失败信息补全：disconnected/connectivity 给组件界面格、两侧组件摘要、
#      可连接邻域；suspension 只搬运校验已算出的锁扣与子组件坐标，没有就不编；
#   2. allowedCells 按「到最近可靠支撑的距离」有界扩展（默认不整模放开）；
#   3. 候选框架：模型空间候选（逐格补丁）与 solution 空间候选（只改铺法）分开；
#      候选在副本执行，编译/绑定/核心/门禁/预检不得退化；class2 必须真实调用求解器
#      并通过统一校验才算救回；候选数/求解时间/取消语义有上限并记录。
# support 稳定原因码（A.3.5）在 support_reasons.py，本模块按原因码分流候选。
# 依赖方向：顶层只依赖 geometry/parts_library/support_reasons，其余模块延迟导入。
# ============================================================
import os
import time

from .geometry import solid_cells_of_model
from .tiler_repair import analyze_disconnected
from .support_reasons import REASON_BRICK, REASON_GROUND, REASON_SLOPE_ROOT

# 候选数与时间上限：候选数、单次求解时间、总候选时间都有硬上限（防候选爆炸/取消失效）。
MAX_MODEL_CANDIDATES = 3
MAX_ADDED_CELLS = 48
MAX_CANDIDATE_SOLVE_S = 15.0
MAX_TOTAL_CANDIDATE_S = 30.0
# solution 空间候选只改铺法：整轮开启跨缝合并优先 / 只开合并优先（不产生模型补丁）。
SOLUTION_VARIANTS = ({"border_first": True, "merge_first_all": True},
                     {"merge_first_all": True})


# ---------- 候选生成（模型空间） ----------

def _failure_cells(failure):
    """失败的全量窗口优先，退回提示格；统一成 (x, y, z) 元组。"""
    raw = (failure or {}).get("window_cells")
    if raw is None:
        raw = (failure or {}).get("cells") or []
    out, seen = [], set()
    for c in raw:
        if isinstance(c, (list, tuple)) and len(c) == 3:
            cell = (int(c[0]), int(c[1]), int(c[2]))
            if cell not in seen:
                seen.add(cell)
                out.append(cell)
    return out


def generate_model_candidates(model, failure, parts_norm=None, assignment=None,
                              default_part=None):
    """按失败类型与 support 原因码分流生成模型空间候选（只新增实体格，不删格）。

    support：对可修复原因码（斜坡根部/普通砖块/接地不可达）在错误格正下方补接地支撑柱；
             颜色碎片与反斜坡奇偶不生成几何候选（需要换色/改段长，交给模型修订）。
    disconnected/connectivity：在组件界面格正上方空位补跨缝桥接格。
    suspension：在锁扣凸点正上方空位补加宽咬合面（只加宽，不改吊挂形状）。
    """
    kind = (failure or {}).get("kind")
    solid = solid_cells_of_model(model)
    grid = model.get("grid") or {}
    width, depth = int(grid.get("w") or 0), int(grid.get("d") or 0)
    n_layers = len(model.get("layers") or [])
    out = []
    if kind == "support":
        info = (failure or {}).get("info") or {}
        reasons = info.get("supportReasons")
        if not reasons:
            from .agent import support_reasons_for_cells
            reasons = support_reasons_for_cells(model, _failure_cells(failure)) or {}
        codes = [c for c in (REASON_SLOPE_ROOT, REASON_BRICK, REASON_GROUND) if c in reasons]
        if codes:
            adds, seen = [], set()
            for code in codes:
                for raw in reasons[code].get("cells") or []:
                    x, y, z = int(raw[0]), int(raw[1]), int(raw[2])
                    if (x, y, z) not in solid:
                        continue
                    column, yy = [], y - 1
                    while yy >= 0 and (x, yy, z) not in solid:
                        column.append((x, yy, z))
                        yy -= 1
                    part = (assignment or {}).get((x, y, z)) or default_part
                    for cell in column:
                        if cell in seen:
                            continue
                        seen.add(cell)
                        adds.append({"cell": cell, "part": part, "reasonCode": code})
                        if len(adds) >= MAX_ADDED_CELLS:
                            break
                    if len(adds) >= MAX_ADDED_CELLS:
                        break
                if len(adds) >= MAX_ADDED_CELLS:
                    break
            if adds:
                out.append({"space": "model", "family": "support_column", "adds": adds,
                            "description": f"按原因码 {codes} 在 {len(adds)} 个无支撑格正下方补接地支撑柱"})
    elif kind in ("disconnected", "connectivity"):
        info = (failure or {}).get("info") or {}
        if not info.get("connectableCells"):
            info = analyze_disconnected(
                model, (failure or {}).get("window_cells") or (failure or {}).get("cells")) or {}
        adds = []
        for raw in info.get("connectableCells") or []:
            cell = (int(raw[0]), int(raw[1]), int(raw[2]))
            if cell in solid or not (0 <= cell[1] < n_layers):
                continue
            adds.append({"cell": cell, "part": default_part, "reasonCode": None})
            if len(adds) >= MAX_ADDED_CELLS:
                break
        if adds:
            out.append({"space": "model", "family": "interface_bridge", "adds": adds,
                        "description": f"在组件界面格上方补 {len(adds)} 格跨缝桥接"})
    elif kind == "suspension":
        info = (failure or {}).get("info") or {}
        locks = info.get("lockCells") or (failure or {}).get("window_cells") or []
        adds, seen = [], set()
        for raw in locks:
            x, y, z = int(raw[0]), int(raw[1]), int(raw[2])
            for dx, dz in ((0, 0), (1, 0), (-1, 0), (0, 1), (0, -1)):
                cell = (x + dx, y + 1, z + dz)
                if (0 <= cell[0] < width and 0 <= cell[2] < depth
                        and 0 <= cell[1] < n_layers and cell not in solid and cell not in seen):
                    seen.add(cell)
                    adds.append({"cell": cell, "part": default_part, "reasonCode": None})
                    if len(adds) >= MAX_ADDED_CELLS:
                        break
            if len(adds) >= MAX_ADDED_CELLS:
                break
        if adds:
            out.append({"space": "model", "family": "lock_widen", "adds": adds,
                        "description": f"在锁扣凸点上方补 {len(adds)} 格加宽咬合面"})
    return out[:MAX_MODEL_CANDIDATES]


# ---------- 候选验收（编译/绑定/核心/门禁/预检） ----------

def _new_cell_color(model, y, x, z):
    """新增实体格的颜色名：同层邻格 → 正下方列 → 层色 → 该层主色；都没有返回 None。"""
    from .parts_library import voxel_color_map
    layers = model.get("layers") or []
    if not (0 <= y < len(layers)):
        return None
    layer = layers[y]
    cmap = voxel_color_map(layer.get("rows") or [], layer.get("colorRows"), layer.get("color")) or {}
    for cand in ((x, z), (x, z - 1), (x, z + 1), (x - 1, z), (x + 1, z)):
        if cmap.get(cand):
            return cmap[cand]
    for yy in range(y - 1, -1, -1):
        lower = layers[yy]
        cm = voxel_color_map(lower.get("rows") or [], lower.get("colorRows"), lower.get("color")) or {}
        if cm.get((x, z)):
            return cm[(x, z)]
    if layer.get("color"):
        return layer["color"]
    names = [name for name in cmap.values() if name]
    if names:
        return max(set(names), key=names.count)  # 逐体素配色层：新增格用该层主色
    return None


def build_model_candidate(model, parts_norm, assignment, default_part, frozen, candidate):
    """把模型空间候选应用到副本，依次跑编译/绑定/核心/门禁/预检。

    返回 (built|None, reasons)。built = {"model","parts","assignment","gateErrors","precheck"}；
    编译/绑定/核心硬失败返回 None 与原因；门禁/预检结果留给调用方比较是否退化。
    """
    from . import design_contract as dc, part_binding as pb, part_gate as pg
    from .agent import model_plan, precheck_details, validate_design_syntax
    plan = model_plan(model)
    edits = []
    for item in candidate.get("adds") or []:
        x, y, z = item["cell"]
        edit = {"x": x, "y": y, "z": z, "voxel": "#"}
        if item.get("part"):
            edit["part"] = item["part"]
        color = _new_cell_color(model, y, x, z)
        if color:
            edit["color"] = color
        edits.append(edit)
    errs, new_layers = dc.apply_edits(plan["layers"], edits)
    if errs:
        return None, ["编译失败：" + errs[0]]
    errs, new_model, _warns = validate_design_syntax(
        {"name": plan["name"], "slug": plan["slug"], "notes": plan["notes"],
         "features": plan["features"], "layers": new_layers}, require_layer_color=False)
    if errs:
        return None, ["编译失败：" + errs[0]]
    new_solid = solid_cells_of_model(new_model)
    new_assign = {c: pid for c, pid in (assignment or {}).items() if c in new_solid}
    for item in candidate.get("adds") or []:
        new_assign[item["cell"]] = item.get("part") or default_part
    frozen_map = None
    if frozen is not None:
        frozen_map = {p["id"]: set(p.get("core_cells") or set())
                      for p in parts_norm if p.get("required")}
    berrs, bound = pb.rebuild_parts(parts_norm, new_assign, new_model, frozen=frozen_map)
    if berrs:
        return None, ["绑定失败：" + berrs[0]]
    gate_errors, _cells = pg.check_parts(new_model, bound["parts"])
    return {"model": new_model, "parts": bound["parts"], "assignment": bound["assign"],
            "bindingErrors": [], "gateErrors": list(gate_errors),
            "precheck": precheck_details(new_model)}, []


def baseline_checks(model, parts_norm):
    """当前有效稿的检查基线：绑定、门禁、预检（判断候选是否让已通过的检查重新失败）。"""
    from . import part_binding as pb, part_gate as pg
    from .agent import precheck_details
    berrs = pb.parts_binding_errors(parts_norm, model)
    gate_errors, _cells = pg.check_parts(model, parts_norm)
    return {"bindingErrors": list(berrs), "gateErrors": list(gate_errors),
            "precheck": precheck_details(model)}


def _regressions(base, built):
    """已通过的检查不得重新失败：绑定/门禁/预检新增错误一律拒绝。"""
    reasons = []
    if not base["bindingErrors"] and built["bindingErrors"]:
        reasons.append("binding_regressed")
    if [e for e in built["gateErrors"] if e not in base["gateErrors"]]:
        reasons.append("gate_regressed")
    base_cells = {tuple(c) for c in (base["precheck"].get("error_cells") or [])}
    if any(tuple(c) not in base_cells for c in (built["precheck"].get("error_cells") or [])):
        reasons.append("precheck_new_cells:" + str(built["precheck"].get("kind")))
    return reasons


def evaluate_model_candidate(model, parts_norm, assignment, default_part, frozen, candidate, base):
    """模型空间候选验收：编译/绑定/核心/门禁不得退化，预检立即重跑。

    预检仍有错误→precheck_still_failing（只记中间改善，不算接受）；出现基线没有的新错误格
    →precheck_new_cells（已通过的检查重新失败，拒绝）。
    """
    built, reasons = build_model_candidate(model, parts_norm, assignment, default_part,
                                           frozen, candidate)
    if built is None:
        return None, reasons
    reasons = _regressions(base, built)
    if reasons:
        return None, reasons
    if built["precheck"].get("errors"):
        return None, ["precheck_still_failing"]
    return built, []


# ---------- 候选编排（workflow_phases.try_structural_candidates 实现体） ----------

def candidates_enabled():
    """LEGOGOD_STRUCT_CANDIDATES=on|off，默认 on；关闭时与原行为完全一致。"""
    raw = os.environ.get("LEGOGOD_STRUCT_CANDIDATES", "on").strip().lower()
    return raw not in ("off", "0", "false", "no")


def _now():
    return time.monotonic()


def _emit(chain, kind, text, meta=None):
    emit = getattr(chain, "emit", None)
    if callable(emit):
        try:
            emit(kind, text, meta) if meta else emit(kind, text)
        except Exception:  # noqa: BLE001 - 日志失败不得改变候选判定
            pass


def _state(chain):
    """chain.structural_candidates 累计器：{attempted, accepted, rejected, results}。"""
    state = getattr(chain, "structural_candidates", None)
    if not isinstance(state, dict) or not isinstance(state.get("results"), list):
        state = {"attempted": 0, "accepted": 0, "rejected": 0, "results": []}
        try:
            setattr(chain, "structural_candidates", state)
        except Exception:  # noqa: BLE001
            return {"attempted": 0, "accepted": 0, "rejected": 0, "results": []}
    state["attempted"] = len(state["results"])
    state["accepted"] = int(state.get("accepted") or 0)
    state["rejected"] = int(state.get("rejected") or 0)
    return state


def _record(state, cls, failure, space, family, outcome, reason, elapsed):
    """记一次候选尝试结果（接受数/拒绝数与修订调用数分开记录）。"""
    item = {"cls": cls, "kind": (failure or {}).get("kind"), "space": space,
            "family": family, "outcome": outcome, "reason": reason,
            "elapsedS": round(float(elapsed), 2)}
    state["results"].append(item)
    state["attempted"] = len(state["results"])
    if outcome == "accepted":
        state["accepted"] += 1
    elif outcome == "rejected":
        state["rejected"] += 1
    return item


def _candidate_deadline(chain):
    now = _now()
    deadline = now + MAX_TOTAL_CANDIDATE_S
    hard = getattr(chain, "hard_deadline", None)
    if isinstance(hard, (int, float)):
        deadline = min(deadline, hard - 30.0)
    return deadline


def _should_stop(chain):
    cancel = getattr(chain, "cancel", None)
    is_set = getattr(cancel, "is_set", None)
    return is_set if callable(is_set) else (lambda: False)


def _raise_cancel(chain):
    check = getattr(chain, "check_cancel", None)
    if callable(check):
        check()  # 正常会抛 CancelledError，由主链统一转取消
    from .tiler import TilerCancelled
    raise TilerCancelled()


def _solve(chain, model, deadline, variant=None):
    """真实调用求解器（带预算/取消），返回 (sol|None, reason)。"""
    from . import tiler
    from .validate import validate_solution
    solve_fn = getattr(chain, "solve_fn", None) or tiler.solve_with_budget
    end = min(deadline, _now() + MAX_CANDIDATE_SOLVE_S)
    if end <= _now():
        return None, "solve_timeout"
    kwargs = {"deadline": end, "validate_fn": validate_solution,
              "log": lambda s: _emit(chain, "solver", s),
              "should_stop": _should_stop(chain),
              "on_progress": lambda info: _emit(chain, "progress", "", dict(info or {}))}
    if variant and solve_fn is tiler.solve_with_budget:
        kwargs.update(variant)
    layers = sorted(model.get("layers") or [], key=lambda item: item["y"])
    try:
        sol, fail = solve_fn(model, layers, **kwargs)
    except tiler.TilerCancelled:
        _raise_cancel(chain)
        return None, "cancelled"
    if sol is not None:
        if (sol.get("validation") or {}).get("ok"):
            return sol, None
        return None, "solution_unvalidated"
    message = str((fail or {}).get("message") or "")
    if (fail or {}).get("budget_exhausted") or "预算" in message:
        return None, "solve_timeout"
    return None, "solve_failed:" + str((fail or {}).get("kind") or "unknown")


def _commit_model(chain, built, note):
    """模型空间候选接受后写入链状态：递增版本并保存设计产物（修订只增不减）。"""
    layers = []
    for layer in built["model"].get("layers") or []:
        module = layer.get("module")
        layers.append({"module": module[0] if isinstance(module, (list, tuple)) and module
                       else (module or "层"),
                       "color": layer.get("color"), "rows": list(layer["rows"]),
                       "colorRows": list(layer["colorRows"]) if layer.get("colorRows") else None})
    chain.layers = layers
    chain.model = built["model"]
    chain.assignment = built["assignment"]
    chain.parts_norm = built["parts"]
    if getattr(chain, "track", None) == "ops":
        chain.ops = None
    record_parts = getattr(chain, "_record_parts", None)
    if callable(record_parts):
        record_parts()
    version = getattr(chain, "_version_design", None)
    if callable(version):
        version(note=note)
    else:
        chain.revision = int(getattr(chain, "revision", 0) or 0) + 1


def _largest_part(parts_norm):
    if not parts_norm:
        return None
    return max(parts_norm, key=lambda p: len(p.get("cells") or []))["id"]


def try_candidates(chain, cls, failure):
    """结构候选入口（契约见 workflow_phases.try_structural_candidates）。

    返回 None=未接受（调用方走原修订）；{"accepted":True,"sol":sol}=solution 空间已救回且
    统一校验通过（调用方直接 finish_success）；{"accepted":True,"model_changed":True}=
    模型空间候选已应用且 class1 预检通过（调用方继续循环重求解）。
    """
    if not candidates_enabled():
        return None
    state = _state(chain)
    model = getattr(chain, "model", None)
    parts_norm = getattr(chain, "parts_norm", None)
    kind = (failure or {}).get("kind")
    if model is None or not parts_norm:
        _record(state, cls, failure, None, None, "rejected", "no_model", 0.0)
        return None
    if kind not in ("support", "connectivity", "disconnected", "suspension"):
        _record(state, cls, failure, None, None, "rejected", "unsupported_kind", 0.0)
        return None
    deadline = _candidate_deadline(chain)
    if deadline <= _now():
        _record(state, cls, failure, None, None, "rejected", "no_time", 0.0)
        return None
    info = dict((failure or {}).get("info") or {})
    if kind in ("disconnected", "connectivity") and not info.get("connectableCells"):
        info.update(analyze_disconnected(
            model, (failure or {}).get("window_cells") or (failure or {}).get("cells")) or {})
    if kind == "suspension":
        info.setdefault("lockCells", (failure or {}).get("window_cells") or [])
    enriched = dict(failure or {}, info=info)
    assignment = dict(getattr(chain, "assignment", None) or {})
    default_part = getattr(chain, "default_part", None) or _largest_part(parts_norm)
    frozen = set(getattr(chain, "frozen_cells", None) or []) \
        if getattr(chain, "cores_frozen", False) else None
    base = baseline_checks(model, parts_norm)
    candidates = generate_model_candidates(model, enriched, parts_norm, assignment, default_part)
    _emit(chain, "info", f"结构候选：{cls}/{kind} 生成 {len(candidates)} 个模型空间候选"
                         f"（单次求解上限 {MAX_CANDIDATE_SOLVE_S:.0f}s，总上限 {MAX_TOTAL_CANDIDATE_S:.0f}s）")
    for candidate in candidates:
        started = _now()
        if started >= deadline:
            _record(state, cls, failure, "model", candidate["family"], "rejected", "no_time", 0.0)
            continue
        built, reasons = evaluate_model_candidate(
            model, parts_norm, assignment, default_part, frozen, candidate, base)
        if built is None:
            reason = ";".join(reasons)[:200]
            _record(state, cls, failure, "model", candidate["family"], "rejected", reason,
                    _now() - started)
            _emit(chain, "info", f"结构候选未接受（模型空间 {candidate['family']}）：{reason}")
            continue
        if cls == "class1":
            _commit_model(chain, built, "结构候选（模型空间，class1 预检已重跑）")
            _record(state, cls, failure, "model", candidate["family"], "accepted", None,
                    _now() - started)
            _emit(chain, "info", f"结构候选接受（模型空间 {candidate['family']}）："
                                 f"编译/绑定/核心/门禁未退化，class1 预检已重跑通过")
            return {"accepted": True, "model_changed": True}
        # class2：模型空间候选也必须真实求解并通过统一校验才算救回
        sol, reason = _solve(chain, built["model"], deadline)
        if sol is not None:
            _commit_model(chain, built, "结构候选（模型空间 + 真实求解，统一校验通过）")
            _record(state, cls, failure, "model", candidate["family"], "accepted", None,
                    _now() - started)
            _emit(chain, "info", f"结构候选救回（模型空间 {candidate['family']}）：真实求解通过统一校验")
            return {"accepted": True, "sol": sol, "model_changed": True}
        _record(state, cls, failure, "model", candidate["family"], "rejected", reason,
                _now() - started)
        _emit(chain, "info", f"结构候选未接受（模型空间 {candidate['family']}）：{reason}")
    if cls != "class1":
        for variant in SOLUTION_VARIANTS:
            started = _now()
            if started >= deadline:
                _record(state, cls, failure, "solution", "retile_variant", "rejected",
                        "no_time", 0.0)
                continue
            sol, reason = _solve(chain, model, deadline, variant)
            if sol is not None:
                _record(state, cls, failure, "solution", "retile_variant", "accepted", None,
                        _now() - started)
                _emit(chain, "info", "结构候选救回（solution 空间重铺变体）：只改铺法，统一校验通过")
                return {"accepted": True, "sol": sol}
            _record(state, cls, failure, "solution", "retile_variant", "rejected", reason,
                    _now() - started)
            _emit(chain, "info", f"结构候选未接受（solution 空间重铺变体）：{reason}")
    if not candidates:
        _record(state, cls, failure, None, None, "rejected", "no_candidate", 0.0)
    _emit(chain, "info", f"结构候选未接受（{cls}/{kind}）：保留原修订路径")
    return None
