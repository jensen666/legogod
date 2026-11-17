# ============================================================
# 画后部位绑定
#
# 几何只由画稿决定，部位只在画完之后标注：
#   - parse_part_labels：校验 save_design / label_parts 的 defaultPart + 稀疏 partPatches，
#     展开成逐格归属；
#   - region_boxes：把部位实体格写成内部矩形覆盖（只用于存档与追溯，不参与校验）；
#   - build_cores：程序生成防删核心（任何部位只保护最多 CONNECT_CORE_LIMIT 格、
#     且不超过实体 1/2 的中心代表格，已取消 32 格分档冻结）；
#   - bind_parts / rebuild_parts：由「实体 + 逐格归属」推导区域与核心；
#   - frozen_core_cells / parts_binding_errors：主链冻结与最终自洽检查。
# 补丁策略与修订上下文在 design_contract.py（本模块只依赖它的常量与格子工具）。
# ============================================================
from .design_contract import PART_KEYS, _cell3, model_dims, solid_cells_of


def parse_part_labels(labels, parts_norm, model):
    """校验画稿的部位标注，并展开成逐格归属。

    返回 (errors, assignment|None, warnings)。assignment 覆盖全部实体格：
    partPatches 显式指定的格子取该部位，其余实体归 defaultPart。

    结构性错误（labels 不是对象、缺 defaultPart、未知部位 id、一格两属）按协议错误处理；
    单个格子的坐标问题（标到空格、标出网格、坐标格式非法）只记警告并忽略该格——
    画稿不整稿打回，必需部位因此缺实体时由只标注阶段补齐。
    """
    if not isinstance(labels, dict):
        return ["部位标注必须是对象（defaultPart + partPatches）"], None, []
    ids = [p["id"] for p in parts_norm]
    default_part = str(labels.get("defaultPart") or "").strip()
    if not default_part:
        return ["缺少 defaultPart：没标到的实体都归它，必须是规划里已有的部位 id"], None, []
    if default_part not in ids:
        return [f"defaultPart「{default_part}」不是规划里的部位（已有：{'、'.join(ids)}）"], None, []
    patches = labels.get("partPatches")
    if patches is None:
        patches = []
    if not isinstance(patches, list):
        return ["partPatches 必须是列表"], None, []
    solid = solid_cells_of(model)
    grid_w, grid_d, n_layers = model_dims(model)
    errs, warns, owner = [], [], {}
    for pi, p in enumerate(patches):
        if not isinstance(p, dict):
            errs.append(f"partPatches[{pi}] 必须是对象")
            continue
        pid = str(p.get("id") or "").strip()
        if not pid:
            errs.append(f"partPatches[{pi}] 缺少 id")
            continue
        if pid not in ids:
            errs.append(f"partPatches[{pi}] 的部位 {pid!r} 不在规划里（不能新增部位；"
                        f"可用 id：{'、'.join(ids)}；多个部位要分开标，不能合并成组名）")
            continue
        cells = p.get("cells")
        if not isinstance(cells, list):
            errs.append(f"partPatches[{pi}]（{pid}）的 cells 必须是列表")
            continue
        for ci, raw in enumerate(cells):
            cell = _cell3(raw)
            if cell is None:
                warns.append(f"partPatches[{pi}]（{pid}）cells[{ci}] 不是三个整数 [x,y,z]：{raw!r}，已忽略该格")
                continue
            x, y, z = cell
            if not (0 <= x < grid_w and 0 <= z < grid_d and 0 <= y < n_layers):
                warns.append(f"partPatches[{pi}]（{pid}）标出网格 (x={x},y={y},z={z})"
                             f"（网格 {grid_w}×{grid_d}×{n_layers} 层），已忽略该格")
                continue
            if cell not in solid:
                warns.append(f"partPatches[{pi}]（{pid}）标到空格 (x={x},y={y},z={z})，"
                             f"该格不是实体，已忽略")
                continue
            if cell in owner and owner[cell] != pid:
                errs.append(f"格子 (x={x},y={y},z={z}) 同时被标给 {owner[cell]} 与 {pid}"
                            f"（一格只能属于一个部位）")
                continue
            owner[cell] = pid
    if errs:
        return errs, None, warns
    assign = {c: default_part for c in solid}
    assign.update(owner)
    return [], assign, warns


# ---------------- 区域（存档用矩形覆盖） ----------------

def _layer_rects(plane):
    """把一层 {(x,z)} 贪心拆成轴对齐矩形 [(x1,x2,z1,z2)]：从最小坐标往 x、z 扩展。"""
    rem = set(plane)
    rects = []
    while rem:
        x0, z0 = min(rem)
        x1 = x0
        while (x1 + 1, z0) in rem:
            x1 += 1
        z1 = z0
        while all((xx, z1 + 1) in rem for xx in range(x0, x1 + 1)):
            z1 += 1
        rem -= {(xx, zz) for xx in range(x0, x1 + 1) for zz in range(z0, z1 + 1)}
        rects.append((x0, x1, z0, z1))
    return rects


def region_boxes(cells):
    """把某部位的实体格子写成内部 boxes（存档/追溯用，不是模型的输出格式）。

    按层贪心矩形覆盖；相邻层轮廓相同则合成一块。返回
    [{"x1","x2","z1","z2","y1","y2"}]（含端点）。
    """
    if not cells:
        return []
    by_y = {}
    for (x, y, z) in cells:
        by_y.setdefault(y, set()).add((x, z))
    per_layer = {y: _layer_rects(plane) for y, plane in by_y.items()}
    ys = sorted(per_layer)
    out, used = [], set()
    for y in ys:
        if y in used:
            continue
        rects = per_layer[y]
        y2 = y
        while (y2 + 1) in per_layer and per_layer[y2 + 1] == rects:
            y2 += 1
            used.add(y2)
        for (x0, x1, z0, z1) in rects:
            out.append({"x1": x0, "x2": x1, "z1": z0, "z2": z1, "y1": y, "y2": y2})
    return out


# ---------------- 防删核心（程序生成，统一规则） ----------------

CONNECT_CORE_LIMIT = 8   # 每个必需部位的核心格数上限（工程参数，需验收校准）


def _part_center(cells):
    """部位包围盒中心（浮点，用于选「靠近中心」的核心格）。"""
    xs = [c[0] for c in cells]
    ys = [c[1] for c in cells]
    zs = [c[2] for c in cells]
    return ((min(xs) + max(xs)) / 2.0, (min(ys) + max(ys)) / 2.0, (min(zs) + max(zs)) / 2.0)


def _connected_cells(cells, all_solid):
    """部位中与「部位外实体」6-连通相邻的连接格：部位挂在主体上的位置。"""
    out = set()
    for (x, y, z) in cells:
        for nb in ((x + 1, y, z), (x - 1, y, z), (x, y + 1, z), (x, y - 1, z),
                   (x, y, z + 1), (x, y, z - 1)):
            if nb in all_solid and nb not in cells:
                out.add((x, y, z))
                break
    return out


def _core_size(n):
    """核心格数：最多 CONNECT_CORE_LIMIT 格，且不超过部位实体的 1/2（至少 1 格）。

    取消「部位实体 ≤32 格整块冻结」的分档：任何部位都只保护一小撮代表格，
    其余格留给修订去修支撑、覆盖与轮廓。
    """
    return min(CONNECT_CORE_LIMIT, max(1, n // 2))


def _pick_core(candidates, cells):
    """从候选格里取离包围盒中心最近的 _core_size 个（候选不足则全取）。"""
    want = _core_size(len(cells))
    cx, cy, cz = _part_center(cells)
    ordered = sorted(candidates, key=lambda c: (
        (c[0] - cx) ** 2 + (c[1] - cy) ** 2 + (c[2] - cz) ** 2, c))
    return set(ordered[:want])


def build_cores(required_cells, all_solid, frozen=None):
    """由程序生成全部必需部位的防删核心，返回 (errors, cores|None)。

    required_cells: [(part_id, 实体格集合)]（只含必需部位）
    all_solid: 全模型实体格（用于识别部位与主体/其它部位的连接格）
    frozen: 已冻结核心 {part_id: set}；非 None 时该部位核心保持不变（只校验还在实体上）。

    通用规则（不按部位大小分档）：核心优先取「与部位外实体相邻的连接格」——
    它证明部位还挂在主体上；再从候选里取离包围盒中心最近的
    min(8, max(1, 实体数 // 2)) 格；没有连接格（孤岛）时从全部实体里按同样方式取。
    不同必需部位的实体互不相交，核心天然不会相交；这里仍做一次防御性检查。
    """
    errs, cores = [], {}
    for pid, cells in required_cells:
        if not cells:
            errs.append(f"必需部位 {pid} 没有实体")
            continue
        if frozen is not None and pid in frozen:
            core = set(frozen[pid])
            lost = core - cells
            if lost:
                sample = "、".join(f"(x={x},y={y},z={z})" for x, y, z in sorted(lost)[:4])
                errs.append(f"部位 {pid} 的冻结核心有 {len(lost)} 格不再是实体：{sample}")
                continue
        else:
            candidates = _connected_cells(cells, all_solid) or set(cells)
            core = _pick_core(candidates, cells)
        if not core:
            errs.append(f"必需部位 {pid} 没有可冻结的核心格")
            continue
        cores[pid] = core
    if errs:
        return errs, None
    seen = {}
    for pid, core in cores.items():
        key = tuple(sorted(core))
        if key in seen:
            errs.append(f"必需部位 {seen[key]} 与 {pid} 的核心完全相同")
        seen[key] = pid
    if errs:
        return errs, None
    return [], cores


# ---------------- 绑定：由标注与实体生成区域和核心 ----------------

def rebuild_parts(parts_decl, assign, model, frozen=None):
    """按逐格归属重建各部位区域与核心（区域始终由「当前实体 + 标注」推导）。

    parts_decl: 部位语义声明（只读 id/name/required/source）
    assign: 逐格归属 {(x,y,z): part_id}（由标注或修订维护，只含实体格）
    frozen: 已冻结核心；非 None 时必需部位核心保持不变，否则按规则重算。
    返回 (errors, bound|None)。bound = {"parts": [...], "assign", "removed"}；
    每个 part 增加 cells / core_cells / boxes。必需部位没有实体 → 错误；
    可选部位没有实体 → 删除并记入 removed（不重画）。
    """
    ids = {p["id"] for p in parts_decl}
    by_part = {pid: set() for pid in ids}
    for cell, pid in assign.items():
        if pid in by_part:
            by_part[pid].add(cell)
    missing = [p["id"] for p in parts_decl if p["required"] and not by_part[p["id"]]]
    if missing:
        return [f"必需部位在画稿里没有实体：{'、'.join(missing)}"
                f"——用 partPatches 把属于它们的实体格标出来"], None
    required_cells = [(p["id"], by_part[p["id"]]) for p in parts_decl if p["required"]]
    errs, cores = build_cores(required_cells, solid_cells_of(model), frozen=frozen)
    if errs:
        return errs, None
    removed, out = [], []
    for p in parts_decl:
        cells = by_part[p["id"]]
        if not cells:
            if p["required"]:
                errs.append(f"必需部位 {p['id']} 没有实体")
                continue
            removed.append(p["id"])
            continue
        out.append({**{k: p.get(k, "solid" if k == "role" else None) for k in PART_KEYS},
                    "cells": cells,
                    "core_cells": cores.get(p["id"], set()),
                    "boxes": region_boxes(cells)})
    if errs:
        return errs, None
    return [], {"parts": out, "assign": dict(assign), "removed": removed}


def bind_parts(parts_decl, labels, model, frozen=None):
    """接受画稿：校验标注 → 由实体算出各部位区域与核心。

    返回 (errors, bound|None, warnings)。结构性错误（未知部位、一格两属等）属于协议错误；
    单个格子的无效标注（标到空格/标出网格）只记警告并忽略，画稿保留、不整稿打回；
    必需部位因此没有实体时返回错误，由主链进入只标注阶段（不重画）。
    """
    errs, assign, warns = parse_part_labels(labels, parts_decl, model)
    if errs:
        return errs, None, warns
    berrs, bound = rebuild_parts(parts_decl, assign, model, frozen=frozen)
    return berrs, bound, warns


def frozen_core_cells(parts_norm):
    """全部必需部位的核心格子并集（冻结后不可被补丁改动）。"""
    out = set()
    for p in parts_norm:
        if p["required"]:
            out |= p.get("core_cells") or set()
    return out


def parts_binding_errors(parts_norm, model):
    """最终阶段的绑定自洽检查：实体与部位格子一一对应，必需部位有实体且核心仍在实体内。"""
    solid = solid_cells_of(model)
    covered, errs = set(), []
    for p in parts_norm:
        cells = p.get("cells") or set()
        if not cells:
            if p["required"]:
                errs.append(f"必需部位 {p['id']} 没有实体")
            continue
        lost = cells - solid
        if lost:
            errs.append(f"部位 {p['id']} 有 {len(lost)} 格不再是实体")
        if p["required"] and not (p.get("core_cells") or set()):
            errs.append(f"必需部位 {p['id']} 的防删核心为空")
        core_lost = (p.get("core_cells") or set()) - cells
        if core_lost:
            errs.append(f"部位 {p['id']} 有 {len(core_lost)} 个核心格跑出了部位区域")
        covered |= cells
    extra = solid - covered
    if extra:
        errs.append(f"有 {len(extra)} 个实体格没有部位归属")
    return errs
