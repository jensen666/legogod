# ============================================================
# 顶部悬吊物理校核与预拼子组件提取
#
# 核心定义：
#   - 接地零件（grounded）：存在自 y=0 沿下层凸点支撑（parents）一路向上的纯承托路径；
#   - 吊挂核心砖（hanging）：无纯自下而上承托路径，依靠上方跨接大砖压住其顶凸点连入主干；
#   - 预拼子组件（subassembly）：将吊挂核心砖簇 H 与直接从上方锁住它的接地跨接砖集 A
#     合并为一个桌面可独立预拼的完整组件 S_sub = H ∪ A（若多簇共享同一跨接砖则自然合并）。
#     如此先在桌面将 H 与 A 拼成刚性整体，待主结构中 A 的下方承托就位时从上方竖直一次扣入，
#     彻底消除「单块悬空砖凭空浮在半空等上层砖」的反物理装配顺序。
# ============================================================
import math

from .geometry import stud_cells
from .parts_library import PART_MAP

F_CLUTCH_N = 5.0        # 单凸点抗拔离合力保守实测值（N）
MASS_PER_VOXEL_G = 0.6  # 满实心单体素名义质量（g）
SAFETY_FACTOR = 2.0     # 抗倾覆静力安全系数
G_MS2 = 9.80665         # 重力加速度（m/s²）
STUD_PITCH_MM = 8.0     # 标准凸点中心距（mm），将格坐标力臂换算为物理毫米

MIN_LOCK_STUDS = 2      # 刚体水平面消旋充要下界：至少 2 个不重合锁扣凸点


def brick_mass_g(part):
    """计算单块零件物理质量（g），楔形斜坡按 massFactor 折减。"""
    factor = part.get("massFactor", 1.0)
    return part["w"] * part["d"] * factor * MASS_PER_VOXEL_G


def find_hanging_clusters(parts, adj):
    """识别全部吊挂簇并合并上方锁扣跨接砖，生成完整预拼子组件列表。

    返回 (clusters, grounded)：
      cluster = {
          "hanging": [无下层直托的吊挂砖索引],
          "anchors": [上方直接锁住 hanging 的接地跨接砖索引],
          "bricks":  sorted(hanging ∪ anchors)   # 完整桌面预拼子组件（至少含悬吊砖+跨接砖）
      }
    """
    n = len(parts)
    grounded = [False] * n
    stack = [i for i in range(n) if parts[i]["layer"] == 0]
    for i in stack:
        grounded[i] = True
    while stack:
        cur = stack.pop()
        for nb in adj[cur]:
            if not grounded[nb] and cur in parts[nb]["parents"]:
                grounded[nb] = True
                stack.append(nb)

    raw_clusters = []
    visited = set()
    for i in range(n):
        if grounded[i] or i in visited:
            continue
        hang_set = set()
        q = [i]
        visited.add(i)
        while q:
            cur = q.pop()
            hang_set.add(cur)
            for nb in adj[cur]:
                if not grounded[nb] and nb not in visited:
                    visited.add(nb)
                    q.append(nb)
        anchors = {
            nb for h in hang_set for nb in adj[h]
            if grounded[nb] and parts[nb]["layer"] > parts[h]["layer"]
        }
        raw_clusters.append((hang_set, anchors))

    # 若两个吊挂簇共用同一块上方跨接锁扣砖，则在桌面必须作为同一个预拼子组件拼装
    merged = []
    for hang_set, anchors in raw_clusters:
        h_union, a_union = set(hang_set), set(anchors)
        kept = []
        for mh, ma in merged:
            if (ma & a_union) or any(nb in mh for h in h_union for nb in adj[h]):
                h_union |= mh
                a_union |= ma
            else:
                kept.append((mh, ma))
        kept.append((h_union, a_union))
        merged = kept

    clusters = []
    for h_union, a_union in merged:
        clusters.append({
            "hanging": sorted(h_union),
            "anchors": sorted(a_union),
            "bricks": sorted(h_union | a_union),
        })
    return clusters, grounded


def lock_cells(hanging_bricks, parts, adj):
    """已经算出的锁扣凸点，收成 (x, y, z)。

    y 是发出凸点的吊挂砖自己的层，不是父砖层，也不另猜一格。
    没有锁扣时返回空集。
    """
    hang_set = set(hanging_bricks)
    engaged = set()
    for bi in hanging_bricks:
        b = parts[bi]
        p_cells = set()
        for nb in adj[bi]:
            if nb in hang_set or parts[nb]["layer"] != b["layer"] + 1:
                continue
            p_cells.update(parts[nb]["cells"])
        if not p_cells:
            continue
        part = PART_MAP[b["piece"]]
        y = b["layer"]
        for (cx, cz) in stud_cells(part, b["x"], b["z"], b["rot"]):
            if (cx, cz) in p_cells:
                engaged.add((int(cx), int(y), int(cz)))
    return engaged


def engagement_cells(hanging_bricks, parts, adj):
    """锁扣凸点的平面位置 {(x, z)}。物理校核仍用这个二维集合。"""
    return {(x, z) for (x, _y, z) in lock_cells(hanging_bricks, parts, adj)}


def subassembly_cells(cluster, parts):
    """吊挂砖自己的体素 (x, y, z)。只搬零件上已有的格子和层号。"""
    hang = cluster.get("hanging") or cluster["bricks"]
    out = []
    seen = set()
    for bi in hang:
        b = parts[bi]
        y = b["layer"]
        for cell in b.get("cells") or []:
            if not isinstance(cell, (list, tuple)) or len(cell) < 2:
                continue
            item = (int(cell[0]), int(y), int(cell[1]))
            if item not in seen:
                seen.add(item)
                out.append(item)
    return out


def _closest_point_on_hull_edge(pt, hull):
    """求平面点 pt 到凸多边形 hull 边界的最近点；若 pt 在 hull 内部或边界上则返回 None。"""
    x, z = pt
    n = len(hull)
    inside = True
    for i in range(n):
        x1, z1 = hull[i]
        x2, z2 = hull[(i + 1) % n]
        cross = (x2 - x1) * (z - z1) - (z2 - z1) * (x - x1)
        if cross < -1e-9:
            inside = False
            break
    if inside:
        return None
    best_pt = None
    best_d2 = float("inf")
    for i in range(n):
        x1, z1 = hull[i]
        x2, z2 = hull[(i + 1) % n]
        vx, vz = x2 - x1, z2 - z1
        l2 = vx * vx + vz * vz
        t = 0.0 if l2 <= 1e-12 else max(0.0, min(1.0, ((x - x1) * vx + (z - z1) * vz) / l2))
        px, pz = x1 + t * vx, z1 + t * vz
        d2 = (x - px) ** 2 + (z - pz) ** 2
        if d2 < best_d2:
            best_d2 = d2
            best_pt = (px, pz)
    return best_pt


def _convex_hull_2d(points):
    """计算二维点集逆时针凸包。"""
    pts = sorted(set(points))
    if len(pts) <= 2:
        return pts

    def cross(o, a, b):
        return (a[0] - o[0]) * (b[1] - o[1]) - (a[1] - o[1]) * (b[0] - o[0])

    lower, upper = [], []
    for p in pts:
        while len(lower) >= 2 and cross(lower[-2], lower[-1], p) <= 0:
            lower.pop()
        lower.append(p)
    for p in reversed(pts):
        while len(upper) >= 2 and cross(upper[-2], upper[-1], p) <= 0:
            upper.pop()
        upper.append(p)
    return lower[:-1] + upper[:-1]


def check_cluster(cluster, parts, adj):
    """对单个吊挂簇执行 ① 双凸点消旋下界 + ② 绕咬合面外边缘棱线的抗倾覆静力平衡校核。"""
    errors = []
    hang_bricks = cluster.get("hanging") or cluster["bricks"]
    engaged = engagement_cells(hang_bricks, parts, adj)
    if len(engaged) < MIN_LOCK_STUDS:
        errors.append(
            f"吊挂子组件只有 {len(engaged)} 个锁扣凸点（物理下界 {MIN_LOCK_STUDS} 个："
            f"单个凸点存在水平旋转自由度，必须至少 2 个不共点凸点才能消旋固定）")
        return errors

    total_mass = 0.0
    com_x = com_z = 0.0
    for bi in hang_bricks:
        b = parts[bi]
        m = brick_mass_g(PART_MAP[b["piece"]])
        cx = sum(c[0] for c in b["cells"]) / len(b["cells"]) + 0.5
        cz = sum(c[1] for c in b["cells"]) / len(b["cells"]) + 0.5
        total_mass += m
        com_x += m * cx
        com_z += m * cz
    com_x /= total_mass
    com_z /= total_mass

    # 咬合接触面由每个锁扣单元 [x, x+1] × [z, z+1] 的四角构成凸包：
    # 质心落在接触凸包内时无外翻悬挑力矩；超出外侧时绕最近外边缘棱线（fulcrum）计算力矩平衡。
    corners = [(cx + dx, cz + dz) for (cx, cz) in engaged for dx in (0.0, 1.0) for dz in (0.0, 1.0)]
    hull = _convex_hull_2d(corners)
    fulcrum = _closest_point_on_hull_edge((com_x, com_z), hull)
    if fulcrum is None:
        return errors
    dx, dz = com_x - fulcrum[0], com_z - fulcrum[1]
    d_overhang_studs = math.hypot(dx, dz)
    if d_overhang_studs <= 1e-9:
        return errors
    ux, uz = dx / d_overhang_studs, dz / d_overhang_studs
    resist_n_mm = 0.0
    for (cx, cz) in sorted(engaged):
        sx, sz = cx + 0.5, cz + 0.5
        arm_studs = (fulcrum[0] - sx) * ux + (fulcrum[1] - sz) * uz
        if arm_studs > 0:
            resist_n_mm += F_CLUTCH_N * (arm_studs * STUD_PITCH_MM)
    tipping_n_mm = total_mass * 1e-3 * G_MS2 * (d_overhang_studs * STUD_PITCH_MM)
    limit_n_mm = resist_n_mm / SAFETY_FACTOR
    if tipping_n_mm > limit_n_mm:
        errors.append(
            f"吊挂子组件偏心倾覆力矩 {tipping_n_mm:.3f} N·mm 超过锁扣抗拔稳定力矩 "
            f"{limit_n_mm:.3f} N·mm（静力平衡 W·d ≤ ΣF·d/SF，SF={SAFETY_FACTOR}）"
            f"——请加宽上方跨接咬合面或增设底部托架")
    return errors


def check_all(parts, adj):
    """对全部吊挂簇执行物理校核，返回 (clusters, errors)。

    每个 cluster 额外记录校验已经算出的真实坐标（工作包 B，供修订使用）：
      lockCells        锁扣凸点 (x, y, z)，y 是发出凸点的吊挂砖自己的层；
      subassemblyCells 吊挂砖自己的体素 (x, y, z)。
    没有坐标就不写空列表以外的内容，不编造位置。
    """
    clusters, _grounded = find_hanging_clusters(parts, adj)
    errors = []
    for k, cluster in enumerate(clusters):
        hang = cluster.get("hanging") or cluster["bricks"]
        sample = parts[hang[0]]
        cluster_errors = check_cluster(cluster, parts, adj)
        locks = lock_cells(hang, parts, adj)
        cluster["lockCells"] = sorted(locks)
        cluster["subassemblyCells"] = subassembly_cells(cluster, parts)
        if cluster_errors:
            # 有锁扣就记锁扣；一个锁扣都没有时才退到吊挂砖自己的体素。没有就留空。
            cluster["failureCells"] = sorted(locks) if locks else cluster["subassemblyCells"]
        for e in cluster_errors:
            errors.append(f"（预拼子组件 {k + 1}，y={sample['layer']} 层附近）{e}")
    return clusters, errors


def topological_part_order(parts, clusters):
    """将预拼子组件缩为超节点执行拓扑排序（兼顾下方承托就位与上方插入无卡口），返回 (order, ordered_clusters)。"""
    import heapq
    key_fn = lambda i: (parts[i]["layer"], parts[i]["z"], parts[i]["x"], parts[i]["piece"])
    if not clusters:
        return sorted(range(len(parts)), key=key_fn), []

    unit_of = {}
    units = []
    for ci, c in enumerate(clusters):
        seq = sorted(c["bricks"], key=key_fn)
        uid = len(units)
        units.append({"bricks": seq, "cluster": c, "is_sub": True,
                      "sort_key": (min(parts[b]["layer"] for b in (c["anchors"] or seq)),
                                   min(parts[b]["z"] for b in seq),
                                   min(parts[b]["x"] for b in seq), uid)})
        for b in seq:
            unit_of[b] = uid
    for i in range(len(parts)):
        if i not in unit_of:
            uid = len(units)
            units.append({"bricks": [i], "cluster": None, "is_sub": False,
                          "sort_key": (parts[i]["layer"], parts[i]["z"], parts[i]["x"], uid)})
            unit_of[i] = uid

    n_u = len(units)
    out_edges = [set() for _ in range(n_u)]
    indeg = [0] * n_u

    def add_edge(u, v):
        if u != v and v not in out_edges[u]:
            out_edges[u].add(v)
            indeg[v] += 1

    # 1) 支撑依赖：子件依赖其外部下方父件先就位
    for uid, u in enumerate(units):
        bset = set(u["bricks"])
        check_bricks = (u["cluster"]["anchors"] or u["bricks"]) if u["is_sub"] else u["bricks"]
        for b in check_bricks:
            for par in parts[b]["parents"]:
                if par not in bset:
                    add_edge(unit_of[par], uid)

    # 2) 防卡口依赖：预拼子组件必须在位于其体素正上方的任何外部零件之前扣入
    col_map = {}
    for i, po in enumerate(parts):
        for (cx, cz) in po["cells"]:
            col_map.setdefault((cx, cz), []).append((po["layer"], i))
    for uid, u in enumerate(units):
        if not u["is_sub"]:
            continue
        bset = set(u["bricks"])
        for b in u["bricks"]:
            by = parts[b]["layer"]
            for (cx, cz) in parts[b]["cells"]:
                for oy, oi in col_map.get((cx, cz), ()):
                    if oy > by and oi not in bset:
                        add_edge(uid, unit_of[oi])

    heap = [(units[u]["sort_key"], u) for u in range(n_u) if indeg[u] == 0]
    heapq.heapify(heap)
    placed_units = []
    done = set()
    while len(done) < n_u:
        if not heap:
            # 存在物理卡口环时按层序兜底输出剩余节点，交由 validate_solution 报告精确卡口原因
            rem = min((u for u in range(n_u) if u not in done), key=lambda u: units[u]["sort_key"])
            heapq.heappush(heap, (units[rem]["sort_key"], rem))
        _k, u = heapq.heappop(heap)
        if u in done:
            continue
        done.add(u)
        placed_units.append(u)
        for v in out_edges[u]:
            indeg[v] -= 1
            if indeg[v] <= 0 and v not in done:
                heapq.heappush(heap, (units[v]["sort_key"], v))

    order = [b for u in placed_units for b in units[u]["bricks"]]
    ordered_clusters = [units[u]["cluster"] for u in placed_units if units[u]["is_sub"]]
    return order, ordered_clusters
