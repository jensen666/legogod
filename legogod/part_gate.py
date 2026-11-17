# ============================================================
# 双角色部位突显门禁
#
# 在初次部位绑定后、进入评审与求解前，按部位声明的角色拦截「伪部位」：
#   - 立体结构部位（role=solid）：拦截单格突起、局部表面贴花及无阶跃整面墙皮贴花；
#   - 表面涂装部位（role=surface）：限制体积占比，要求 100% 外露且与同层邻格异色。
# ============================================================
from .geometry import ALL_SLOPE_CHARS
from .parts_library import voxel_color_map

MIN_SOLID_VOLUME = 2        # 立体部位最小体量（防单格突起套利）
SURFACE_VOLUME_CAP = 0.08   # 表面涂装部位占全模体素上限
SHEET_LONG = 4              # 薄壁判据：长轴跨度下界
SHEET_THIN = 2              # 薄壁判据：厚度轴跨度上界
SHEET_FREE_RATIO = 0.5      # 薄壁判据：未贴靠其它部位的自由体素占比下界（排除整面墙皮贴花）

_NEIGHBORS6 = ((1, 0, 0), (-1, 0, 0), (0, 1, 0), (0, -1, 0), (0, 0, 1), (0, 0, -1))
_NEIGHBORS4 = ((1, 0), (-1, 0), (0, 1), (0, -1))


def _solid_with_chars(model):
    """提取模型全部非空体素及其字符 {(x,y,z): ch}。"""
    out = {}
    for L in model.get("layers") or []:
        y = L["y"]
        for z, row in enumerate(L.get("rows") or []):
            for x, ch in enumerate(row):
                if ch != ".":
                    out[(x, y, z)] = ch
    return out


def _cell_colors(model):
    """提取模型逐体素颜色映射 {(x,y,z): 颜色中文名}。"""
    out = {}
    for L in model.get("layers") or []:
        cmap = voxel_color_map(L.get("rows") or [], L.get("colorRows"), L.get("color"))
        for (x, z), name in (cmap or {}).items():
            if name:
                out[(x, L["y"], z)] = name
    return out


def _faces_split(cells, all_solid):
    """计算部位内每格的 (暴露空气面数, 贴合其它部位实体面数)。"""
    own = set(cells)
    out = {}
    for c in cells:
        air = contact = 0
        for dx, dy, dz in _NEIGHBORS6:
            nb = (c[0] + dx, c[1] + dy, c[2] + dz)
            if nb not in all_solid:
                air += 1
            elif nb not in own:
                contact += 1
        out[c] = (air, contact)
    return out


def _is_flush_skin_slab(cells, rest_solid):
    """判断部位是否只是紧贴在同截面实心块侧面的 1 格厚无阶跃平齐墙皮（整面贴花）。

    若部位存在离开接触面延伸的第 2 格（contact(c)==0），则非 1 格厚墙皮；
    若全部体素均紧贴 rest_solid，检查其统一接触法向背后的宿主体截面是否与自身完全平齐重合。
    """
    if not rest_solid:
        return False
    normals = set()
    backing = set()
    for (x, y, z) in cells:
        local_nbs = []
        for dx, dy, dz in _NEIGHBORS6:
            nb = (x + dx, y + dy, z + dz)
            if nb in rest_solid:
                local_nbs.append((dx, dy, dz, nb))
        if not local_nbs:
            return False  # 存在脱离接触面 ≥2 格的真实外伸体素
        for dx, dy, dz, nb in local_nbs:
            normals.add((dx, dy, dz))
            backing.add(nb)
    if len(normals) != 1:
        return False
    dx, dy, dz = next(iter(normals))
    # 沿法向切片：宿主在 nb 所在平面上的完整连通截面是否恰好等于 backing（无凸台轮廓阶跃）
    host_slice = set(backing)
    stack = list(backing)
    while stack:
        bx, by, bz = stack.pop()
        for tx, ty, tz in _NEIGHBORS6:
            if (tx, ty, tz) in ((dx, dy, dz), (-dx, -dy, -dz)):
                continue
            cand = (bx + tx, by + ty, bz + tz)
            if cand in rest_solid and cand not in host_slice:
                host_slice.add(cand)
                stack.append(cand)
    return len(host_slice) == len(cells)


def _is_one_thick_flush(cells, rest_solid):
    """1 格厚、贴在主接触面上、投影没有超出宿主。外侧再贴一个小块也不改变这个结论。"""
    if _is_flush_skin_slab(cells, rest_solid):
        return True
    if not rest_solid:
        return False
    own = set(cells)
    groups = {}
    for x, y, z in own:
        for dx, dy, dz in _NEIGHBORS6:
            if (x + dx, y + dy, z + dz) in rest_solid:
                groups.setdefault((dx, dy, dz), []).append((x, y, z))
    if not groups:
        return False
    normal, touched = max(groups.items(), key=lambda kv: len(kv[1]))
    if len(touched) != len(own) or _thickness_along(own, normal, touched) != 1:
        return False
    axis = 0 if normal[0] else (1 if normal[1] else 2)
    return not (_project(own, axis) - _project(rest_solid, axis))


def _is_double_exposed_sheet(cells, all_solid):
    """最薄那一轴的两侧大面都露在空气里（厚度不超过 SHEET_THIN）。贴在宿主上的单侧墙皮不算。

    只看最薄轴。更厚的轴两端露空（比如贴花没有铺满墙高）不能当成薄壁。
    厚度正好是 1 时，同一格同时是两侧表面，两侧邻居都要是空气。
    """
    own = set(cells)
    spans = []
    for axis in range(3):
        vals = [c[axis] for c in own]
        spans.append(max(vals) - min(vals) + 1)
    thin = min(spans)
    if thin > SHEET_THIN:
        return False
    for axis, span in enumerate(spans):
        if span != thin:
            continue
        lo = min(c[axis] for c in own)
        hi = max(c[axis] for c in own)
        exposed = True
        for c in own:
            if c[axis] not in (lo, hi):
                continue
            directions = []
            if c[axis] == lo:
                directions.append(lo - 1)
            if c[axis] == hi:
                directions.append(hi + 1)
            for outward in directions:
                nb = list(c)
                nb[axis] = outward
                if tuple(nb) in all_solid:
                    exposed = False
                    break
            if not exposed:
                break
        if exposed:
            return True
    return False


def _plane_has_gap(points):
    """二维截面里，同一行或同一列的占格之间有空洞（门洞、拱洞、封闭空腔的切片）。"""
    if len(points) < 4:
        return False
    by_b = {}
    for a, b in points:
        by_b.setdefault(b, []).append(a)
    for arr in by_b.values():
        arr.sort()
        if arr[-1] - arr[0] + 1 > len(arr):
            return True
    by_a = {}
    for a, b in points:
        by_a.setdefault(a, []).append(b)
    for arr in by_a.values():
        arr.sort()
        if arr[-1] - arr[0] + 1 > len(arr):
            return True
    return False


def _has_opening(cells):
    """部位沿任一轴的切片出现贯通空洞。实心小块返回 False。"""
    for fixed in range(3):
        groups = {}
        for c in cells:
            groups.setdefault(c[fixed], set()).add(tuple(c[i] for i in range(3) if i != fixed))
        for plane in groups.values():
            if _plane_has_gap(plane):
                return True
    return False


def _project(cells, axis):
    idx = [i for i in range(3) if i != axis]
    return {(c[idx[0]], c[idx[1]]) for c in cells}


def _thickness_along(own, normal, touched):
    """沿接触法向的反方向，本部位自己有多厚。"""
    dx, dy, dz = normal
    thick = 1
    for x, y, z in touched:
        depth, cx, cy, cz = 1, x - dx, y - dy, z - dz
        while (cx, cy, cz) in own:
            depth += 1
            cx, cy, cz = cx - dx, cy - dy, cz - dz
        thick = max(thick, depth)
    return thick


def _is_structural_host(cells, parts_norm, pid):
    """有别的部位贴在身上，且主接触方向厚度至少为 2，或轮廓超出主贴合体并另有子件。

    阶跃只认本部位投影超出接触格最多的那一份贴合体，不认「足迹不同」。
    否则小贴花会因为比墙小而被放行。
    """
    own = set(cells)
    others = []
    for p in parts_norm or []:
        if p.get("id") == pid:
            continue
        oc = set(p.get("cells") or ())
        if oc:
            others.append((p.get("id"), oc))
    if not others:
        return False
    groups = {}
    for x, y, z in own:
        for dx, dy, dz in _NEIGHBORS6:
            nb = (x + dx, y + dy, z + dz)
            for oid, oc in others:
                if nb in oc:
                    groups.setdefault(((dx, dy, dz), oid), []).append((x, y, z))
    if not groups:
        return False
    (normal, oid), touched = max(groups.items(), key=lambda kv: len(kv[1]))
    if _thickness_along(own, normal, touched) >= 2:
        return True
    main_cells = dict(others)[oid]
    axis = 0 if normal[0] else (1 if normal[1] else 2)
    if not (_project(own, axis) - _project(main_cells, axis)):
        return False
    return any(other_id != oid for (_normal, other_id) in groups)


def _low_air_passes(pid, cells, all_solid, parts_norm):
    """空气面不多于贴合面时，按方案顺序看能否直接通过。不能通过则交给原判据。"""
    if any(all_solid.get(c) in ALL_SLOPE_CHARS for c in cells):
        return True
    if _is_double_exposed_sheet(cells, all_solid):
        return True
    if _is_structural_host(cells, parts_norm, pid):
        return True
    if _has_opening(cells):
        return True
    return False


def _has_cycle(cells_xz):
    """判断同层二维格集是否构成包含中空内腔或闭合周界的截面环（边数 ≥ 点数）。"""
    nodes = set(cells_xz)
    if len(nodes) < 4:
        return False
    edges = 0
    for (x, z) in nodes:
        for dx, dz in _NEIGHBORS4:
            if (x + dx, z + dz) in nodes and (x + dx, z + dz) > (x, z):
                edges += 1
    return edges >= len(nodes)


def _flush_reject(pid, air, contact):
    """平齐贴花的拒收说明。墙皮与其余小体面共用这一句。"""
    return [
        f"立体部位「{pid}」不满足任何几何独立判据（空气面 {air} vs 贴合面 {contact}，"
        f"属于实心块侧面局部抠格或无阶跃墙皮贴花）——即使换了颜色也不免检几何："
        f"请将其画成真实脱离主体轮廓凸出、串联截面阶跃或独立薄壁/斜面的结构；"
        f"若只是平齐、无阶跃、没有子件的小体面，改为 role=\"surface\" 或用 paint 涂在宿主上"
    ]


def _solid_part_errors(pid, cells, all_solid, model, parts_norm=None):
    """校验立体结构部位（role=solid）是否具备真实几何独立性。"""
    if len(cells) < MIN_SOLID_VOLUME:
        return [
            f"立体部位「{pid}」只有 {len(cells)} 格（最小体量 {MIN_SOLID_VOLUME}）："
            f"单格突起属于伪部位——若是眼睛/鼻尖/徽章/车灯这类平面细节，请声明 role=\"surface\"；"
            f"若是立体部件，请画成体积 ≥{MIN_SOLID_VOLUME} 且真实凸出的结构"
        ]
    rest_solid = set(all_solid) - set(cells)
    faces = _faces_split(cells, all_solid)
    air = sum(a for a, _c in faces.values())
    contact = sum(c for _a, c in faces.values())

    # ① 向外伸出型：空气面 > 贴合面，且排除 1 格厚、没有超出宿主的墙皮贴花
    if air > contact and not _is_one_thick_flush(cells, rest_solid):
        return []
    # 空气面不多于贴合面时先放行，再拒绝墙皮。斜面、双面薄壁、宿主、洞口，
    # 以及下面的占满整层楼层，都排在墙皮拒绝之前，避免收分楼层被提前拒掉。
    if air <= contact and _low_air_passes(pid, cells, all_solid, parts_norm):
        return []

    # ② 上下串联承载型（塔身/楼层墙环/腰线）：占满所在层全截面（同层无其它立体部位并列切块）
    # 且存在跨层轮廓阶跃或独立配色分段。必须先于墙皮拒绝。
    by_y = {}
    for (x, y, z) in cells:
        by_y.setdefault(y, set()).add((x, z))
    full_ring_layers = [
        y for y, plane in by_y.items()
        if _has_cycle(plane) and not any(ry == y for (_rx, ry, _rz) in rest_solid)
    ]
    if full_ring_layers:
        all_by_y = {}
        for (x, y, z) in all_solid:
            all_by_y.setdefault(y, set()).add((x, z))
        ys = sorted(all_by_y)
        step = any(all_by_y[ys[i]] != all_by_y[ys[i - 1]] for i in range(1, len(ys)))
        colors = _cell_colors(model)
        own_colors = {colors.get(c) for c in cells if colors.get(c)}
        if step or own_colors:
            return []

    # ③ 薄壁/斜面型（风帆/垛口/薄翼）：含斜面格，或呈双侧露空薄片（排除单侧全贴死墙皮）
    if any(all_solid[c] in ALL_SLOPE_CHARS for c in cells):
        return []
    free_cells = sum(1 for _c, (_a, ct) in faces.items() if ct == 0)
    if (not rest_solid) or (free_cells / max(1, len(cells)) >= SHEET_FREE_RATIO):
        for _y, plane in by_y.items():
            xs = [p[0] for p in plane]
            zs = [p[1] for p in plane]
            w, d = max(xs) - min(xs) + 1, max(zs) - min(zs) + 1
            if (w >= SHEET_LONG and d <= SHEET_THIN) or (d >= SHEET_LONG and w <= SHEET_THIN):
                return []

    return _flush_reject(pid, air, contact)


def _surface_part_errors(pid, cells, all_solid, model, total_voxels):
    """校验表面涂装部位（role=surface）：体积受限、全外露、与邻格异色。"""
    errs = []
    if len(cells) > max(1, int(total_voxels * SURFACE_VOLUME_CAP)):
        errs.append(f"表面涂装部位「{pid}」占全模体积 {len(cells)}/{total_voxels}，"
                    f"超过上限 {SURFACE_VOLUME_CAP:.0%}——大面积区域应声明为立体部位")
    faces = _faces_split(cells, all_solid)
    buried = [c for c, (air, _ct) in faces.items() if air == 0]
    if buried:
        sample = "、".join(f"(x={x},y={y},z={z})" for x, y, z in sorted(buried)[:4])
        errs.append(f"表面涂装部位「{pid}」有 {len(buried)} 格完全内埋（{sample}）"
                    f"——表面细节必须全部暴露在外表面，严禁内埋充数；"
                    f"若它实际是整体材质/主色/大面积涂装分区，请并入宿主立体部位的颜色"
                    f"（给几何算子写 color 或用 paint 涂宿主表面），不要声明成独立表面部位")
    colors = _cell_colors(model)
    if not colors:
        errs.append(f"表面涂装部位「{pid}」要求显式配色，当前设计没有颜色信息")
        return errs
    own = set(cells)
    mono = []
    for c in cells:
        col = colors.get(c)
        if not col:
            mono.append(c)
            continue
        for dx, dz in _NEIGHBORS4:
            nb = (c[0] + dx, c[1], c[2] + dz)
            if nb in all_solid and nb not in own and colors.get(nb) == col:
                mono.append(c)
                break
    if mono:
        sample = "、".join(f"(x={x},y={y},z={z})" for x, y, z in sorted(mono)[:4])
        errs.append(f"表面涂装部位「{pid}」有 {len(mono)} 格与同层相邻主体同色（{sample}）"
                    f"——涂装细节必须与周围主体异色才可辨识；"
                    f"需要可辨识的同色分界/缝线时，请用真实几何凹槽、台阶或与宿主异色的窄条，"
                    f"不要靠整片换色或内埋格凑过门禁")
    return errs


def check_parts(model, parts_norm):
    """执行双角色部位突显门禁校验，返回 (errors, error_cells)。"""
    errs, bad_cells = [], set()
    all_solid = _solid_with_chars(model)
    total = len(all_solid)
    for p in parts_norm or []:
        cells = set(p.get("cells") or set())
        if not cells:
            continue
        role = p.get("role") or "solid"
        if role == "surface":
            pes = _surface_part_errors(p["id"], cells, all_solid, model, total)
        else:
            pes = _solid_part_errors(p["id"], cells, all_solid, model, parts_norm)
        if pes:
            errs += pes
            bad_cells |= cells
    return errs, sorted(bad_cells)
