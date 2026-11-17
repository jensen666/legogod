# ============================================================
# A.3.5 support 稳定原因码（工作包 B 的 A.3.5 子项）
#
# find_unsupported 的每条 bad 仍返回 (x, z, reason) 三元组，元素是 UnsupportedCell：
# 三元解包/索引/len 完全兼容旧调用方，额外带 .code 稳定原因码。
# 原因码（至少 5 类）：
#   slope_root_support  正/反斜坡根部无承托
#   brick_support       普通砖块无支撑且上方无可吊挂
#   color_fragment      颜色碎片导致无同色砖可铺
#   inverted_slope_pair 反斜坡奇偶/配对失败
#   ground_reachability 接地不可达/浮动碎块
#   slope_tip_interference 反斜坡尖端正下方有向上凸点（模具干涉，补充类）
#   unknown             无法判明：保留原始 reason，不猜测类别
# 判定与旧 find_unsupported 逐条一致（reason 文本不变），只附加原因码；
# 本模块只依赖 geometry/parts_library，避免与求解器其它模块循环依赖。
# ============================================================
from .geometry import (INV_SLOPE_CHARS, SLOPE_CHARS, SOLID_CHAR, brick_sizes,
                       can_support_above, slope_run)

BRICK_SIZES = brick_sizes()

REASON_SLOPE_ROOT = "slope_root_support"
REASON_BRICK = "brick_support"
REASON_COLOR = "color_fragment"
REASON_INV_PAIR = "inverted_slope_pair"
REASON_GROUND = "ground_reachability"
REASON_SLOPE_TIP = "slope_tip_interference"
REASON_UNKNOWN = "unknown"
SUPPORT_REASON_CODES = (REASON_SLOPE_ROOT, REASON_BRICK, REASON_COLOR,
                        REASON_INV_PAIR, REASON_GROUND, REASON_SLOPE_TIP)


class UnsupportedCell(tuple):
    """(x, z, reason) 三元组 + 稳定原因码 code；旧代码按三元解包完全兼容。"""

    def __new__(cls, x, z, reason, code):
        obj = super().__new__(cls, (x, z, reason))
        obj.code = code
        return obj


def issue_code(issue):
    """取稳定原因码；旧调用方给的普通三元组/未知码一律归 unknown（不猜测类别）。"""
    code = getattr(issue, "code", None)
    return code if code in SUPPORT_REASON_CODES else REASON_UNKNOWN


def _floating_components(typed, support_ok, above):
    """同层 4-连通分量中「既无支撑也不在可吊挂集」的浮动分量格集合（接地不可达判定）。"""
    seen, floating = set(), set()
    for start in typed:
        if start in seen:
            continue
        comp, stack, ok = [], [start], False
        seen.add(start)
        while stack:
            c = stack.pop()
            comp.append(c)
            if support_ok(c) or (above and c in above):
                ok = True
            for nb in ((c[0] + 1, c[1]), (c[0] - 1, c[1]), (c[0], c[1] + 1), (c[0], c[1] - 1)):
                if nb in typed and nb not in seen:
                    seen.add(nb)
                    stack.append(nb)
        if not ok:
            floating.update(comp)
    return floating


def find_unsupported_coded(typed, below_typed, cell_color=None, above=None):
    """带原因码的 find_unsupported：返回 [UnsupportedCell(x, z, reason, code), ...]。

    反斜坡奇数段→inverted_slope_pair；斜坡根部无承托→slope_root_support；
    反斜坡尖端下方有凸点→slope_tip_interference；普通砖块无支撑且上方无可吊挂时，
    同层整段浮动→ground_reachability，仅颜色碎片冲突→color_fragment，其余→brick_support。
    """
    bad = []
    inv_runs_done = set()
    # 即使在 y=0 底层（below_typed is None），反斜坡也必须 2 格一砖，奇数段必无解
    for (x, z), ch in sorted(typed.items()):
        if ch in INV_SLOPE_CHARS:
            run = slope_run(typed, x, z, ch)
            key = run[0]
            if key in inv_runs_done:
                continue
            inv_runs_done.add(key)
            if len(run) % 2 != 0:
                for c in run:
                    bad.append(UnsupportedCell(
                        c[0], c[1],
                        "反斜坡必须 2 格一砖（无 1x1 反斜坡），该同字符段长度为奇数无法覆盖",
                        REASON_INV_PAIR))
    if below_typed is None:
        return bad

    def support_ok(c):
        ch_b = below_typed.get(c)
        return ch_b is not None and can_support_above(ch_b, below_typed, c[0], c[1])

    def stud_below(c):
        return below_typed.get(c) == SOLID_CHAR

    floating = _floating_components(typed, support_ok, above)
    inv_checked = set()
    for (x, z), ch in sorted(typed.items()):
        if ch in INV_SLOPE_CHARS:
            run = slope_run(typed, x, z, ch)
            key = run[0]
            if key in inv_checked or len(run) % 2 != 0:
                continue
            inv_checked.add(key)
            for k in range(0, len(run), 2):
                a, b = run[k], run[k + 1]
                a_ok, b_ok = support_ok(a), support_ok(b)
                if (a_ok and not stud_below(b)) or (b_ok and not stud_below(a)):
                    continue
                c_bad = a if not a_ok else b
                code = REASON_SLOPE_ROOT if not (a_ok or b_ok) else REASON_SLOPE_TIP
                bad.append(UnsupportedCell(
                    c_bad[0], c_bad[1],
                    "反斜坡根部必须压在下方凸点上（仅根部底面承托），且尖端正下方不得有向上凸点",
                    code))
            continue
        if support_ok((x, z)):
            continue
        if ch in SLOPE_CHARS:
            run = slope_run(typed, x, z, ch)
            if any(support_ok(c) for c in run):
                continue
            bad.append(UnsupportedCell(
                x, z,
                "斜坡段下方没有可承托面（多格正斜坡至少要有一端压在下方凸点上，坡尖才允许出檐）",
                REASON_SLOPE_ROOT))
            continue
        if above and (x, z) in above:
            continue  # 允许上方跨接砖吊挂（物理校核在统一校验层执行）
        ok, supported_geom, color_conflict = False, False, False
        for w, d in BRICK_SIZES:
            for ox in range(w):
                for oz in range(d):
                    x0, z0 = x - ox, z - oz
                    cells = [(x0 + i, z0 + j) for i in range(w) for j in range(d)]
                    if not all(typed.get(cell) == SOLID_CHAR for cell in cells):
                        continue
                    if not any(support_ok(cell) for cell in cells):
                        continue
                    supported_geom = True
                    if cell_color:
                        colors_here = {cell_color.get(c) for c in cells if cell_color.get(c)}
                        if len(colors_here) > 1:
                            color_conflict = True
                            continue
                    ok = True
                    break
                if ok:
                    break
            if ok:
                break
        if not ok:
            if (x, z) in floating:
                code = REASON_GROUND
            elif cell_color and supported_geom and color_conflict:
                code = REASON_COLOR
            else:
                code = REASON_BRICK
            bad.append(UnsupportedCell(
                x, z,
                "下方没有支撑、上方也没有可吊挂它的实体，"
                "且没有任何一块「同色」砖能同时覆盖它和受支撑的体素",
                code))
    return bad


def reason_buckets(items, cap=64):
    """[(y, issue), ...] → {code: {"count", "cells": [[x,y,z]...cap], "rawReasons": [...]}}。

    rawReasons 只在 unknown 时保留原始 reason 文本（不猜测类别，原样留给修订）。
    """
    out = {}
    for y, issue in items:
        code = issue_code(issue)
        entry = out.setdefault(code, {"count": 0, "cells": []})
        entry["count"] += 1
        if len(entry["cells"]) < cap:
            entry["cells"].append([int(issue[0]), int(y), int(issue[1])])
        if code == REASON_UNKNOWN:
            raws = entry.setdefault("rawReasons", [])
            reason = str(issue[2])
            if len(raws) < 4 and reason not in raws:
                raws.append(reason)
    return out
