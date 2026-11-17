# ============================================================
# 乐高 Agent：设计校验（语法/尺寸、设计预检）与 3D 可视化页面生成
#
# 系统提示词与规模上限拆分在 prompts.py（单文件 ≤500 行约束），此处统一再导出，
# 保持外部 `from .agent import AGENT_SYSTEM, MAX_WD, ...` 完全兼容。
# ============================================================
import json
import os
import re

from .geometry import GEO_CHARS, interior_cells, solid_cells_of_model
from .parts_library import (CHAR_COLORS, COLORS, COLOR_CHARS, COLOR_CHAR_TABLE,
                            COLOR_NAMES, PARTS, voxel_color_map)
from .paths import WEB_DIR
from .prompts import (AGENT_SYSTEM, FIDELITY_PASS, FIDELITY_PROMPT,  # noqa: F401
                      MAX_LAYERS, MAX_REVISE_COLOR_OPS, MAX_REVISE_OPS, MAX_VOX, MAX_WD,
                      OPS_REVISE_DOC, OPS_TOOL_DOC)  # noqa: F401
from .support_reasons import reason_buckets
from .tiler import find_unsupported

VIZ_TEMPLATE = os.path.join(WEB_DIR, "shell.html")
VIEWER_SRC = os.path.join(WEB_DIR, "viewer.js")


def _expand_color_patches(y, rows, W, D, color, patches, errs):
    """将单层稀疏 colorPatches 校验并展开为完整 colorRows；非法时记录 errs 并返回 None。"""
    if not isinstance(patches, list):
        errs.append(f"y={y} 层 colorPatches 必须是列表")
        return None
    if not color:
        errs.append(f"y={y} 层使用 colorPatches 时必须给 color 作为默认色")
        return None
    if color not in COLORS:
        return None
    patch_map = {}
    patch_ok = True
    for p in patches:
        if not isinstance(p, dict):
            errs.append(f"y={y} colorPatches 条目必须是对象")
            patch_ok = False
            continue
        pcolor = str(p.get("color") or "").strip()
        if pcolor not in COLORS:
            errs.append(f"y={y} colorPatches 颜色 {pcolor!r} 不可用")
            patch_ok = False
            continue
        for cell in (p.get("cells") or []):
            if not (isinstance(cell, (list, tuple)) and len(cell) == 2):
                errs.append(f"y={y} colorPatches cells 格式错误（应为 [x,z]）：{cell!r}")
                patch_ok = False
                continue
            try:
                px, pz = int(cell[0]), int(cell[1])
            except (TypeError, ValueError):
                errs.append(f"y={y} colorPatches 坐标必须是整数：{cell!r}")
                patch_ok = False
                continue
            if not (0 <= px < W and 0 <= pz < D) or rows[pz][px] == ".":
                errs.append(f"y={y} colorPatches 坐标 (x={px},z={pz}) 不是实体体素")
                patch_ok = False
                continue
            patch_map[(px, pz)] = pcolor
    if not (patch_ok and patch_map):
        return None
    colored = []
    for pz, row in enumerate(rows):
        line = [
            "." if ch == "." else COLOR_CHARS.get(patch_map.get((px, pz), color), ".")
            for px, ch in enumerate(row)
        ]
        colored.append("".join(line))
    return colored


def validate_design_syntax(plan, require_layer_color=True):
    """校验设计 JSON 的语法、尺寸与颜色，返回 (errors, model|None, warnings)。"""
    if not isinstance(plan, dict):
        return ["设计数据必须是 JSON 对象"], None, []
    errs, warns = [], []
    features = [str(f).strip() for f in (plan.get("features") or []) if str(f).strip()]
    layers_in = plan.get("layers")
    if not isinstance(layers_in, list) or not layers_in:
        return ["layers 缺失或为空"], None, []
    if not isinstance(layers_in[0], dict):
        return ["layers[0] 必须是对象"], None, []
    rows0 = layers_in[0].get("rows") or []
    W = len(rows0[0]) if (rows0 and isinstance(rows0[0], str)) else 0
    D = len(rows0)
    if not (1 <= W <= MAX_WD and 1 <= D <= MAX_WD):
        return [f"网格尺寸 {W}x{D} 超出 {MAX_WD}x{MAX_WD}"], None, []
    if len(layers_in) > MAX_LAYERS:
        return [f"层数 {len(layers_in)} 超过 {MAX_LAYERS}"], None, []

    layers, total, solid = [], 0, {}
    layer_chars = []
    for y, L in enumerate(layers_in):
        if not isinstance(L, dict):
            errs.append(f"y={y} 层必须是对象")
            continue
        rows = L.get("rows") or []
        mod = str(L.get("module") or ("模块%d" % y))
        color = str(L.get("color") or "").strip()
        color_rows = L.get("colorRows")
        has_color_rows = False
        if len(rows) != D or any(not isinstance(r, str) or len(r) != W for r in rows):
            errs.append(f"y={y} 层 rows 尺寸不一致（应 {D} 行 × {W} 列）")
            continue
        if any(c not in GEO_CHARS for r in rows for c in r):
            errs.append(f"y={y} 层 rows 含非法字符（只允许 {GEO_CHARS}，"
                        f"其中 b d p q 为反斜坡：根部朝 西/东/北/南）")
            continue
        patches = L.get("colorPatches")
        if patches:
            expanded = _expand_color_patches(y, rows, W, D, color, patches, errs)
            if expanded is not None:
                color_rows = expanded
        if color_rows is not None:
            if not isinstance(color_rows, list) or len(color_rows) != D or any(
                    not isinstance(r, str) or len(r) != W for r in color_rows):
                errs.append(f"y={y} 层 colorRows 尺寸不一致（应 {D} 行 × {W} 列）")
            else:
                bad_chars = sorted({ch for row in color_rows for ch in row
                                    if ch != "." and ch not in CHAR_COLORS})
                if bad_chars:
                    errs.append(f"y={y} 层 colorRows 含非法颜色字符 {bad_chars}（可用：{COLOR_CHAR_TABLE}）")
                else:
                    missing_color = [(x, z) for z, row in enumerate(rows) for x, ch in enumerate(row)
                                     if ch != "." and color_rows[z][x] == "."]
                    if missing_color:
                        errs.append(f"y={y} 层实体体素缺少颜色字符（colorRows 对应位置是 '.'）：{missing_color[:4]}")
                    else:
                        has_color_rows = True
        if color and color not in COLORS:
            errs.append(f"y={y} 层颜色 {color!r} 不可用（可用：{'、'.join(COLOR_NAMES)}）")
        elif not color and not has_color_rows and require_layer_color:
            errs.append(f"y={y} 层缺少 color 颜色，且没有提供逐体素 colorRows"
                        f"（颜色字符：{COLOR_CHAR_TABLE}）")
        cells = [[x, z] for z, r in enumerate(rows) for x, c in enumerate(r) if c != "."]
        chars = {(x, z): c for z, r in enumerate(rows) for x, c in enumerate(r) if c != "."}
        for (x, z) in cells:
            solid[(x, y, z)] = True
        total += len(cells)
        layer_chars.append(chars)
        layers.append({"y": y, "rows": rows, "cells": cells, "module": [mod],
                       "color": color or None, "colorRows": color_rows if has_color_rows else None,
                       "count": len(cells)})
    if errs:
        return errs, None, []
    if total == 0:
        return ["模型是空的"], None, []
    if total > MAX_VOX:
        return [f"体素总数 {total} 超过 {MAX_VOX}，请简化"], None, []
    if not layers[0]["cells"]:
        return ["y=0 底层没有实体，模型无法落地"], None, []

    floating = sum(1 for (x, y, z) in solid if y > 0 and (x, y - 1, z) not in solid)
    comps = _voxel_components(solid)
    slug = re.sub(r"[^a-z0-9-]+", "-", str(plan.get("slug") or "model").lower()).strip("-") or "model"
    slope_voxels = sum(1 for chars in layer_chars for c in chars.values() if c != "#")
    slopey = [f for f in features
              if re.search(r"斜|坡|尖|收|锥|翘|流线|楔", f)
              and not re.search(r"(无|不|非)\s*(使用)?\s*(收分|斜面)|平顶", f)]
    if features and slopey and slope_voxels == 0:
        warns.append("你列出的几何特征包含坡度/收尖（" + "；".join(slopey[:3]) +
                     "），但设计中一个斜面体素都没有——请把对应边缘用斜面算子或字符标注。")
    if not features:
        warns.append("未提供 features 几何特征清单——请先推理物体的几何特征，再让设计与之一致。")
    model = {
        "name": str(plan.get("name") or "乐高模型"),
        "slug": slug,
        "notes": str(plan.get("notes") or ""),
        "features": features,
        "grid": {"w": W, "d": D},
        "totalVoxels": total,
        "slopeVoxels": slope_voxels,
        "hasSlopes": slope_voxels > 0,
        "modules": sorted({m for L in layers for m in L["module"]}),
        "openings": [],
        "floatingVoxels": floating,
        "unsupportedVoxels": 0,
        "components": comps,
        "hasVoxelColors": any(L.get("colorRows") for L in layers),
        "layers": layers,
    }
    return [], model, warns


def _voxel_components(solid):
    """计算三维体素 6-连通分量数。"""
    seen, comps = set(), 0
    for v in solid:
        if v in seen:
            continue
        comps += 1
        stack = [v]
        seen.add(v)
        while stack:
            x, y, z = stack.pop()
            for nb in ((x + 1, y, z), (x - 1, y, z), (x, y, z + 1),
                       (x, y, z - 1), (x, y + 1, z), (x, y - 1, z)):
                if nb in solid and nb not in seen:
                    seen.add(nb)
                    stack.append(nb)
    return comps


def _layer_issue_scan(model):
    """逐层运行 find_unsupported，返回 [(y, issues), ...]。

    与旧 precheck_details 的逐层上下文完全一致：below 为上一层字符映射（y=0 为 None）、
    above 为下一层实体格、逐体素颜色经内部通配骨架处理。issues 元素带 A.3.5 原因码。
    """
    layer_chars = []
    for L in model.get("layers") or []:
        chars = {}
        for z, row in enumerate(L["rows"]):
            for x, ch in enumerate(row):
                if ch != ".":
                    chars[(x, z)] = ch
        layer_chars.append(chars)
    interior = interior_cells(model)
    out = []
    for idx, chars in enumerate(layer_chars):
        below = None if idx == 0 else layer_chars[idx - 1]
        above = set() if idx + 1 >= len(layer_chars) else set(layer_chars[idx + 1])
        L_cur = model["layers"][idx]
        layer_map = None
        if L_cur.get("colorRows") or L_cur.get("color"):
            layer_map = voxel_color_map(L_cur["rows"], L_cur.get("colorRows"), L_cur.get("color"))
            y_here = L_cur["y"]
            for (x_i, y_i, z_i) in interior:
                if y_i == y_here and (x_i, z_i) in layer_map:
                    layer_map[(x_i, z_i)] = None  # 内部通配骨架格：不约束铺砖颜色
        out.append((L_cur["y"], find_unsupported(chars, below, layer_map, above=above)))
    return out


def support_reasons_for_cells(model, cells):
    """把指定错误格映射到 A.3.5 稳定原因码：{code: {"count", "cells", ...}}。

    按层重跑 find_unsupported（与 precheck_details 同一判定），只统计给定格；
    没有对应判定（例如非 support 失败）时返回 {}。unknown 码保留原始 reason 文本。
    """
    wanted = {tuple(int(v) for v in c) for c in (cells or [])
              if isinstance(c, (list, tuple)) and len(c) == 3}
    if not wanted:
        return {}
    items = []
    for y, issues in _layer_issue_scan(model):
        for issue in issues:
            if (issue[0], y, issue[1]) in wanted:
                items.append((y, issue))
    return reason_buckets(items)


def precheck_details(model):
    """设计层预检明细：返回 {"errors", "error_cells", "kind", "support_reasons"}。

    kind/errors/error_cells 语义与旧版完全一致；新增 support_reasons 是 A.3.5 的按原因码
    聚合 {code: {"count", "cells": [[x,y,z]...前64]}}，unknown 类额外保留 rawReasons。
    """
    solid = {}
    for L in model.get("layers") or []:
        for z, row in enumerate(L["rows"]):
            for x, ch in enumerate(row):
                if ch != ".":
                    solid[(x, L["y"], z)] = True
    error_cells, items = [], []
    for y, issues in _layer_issue_scan(model):
        for issue in issues:
            error_cells.append((issue[0], y, issue[1]))
            items.append((y, issue))
    if error_cells:
        preview = "；".join(f"y={y}(x={x},z={z})" for x, y, z in error_cells[:4])
        return {
            "errors": [f"有 {len(error_cells)} 个体素无论怎么铺砖都得不到支撑或连接：{preview}"
                       f"——请收窄悬挑（每边悬空 ≤1 格）、加宽支撑柱，或在悬臂根部增设托架/立柱"],
            "error_cells": error_cells,
            "kind": "support",
            "support_reasons": reason_buckets(items),
        }
    comps = _voxel_components(solid)
    if comps > 1:
        comp_of, cid = {}, 0
        for v in solid:
            if v in comp_of:
                continue
            stack = [v]
            comp_of[v] = cid
            while stack:
                x, y, z = stack.pop()
                for nb in ((x + 1, y, z), (x - 1, y, z), (x, y, z + 1),
                           (x, y, z - 1), (x, y + 1, z), (x, y - 1, z)):
                    if nb in solid and nb not in comp_of:
                        comp_of[nb] = cid
                        stack.append(nb)
            cid += 1
        sizes = {}
        for _c, k in comp_of.items():
            sizes[k] = sizes.get(k, 0) + 1
        main = max(sizes, key=lambda k: sizes[k])
        minority = sorted(c for c, k in comp_of.items() if k != main)
        return {
            "errors": [f"模型有 {comps} 个互不相连的部分（整体必须连成一体）："
                       f"请让各部位在体素上相互接触，或去掉孤立碎块"],
            "error_cells": minority,
            "kind": "connectivity",
            "support_reasons": {},
        }
    return {"errors": [], "error_cells": [], "kind": None, "support_reasons": {}}


def support_distance_allowed(model, seed_cells, k=3, cap=1200):
    """按「到最近可靠支撑的距离」有界扩展 allowedCells（工作包 B.5）。

    可靠支撑格 = 实体格 y=0，或正下方 (x,y-1,z) 也是实体格（预检层可承托）。
    距离 = 网格内 6-邻域到最近可靠支撑格的最短步数（不可达视为无穷）。
    返回 seed ∪ {距离 ≤ k 的格}，按 (距离, 坐标) 排序取前 cap 个：默认不整模放开，
    只让修订够得着「离支撑不远」的下层/邻域格。
    """
    solid = solid_cells_of_model(model)
    grid = model.get("grid") or {}
    width, depth = int(grid.get("w") or 0), int(grid.get("d") or 0)
    n_layers = len(model.get("layers") or [])
    reliable = [c for c in solid if c[1] == 0 or (c[0], c[1] - 1, c[2]) in solid]
    if not reliable:
        return set(seed_cells)
    dist = {c: 0 for c in reliable}
    frontier = list(reliable)
    level = 0
    while frontier and level <= k:
        nxt = []
        for c in frontier:
            for d in ((1, 0, 0), (-1, 0, 0), (0, 1, 0), (0, -1, 0), (0, 0, 1), (0, 0, -1)):
                nb = (c[0] + d[0], c[1] + d[1], c[2] + d[2])
                if (0 <= nb[0] < width and 0 <= nb[1] < n_layers
                        and 0 <= nb[2] < depth and nb not in dist):
                    dist[nb] = level + 1
                    nxt.append(nb)
        frontier, level = nxt, level + 1
    out = set(seed_cells)
    extra = sorted((c for c, dd in dist.items() if dd <= k), key=lambda c: (dist[c], c))
    out.update(extra[:cap])
    return out


def model_plan(model):
    """把编译器产物还原成 validate_design_syntax 可接受的 plan（层数据 + 设计元信息）。"""
    layers = []
    for L in model.get("layers") or []:
        module = L.get("module")
        layers.append({
            "module": module[0] if isinstance(module, (list, tuple)) and module else (module or "层"),
            "color": L.get("color"), "rows": list(L.get("rows") or []),
            "colorRows": list(L["colorRows"]) if L.get("colorRows") else None,
        })
    return {"name": model.get("name") or "乐高模型", "slug": model.get("slug") or "model",
            "notes": model.get("notes") or "", "features": list(model.get("features") or []),
            "layers": layers}


def gen_viz(model, solution, out_path):
    """生成独立 3D 可视化 HTML（安全转义防存储型 XSS，自动创建父目录）。"""
    data = {
        "name": model["name"],
        "grid": model["grid"],
        "layers": [{"y": L["y"], "module": L["module"], "cells": L["cells"], "rows": L["rows"],
                    "color": L.get("color")} for L in model["layers"]],
        "parts": PARTS,
        "steps": solution["steps"],
        "usage": solution["usage"],
        "strategy": solution["strategy"],
        "valid": solution["valid"],
        "attempts": solution["attempts"],
        "subassemblies": solution.get("subassemblies") or [],
    }
    with open(VIZ_TEMPLATE, encoding="utf-8") as f:
        tpl = f.read()
    with open(VIEWER_SRC, encoding="utf-8") as f:
        viewer = f.read()
    if "/*__VIEWER__*/" not in tpl:
        raise RuntimeError("模板中未找到 /*__VIEWER__*/ 占位符")
    tpl = tpl.replace("/*__VIEWER__*/", viewer)
    payload = json.dumps(data, ensure_ascii=False).replace("<", "\\u003c").replace(">", "\\u003e")
    html, n = re.subn(r"const DATA = [^\n]+;",
                      lambda m: "const DATA = " + payload + ";",
                      tpl, count=1)
    if n != 1:
        raise RuntimeError("模板中未找到 DATA 行")
    os.makedirs(os.path.dirname(out_path) or ".", exist_ok=True)
    with open(out_path, "w", encoding="utf-8") as f:
        f.write(html)
