# ============================================================
# 修订失败后的留稿、改动计数与视觉最高分回滚
# 视觉：连续两次没超过最高分或请求打满，回滚到最高分整模再求解；结构：次数/请求用尽时
# 绑定和预检都过就最终求解。计数：结构追加（盒体/倒置楔）与改写/删除分开封顶并落记录。
# 版本只增不减：回滚恢复旧稿后再落盘取新版本号，记录 rolledBackTo，不覆盖旧模型文件。
# ============================================================
import copy
import json

from .revision_exhaust import solve_after_revision_exhausted  # noqa: F401 （对外路径不变）
from .voxel_ops import _Grid, _rasterize_op

# 不连通、悬空、覆盖不足。库存不足（inventory）仍走原来的几何上限。
STRUCTURAL_KINDS = frozenset({"connectivity", "disconnected", "support", "coverage"})
MAX_STRUCT_APPEND = 16
MAX_STRUCT_REWRITE = 12

VISUAL_STREAK_REASON = "视觉连续两次评审未超过当前最高分"
VISUAL_REQUEST_REASON = "视觉修订请求打满"


class RevisionBudgetExhausted(Exception):
    """修订次数用尽或本阶段请求打满。调用方决定留哪份稿，不得直接整单失败。"""

    def __init__(self, cls, failure, reason):
        super().__init__(reason)
        self.cls = cls
        self.failure = failure
        self.reason = reason


def budget_reason(cls, how):
    """次数用尽或请求打满的未完成原因。how 为 count 或 request。"""
    if cls == "visual":
        return VISUAL_REQUEST_REASON
    if how == "request":
        return "结构修订请求打满"
    label = {"class1": "第 1 类", "class2": "第 2 类"}.get(cls, cls)
    return f"{label}修订次数已用尽"


def revision_clause(cls, kind):
    """写进修订阶段提示的计数规则。非结构、非视觉返回空串。"""
    if cls == "visual":
        return ("视觉修订只改评审点名部位对应的算子（部位 id 或名称出现在评审意见里）；"
                "paint 按目标格当前所属部位判断，不能涂到未点名部位；"
                "其余部位的算子必须原样保留。改动个数不超过当前算子总数。")
    if cls in ("class1", "class2") and kind in STRUCTURAL_KINDS:
        return (f"结构修订（不连通/悬空/覆盖不足）：追加托架或跨缝砖不计入改写，"
                f"每次不超过 {MAX_STRUCT_APPEND} 个，只许 box 或 kind=\"inverted\" 的 wedge，"
                f"不得盖住其他部位已有体素；改写或删除已有算子合计不超过 {MAX_STRUCT_REWRITE} 个"
                f"（删除按被去掉的旧算子计数）。")
    return ""


def _model_hash(model):
    """当前整模的稳定哈希（workflow_artifacts.model_hash 的惰性导入，避免循环依赖）。"""
    if not isinstance(model, dict):
        return None
    try:
        from .workflow_artifacts import model_hash
        return model_hash(model)
    except (TypeError, ValueError):
        return None


def capture_design(chain, score, review):
    """拍下当前整模：模型、算子、部位归属、层数据，以及这份稿的评审与评审模型哈希。"""
    reviewed_hash = ((review or {}).get("modelHash")
                     if isinstance(review, dict) and review.get("modelHash")
                     else _model_hash(chain.model))
    if reviewed_hash:
        chain.reviewed_model_hash = reviewed_hash
    return {
        "score": score,
        "review_state": copy.deepcopy(review),
        "reviewed_hash": reviewed_hash,
        "model": copy.deepcopy(chain.model),
        "ops": copy.deepcopy(chain.ops),
        "assignment": copy.deepcopy(chain.assignment),
        "parts_norm": copy.deepcopy(chain.parts_norm),
        "layers": copy.deepcopy(chain.layers),
        "default_part": chain.default_part,
        "revision": chain.revision,
        "design_meta": copy.deepcopy(chain.design_meta),
        "track": chain.track,
    }


def fold_visual_score(best, streak, snap):
    """并入一次评审。超过最高分则清零连续未超过次数；同分留较新的一份。"""
    if best is None or snap["score"] > best["score"]:
        return snap, 0
    if snap["score"] == best["score"]:
        return snap, streak + 1
    return best, streak + 1


def restore_design(chain, snap):
    """回滚到拍下的整模（最高分稿）：恢复内容，但版本号不倒退，落一个新单调版本。

    2026-11-03 复核修正：旧实现把 chain.revision 也拨回快照版本，导致最终记录 revision
    小于已落盘的最大版本；读取最终产物若"取最后版本"就会读到被废弃的补丁稿。
    现在恢复内容后立刻由主链落一个新版本号（max(revision, max_revision)+1），并在
    revisionChain 里记录 rolledBackTo/parentRevision；旧模型文件一律不覆盖。
    """
    if snap is None:
        return
    previous = chain.revision
    chain.model = snap["model"]
    chain.ops = snap["ops"]
    chain.assignment = snap["assignment"]
    chain.parts_norm = snap["parts_norm"]
    chain.layers = snap["layers"]
    chain.default_part = snap["default_part"]
    chain.design_meta = snap["design_meta"]
    chain.track = snap["track"]
    chain.review_state = snap["review_state"]
    chain.rollback_pending = {"rolledBackTo": snap["revision"],
                              "parentRevision": previous, "cause": "visual_rollback"}
    if snap.get("reviewed_hash") is not None:
        chain.reviewed_model_hash = snap["reviewed_hash"]
    if chain.parts_norm is not None and chain.model is not None:
        chain._record_parts()
    chain.emit("info", f"视觉阶段改用最高分整模（overall={snap['score']}，原 r{snap['revision']:03d}）")
    version = getattr(chain, "_version_design", None)
    if callable(version):
        rid = version(note=f"回滚到最高分整模 r{snap['revision']:03d}（视觉）",
                      cause="visual_rollback")
        chain.emit("version", f"回滚稿已落新版本 {rid}（版本只增不减，旧文件不覆盖）")


def stop_visual(chain, best, reason):
    """视觉修订不再继续：留最高分整模，记 review_failed，交给后续冻结与求解。"""
    restore_design(chain, best)
    score = None if best is None else best.get("score")
    chain.review_flag = "review_failed"
    chain.revision_incomplete = True
    chain.revision_incomplete_reason = f"{reason}（保留最高分 {score}）"
    chain.emit("error", chain.revision_incomplete_reason + "，继续冻结、预检、求解（不计高保真成功）")


def _canon(op, *, geo=False):
    """算子的稳定指纹。geo=True 时去掉纯颜色，用来区分改写和换色。"""
    if geo:
        op = _strip_color(op)
    return json.dumps(op, ensure_ascii=False, sort_keys=True)


def _strip_color(op):
    if not isinstance(op, dict):
        return op
    if op.get("op") == "mirror":
        return {"op": "mirror", "axis": op.get("axis"),
                "ops": [_strip_color(sub) for sub in (op.get("ops") or [])]}
    return {k: v for k, v in op.items() if k != "color"}


def _lcs_matched(old_keys, new_keys):
    """按顺序对齐相同指纹，返回 (旧下标, 新下标) 列表。"""
    n, m = len(old_keys), len(new_keys)
    dp = [[0] * (m + 1) for _ in range(n + 1)]
    for i in range(n - 1, -1, -1):
        row = dp[i]
        nxt = dp[i + 1]
        for j in range(m - 1, -1, -1):
            if old_keys[i] == new_keys[j]:
                row[j] = nxt[j + 1] + 1
            else:
                row[j] = nxt[j] if nxt[j] >= row[j + 1] else row[j + 1]
    pairs, i, j = [], 0, 0
    while i < n and j < m:
        if old_keys[i] == new_keys[j]:
            pairs.append((i, j))
            i += 1
            j += 1
        elif dp[i + 1][j] >= dp[i][j + 1]:
            i += 1
        else:
            j += 1
    return pairs


def _op_part(op, default_part):
    if not isinstance(op, dict):
        return None
    if op.get("op") in ("paint", "hollow"):
        return op.get("part") or default_part
    return op.get("part") or default_part


def _is_append_op(op):
    """追加只允许盒体或倒置楔。"""
    if not isinstance(op, dict):
        return False
    if op.get("op") == "box":
        return True
    return op.get("op") == "wedge" and op.get("kind") == "inverted"


def classify_ops(old_ops, new_ops, default_part):
    """把算子差异分成追加、改写、删除。几何相同仅换色不计入改写。"""
    old_ops, new_ops = list(old_ops or []), list(new_ops or [])
    old_geo = [_canon(op, geo=True) for op in old_ops]
    new_geo = [_canon(op, geo=True) for op in new_ops]
    matched = _lcs_matched(old_geo, new_geo)
    matched_old = {i for i, _j in matched}
    matched_new = {j for _i, j in matched}
    removed = [i for i in range(len(old_ops)) if i not in matched_old]
    added = [j for j in range(len(new_ops)) if j not in matched_new]
    rewrites, deletes, appends = [], list(removed), []
    pool = list(removed)
    for j in added:
        op = new_ops[j]
        partner = next((i for i in pool
                        if isinstance(old_ops[i], dict) and isinstance(op, dict)
                        and old_ops[i].get("op") == op.get("op")
                        and _op_part(old_ops[i], default_part) == _op_part(op, default_part)), None)
        if partner is None:
            appends.append(j)
            continue
        pool.remove(partner)
        deletes.remove(partner)
        rewrites.append(j)
    color_only = [j for i, j in matched
                  if _canon(old_ops[i]) != _canon(new_ops[j])]
    return {"appends": appends, "rewrites": rewrites, "deletes": deletes, "colorOnly": color_only}


def _grid_shape(chain):
    model = chain.model or {}
    grid = model.get("grid") or {}
    try:
        return int(grid["w"]), int(grid["d"]), len(model.get("layers") or [])
    except (KeyError, TypeError, ValueError):
        return None


def _final_owner(ops, shape, default_part):
    """每个最终实心格的最后写入算子下标。光栅化失败时返回 (错误, None)。"""
    w, d, n_layers = shape
    if n_layers <= 0:
        return ["层数为空，无法核对追加算子的覆盖"], None
    grid = _Grid(w, d, n_layers)
    for i, op in enumerate(ops):
        errs = _rasterize_op(op, grid, i, default_part)
        if errs:
            return errs, None
    owner = {}
    for rec in grid.writes:
        cell = rec["cell"]
        if rec["new_part"] is None:
            owner.pop(cell, None)
        else:
            owner[cell] = rec["op"]
    return [], owner


def _append_coverage_error(new_ops, appends, chain):
    """追加算子最终写下的格子不能盖住其他部位已有的体素。"""
    shape = _grid_shape(chain)
    if shape is None or not appends:
        return None
    errs, owner = _final_owner(new_ops, shape, chain.default_part)
    if errs:
        return None  # 光栅化错误交给编译阶段原文打回
    old_assign = chain.assignment or {}
    for idx in appends:
        part = _op_part(new_ops[idx], chain.default_part)
        for cell, op_i in owner.items():
            if op_i != idx:
                continue
            prev = old_assign.get(cell)
            if prev is not None and prev != part:
                return (f"追加算子 #{idx}（{new_ops[idx].get('op')}）盖住了部位「{prev}」的已有体素"
                        f"——追加只能填空位或本部位，不能盖住其他部位")
    return None


def _parts_touched(op, default_part, old_assign):
    """这个算子涉及的部位。paint 看目标格现在属于谁。"""
    if not isinstance(op, dict):
        return set()
    name = op.get("op")
    if name == "paint":
        parts = set()
        for c in op.get("cells") or []:
            try:
                key = (int(c[0]), int(c[1]), int(c[2]))
            except (TypeError, ValueError, IndexError):
                parts.add(None)
                continue
            parts.add((old_assign or {}).get(key))
        if op.get("part"):
            parts.add(op.get("part"))
        return parts
    if name == "mirror":
        parts = set()
        for sub in op.get("ops") or []:
            parts |= _parts_touched(sub, default_part, old_assign)
        return parts
    return {op.get("part") or default_part}


def named_part_ids(chain):
    """评审文本里点到的部位 id（匹配 id 或名称）。"""
    pending = getattr(chain, "pending_revision", None) or {}
    failure = pending.get("failure") or {}
    review = (failure.get("info") or {}).get("review") or {}
    texts = [str(failure.get("message") or "")]
    for key in ("worst_parts", "suggestions", "missing_features", "keep"):
        for item in review.get(key) or []:
            texts.append(str(item))
    blob = "\n".join(texts)
    found = []
    for p in chain.parts_norm or []:
        pid = str(p.get("id") or "")
        name = str(p.get("name") or "")
        if (pid and pid in blob) or (name and name in blob):
            found.append(pid)
    return found


def _visual_scope_error(chain, old_ops, new_ops, diff):
    named = set(named_part_ids(chain))
    old_assign = chain.assignment or {}
    touched = []
    for i in diff["deletes"]:
        touched.append(old_ops[i])
    for j in diff["appends"] + diff["rewrites"] + diff["colorOnly"]:
        touched.append(new_ops[j])
    if not touched:
        return None
    if not named:
        return "视觉评审没有点名可改的部位，其余部位的算子必须保持不变"
    for op in touched:
        if isinstance(op, dict) and op.get("op") == "hollow":
            err = _hollow_scope_error(op, old_assign, named)
            if err:
                return err
            continue
        parts = _parts_touched(op, chain.default_part, old_assign)
        foreign = [p for p in parts if p not in named]
        if foreign:
            return (f"视觉修订改到了未点名部位 {foreign}——"
                    f"只能改评审点名的部位 {sorted(named)}；paint 按目标格所属部位判断")
    return None


def _hollow_scope_error(op, old_assign, named):
    try:
        x, y, z = int(op["x"]), int(op["y"]), int(op["z"])
        w, d, h = int(op["w"]), int(op["d"]), int(op["h"])
    except (KeyError, TypeError, ValueError):
        return "hollow 参数不完整，无法确认它挖掉的部位"
    for xx in range(x, x + w):
        for yy in range(y, y + h):
            for zz in range(z, z + d):
                prev = old_assign.get((xx, yy, zz))
                if prev is not None and prev not in named:
                    return f"hollow 会挖掉未点名部位「{prev}」的体素"
    return None


def _stat_from(chain, diff, new_ops):
    scope_parts = []
    for j in diff["appends"] + diff["rewrites"] + diff["colorOnly"]:
        scope_parts.extend(sorted(p for p in _parts_touched(new_ops[j], chain.default_part, chain.assignment) if p))
    pending = getattr(chain, "pending_revision", None) or {}
    return {
        "cls": pending.get("cls"),
        "kind": pending.get("kind"),
        "append": len(diff["appends"]),
        "rewrite": len(diff["rewrites"]) + len(diff["deletes"]),
        "scope": {
            "appended": list(diff["appends"]),
            "rewritten": list(diff["rewrites"]),
            "deleted": list(diff["deletes"]),
            "colorOnly": list(diff["colorOnly"]),
            "parts": sorted(set(scope_parts)),
        },
    }


def enforce_ops_policy(chain, old_ops, new_ops):
    """结构修订封顶追加/改写；视觉修订限制点名部位。通过时把统计挂到链上。"""
    old_ops, new_ops = list(old_ops or []), list(new_ops or [])
    pending = getattr(chain, "pending_revision", None) or {}
    cls, kind = pending.get("cls"), pending.get("kind")
    diff = classify_ops(old_ops, new_ops, chain.default_part)
    chain._pending_revision_stat = _stat_from(chain, diff, new_ops)
    chain.revision_skip_geo_cap = False
    if cls == "visual" and getattr(chain, "track", None) == "ops":
        # 视觉不套结构修订的 12。几何上限在 apply_ops_revision，按 max(8, 当时算子个数)。
        return _visual_scope_error(chain, old_ops, new_ops, diff)
    if cls in ("class1", "class2") and kind in STRUCTURAL_KINDS and getattr(chain, "track", None) == "ops":
        chain.revision_skip_geo_cap = True
        return _structural_error(chain, new_ops, diff)
    return None


def _structural_error(chain, new_ops, diff):
    appends = diff["appends"]
    if len(appends) > MAX_STRUCT_APPEND:
        return f"追加了 {len(appends)} 个算子，超过单次上限 {MAX_STRUCT_APPEND}"
    for j in appends:
        op = new_ops[j]
        if not _is_append_op(op):
            return (f"追加算子 #{j} 是 {op.get('op')!r}，结构修订的追加只许 box 或倒置楔"
                    f"（wedge 且 kind=\"inverted\"）")
    rewrite_n = len(diff["rewrites"]) + len(diff["deletes"])
    if rewrite_n > MAX_STRUCT_REWRITE:
        return (f"改写或删除了 {rewrite_n} 个已有算子，超过单次上限 {MAX_STRUCT_REWRITE}"
                f"（删除按被去掉的旧算子计数）")
    return _append_coverage_error(new_ops, appends, chain)


def note_accepted_geo(chain, geo_changes, op_count):
    """已接受修订：记几何变更数和当时算子个数（多重集对称差，与 rewrite 不是同一个数）。"""
    stat = getattr(chain, "_pending_revision_stat", None)
    if not isinstance(stat, dict):
        return
    stat["geoChanges"] = int(geo_changes)
    stat["opCount"] = int(op_count)


def remember_revision(chain):
    """接受修订后记下追加数、改写数和改动范围。"""
    stat = getattr(chain, "_pending_revision_stat", None)
    if not stat:
        return
    chain.revision_entries.append(stat)
    scope = stat.get("scope") or {}
    extra = ""
    if stat.get("geoChanges") is not None and stat.get("opCount") is not None:
        extra = f"，几何变更 {stat['geoChanges']}（当时算子 {stat['opCount']}）"
    chain.emit("info", f"修订计数：追加 {stat['append']}，改写 {stat['rewrite']}{extra}，"
                       f"部位 {scope.get('parts') or []}")


def remember_cell_revision(chain, cls, kind, n_edits):
    """逐格补丁没有算子追加/改写，范围记成格子数，避免和算子计数混用。"""
    chain.revision_entries.append({
        "cls": cls, "kind": kind, "append": 0, "rewrite": 0,
        "scope": {"track": "cells", "edits": n_edits},
    })
    chain.emit("info", f"修订计数：逐格补丁 {n_edits} 格（追加 0，改写 0）")


def accounting(chain):
    """运行记录用的累计追加数、改写数和逐次改动范围。"""
    entries = list(getattr(chain, "revision_entries", None) or [])
    return {
        "append": sum(int(e.get("append") or 0) for e in entries),
        "rewrite": sum(int(e.get("rewrite") or 0) for e in entries),
        "scope": [e.get("scope") for e in entries],
        "entries": entries,
    }
