# ============================================================
# 几何契约单源
#
# 全仓唯一的「零件几何事实源」，下游（求解器 / 校验器 / 渲染 / 步骤文档）
# 一律从这里取事实，不再各自实现一遍：
#   - 体素字符语义：普通 '#'、正斜坡 '/' '\\' '^' 'v'、反斜坡 'b' 'd' 'p' 'q'；
#   - 零件占用的 (x,z) 体素（step_cells）；
#   - 零件顶面凸点位置（stud_cells：决定能否作为上方零件的支撑面）；
#   - 反斜坡根部承托位（root_cells：仅根部底面可承托，尖端下方不得有向上凸点）；
#   - 矩形砖覆盖尺寸（BRICK_SIZES 由零件库 SHAPES 派生，消除双份手工表）；
#   - 内部通配骨架格（interior_cells：六面被满体积实心格严密包裹）。
#
# 体素字符语义（与提示词一致，单字符）：
#   '#'          满实心格：顶面有凸点，可为上方零件提供支撑；
#   '/' '\\'     正斜坡楔形格（45°，沿 x）：'/' 左低右高（高端在 x 大侧），'\\' 左高右低；
#   '^' 'v'      正斜坡楔形格（沿 z）：'^' 靠上（z 小）一侧高，'v' 靠下（z 大）一侧高；
#   'b' 'd'      反斜坡楔形格（沿 x）：'b' 根部在西（x 小侧）、'd' 根部在东（x 大侧）；
#   'p' 'q'      反斜坡楔形格（沿 z）：'p' 根部在上（z 小侧）、'q' 根部在下（z 大侧）。
# 正斜坡：仅高端带顶凸点（多格斜坡砖），底面全长可承托（允许坡尖出檐）；
# 反斜坡：顶面满凸点，仅根部底面承托，悬挑斜面正下方不得有向上凸点（无干涉）。
# 楔形格（一切非 '#' 实体格）按半体积计入重心质量。
# 注意：web/viewer.js 内的 cellsOf/stud 逻辑是本文件的 JS 镜像，改动需同步。
# ============================================================
from .parts_library import PART_MAP

SCHEMA_VERSION = 2            # model / solution 产物版本号（读取端向后兼容旧产物）

# 正斜坡字符 → (坡向轴, 高端方向)；高端方向 +1 表示高端在坐标大的一侧
SLOPE_CHARS = {"/": ("x", +1), "\\": ("x", -1), "^": ("z", -1), "v": ("z", +1)}
# 反斜坡字符 → (坡向轴, 根部方向)；根部 = 满高承托侧
INV_SLOPE_CHARS = {"b": ("x", -1), "d": ("x", +1), "p": ("z", -1), "q": ("z", +1)}
ALL_SLOPE_CHARS = {**SLOPE_CHARS, **INV_SLOPE_CHARS}
SOLID_CHAR = "#"
GEO_CHARS = "#." + "".join(ALL_SLOPE_CHARS)   # rows / 编辑补丁的合法体素字符全集


def step_cells(step):
    """solution step（piece/x/z/w/d/rotate）覆盖的 (x,z) 体素——唯一实现。"""
    part = PART_MAP.get(step.get("piece"))
    if part is None:
        return []
    if step.get("w") and step.get("d"):
        w, d = step["w"], step["d"]
    elif step.get("rotate"):
        w, d = part["d"], part["w"]
    else:
        w, d = part["w"], part["d"]
    x, z = step["x"], step["z"]
    return [(x + i, z + j) for i in range(w) for j in range(d)]


def stud_cells(part, x, z, rotate):
    """零件摆在 (x,z) 时顶面带凸点的体素（决定它能否支撑上方零件）。

    - hasStuds=False（1x1 斜坡砖）：顶面是斜面，无凸点；
    - 形状带 studMask（多格正斜坡：仅高端带凸点）：只返回掩码位；
    - 其余矩形砖 / 反斜坡砖：全部体素带凸点。
    """
    if not part.get("hasStuds", True):
        return []
    w, d = (part["d"], part["w"]) if rotate else (part["w"], part["d"])
    mask = part.get("studMask")
    if mask:
        cells = [(j, i) for (i, j) in mask] if rotate else list(mask)
    else:
        cells = [(i, j) for i in range(w) for j in range(d)]
    return [(x + i, z + j) for (i, j) in cells if i < w and j < d]


def root_cells(part, x, z, rotate):
    """反斜坡砖摆在 (x,z) 时「根部承托」的体素；非反斜坡返回 None。

    仅根部底面可承托（须压在下方凸点上）；尖端底面是斜面——其正下方
    不得有任何带凸点的零件（防干涉）。
    """
    mask = part.get("rootMask")
    if not mask:
        return None
    cells = [(j, i) for (i, j) in mask] if rotate else list(mask)
    return [(x + i, z + j) for (i, j) in cells]


def brick_sizes():
    """矩形砖全部可行覆盖尺寸（含旋转 90°），由零件库 SHAPES 派生（唯一事实源）。"""
    from .parts_library import RECT_SHAPES, SHAPE_MAP
    sizes = set()
    for sid in RECT_SHAPES:
        s = SHAPE_MAP[sid]
        sizes.add((s["w"], s["d"]))
        sizes.add((s["d"], s["w"]))
    return sorted(sizes, key=lambda t: (t[0] * t[1], t))


def solid_cells_of_model(model):
    """model（validate_design_syntax / 编译器产物）的全部实体格 {(x,y,z)}。"""
    solid = set()
    for L in model.get("layers") or []:
        y = L["y"]
        for c in L.get("cells") or []:
            solid.add((c[0], y, c[1]))
    return solid


def interior_cells(model):
    """内部通配骨架格：上下前后左右六面全部被满体积实心格（'#'）严密包裹。

    紧邻任何斜坡楔形格的位置仍算表面（斜面缺口会透出彩），网格边界外侧视为空气。
    这些格对外不可见，颜色可通配：允许表面单格异色细节用长砖向内部纵深锚定。
    """
    solid = {}
    for L in model.get("layers") or []:
        y = L["y"]
        for z, row in enumerate(L.get("rows") or []):
            for x, ch in enumerate(row):
                if ch != ".":
                    solid[(x, y, z)] = ch
    out = set()
    for (x, y, z), ch in solid.items():
        if ch != SOLID_CHAR:
            continue
        for nb in ((x + 1, y, z), (x - 1, y, z), (x, y, z + 1),
                   (x, y, z - 1), (x, y + 1, z), (x, y - 1, z)):
            if solid.get(nb) != SOLID_CHAR:
                break
        else:
            out.add((x, y, z))
    return out


def slope_run(typed, x, z, ch):
    """斜面格 (x,z)（字符 ch）沿坡向轴的最大同字符连续段，返回按序 cell 列表。

    多格正/反斜坡砖只能沿坡向轴覆盖同字符连续段；段之外的格属于别的砖。
    """
    axis, _sign = ALL_SLOPE_CHARS[ch]
    dx, dz = (1, 0) if axis == "x" else (0, 1)
    start = (x, z)
    while (start[0] - dx, start[1] - dz) in typed and typed[(start[0] - dx, start[1] - dz)] == ch:
        start = (start[0] - dx, start[1] - dz)
    end = (x, z)
    while (end[0] + dx, end[1] + dz) in typed and typed[(end[0] + dx, end[1] + dz)] == ch:
        end = (end[0] + dx, end[1] + dz)
    cells = [start]
    while cells[-1] != end:
        cells.append((cells[-1][0] + dx, cells[-1][1] + dz))
    return cells


def can_support_above(ch, typed=None, x=None, z=None):
    """下一层字符 ch 的格能否给上方零件提供凸点支撑。

    '#' 恒可（矩形砖覆盖后必有凸点）；反斜坡格顶面满凸点、恒可；
    正斜坡格只有当它是同字符连续段的高端（段内还有更高端的同字符格，可组成
    多格斜坡砖）时才可——需要传 typed/x/z 判断上下文；单独存在的 1x1
    斜坡格不可。其它字符（空位/未知）不可。
    """
    if ch == SOLID_CHAR:
        return True
    if ch in INV_SLOPE_CHARS:
        return True
    if ch in SLOPE_CHARS:
        if typed is None or x is None or z is None:
            return False
        axis, sign = SLOPE_CHARS[ch]
        # 该格为「段高端」（可带顶凸点）⟺ 下坡方向一侧还有同字符格
        dx, dz = (-sign, 0) if axis == "x" else (0, -sign)
        return typed.get((x + dx, z + dz)) == ch
    return False
