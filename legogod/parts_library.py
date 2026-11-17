# ============================================================
# 积木零件库（简化版，项目自建数据）
#
# 数据来源说明（开源发布口径）：
#   - 形状：使用积木行业通用的几何约定——stud 间距按 8mm 计、砖高按 9.6mm 计、
#     板高按 3.2mm 计；1x1/2x4/斜坡等为行业通用的形状命名，不复制任何厂商产品目录；
#   - 颜色：下表 hex 为项目自建的简化色值，不复制任何第三方零件数据库或厂商色库；
#   - 零件编号/库存：项目自建的演示数据（默认每色 2000 个），与实际市售库存无关；
#   - 本文件未复制 LDraw/Rebrickable/BrickLink 等数据库的条目、结构或文本。
#
# 结构（颜色与形状解耦，这是配色可用的根源）：
#   - SHAPES：只描述几何形状（尺寸/层高/斜面朝向），不含颜色；
#   - COLORS：可用颜色（中文名 + 色值 + 同色系分组，用于库存不足时的近似回退）；
#   - STOCK ：每种形状 × 每种颜色的库存（相同形状不同颜色各自独立计数）；
#   - PARTS ：展平后的「形状×颜色」可购零件列表，每条有唯一 id 供求解/渲染使用。
#            默认色沿用旧 id（如 B2x4），其它色加后缀（如 B2x4_LGRAY），
#            因此历史模型/历史方案仍能按原样渲染。
#
# 设计数据里每层带 color（颜色中文名），"颜色"是设计意图，不再是形状的固有属性。
# 单位约定：w/d 以 stud 间距计（1 stud = 8mm），h 以"砖层"计
# （1 砖层 = 通用砖高 9.6mm = 3 块板高 3.2mm）
# 连接方式：顶面每个 1x1 单元 1 个凸点(stud)，底面对应空腔，
#           与下方任意零件顶面的 stud 按网格对齐连接；rotate=True 表示宽深互换（水平旋转90°）
# ============================================================

COLORS = {
    "白色": {"key": "WHITE", "hex": "#F2F3F2", "family": "white"},
    # 候选颜色（首批）：米白（Tan）/深棕/藏蓝。Tan 等为通用颜色称呼，仅为便于理解；
    # 色值是项目自建的简化值，不复制第三方色库，也不声称与任何厂商色号一致。
    # 一砖不跨色约束不变，扩色后必须检查颜色碎片对铺法的影响（find_unsupported 同色检查）
    "米白": {"key": "TAN", "hex": "#E4CD9E", "family": "white"},
    "浅灰": {"key": "LGRAY", "hex": "#A0A5A9", "family": "gray"},
    "深灰": {"key": "DGRAY", "hex": "#6C6E68", "family": "gray"},
    "黑色": {"key": "BLACK", "hex": "#1B1B1B", "family": "dark"},
    "红色": {"key": "RED", "hex": "#C4281B", "family": "red"},
    "橙色": {"key": "ORANGE", "hex": "#FE8A18", "family": "orange"},
    "黄色": {"key": "YELLOW", "hex": "#F2CD37", "family": "yellow"},
    "蓝色": {"key": "BLUE", "hex": "#0055BF", "family": "blue"},
    "藏蓝": {"key": "NAVY", "hex": "#0A3463", "family": "blue"},
    # 绿色系按「亮 → 中 → 暗」排列：植物类主体优先用亮绿/草绿，绿色作过渡，深绿只做暗部
    "亮绿": {"key": "BGREEN", "hex": "#4B9F4A", "family": "green"},
    "草绿": {"key": "LGREEN", "hex": "#7DC242", "family": "green"},
    "绿色": {"key": "GREEN", "hex": "#237841", "family": "green"},
    "深绿": {"key": "DGREEN", "hex": "#184632", "family": "green"},
    "棕色": {"key": "BROWN", "hex": "#6B3E23", "family": "brown"},
    "深棕": {"key": "DBROWN", "hex": "#352100", "family": "brown"},
}
COLOR_NAMES = list(COLORS)

# 逐体素颜色用的单字符编码（设计文档 colorRows 里用）：
# 空位用 '.'，实体体素用对应颜色字符。LLM 只写这些字符，不必写颜色中文名。
COLOR_CHARS = {
    "白色": "W", "米白": "M", "浅灰": "L", "深灰": "D", "黑色": "K", "红色": "R", "橙色": "O",
    "黄色": "Y", "蓝色": "B", "藏蓝": "I", "亮绿": "G", "草绿": "A", "绿色": "E", "深绿": "N",
    "棕色": "T", "深棕": "U",
}
CHAR_COLORS = {ch: name for name, ch in COLOR_CHARS.items()}
COLOR_CHAR_TABLE = "、".join(f"{name}={ch}" for name, ch in COLOR_CHARS.items())

SHAPES = [
    {"id": "B1x1", "name": "1x1 砖", "w": 1, "d": 1, "h": 1, "defaultColor": "绿色", "studs": True},
    {"id": "B1x2", "name": "1x2 砖", "w": 1, "d": 2, "h": 1, "defaultColor": "白色", "studs": True},
    {"id": "B1x3", "name": "1x3 砖", "w": 1, "d": 3, "h": 1, "defaultColor": "白色", "studs": True},
    {"id": "B1x4", "name": "1x4 砖", "w": 1, "d": 4, "h": 1, "defaultColor": "白色", "studs": True},
    {"id": "B1x6", "name": "1x6 砖", "w": 1, "d": 6, "h": 1, "defaultColor": "白色", "studs": True},
    {"id": "B1x8", "name": "1x8 砖", "w": 1, "d": 8, "h": 1, "defaultColor": "白色", "studs": True},
    {"id": "B2x2", "name": "2x2 砖", "w": 2, "d": 2, "h": 1, "defaultColor": "蓝色", "studs": True},
    {"id": "B2x3", "name": "2x3 砖", "w": 2, "d": 3, "h": 1, "defaultColor": "红色", "studs": True},
    {"id": "B2x4", "name": "2x4 砖", "w": 2, "d": 4, "h": 1, "defaultColor": "红色", "studs": True},
    {"id": "B2x6", "name": "2x6 砖", "w": 2, "d": 6, "h": 1, "defaultColor": "红色", "studs": True},
    {"id": "B2x8", "name": "2x8 砖", "w": 2, "d": 8, "h": 1, "defaultColor": "红色", "studs": True},
    # 斜坡砖：覆盖一个"斜面体素"（设计中用字符标注方向），1x1 底面
    # 顶面是斜面、没有凸点（studs=False）→ 不能在其上方连接任何普通砖
    {"id": "SLOPE_XP", "name": "斜坡砖(/, 左低右高)", "w": 1, "d": 1, "h": 1, "defaultColor": "浅灰", "studs": False, "slope": "/"},
    {"id": "SLOPE_XM", "name": "斜坡砖(\\, 左高右低)", "w": 1, "d": 1, "h": 1, "defaultColor": "浅灰", "studs": False, "slope": "\\"},
    {"id": "SLOPE_ZM", "name": "斜坡砖(^, 前低后高)", "w": 1, "d": 1, "h": 1, "defaultColor": "浅灰", "studs": False, "slope": "^"},
    {"id": "SLOPE_ZP", "name": "斜坡砖(v, 前高后低)", "w": 1, "d": 1, "h": 1, "defaultColor": "浅灰", "studs": False, "slope": "v"},
    # ---- 多格斜坡几何（项目简化的正/反斜坡模型）----
    # 正斜坡（2x1 / 2x2）：仅高端带顶凸点（studMask），底面全长可承托，
    #   允许坡尖出檐（高端压在下方凸点上即可，坡尖可悬空跨接内侧实体）；
    # 反斜坡（2x1 / 2x2）：顶面满凸点，仅根部底面承托（rootMask），
    #   悬挑斜面正下方不得有向上凸点（防干涉，求解与校验层执行）。
    # 字段约定：slope=该砖覆盖的体素字符；studMask=形状坐标系里带顶凸点的 (i,j)（缺省全部）；
    #           rootMask=反斜坡根部承托位（仅反斜坡有）；两类多格斜坡不做 90° 旋转（按朝向单列）。
    # 命名说明：下列 name 中的 3040/3039/3665/3660 是沿用行业通用斜坡编号的历史兼容标签，
    #           仅用于命名与历史 id 兼容，不代表采用了任何厂商的规范、编号或数据。
    {"id": "SLOPE2_XL", "name": "2x1 正斜坡(3040, \\ 高端在西)", "w": 2, "d": 1, "h": 1, "defaultColor": "浅灰", "slope": "\\", "studMask": [(0, 0)]},
    {"id": "SLOPE2_XR", "name": "2x1 正斜坡(3040, / 高端在东)", "w": 2, "d": 1, "h": 1, "defaultColor": "浅灰", "slope": "/", "studMask": [(1, 0)]},
    {"id": "SLOPE2_ZU", "name": "2x1 正斜坡(3040, ^ 高端在北)", "w": 1, "d": 2, "h": 1, "defaultColor": "浅灰", "slope": "^", "studMask": [(0, 0)]},
    {"id": "SLOPE2_ZD", "name": "2x1 正斜坡(3040, v 高端在南)", "w": 1, "d": 2, "h": 1, "defaultColor": "浅灰", "slope": "v", "studMask": [(0, 1)]},
    {"id": "SLOPE22_XL", "name": "2x2 正斜坡(3039, \\ 高端在西)", "w": 2, "d": 2, "h": 1, "defaultColor": "浅灰", "slope": "\\", "studMask": [(0, 0), (0, 1)]},
    {"id": "SLOPE22_XR", "name": "2x2 正斜坡(3039, / 高端在东)", "w": 2, "d": 2, "h": 1, "defaultColor": "浅灰", "slope": "/", "studMask": [(1, 0), (1, 1)]},
    {"id": "SLOPE22_ZU", "name": "2x2 正斜坡(3039, ^ 高端在北)", "w": 2, "d": 2, "h": 1, "defaultColor": "浅灰", "slope": "^", "studMask": [(0, 0), (1, 0)]},
    {"id": "SLOPE22_ZD", "name": "2x2 正斜坡(3039, v 高端在南)", "w": 2, "d": 2, "h": 1, "defaultColor": "浅灰", "slope": "v", "studMask": [(0, 1), (1, 1)]},
    {"id": "ISLOPE_XL", "name": "2x1 反斜坡(3665, 根部在西)", "w": 2, "d": 1, "h": 1, "defaultColor": "浅灰", "slope": "b", "rootMask": [(0, 0)]},
    {"id": "ISLOPE_XR", "name": "2x1 反斜坡(3665, 根部在东)", "w": 2, "d": 1, "h": 1, "defaultColor": "浅灰", "slope": "d", "rootMask": [(1, 0)]},
    {"id": "ISLOPE_ZU", "name": "2x1 反斜坡(3665, 根部在北)", "w": 1, "d": 2, "h": 1, "defaultColor": "浅灰", "slope": "p", "rootMask": [(0, 0)]},
    {"id": "ISLOPE_ZD", "name": "2x1 反斜坡(3665, 根部在南)", "w": 1, "d": 2, "h": 1, "defaultColor": "浅灰", "slope": "q", "rootMask": [(0, 1)]},
    {"id": "ISLOPE22_XL", "name": "2x2 反斜坡(3660, 根部在西)", "w": 2, "d": 2, "h": 1, "defaultColor": "浅灰", "slope": "b", "rootMask": [(0, 0), (0, 1)]},
    {"id": "ISLOPE22_XR", "name": "2x2 反斜坡(3660, 根部在东)", "w": 2, "d": 2, "h": 1, "defaultColor": "浅灰", "slope": "d", "rootMask": [(1, 0), (1, 1)]},
    {"id": "ISLOPE22_ZU", "name": "2x2 反斜坡(3660, 根部在北)", "w": 2, "d": 2, "h": 1, "defaultColor": "浅灰", "slope": "p", "rootMask": [(0, 0), (1, 0)]},
    {"id": "ISLOPE22_ZD", "name": "2x2 反斜坡(3660, 根部在南)", "w": 2, "d": 2, "h": 1, "defaultColor": "浅灰", "slope": "q", "rootMask": [(0, 1), (1, 1)]},
]

# 造型优先阶段不限制零件数量：每种形状 × 每种颜色给足库存（项目自建演示值，每色 2000 个），
# 让设计者按外观需要自由用砖，不再因为"库存不足"被迫简化形状或换色。
# （后续接入用户真实库存时，再按任务传入 inventory 覆盖这里的默认值。）
DEFAULT_STOCK_PER_COLOR = 2000
STOCK = {
    shape["id"]: {color: DEFAULT_STOCK_PER_COLOR for color in COLORS}
    for shape in SHAPES
}

SHAPE_MAP = {s["id"]: s for s in SHAPES}
RECT_SHAPES = [s["id"] for s in SHAPES if "slope" not in s]

# 斜坡几何质量系数（稳定性/重心用）：1x1 斜坡为半体积楔；2 格斜坡=满格+半格=0.75；
# 2x2 斜坡=两满格+两半格=0.75。矩形砖默认 1.0。
for _s in SHAPES:
    if "slope" in _s:
        _s["massFactor"] = 0.5 if (_s["w"] * _s["d"] == 1) else 0.75


def _part_id(shape_id, color_name):
    """默认色沿用旧 id（历史数据兼容），其它颜色追加颜色 key 后缀。"""
    if color_name == SHAPE_MAP[shape_id]["defaultColor"]:
        return shape_id
    return f"{shape_id}_{COLORS[color_name]['key']}"


PARTS = []
for _shape in SHAPES:
    _stock = STOCK[_shape["id"]]
    # 默认色排最前，其余按 COLORS 定义顺序，便于前端/提示词稳定展示
    _colors = [c for c in [ _shape["defaultColor"] ] + COLOR_NAMES if c in _stock and _stock[c] > 0]
    for _color_name in dict.fromkeys(_colors):
        _c = COLORS[_color_name]
        _part = {
            "id": _part_id(_shape["id"], _color_name),
            "shape": _shape["id"],
            "name": _shape["name"],
            "w": _shape["w"], "d": _shape["d"], "h": _shape["h"],
            "color": _c["hex"],
            "colorName": _color_name,
            "colorKey": _c["key"],
            "count": _stock[_color_name],
            # 顶面是否有凸点（stud）：斜坡砖顶面是斜面、无凸点，不能向上连接
            "hasStuds": bool(_shape.get("studs", True)),
        }
        if "slope" in _shape:
            _part["slope"] = _shape["slope"]
        if "studMask" in _shape:
            _part["studMask"] = _shape["studMask"]
        if "rootMask" in _shape:
            _part["rootMask"] = _shape["rootMask"]
        if "massFactor" in _shape:
            _part["massFactor"] = _shape["massFactor"]
        PARTS.append(_part)

PART_MAP = {p["id"]: p for p in PARTS}

# 索引：形状 → {颜色名: 零件}
PARTS_BY_SHAPE_COLOR = {}
for _p in PARTS:
    PARTS_BY_SHAPE_COLOR.setdefault(_p["shape"], {})[_p["colorName"]] = _p

# 斜面字符 → 该朝向的斜坡砖（按颜色索引；同字符可能有 1x1/2x1/2x2 多种规格，
# 因此值是列表，供求解器按层色挑选）
SLOPE_PARTS_BY_CHAR = {}
for _p in PARTS:
    if "slope" in _p:
        SLOPE_PARTS_BY_CHAR.setdefault(_p["slope"], {}).setdefault(_p["colorName"], []).append(_p)


def voxel_color_map(rows, color_rows=None, layer_color=None):
    """根据 rows / colorRows / 层色解析出 {(x,z): 颜色名}。

    colorRows 优先（逐体素颜色）；缺失的位置回退层色；再缺失则返回 None。
    """
    colors = {}
    for z, row in enumerate(rows):
        for x, ch in enumerate(row):
            if ch == ".":
                continue
            name = None
            if color_rows and z < len(color_rows) and x < len(color_rows[z]):
                name = CHAR_COLORS.get(color_rows[z][x])
            colors[(x, z)] = name or layer_color
    return colors


def part_for(shape_id, color_name):
    """取某形状在某颜色下的零件；该颜色无此形状时返回 None。"""
    return PARTS_BY_SHAPE_COLOR.get(shape_id, {}).get(color_name)
