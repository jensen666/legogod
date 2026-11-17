# ============================================================
# 最终门禁重放、结构化选稿排序与降级候选回归检测
#
# 供 workflow_ops 选稿/降级与 workflow_artifacts 运行记录共用：
#   - rank_key_gate：固定的结构化草稿排序键（规则已冻结，禁止看到结果后更换）；
#   - replay_final_gate：对最终模型真实重放 part_gate.check_parts，
#     不得只读 gateFailed 过程标记；
#   - degraded_regression：已降级候选的回归检测（继承既有门禁错误，但不得恶化）；
#   - 末尾一组 chain 记录维护辅助（draft_ranking/best_draft/降级基线/回归拒绝）。
# 本模块只依赖 part_gate，不导入 workflow，不写文件；除末尾显式标注的 chain 内存记录辅助外
# 不产生状态，所有对外函数绝不向外抛异常。
#
# ---------------- 冻结排序规则（2026-11-03，写死不得改） ----------------
# 排序键 rank_key_gate 为 4 元组，按下标依次比较，越小越好：
#   1) 受影响部位数：优先用错误格经「cells→部位归属映射」精确归属后去重计数；
#      拿不到映射或错误格归属不到任何部位时，退回统计错误文本中「部位名」的数量（去重）。
#   2) 错误格总数：去重后的错误格数量；调用方未提供错误格（None）时，退回错误文本中
#      出现的不同坐标 (x,y,z) 数量（错误格为 [] 视为真实 0 格）。
#   3) 严重度 = (错误条数, 规范化错误类型多重集)：
#      - 先比错误条数，条数少者更优；
#      - 条数相同再比规范化错误类型的升序元组（包含重复，即多重集），按 Unicode 码点
#        字典序比较，更小者更优。
#   4) 错误类型多重集（第 3 维元组内已含）。无任何门禁错误时排序键恒为最优 (0, 0, 0, ())。
#
# ---------------- 冻结错误类型规范化（2026-11-03） ----------------
# 一条门禁错误的「规范化错误类型」= 原错误文本依次做：
#   a) 坐标 (x=...,y=...,z=...) → "(坐标)"；
#   b) 「部位名」→ 「部位」（类型与具体部位无关，部位数单列第一维）；
#   c) 连续数字 → "N"（数量单列错误格/错误条数，类型只保留结构模板）；
#   d) 连续空白压成一个空格并去首尾空白。
# 该规范化对同一错误的任意出现顺序、坐标与部位无关，保证排序稳定可复现。
#
# ---------------- 冻结回归判定（2026-11-03，degraded_regression） ----------------
# 基线为降级时冻结的 {"affectedPartCount", "errorCellCount", "errorTypes"}；
# 当前候选的同一三维度（部位数 / 错误格数 / 严重度）任一严格大于基线即判恶化并拒绝，
# 返回中文原因；全部不大于（不变或减少）返回 None；候选门禁完全干净直接返回 None。
# 基线某维度缺失（None）时跳过该维度不可判的项，不猜测、不放宽其他维度。
# ============================================================
import json
import re

from . import design_contract as dc
from . import part_gate

GATE_RANK_RULE = "parts>cells>types"   # 排序规则标识（写进 chain.draft_ranking/run 记录，冻结）
MAX_RANKED_DRAFTS = 8                  # chain.draft_ranking 保留的候选排序记录条数（审计用）
PART_PLACEHOLDER = "「部位」"

# 坐标形如 (x=1,y=2,z=3)；允许空格容忍模型输出差异
_COORD_RE = re.compile(r"\(\s*x\s*=\s*-?\d+\s*,\s*y\s*=\s*-?\d+\s*,\s*z\s*=\s*-?\d+\s*\)")
_PART_NAME_RE = re.compile(r"「[^」]*」")
_NUMBER_RE = re.compile(r"\d+")
_SPACE_RE = re.compile(r"\s+")


def normalize_error_type(error):
    """把一条门禁错误规范化为「错误类型」文本（见模块 docstring 冻结规则 a-d）。"""
    text = _COORD_RE.sub("(坐标)", str(error))
    text = _PART_NAME_RE.sub(PART_PLACEHOLDER, text)
    text = _NUMBER_RE.sub("N", text)
    return _SPACE_RE.sub(" ", text).strip()


def error_types(gate_errors):
    """规范化全部门禁错误的类型文本，保持原顺序（多重集仍由调用方排序后使用）。"""
    return [normalize_error_type(e) for e in (gate_errors or [])]


def _normalize_cells(gate_cells):
    """把错误格统一成 (x,y,z) 整数元组集合；非法项跳过，保证去重与排序稳定。"""
    cells = set()
    for cell in gate_cells or ():
        try:
            cells.add((int(cell[0]), int(cell[1]), int(cell[2])))
        except (TypeError, ValueError, IndexError, KeyError):
            continue
    return cells


def cells_part_map(parts_norm):
    """由 parts_norm 的 cells 建立 {格: 部位 id} 归属映射（同格重复归属取先出现者）。"""
    mapping = {}
    for part in parts_norm or []:
        pid = str(part.get("id") or "")
        if not pid:
            continue
        for cell in part.get("cells") or ():
            try:
                key = (int(cell[0]), int(cell[1]), int(cell[2]))
            except (TypeError, ValueError, IndexError, KeyError):
                continue
            mapping.setdefault(key, pid)
    return mapping


def _quoted_part_names(gate_errors):
    """错误文本里「部位名」引号中的名称列表（保持出现顺序，可能重复）。"""
    names = []
    for error in gate_errors or []:
        for match in re.finditer(r"「([^」]+)」", str(error)):
            names.append(match.group(1))
    return names


def _affected_part_count(gate_errors, gate_cells, part_map=None, part_ids=None):
    """受影响部位数：错误格精确归属优先，其次错误文本部位名数量（见冻结规则第 1 条）。"""
    if part_map and gate_cells:
        hit = {part_map[cell] for cell in _normalize_cells(gate_cells) if cell in part_map}
        if hit:
            return len(hit)
    names = _quoted_part_names(gate_errors)
    if part_ids:
        known = {str(p) for p in part_ids}
        names = [n for n in names if n in known]
    return len(set(names))


def _error_cell_count(gate_cells, gate_errors):
    """错误格总数：提供错误格时按去重格数；未提供时退回错误文本里的不同坐标数。"""
    if gate_cells is not None:
        return len(_normalize_cells(gate_cells))
    coords = set()
    for error in gate_errors or []:
        coords.update(match.group(0) for match in _COORD_RE.finditer(str(error)))
    return len(coords)


def _severity(gate_errors):
    """严重度 = (错误条数, 规范化错误类型升序多重集元组)，见冻结规则第 3 条。"""
    types = tuple(sorted(error_types(gate_errors)))
    return (len(types), types)


def _severity_from_types(error_type_list):
    """由已规范化的错误类型列表重建严重度（基线记录里的 errorTypes 是规范类型）。"""
    types = tuple(sorted(str(t) for t in (error_type_list or [])))
    return (len(types), types)


def rank_detail(gate_errors, gate_cells=None, part_ids=None):
    """结构化排序明细（供 chain.draft_ranking/run 记录）：
    {"affectedPartCount", "errorCellCount", "errorTypes"}；无错误时全为 0/[]。"""
    errors = [str(e) for e in (gate_errors or [])]
    if not errors:
        return {"affectedPartCount": 0, "errorCellCount": 0, "errorTypes": []}
    part_map = part_ids if isinstance(part_ids, dict) else None
    known = None if isinstance(part_ids, dict) else part_ids
    return {
        "affectedPartCount": _affected_part_count(errors, gate_cells, part_map, known),
        "errorCellCount": _error_cell_count(gate_cells, errors),
        "errorTypes": sorted(error_types(errors)),
    }


def rank_key_gate(gate_errors, gate_cells=None, part_ids=None):
    """固定的结构化草稿排序键（见模块 docstring 冻结规则），越小越好。

    part_ids 兼容两种传法：
      - dict：{格(x,y,z) → 部位 id}，由错误格精确归属部位；
      - 序列：已知部位 id 列表，仅用于错误文本匹配收窄；
      - None：只按错误文本里的部位名数量兜底。
    同一批错误换顺序、换坐标写法得到的键完全相同（稳定可复现）。
    """
    errors = [str(e) for e in (gate_errors or [])]
    if not errors:
        return (0, 0, 0, ())
    part_map = part_ids if isinstance(part_ids, dict) else None
    known = None if isinstance(part_ids, dict) else part_ids
    affected = _affected_part_count(errors, gate_cells, part_map, known)
    cells = _error_cell_count(gate_cells, errors)
    return (affected, cells) + _severity(errors)


def replay_final_gate(model, parts_norm):
    """对最终模型真实重放 part_gate.check_parts，返回结构化门禁结果。

    返回 {"ok", "errors", "affectedPartCount", "errorCellCount"}：
      - ok=True：最终模型门禁干净（errors=[]、计数 0）；
      - ok=False：最终模型门禁仍失败（errors 为完整错误列表，非截断）；
      - ok=None：没有可重放的模型或重放过程异常，额外带 "error" 中文原因。
    异常绝不外抛——运行记录宁可少一个字段，也不能让任务结果变成内部异常。
    """
    if not isinstance(model, dict) or not model.get("layers"):
        return {"ok": None, "errors": [], "affectedPartCount": None, "errorCellCount": None,
                "error": "没有可重放门禁的最终模型（model 缺失或为空）"}
    try:
        errors, cells = part_gate.check_parts(model, parts_norm)
    except Exception as exc:  # noqa: BLE001 - 重放失败只记录原因，绝不抛出
        return {"ok": None, "errors": [], "affectedPartCount": None, "errorCellCount": None,
                "error": f"最终门禁重放异常：{type(exc).__name__}: {exc}"}
    errors = [str(e) for e in (errors or [])]
    part_map = cells_part_map(parts_norm)
    return {
        "ok": not errors,
        "errors": errors,
        "affectedPartCount": _affected_part_count(errors, cells, part_map) if errors else 0,
        "errorCellCount": len(_normalize_cells(cells)),
    }


def degraded_baseline(gate_errors, gate_cells=None, bad_part_ids=None):
    """冻结降级候选的门禁基线：{"affectedPartCount", "errorCellCount", "errorTypes"}。

    bad_part_ids 为降级稿的真实失败部位集合（优先用它计数）；缺失时退回错误文本部位名。
    """
    errors = [str(e) for e in (gate_errors or [])]
    if bad_part_ids:
        affected = len({str(p) for p in bad_part_ids})
    else:
        affected = _affected_part_count(errors, gate_cells)
    return {
        "affectedPartCount": affected,
        "errorCellCount": None if gate_cells is None else len(_normalize_cells(gate_cells)),
        "errorTypes": sorted(error_types(errors)),
    }


def degraded_regression(baseline, gate_errors, gate_cells=None, bad_part_ids=None):
    """已降级候选的回归检测：任一维度恶化返回中文原因，不变/减少返回 None。

    恶化定义（冻结）：受影响部位数、错误格总数、严重度（见模块 docstring）任一严格大于
    降级基线即拒绝；候选门禁完全干净（无错误）直接返回 None。基线缺失或某维度不可判时
    跳过该维度，不猜测、不放宽其他维度。
    """
    if not isinstance(baseline, dict) or not baseline:
        return None
    errors = [str(e) for e in (gate_errors or [])]
    if not errors:
        return None  # 候选门禁干净：严格优于降级基线，允许继续
    reasons = []

    cur_parts = (len({str(p) for p in bad_part_ids}) if bad_part_ids
                 else _affected_part_count(errors, gate_cells))
    base_parts = baseline.get("affectedPartCount")
    if base_parts is not None and cur_parts > int(base_parts):
        reasons.append(f"受影响部位数 {cur_parts} > 降级基线 {int(base_parts)}")

    base_cells = baseline.get("errorCellCount")
    if base_cells is not None and gate_cells is not None:
        cur_cells = len(_normalize_cells(gate_cells))
        if cur_cells > int(base_cells):
            reasons.append(f"错误格总数 {cur_cells} > 降级基线 {int(base_cells)}")

    base_types = baseline.get("errorTypes")
    if base_types is not None:
        base_sev = _severity_from_types(base_types)
        cur_sev = _severity(errors)
        if cur_sev > base_sev:
            if cur_sev[0] != base_sev[0]:
                reasons.append(f"错误条数 {base_sev[0]} → {cur_sev[0]}（严重度恶化）")
            else:
                reasons.append("错误类型严重度恶化（"
                               + f"{'、'.join(base_sev[1][:2]) or '无'} → "
                               + f"{'、'.join(cur_sev[1][:2]) or '无'}）")
    return ("门禁回归：" + "；".join(reasons)) if reasons else None


# ------------------------------------------------------------
# chain 记录维护辅助：选稿排序记录、降级基线冻结与回归拒绝。
# 只改内存里的 chain 字段（draft_ranking/best_draft/gate_degraded_baseline/gate_regressions），
# 不写文件、不推进 revision、绝不抛异常；workflow_ops 调用这些辅助保持单源，避免两处规则分叉。
# ------------------------------------------------------------
def draft_rank(draft):
    """读取草稿的结构化排序键；缺 rank 字段时按同一冻结规则现算（旧草稿兼容）。"""
    rank = draft.get("rank")
    if isinstance(rank, tuple) and len(rank) == 4:
        return rank
    part_map = cells_part_map(draft.get("parts_norm") or [])
    return rank_key_gate(draft.get("gate_errors") or [], draft.get("gate_cells"), part_map)


def draft_ranking_entry(draft):
    """chain.draft_ranking 里的单个候选审计项（字段名与运行记录契约一致）。"""
    detail = rank_detail(draft.get("gate_errors") or [], draft.get("gate_cells"),
                         cells_part_map(draft.get("parts_norm") or []))
    return {
        "signature": draft.get("signature"),
        "gateErrorCount": len(draft.get("gate_errors") or []),
        "affectedPartCount": detail["affectedPartCount"],
        "errorCellCount": detail["errorCellCount"],
        "errorTypes": list(detail["errorTypes"]),
    }


def record_draft_ranking(chain, draft):
    """维护 chain.draft_ranking 与 chain.best_draft：按冻结排序键选最佳，平手保留先出现的。"""
    ranking = getattr(chain, "draft_ranking", None)
    if not isinstance(ranking, dict) or not isinstance(ranking.get("candidates"), list):
        ranking = {"rule": GATE_RANK_RULE, "candidates": [], "selected": "latest"}
    ranking["rule"] = GATE_RANK_RULE
    ranking["candidates"].append(draft_ranking_entry(draft))
    ranking["candidates"] = ranking["candidates"][-MAX_RANKED_DRAFTS:]
    best = getattr(chain, "best_draft", None)
    if best is None or draft_rank(draft) < draft_rank(best):
        chain.best_draft = draft
    # 降级会采用哪份稿：最新稿本身就是历史最佳 → latest；历史最佳更优 → best
    ranking["selected"] = "latest" if chain.best_draft is draft else "best"
    chain.draft_ranking = ranking
    return ranking


def freeze_degraded_baseline(chain, degraded_gate_errs):
    """降级时冻结门禁基线到 chain.gate_degraded_baseline（取真实降级稿的错误格/失败部位）。"""
    source = getattr(chain, "best_draft", None) or getattr(chain, "draft", None) or {}
    chain.gate_degraded_baseline = degraded_baseline(
        degraded_gate_errs, source.get("gate_cells"), source.get("bad_part_ids"))
    return chain.gate_degraded_baseline


def chain_regression_reason(chain, gate_errors, gate_cells=None, bad_part_ids=None):
    """已降级链路（chain.gate_errors 非空）下候选门禁是否比冻结基线更差；纯读取。

    未降级/候选门禁干净返回 None；缺冻结基线时按 chain.gate_errors 的截断记录兜底构造。
    """
    if not gate_errors or not getattr(chain, "gate_errors", None):
        return None
    baseline = getattr(chain, "gate_degraded_baseline", None)
    if not isinstance(baseline, dict) or not baseline:
        baseline = degraded_baseline(chain.gate_errors)
    return degraded_regression(baseline, gate_errors, gate_cells, bad_part_ids)


def reject_gate_regression(chain, reason):
    """拒绝已降级候选的恶化修订：记 gate_regression + 计数，并向模型给出可纠正反馈。"""
    try:
        chain.gate_regressions = int(getattr(chain, "gate_regressions", 0) or 0) + 1
    except (TypeError, ValueError):
        chain.gate_regressions = 1
    chain.record_protocol_error("gate_regression", reason)
    chain.observe(
        "候选的门禁错误比当前降级稿更差，已拒绝（上一有效版本未变）：" + reason
        + "\n降级稿允许保留既有门禁错误，但后续修订不得增加错误部位、错误格或严重度；"
        "请只修复结构失败，并保持既有门禁错误不增加。")


def draft_gate_feedback_text(draft, max_redraws=0, redraws=0,
                             base_revision="r000", max_revise_ops=8):
    """门禁打回的统一反馈文本：错误明细 + currentOps + revise_ops(r000) 局部纠错要求。

    纯文本构造（无副作用），由 workflow_ops 转给 chain.observe；放在本模块是为了让
    「门禁错误明细/排序/重放」口径同源。
    """
    roles = {p["id"]: (p.get("role") or "solid") for p in draft["parts_norm"]}
    surface_only = bool(draft["bad_part_ids"]) and all(
        roles.get(pid) == "surface" for pid in draft["bad_part_ids"])
    err_cells = dc.cells_to_lists(draft["gate_cells"], cap=64)
    ops_json = json.dumps(draft["ops"], ensure_ascii=False)
    fix_hint = ("纯表面涂装错误优先用 paint/颜色修订修正目标格，"
                if surface_only else
                f"需要真实几何凹槽/立体调整时可做有界几何修订"
                f"（几何参数改动 ≤{max_revise_ops} 个算子），")
    redraw_hint = ("也可以重新输出完整 save_design3 整模重绘一次。"
                   if redraws < max_redraws else
                   "完整重绘机会已用尽，只接受 revise_ops 局部纠错。")
    return (
        "部位突显门禁未通过（编译通过，候选已存为草稿 r000，不整稿打回）：\n- "
        + "\n- ".join(draft["gate_errors"][:8])
        + "\n失败部位：" + "、".join(draft["bad_part_ids"][:8])
        + "\n错误格（展示 "
        + f"{len(err_cells)} / 共 {len(draft['gate_cells'])}）："
        + json.dumps(err_cells, ensure_ascii=False)
        + f"\n当前草稿算子 currentOps（共 {len(draft['ops'])} 个）：\n{ops_json}\n"
        + f"请输出 {{\"action\":\"revise_ops\",\"args\":{{\"baseRevision\":\"{base_revision}\","
        + "\"ops\":[基于上面 currentOps 原样复制并只修正与上述错误相关算子后的完整列表]}}}}；"
        + "无需改变的立体部位必须原样保留，不得借机改写无关实体算子；" + fix_hint + redraw_hint
    )
