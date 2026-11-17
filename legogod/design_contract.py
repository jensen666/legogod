# ============================================================
# 部位契约与补丁修订
#
# 几何只由画稿决定，部位只在画完之后标注：
#   - plan_design 的 parts 只报语义 {id, name, required, source}，不再输出 boxes/coreBoxes；
#   - save_design 用默认归属 defaultPart + 稀疏 partPatches 标出桅杆、帆、舷墙等非主体部位；
#   - 程序从标注与实体算出每个部位的 cells，并生成防删核心：
#     任何部位只保护最多 CONNECT_CORE_LIMIT 格、且不超过实体 1/2 的中心代表格
#     （已取消「部位实体 ≤32 格整块冻结」的分档）；
#   - 内部 boxes 由程序写成矩形覆盖，只用于存档与追溯，不参与校验；
#   - 修订用 revise_design 补丁，区域始终由「当前实体 + 逐格归属」推导。
#
# 本模块保留：部位语义解析、补丁策略校验与应用、修订上下文格子工具。
# 画后标注、区域矩形覆盖、防删核心与绑定在 part_binding.py（避免单文件超过 500 行）。
# ============================================================
from .geometry import GEO_CHARS
from .parts_library import COLORS

MAX_GEO_CELLS = 32             # 每稿最多改变的几何体素数
MAX_COLOR_CELLS = 96           # 纯换色格子数的工程上限（防整模重刷色）
PART_KEYS = ("id", "name", "required", "source", "role")
LEGACY_PART_KEYS = ("boxes", "coreBoxes")   # 规划里出现即协议错误（区域由程序生成）


def _is_int(v):
    return isinstance(v, int) and not isinstance(v, bool)


def _cell3(raw):
    """[x, y, z] 形式的格子 → (x, y, z)；非法返回 None。"""
    if not (isinstance(raw, (list, tuple)) and len(raw) == 3):
        return None
    if not all(_is_int(v) for v in raw):
        return None
    return (raw[0], raw[1], raw[2])


def solid_cells_of(model):
    """model（validate_design_syntax 产物）的全部实体格子 {(x,y,z)}。"""
    solid = set()
    for L in model.get("layers") or []:
        y = L["y"]
        for c in L.get("cells") or []:
            solid.add((c[0], y, c[1]))
    return solid


def model_dims(model):
    """model 的 (grid_w, grid_d, n_layers)。"""
    return (model["grid"]["w"], model["grid"]["d"], len(model["layers"]))


# ---------------- 规划：只收语义 ----------------

def parse_parts_decl(parts, desc):
    """校验规划响应的 parts 语义声明，返回 (errors, normalized|None)。

    只收 id/name/required/source/role。规划里出现 boxes 或 coreBoxes 属于协议错误
    （区域与防删核心由程序在画完之后按标注生成）。缺 parts 或格式错误同样按协议重试。

    role 已由 schema 原生支持（solid=立体结构 / surface=表面涂装），不再新增字段；
    门禁失败时应改几何或纠正错误声明，不得为了过门禁删部位、缩体量或把立体件改成贴花。
    """
    if not isinstance(parts, list) or not parts:
        return ["parts 缺失或为空：规划必须列出部位清单（id/name/required/source），不要写区域"], None
    errs, out, seen = [], [], set()
    for i, raw in enumerate(parts):
        if not isinstance(raw, dict):
            errs.append(f"parts[{i}] 必须是对象")
            continue
        pid = str(raw.get("id") or "").strip()
        if not pid:
            errs.append(f"parts[{i}] 缺少 id")
            continue
        if pid in seen:
            errs.append(f"部位 id 重复：{pid!r}")
            continue
        seen.add(pid)
        legacy = [k for k in LEGACY_PART_KEYS if k in raw]
        if legacy:
            errs.append(f"部位 {pid} 带了 {'/'.join(legacy)}：规划只报部位语义，"
                        f"区域和防删核心由程序在画完后按标注生成")
            continue
        required = raw.get("required", True)
        if not isinstance(required, bool):
            errs.append(f"parts[{i}] required 必须是布尔值")
            required = True
        role = str(raw.get("role") or "solid").strip()
        if role not in ("solid", "surface"):
            errs.append(f"parts[{i}] 的 role 只能是 solid（立体结构：四肢/桅杆/炮塔/耳朵等"
                        f"真实凸出部件）或 surface（表面涂装：仅眼睛/鼻尖/车灯等不占独立体量的"
                        f"小型平面色点），实际 {role!r}")
            continue
        name = str(raw.get("name") or "").strip()
        source = str(raw.get("source") or "").strip()
        if required:
            if not name:
                errs.append(f"必需部位 {pid} 缺少非空名称 name")
            if not source:
                errs.append(f"必需部位 {pid} 缺少来源 source")
            elif desc and source not in desc:
                errs.append(f"必需部位 {pid} 的来源「{source}」没有在原始需求中逐字出现")
        out.append({"id": pid, "name": name, "required": required, "source": source, "role": role})
    if errs:
        return errs, None
    return [], out



# ---------------- revise_design 补丁 ----------------

def _cell_of(edit):
    x, y, z = edit.get("x"), edit.get("y"), edit.get("z")
    if not (_is_int(x) and _is_int(y) and _is_int(z)):
        return None
    return (x, y, z)


def _delete_cap(n):
    """单部位单稿最多删除当前实体的 1/2（向上取整，至少 1 格）。"""
    return max(1, (n + 1) // 2)


def patch_errors(patch, ctx):
    """校验 revise_design 补丁的策略约束。返回 (errors, meta)。

    ctx: {"base_revision", "layers", "allowed_cells", "frozen_cells",
          "assignment": 逐格归属 {(x,y,z): part_id},
          "part_ids": 规划里全部部位 id,
          "default_part": 新增实体没带 part 时归它}
    meta: {"geo_changes", "color_changes", "n_edits", "new_part_assign"}
    全部拒收都按协议失败处理：保留上一有效版本、当前阶段重试，不消耗修订次数。
    修订不接受 boxes/coreBoxes/parts 区域更新：区域始终由实体与标注推导。
    删除规则（通用，不按部位大小分档）：核心格不可删（可换色）；
    单部位单稿最多删除其当前实体的 1/2，部位不能删空。
    """
    meta = {"geo_changes": 0, "color_changes": 0, "n_edits": 0, "new_part_assign": {}}
    if not isinstance(patch, dict):
        return ["补丁必须是对象"], meta
    base = str(patch.get("baseRevision") or "").strip()
    if base != ctx["base_revision"]:
        return [f"补丁基于 {base or '(空)'}，但当前有效版本是 {ctx['base_revision']}"
                f"——版本过期，请基于当前版本重新提交"], meta
    for k in ("parts", "boxes", "coreBoxes"):
        if k in patch:
            return [f"补丁不能携带 {k}：区域由程序按实体与标注推导，"
                    f"新增实体请在 edit 里带 part（已有部位 id）"], meta
    edits = patch.get("edits")
    if not isinstance(edits, list) or not edits:
        return ["补丁缺少 edits"], meta
    layers = ctx["layers"]
    W = len(layers[0]["rows"][0]) if layers and layers[0].get("rows") else 0
    D = len(layers[0]["rows"]) if layers else 0
    Y = len(layers)
    allowed = ctx["allowed_cells"]
    frozen = ctx.get("frozen_cells") or set()
    assign = ctx.get("assignment") or {}
    part_ids = ctx.get("part_ids")
    default_part = str(ctx.get("default_part") or "")
    entity_counts, del_counts = {}, {}
    for _owner in assign.values():
        entity_counts[_owner] = entity_counts.get(_owner, 0) + 1
    errs = []
    seen = {}
    max_geo = ctx.get("max_geo", MAX_GEO_CELLS)
    max_color = ctx.get("max_color", MAX_COLOR_CELLS)
    for i, e in enumerate(edits):
        if not isinstance(e, dict):
            errs.append(f"edits[{i}] 必须是对象")
            continue
        cell = _cell_of(e)
        if cell is None:
            errs.append(f"edits[{i}] 的 x/y/z 必须是整数：{e!r}")
            continue
        x, y, z = cell
        if not (0 <= x < W and 0 <= z < D and 0 <= y < Y):
            errs.append(f"edits[{i}] 越界 (x={x},y={y},z={z})（网格 {W}×{D}×{Y} 层）")
            continue
        voxel = e.get("voxel")
        if voxel not in GEO_CHARS:
            errs.append(f"edits[{i}] 的 voxel 必须是 {'、'.join(GEO_CHARS)} 之一，实际 {voxel!r}")
            continue
        color = e.get("color")
        if color is not None and str(color).strip() not in COLORS:
            errs.append(f"edits[{i}] 的颜色 {color!r} 不可用")
            continue
        if cell in seen:
            errs.append(f"edits[{i}] 与 edits[{seen[cell]}] 修改了同一格 (x={x},y={y},z={z})")
            continue
        seen[cell] = i
        if cell not in allowed:
            errs.append(f"edits[{i}] 的 (x={x},y={y},z={z}) 不在本次允许修改的 allowedCells 内")
            continue
        cur = layers[y]["rows"][z][x]
        part = e.get("part")
        if part is not None:
            part = str(part).strip()
            if part_ids is not None and part not in part_ids:
                errs.append(f"edits[{i}] 的 part「{part}」不在规划里（不能新增部位）")
                continue
        if cur != "." and voxel == ".":
            # 从实体改成空：该格离开原部位。核心格不可删（可换色）；
            # 单部位单稿最多删当前实体的 1/2，防止小部位被一次削光。
            owner = assign.get(cell)
            if cell in frozen:
                errs.append(f"edits[{i}] 想删 (x={x},y={y},z={z})，但它是部位 {owner or '?'} 的防删核心格"
                            f"（核心格不可删除，可以换色；该部位其余格可删）")
                continue
            if owner is not None:
                n = entity_counts.get(owner, 0)
                cap = _delete_cap(n)
                del_counts[owner] = del_counts.get(owner, 0) + 1
                if del_counts[owner] > cap:
                    errs.append(f"edits[{i}] 想删 (x={x},y={y},z={z})：本稿对部位 {owner} 已删 "
                                f"{del_counts[owner]} 格，超过该部位当前 {n} 格的 1/2（最多 {cap} 格）")
                    continue
            meta["geo_changes"] += 1
        elif cur == "." and voxel != ".":
            # 新增实体：必须能落到一个已有部位；没带 part 就归 defaultPart。
            owner = part or default_part
            if not owner:
                errs.append(f"edits[{i}] 新增实体 (x={x},y={y},z={z}) 必须带 part"
                            f"（已有部位 id），或由 defaultPart 兜底")
                continue
            meta["new_part_assign"][cell] = owner
            meta["geo_changes"] += 1
        elif voxel != cur:
            # 实体→另一种实体字符（例如收尖改斜面）：不删格，允许；归属保持不变。
            meta["geo_changes"] += 1
        elif color is not None and str(color).strip():
            meta["color_changes"] += 1
    meta["n_edits"] = len(edits)
    if meta["geo_changes"] > max_geo:
        errs.append(f"补丁改变了 {meta['geo_changes']} 个几何体素，超过每稿上限 {max_geo}")
    if meta["color_changes"] > max_color:
        errs.append(f"补丁换色的格子有 {meta['color_changes']} 个，超过每稿上限 {max_color}")
    if errs:
        return errs, meta
    return [], meta


def apply_edits(layers, edits):
    """把通过策略校验的 edits 应用到 plan 格式 layers，返回 (errors, new_layers)。

    color 编辑落到 colorRows：该层没有 colorRows 时用层色补全后再改。
    不改变网格尺寸与层数（调用方已在 patch_errors 里校验过坐标范围）。
    """
    errs = []
    new_layers = [{"module": L.get("module"), "color": L.get("color"),
                   "rows": list(L["rows"]),
                   "colorRows": list(L["colorRows"]) if L.get("colorRows") else None}
                  for L in layers]
    for i, e in enumerate(edits):
        x, y, z = e["x"], e["y"], e["z"]
        voxel = e["voxel"]
        color = e.get("color")
        row = list(new_layers[y]["rows"][z])
        row[x] = voxel
        new_layers[y]["rows"][z] = "".join(row)
        if color:
            color = str(color).strip()
            cr = new_layers[y]["colorRows"]
            if cr is None:
                base = new_layers[y].get("color")
                from .parts_library import COLOR_CHARS
                fill = COLOR_CHARS.get(base, ".")
                cr = ["".join((fill if ch != "." else ".") for ch in r) for r in new_layers[y]["rows"]]
            cr = [list(r) for r in cr]
            from .parts_library import COLOR_CHARS
            ch = COLOR_CHARS.get(color)
            if ch is None:
                errs.append(f"edits[{i}] 的颜色 {color!r} 没有对应的颜色字符")
                continue
            cr[z][x] = ch
            new_layers[y]["colorRows"] = ["".join(r) for r in cr]
    if errs:
        return errs, None
    return [], new_layers


# ---------------- 修订上下文的格子集合 ----------------


def cells_near_grid(seed_cells, grid_w, grid_d, n_layers, max_dxz=1, dy=(0,)):
    """网格范围内与 seed_cells 任一格的 xz 距离 ≤max_dxz、y 差 ∈dy 的全部格子。

    与 cells_near 不同：不要求格子已是实体——修订既可能删格也可能加格
    （支撑失败要包含下层支撑候选，断连失败要包含跨组件候选，含空位）。
    """
    out = set()
    for (x, y, z) in seed_cells:
        for dx in range(-max_dxz, max_dxz + 1):
            for dz in range(-max_dxz, max_dxz + 1):
                for dyy in dy:
                    nx, ny, nz = x + dx, y + dyy, z + dz
                    if 0 <= nx < grid_w and 0 <= ny < n_layers and 0 <= nz < grid_d:
                        out.add((nx, ny, nz))
    return out


def cells_to_lists(cells, cap=400):
    """把格子集合序列化成 [[x,y,z], ...]（排序后截断到 cap 个，供提示词使用）。"""
    out = sorted(cells)[:cap]
    return [[x, y, z] for (x, y, z) in out]
