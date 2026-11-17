# ============================================================
# 声明式三维体积造型：算子闭集编译器
#
# 算子闭集（四类基础体元 + 三类操作）：
#   {"op":"box",      "x":X,"y":Y,"z":Z,"w":W,"d":D,"h":H, "part":P, "color":可选}
#   {"op":"cylinder", "cx":CX,"cz":CZ,"y":Y,"h":H,"r":R, "rTop":RT可选, "part":P, "color":可选}
#   {"op":"wedge",    "dir":"+x"|"-x"|"+z"|"-z", "x":X,"y":Y,"z":Z,
#                     "w"(或"len"):W,"d":D,"h":H, "kind":"regular"|"inverted", "part":P, "color":可选}
#   {"op":"loft",     "part":P, "sections":[{"y":Y,"w":W,"d":D,"cx":CX,"cz":CZ}, ...≥2],
#                     "shape":"rect"|"ellipse", "color":可选}
#   {"op":"hollow",   "x":X,"y":Y,"z":Z,"w":W,"d":D,"h":H}
#   {"op":"mirror",   "axis":"x"|"z", "ops":[子算子…]}
#   {"op":"paint",    "color":C, "cells":[[x,y,z],…]}
# ============================================================
from collections import Counter
import math

from .geometry import ALL_SLOPE_CHARS, SOLID_CHAR
from .parts_library import COLORS, COLOR_CHARS
from .prompts import MAX_VOX as MAX_VOX_GUARD

WEDGE_DOWN_CHAR = {"+x": "\\", "-x": "/", "+z": "^", "-z": "v"}   # 正斜坡：dir 为下坡方向
INV_ROOT_CHAR = {"+x": "b", "-x": "d", "+z": "p", "-z": "q"}      # 反斜坡：dir 为外挑方向（根在反侧）
MIRROR_X = {"/": "\\", "\\": "/", "b": "d", "d": "b"}
MIRROR_Z = {"^": "v", "v": "^", "p": "q", "q": "p"}

GEO_OP_NAMES = ("box", "cylinder", "wedge", "loft")
ALL_OP_NAMES = GEO_OP_NAMES + ("hollow", "mirror", "paint")


def _int_of(v):
    """解析 JSON 整数（容忍整值 float，拒绝 bool）。"""
    if isinstance(v, bool):
        return None
    if isinstance(v, int):
        return v
    if isinstance(v, float) and v.is_integer():
        return int(v)
    return None


def _num_of(v):
    """解析 JSON 数值（int/float，拒绝 bool）。"""
    if isinstance(v, bool):
        return None
    if isinstance(v, (int, float)):
        return float(v)
    return None


def _wedge_spans(op):
    """解析 wedge 的 (span_x, span_z, h)：兼容 w 或 len 表示 X 轴宽度，d 恒表示 Z 轴深度。"""
    wx = op.get("w") if op.get("w") is not None else op.get("len")
    return _int_of(wx), _int_of(op.get("d")), _int_of(op.get("h"))


class _Grid:
    """编译期三维体素工作区：维护字符、颜色、部位归属与覆盖审计日志。"""

    def __init__(self, w, d, n_layers):
        self.w, self.d, self.n_layers = w, d, n_layers
        self.chars = [{(x, z): None for x in range(w) for z in range(d)} for _ in range(n_layers)]
        self.colors = [{(x, z): None for x in range(w) for z in range(d)} for _ in range(n_layers)]
        self.assign = {}
        self.writes = []

    def set(self, x, y, z, ch, part, color=None, op_i=None):
        """写入或清除单个体素，并记录部位覆盖轨迹用于防吞没审计。"""
        prev = self.assign.get((x, y, z))
        if ch is None:
            self.chars[y][(x, z)] = None
            self.colors[y][(x, z)] = None
            self.assign.pop((x, y, z), None)
        else:
            self.chars[y][(x, z)] = ch
            if color:
                self.colors[y][(x, z)] = color
            if part:
                self.assign[(x, y, z)] = part
        if prev is not None or part is not None:
            self.writes.append({"op": op_i, "cell": (x, y, z),
                                "prev_part": prev, "new_part": part if ch else None})


def validate_ops_schema(ops, default_part, part_ids):
    """算子列表静态结构校验（不做光栅化），返回错误列表。"""
    errs = []
    if not isinstance(ops, list) or not ops:
        return ["ops 缺失或为空：至少需要一个构造算子"]
    for i, op in enumerate(ops):
        if not isinstance(op, dict):
            errs.append(f"ops[{i}] 必须是对象")
            continue
        name = op.get("op")
        if name not in ALL_OP_NAMES:
            errs.append(f"ops[{i}] 的 op {name!r} 不在算子闭集内（可用：{'、'.join(ALL_OP_NAMES)}）")
            continue
        if name == "mirror":
            sub = op.get("ops")
            if not isinstance(sub, list) or not sub:
                errs.append(f"ops[{i}]（mirror）缺少 ops 子算子列表")
            else:
                for e in validate_ops_schema(sub, default_part, part_ids):
                    errs.append(f"ops[{i}]（mirror 子算子）{e}")
            if str(op.get("axis") or "") not in ("x", "z"):
                errs.append(f"ops[{i}]（mirror）的 axis 必须是 x 或 z")
            continue
        if name == "paint":
            if str(op.get("color") or "") not in COLORS:
                errs.append(f"ops[{i}]（paint）的颜色 {op.get('color')!r} 不可用")
            cells = op.get("cells")
            if not isinstance(cells, list) or not cells:
                errs.append(f"ops[{i}]（paint）缺少 cells 列表")
            else:
                for c in cells[:64]:
                    if not (isinstance(c, (list, tuple)) and len(c) == 3
                            and all(_int_of(v) is not None for v in c)):
                        errs.append(f"ops[{i}]（paint）cells 必须是 [x,y,z] 整数三元组：{c!r}")
                        break
            continue
        if "role" in op and str(op.get("role")) not in ("solid", "surface"):
            errs.append(f"ops[{i}] 的 role 只能是 solid（立体结构）或 surface（表面涂装）")
        if name != "hollow":
            part = op.get("part") or default_part
            if not part:
                errs.append(f"ops[{i}]（{name}）缺少 part（或顶层 defaultPart 兜底）")
            elif part_ids is not None and part not in part_ids:
                errs.append(f"ops[{i}]（{name}）的 part「{part}」不在规划里")
        if name == "loft":
            secs = op.get("sections")
            if not isinstance(secs, list) or len(secs) < 2:
                errs.append(f"ops[{i}]（loft）需要 ≥2 个 sections")
                continue
            for s in secs:
                if not isinstance(s, dict) or _int_of(s.get("y")) is None \
                        or _num_of(s.get("w")) is None or _num_of(s.get("d")) is None:
                    errs.append(f"ops[{i}]（loft）section 必须含 y/w/d：{s!r}")
                    break
        elif name in ("box", "hollow"):
            for k in ("x", "y", "z", "w", "d", "h"):
                if _int_of(op.get(k)) is None:
                    errs.append(f"ops[{i}]（{name}）缺少整数参数 {k}")
                    break
        elif name == "cylinder":
            for k in ("cx", "cz", "y", "h", "r"):
                if _num_of(op.get(k)) is None:
                    errs.append(f"ops[{i}]（cylinder）缺少数值参数 {k}")
                    break
        elif name == "wedge":
            for k in ("x", "y", "z"):
                if _int_of(op.get(k)) is None:
                    errs.append(f"ops[{i}]（wedge）缺少整数参数 {k}")
                    break
            sx, sz, wh = _wedge_spans(op)
            if sx is None or sz is None or wh is None:
                errs.append(f"ops[{i}]（wedge）缺少整数尺寸参数 w(或 len)/d/h")
            direction = str(op.get("dir") or "")
            kind = str(op.get("kind") or "regular")
            if direction not in WEDGE_DOWN_CHAR:
                errs.append(f"ops[{i}]（wedge）的 dir 必须是 +x/-x/+z/-z")
            elif kind not in ("regular", "inverted"):
                errs.append(f"ops[{i}]（wedge）的 kind 必须是 regular 或 inverted")
            elif kind == "inverted" and sx is not None and sz is not None:
                along = sx if direction[1] == "x" else sz
                if along < 2 or along % 2 != 0:
                    errs.append(f"ops[{i}]（wedge inverted）沿 {direction[1]} 轴跨度为 {along}，"
                                f"反斜坡砖 2 格一砖（无 1x1 反斜坡），沿坡向跨度必须为 ≥2 的偶数")
        if "color" in op and op.get("color") not in (None, "") and str(op.get("color")) not in COLORS:
            errs.append(f"ops[{i}] 的颜色 {op.get('color')!r} 不可用")
    return errs


def _rect_cells(cx, cz, w, d):
    """浮点中心 (cx,cz)、尺寸 w×d 的矩形截面覆盖格。"""
    x0, x1 = cx - w / 2.0, cx + w / 2.0
    z0, z1 = cz - d / 2.0, cz + d / 2.0
    return [(x, z) for x in range(math.floor(x0), math.ceil(x1))
            for z in range(math.floor(z0), math.ceil(z1))
            if x + 0.5 > x0 and x < x1 and z + 0.5 > z0 and z < z1]


def _ellipse_cells(cx, cz, w, d):
    """浮点中心 (cx,cz)、轴长 w×d 的椭圆截面覆盖格。"""
    rx, rz = w / 2.0, d / 2.0
    out = []
    for x in range(math.floor(cx - rx), math.ceil(cx + rx)):
        for z in range(math.floor(cz - rz), math.ceil(cz + rz)):
            dx, dz = (x + 0.5 - cx) / max(rx, 1e-9), (z + 0.5 - cz) / max(rz, 1e-9)
            if dx * dx + dz * dz <= 1.0:
                out.append((x, z))
    return out


def _rasterize_wedge(op, put, op_i):
    """光栅化正/反斜楔：始终占用 [x, x+span_x) × [z, z+span_z)，消除 ±z 方向长宽颠倒。"""
    direction = str(op["dir"])
    x, y, z = (_int_of(op[k]) for k in ("x", "y", "z"))
    span_x, span_z, h = _wedge_spans(op)
    kind = str(op.get("kind") or "regular")
    if span_x <= 0 or span_z <= 0 or h <= 0:
        return [f"算子#{op_i}（wedge）的 w(len)/d/h 必须 ≥1"]
    sign = 1 if direction.startswith("+") else -1
    axis = direction[1]
    n_along = span_x if axis == "x" else span_z
    n_across = span_z if axis == "x" else span_x
    if kind == "inverted" and (n_along < 2 or n_along % 2 != 0):
        return [f"算子#{op_i}（wedge inverted）沿 {axis} 轴跨度必须为 ≥2 的偶数，实际 {n_along}"]

    def coord_at(along_i, across_j):
        if axis == "x":
            px = (x + along_i) if sign > 0 else (x + span_x - 1 - along_i)
            return px, z + across_j
        pz = (z + along_i) if sign > 0 else (z + span_z - 1 - along_i)
        return x + across_j, pz

    if kind == "inverted":
        for j in range(n_across):
            for i in range(n_along):
                px, pz = coord_at(i, j)
                base = y + (i // 2)
                if base >= y + h:
                    continue
                for py in range(base, y + h):
                    ch = INV_ROOT_CHAR[direction] if py == base else SOLID_CHAR
                    put([(px, py, pz)], ch)
        return []

    # 正斜坡：按层计算自高端起的水平跨度 L_k；当单阶水平跨度 ≥2（如缓坡/2格檐）时，
    # 外缘生成连续 2 格斜面段以使用 2x1/2x2 斜坡形状（定义见 parts_library 的 SHAPES），否则生成 1 格斜面。
    for k in range(h):
        l_cur = max(1, round(n_along * (h - k) / h)) if n_along >= h else max(0, n_along - k)
        l_next = (max(1, round(n_along * (h - k - 1) / h)) if (k + 1 < h and n_along >= h)
                  else max(0, n_along - (k + 1) if k + 1 < h else 0))
        if l_cur <= 0:
            break
        step_run = l_cur - l_next
        slope_width = 2 if (step_run >= 2 and l_cur >= 2) else 1
        solid_end = l_cur - slope_width
        for j in range(n_across):
            for i in range(l_cur):
                px, pz = coord_at(i, j)
                ch = SOLID_CHAR if i < solid_end else WEDGE_DOWN_CHAR[direction]
                put([(px, y + k, pz)], ch)
    return []


def _rasterize_op(op, grid, op_i, default_part):
    """光栅化单个算子写入网格；越界或参数非法直接返回错误列表（禁止静默裁剪）。"""
    errs = []
    name = op["op"]
    if name == "mirror":
        axis = op["axis"]
        flip_map = MIRROR_X if axis == "x" else MIRROR_Z
        tmp = _Grid(grid.w, grid.d, grid.n_layers)
        for j, sub in enumerate(op["ops"]):
            errs += _rasterize_op(sub, tmp, f"{op_i}.m{j}", default_part)
        if errs:
            return errs
        for y in range(grid.n_layers):
            for (x, z), ch in list(tmp.chars[y].items()):
                if ch is None:
                    continue
                mx = (grid.w - 1 - x) if axis == "x" else x
                mz = (grid.d - 1 - z) if axis == "z" else z
                grid.set(mx, y, mz, flip_map.get(ch, ch),
                         tmp.assign.get((x, y, z)), tmp.colors[y][(x, z)], op_i)
        return errs
    if name == "paint":
        color = str(op["color"])
        for c in op["cells"]:
            x, y, z = (_int_of(v) for v in c)
            if not (0 <= x < grid.w and 0 <= y < grid.n_layers and 0 <= z < grid.d):
                errs.append(f"算子#{op_i}（paint）越界：(x={x},y={y},z={z}) 不在网格内")
                continue
            if grid.chars[y][(x, z)] is None:
                errs.append(f"算子#{op_i}（paint）坐标 (x={x},y={y},z={z}) 不是实体格")
                continue
            part_override = op.get("part") or grid.assign.get((x, y, z))
            grid.set(x, y, z, grid.chars[y][(x, z)], part_override, color, op_i)
        return errs

    color = str(op["color"]) if op.get("color") else None
    if name == "hollow":
        x, y, z, w, d, h = (_int_of(op[k]) for k in ("x", "y", "z", "w", "d", "h"))
        if not (w > 0 and d > 0 and h > 0):
            return [f"算子#{op_i}（hollow）的 w/d/h 必须 ≥1"]
        for xx in range(x, x + w):
            for yy in range(y, y + h):
                for zz in range(z, z + d):
                    if not (0 <= xx < grid.w and 0 <= yy < grid.n_layers and 0 <= zz < grid.d):
                        errs.append(f"算子#{op_i}（hollow）越界：(x={xx},y={yy},z={zz}) 不在网格内")
                        continue
                    if grid.chars[yy][(xx, zz)] is not None:
                        grid.set(xx, yy, zz, None, None, None, op_i)
        return errs

    part = op.get("part") or default_part

    def put(cells, ch):
        for (x, y, z) in cells:
            if not (0 <= x < grid.w and 0 <= y < grid.n_layers and 0 <= z < grid.d):
                errs.append(f"算子#{op_i}（{name}）越界：(x={x},y={y},z={z}) 不在网格内"
                            f"（越界即报错，禁止静默裁剪——请收进 {grid.w}×{grid.d}×{grid.n_layers}）")
                continue
            grid.set(x, y, z, ch, part, color, op_i)

    if name == "box":
        x, y, z, w, d, h = (_int_of(op[k]) for k in ("x", "y", "z", "w", "d", "h"))
        if not (w > 0 and d > 0 and h > 0):
            return [f"算子#{op_i}（box）的 w/d/h 必须 ≥1"]
        put([(xx, yy, zz) for xx in range(x, x + w) for yy in range(y, y + h)
             for zz in range(z, z + d)], SOLID_CHAR)
        return errs
    if name == "cylinder":
        cx, cz = _num_of(op["cx"]), _num_of(op["cz"])
        y, h, r = _int_of(op["y"]), _int_of(op["h"]), _num_of(op["r"])
        r_top = _num_of(op["rTop"]) if op.get("rTop") is not None else r
        if h <= 0 or r <= 0 or r_top < 0:
            return [f"算子#{op_i}（cylinder）的 h 必须 ≥1、r >0"]
        max_r = max(r, r_top)
        if (cx - max_r < -0.5 or cx + max_r > grid.w + 0.5
                or cz - max_r < -0.5 or cz + max_r > grid.d + 0.5
                or y < 0 or y + h > grid.n_layers):
            return [f"算子#{op_i}（cylinder）超出网格边界 {grid.w}×{grid.d}×{grid.n_layers}"]
        for yy in range(y, y + h):
            t = (yy - y) / max(1, h - 1) if h > 1 else 0.0
            rr = r + (r_top - r) * t
            if rr <= 0:
                continue
            for x in range(math.floor(cx - rr), math.ceil(cx + rr)):
                for z in range(math.floor(cz - rr), math.ceil(cz + rr)):
                    if (x + 0.5 - cx) ** 2 + (z + 0.5 - cz) ** 2 <= rr * rr:
                        put([(x, yy, z)], SOLID_CHAR)
        return errs
    if name == "wedge":
        errs += _rasterize_wedge(op, put, op_i)
        return errs
    if name == "loft":
        secs = op["sections"]
        shape = str(op.get("shape") or "rect")
        for s in secs:
            if str(s.get("shape") or shape) not in ("rect", "ellipse"):
                return [f"算子#{op_i}（loft）shape 只能是 rect 或 ellipse"]
        ordered = sorted(secs, key=lambda s: _int_of(s["y"]))
        for a, b in zip(ordered, ordered[1:]):
            if _int_of(b["y"]) <= _int_of(a["y"]):
                return [f"算子#{op_i}（loft）sections 的 y 必须严格递增"]
        y_first, y_last = _int_of(ordered[0]["y"]), _int_of(ordered[-1]["y"])
        if y_first < 0 or y_last >= grid.n_layers:
            return [f"算子#{op_i}（loft）y 范围 {y_first}..{y_last} 超出层数 0..{grid.n_layers - 1}"]
        cx_def, cz_def = (grid.w - 1) / 2.0, (grid.d - 1) / 2.0
        for yy in range(y_first, y_last + 1):
            if yy == y_last:
                a = b = ordered[-1]
                t = 0.0
            else:
                for a, b in zip(ordered, ordered[1:]):
                    if _int_of(a["y"]) <= yy <= _int_of(b["y"]):
                        span = max(1, _int_of(b["y"]) - _int_of(a["y"]))
                        t = (yy - _int_of(a["y"])) / span
                        break
            w = _num_of(a["w"]) + (_num_of(b["w"]) - _num_of(a["w"])) * t
            d = _num_of(a["d"]) + (_num_of(b["d"]) - _num_of(a["d"])) * t
            cxa = _num_of(a["cx"]) if a.get("cx") is not None else cx_def
            cza = _num_of(a["cz"]) if a.get("cz") is not None else cz_def
            cxb = _num_of(b["cx"]) if b.get("cx") is not None else cx_def
            czb = _num_of(b["cz"]) if b.get("cz") is not None else cz_def
            cx, cz = cxa + (cxb - cxa) * t, cza + (czb - cza) * t
            cells = _ellipse_cells(cx, cz, w, d) if shape == "ellipse" else _rect_cells(cx, cz, w, d)
            put([(x, yy, z) for (x, z) in cells], SOLID_CHAR)
        return errs
    return [f"算子#{op_i} 的 op {name!r} 不受支持"]


def compile_ops(ops, grid_w, grid_d, n_layers, default_part=None, part_ids=None,
                required_ids=None, frozen_cells=None, name="乐高模型", slug="model",
                features=None, notes=""):
    """编译三维算子列表 → 标准 model 字典与逐格部位归属。"""
    ops = ops or []
    errs = validate_ops_schema(ops, default_part, part_ids)
    if errs:
        return errs, None
    grid = _Grid(grid_w, grid_d, n_layers)
    for i, op in enumerate(ops):
        sub_errs = _rasterize_op(op, grid, i, default_part)
        if sub_errs:
            return sub_errs, None
    solid = {(x, y, z) for y in range(n_layers) for (x, z), ch in grid.chars[y].items() if ch}
    if not solid:
        return ["编译结果没有任何实体体素"], None
    if frozen_cells is not None:
        lost = sorted(frozen_cells - solid)
        if lost:
            sample = "、".join(f"(x={x},y={y},z={z})" for x, y, z in lost[:4])
            return [f"重编译丢失了 {len(lost)} 个防删核心体素：{sample}"
                    f"——修订只能调整尺寸/位置/坡向，不能删除核心"], None
    for pid in (required_ids or []):
        if any(c == pid for c in grid.assign.values()):
            continue
        culprits = sorted({str(w["op"]) for w in grid.writes
                           if w["prev_part"] == pid and w["new_part"] != pid})
        hint = f"（肇事算子序号：{culprits[:4]}）" if culprits else "（没有任何算子为它写入实体）"
        return [f"必需部位「{pid}」被后续算子完全覆盖/挖空至零体素{hint}"
                f"——请调整算子顺序或给它保留独立体素"], None

    global_cnt = Counter(v for y in range(n_layers) for v in grid.colors[y].values() if v)
    global_default = global_cnt.most_common(1)[0][0] if global_cnt else None
    layers, total = [], 0
    for y in range(n_layers):
        rows = ["".join(grid.chars[y][(x, z)] or "." for x in range(grid.w))
                for z in range(grid.d)]
        cells = [[x, z] for z in range(grid.d) for x in range(grid.w)
                 if grid.chars[y][(x, z)] is not None]
        color_rows = None
        if global_default is not None:
            cnt = Counter(v for v in grid.colors[y].values() if v)
            fallback = cnt.most_common(1)[0][0] if cnt else global_default
            color_rows = ["".join(COLOR_CHARS.get(grid.colors[y][(x, z)] or fallback, ".")
                                  if grid.chars[y][(x, z)] else "."
                                  for x in range(grid.w))
                          for z in range(grid.d)]
        total += len(cells)
        layers.append({"y": y, "rows": rows, "cells": cells,
                       "module": [f"y{y}"], "color": None,
                       "colorRows": color_rows, "count": len(cells)})
    if not layers[0]["cells"]:
        return ["编译后 y=0 底层没有实体（模型无法落地）——请让底部结构落到 y=0"], None
    if total > MAX_VOX_GUARD:
        return [f"编译结果 {total} 体素超过上限 {MAX_VOX_GUARD}"], None
    role_overrides = {}
    for op in ops:
        if op.get("role") and (op.get("part") or default_part):
            role_overrides[op["part"] or default_part] = str(op["role"])
    model = {
        "name": name, "slug": slug, "notes": notes,
        "features": [str(f) for f in (features or [])],
        "grid": {"w": grid_w, "d": grid_d},
        "totalVoxels": total,
        "slopeVoxels": sum(1 for y in range(n_layers) for ch in grid.chars[y].values()
                           if ch in ALL_SLOPE_CHARS),
        "hasSlopes": any(ch in ALL_SLOPE_CHARS for y in range(n_layers)
                         for ch in grid.chars[y].values()),
        "modules": sorted({m for L in layers for m in L["module"]}),
        "openings": [], "floatingVoxels": 0, "unsupportedVoxels": 0, "components": 1,
        "hasVoxelColors": any(L["colorRows"] for L in layers),
        "layers": layers,
        "track": "ops",
    }
    return [], {"model": model, "assign": dict(grid.assign), "ops": ops,
                "role_overrides": role_overrides}
