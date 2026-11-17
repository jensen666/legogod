"""多视角渲染：把体素模型渲染成正视图 / 侧视图 / 顶视图 / 等轴测图（PNG）。

用途：
1) 高保真模式的视觉评审输入（可拼成一张 contact sheet 给视觉模型）；
2) 生成产出预览，方便人工检查轮廓、比例、配色。

颜色优先取 solution 的零件颜色（精确），没有方案时回退到 model 的逐体素 colorRows / 层色。
斜面体素（'/'、'\\'、'^'、'v'）按坡向渲染：正视/侧视显示为三角截面（坡向沿视线时显示
为整面），顶视显示为沿坡向的三段明暗坡度，等轴测画出斜面与高端竖面——不再统一画成方块。
纯程序化正交投影 + 简单明暗，不依赖 GPU / WebGL。
"""
import os

from PIL import Image, ImageDraw

from .parts_library import COLORS, PART_MAP, voxel_color_map

_BG = (250, 250, 250)
SLOPE_CHARS = ("/", "\\", "^", "v")
# 反斜坡楔形格（顶面平带凸点、底面斜挑）：b 根部在西、d 在东、p 在北(z 小)、q 在南(z 大)
INV_SLOPE_CHARS = ("b", "d", "p", "q")


def _shade(hex_color, factor):
    """按亮度系数调整颜色（模拟简单光照）。"""
    hex_color = hex_color.lstrip("#")
    r, g, b = (int(hex_color[i:i + 2], 16) for i in (0, 2, 4))
    return (max(0, min(255, int(r * factor))),
            max(0, min(255, int(g * factor))),
            max(0, min(255, int(b * factor))))


def voxel_colors(model, solution=None):
    """把模型解析成 {(x, y, z): '#RRGGBB'}。

    solution 优先（零件级精确颜色）；否则用 colorRows / 层色。
    """
    colors = {}
    for L in model.get("layers", []):
        cmap = voxel_color_map(L.get("rows") or [], L.get("colorRows"), L.get("color"))
        for (x, z), name in cmap.items():
            if name in COLORS:
                colors[(x, L["y"], z)] = COLORS[name]["hex"]
    if solution:
        for s in solution.get("steps", []):
            part = PART_MAP.get(s.get("piece"))
            if part is None or s.get("layer") is None:
                continue
            w = s.get("w") or part["w"]
            d = s.get("d") or part["d"]
            for i in range(w):
                for j in range(d):
                    colors[(s["x"] + i, s["layer"], s["z"] + j)] = part["color"]
    return colors


def vox_types(model):
    """把模型解析成 {(x, y, z): 字符}（'#' 或斜面字符），供按坡向渲染。"""
    types = {}
    for L in model.get("layers", []):
        for z, row in enumerate(L.get("rows") or []):
            for x, ch in enumerate(row):
                if ch != ".":
                    types[(x, L["y"], z)] = ch
    return types


def _orthographic(vox, axis, reverse, grid_w, grid_d, height, scale, light, vtypes=None):
    """通用正交投影：axis 为投影方向（'x'/'y'/'z'）。

    斜面体素按坡向绘制：
    - 正视（沿 z 看）：'/' 三角（低端在左）、'\\' 三角（低端在右）；'^'/'v' 坡向沿视线 → 整面；
    - 侧视（沿 x 看）：'^' 三角（高端靠 z 小）、'v' 三角（高端靠 z 大）；'/'、'\\' → 整面；
    - 顶视（沿 y 看）：全部显示为整面，但沿坡向画三段明暗表示坡度（高端最亮）。
    """
    vtypes = vtypes or {}
    if axis == "y":
        w_px, h_px = grid_w, grid_d
    elif axis == "x":
        w_px, h_px = grid_d, height
    else:
        w_px, h_px = grid_w, height
    img = Image.new("RGB", (w_px * scale + 2, h_px * scale + 2), _BG)
    draw = ImageDraw.Draw(img)

    def hp(g):
        """水平格坐标 → 像素 x。"""
        return g * scale + 1

    def vp(g):
        """竖直格坐标 → 像素 y（顶视不翻转；正视/侧视 y 向上）。"""
        if axis == "y":
            return g * scale + 1
        return (height - g) * scale + 1

    # 先求每个屏幕格最近的体素（按投影方向）
    best = {}
    for (x, y, z), color in vox.items():
        ch = vtypes.get((x, y, z), "#")
        if axis == "y":
            key = (x, z)
            depth = y
        elif axis == "x":
            key = (z, y)
            depth = x
        else:
            key = (x, y)
            depth = z
        cur = best.get(key)
        if cur is None or (depth < cur[0] if not reverse else depth > cur[0]):
            best[key] = (depth, color, ch, (x, y, z))
    for (u, v), (_d, color, ch, (x, y, z)) in best.items():
        # 该体素在屏幕上的格坐标（u=水平格，v=竖直格）
        if axis == "y":
            gu, gv, gz, gy = x, z, None, None
        elif axis == "x":
            gu, gv = z, y
        else:
            gu, gv = x, y

        def rect(gu0, gu1, gv0, gv1, factor):
            ya, yb = vp(gv0), vp(gv1)
            if ya > yb:
                ya, yb = yb, ya
            draw.rectangle([hp(gu0), ya, hp(gu1) - 1, yb - 1], fill=_shade(color, factor))

        def poly(pts, factor):
            draw.polygon([(hp(a), vp(b)) for (a, b) in pts], fill=_shade(color, factor))

        if ch not in SLOPE_CHARS and ch not in INV_SLOPE_CHARS:
            rect(gu, gu + 1, gv, gv + 1, light)
            continue
        if ch in INV_SLOPE_CHARS:
            # 反斜坡：顶面平（整面），底面斜挑——正视/侧视画「贴顶楔形」截面
            if axis == "z":  # 正视：b/d 有三角截面，p/q 坡向沿视线 → 整面
                if ch == "b":      # 根部在西：竖边在左、贴顶
                    poly([(gu, gv), (gu, gv + 1), (gu + 1, gv + 1)], light)
                elif ch == "d":    # 根部在东
                    poly([(gu + 1, gv), (gu + 1, gv + 1), (gu, gv + 1)], light)
                else:
                    rect(gu, gu + 1, gv, gv + 1, light)
            elif axis == "x":  # 侧视：p/q 有三角截面，b/d 坡向沿视线 → 整面
                if ch == "p":      # 根部在北（z 小）
                    poly([(gu, gv), (gu, gv + 1), (gu + 1, gv + 1)], light)
                elif ch == "q":    # 根部在南
                    poly([(gu + 1, gv), (gu + 1, gv + 1), (gu, gv + 1)], light)
                else:
                    rect(gu, gu + 1, gv, gv + 1, light)
            else:  # 顶视：顶面平带凸点 → 整面
                rect(gu, gu + 1, gv, gv + 1, light)
            continue
        if axis == "y":
            # 顶视：沿坡向三段明暗（高端最亮）。段序统一按「从低端到高端」排列。
            bands_low_to_high = (0.84, 0.96, light)
            if ch in ("/", "\\"):
                for i, f in enumerate(bands_low_to_high):
                    x0 = gu + i / 3
                    x1 = gu + (i + 1) / 3
                    if ch == "\\":  # '\\' 低端在右（x 大）：镜像
                        x0, x1 = 2 * gu + 1 - x1, 2 * gu + 1 - x0
                    rect(x0, x1, gv, gv + 1, f)
            else:
                for i, f in enumerate(bands_low_to_high):
                    z0 = gv + i / 3
                    z1 = gv + (i + 1) / 3
                    if ch == "^":  # '^' 低端靠 z 大：镜像
                        z0, z1 = 2 * gv + 1 - z1, 2 * gv + 1 - z0
                    rect(gu, gu + 1, z0, z1, f)
        elif axis == "z":
            # 正视：'/','\\' 显示三角截面；'^','v' 坡向沿视线 → 整面
            if ch == "/":
                poly([(gu, gv), (gu + 1, gv), (gu + 1, gv + 1)], light)
            elif ch == "\\":
                poly([(gu, gv), (gu + 1, gv), (gu, gv + 1)], light)
            else:
                rect(gu, gu + 1, gv, gv + 1, light)
        else:  # axis == "x"（侧视）
            if ch == "^":
                poly([(gu, gv), (gu + 1, gv), (gu, gv + 1)], light)
            elif ch == "v":
                poly([(gu, gv), (gu + 1, gv), (gu + 1, gv + 1)], light)
            else:
                rect(gu, gu + 1, gv, gv + 1, light)
    return img


def _slope_faces(ch, x, y, z):
    """斜面体素的面片：返回 [(顶点列表, 明暗系数), ...]，顶点为 3D 格坐标。

    每种坡向画：斜面（高端最亮）+ 高端竖面 + 两个侧面三角形。低端竖面高度为 0，不画。
    """
    if ch == "/":  # 左低右高（沿 x）
        return [
            ([(x, y, z), (x + 1, y, z), (x + 1, y + 1, z)], 0.88),                    # z 面
            ([(x, y, z + 1), (x + 1, y, z + 1), (x + 1, y + 1, z + 1)], 0.88),        # z+1 面
            ([(x + 1, y, z), (x + 1, y + 1, z), (x + 1, y + 1, z + 1), (x + 1, y, z + 1)], 0.74),  # 高端竖面
            ([(x, y, z), (x + 1, y + 1, z), (x + 1, y + 1, z + 1), (x, y, z + 1)], 1.08),          # 斜面
        ]
    if ch == "\\":  # 左高右低
        return [
            ([(x, y, z), (x + 1, y, z), (x, y + 1, z)], 0.88),
            ([(x, y, z + 1), (x + 1, y, z + 1), (x, y + 1, z + 1)], 0.88),
            ([(x, y, z), (x, y + 1, z), (x, y + 1, z + 1), (x, y, z + 1)], 0.74),
            ([(x + 1, y, z), (x, y + 1, z), (x, y + 1, z + 1), (x + 1, y, z + 1)], 1.08),
        ]
    if ch == "^":  # 靠上（z 小）一侧高
        return [
            ([(x, y, z), (x, y, z + 1), (x, y + 1, z)], 0.88),
            ([(x + 1, y, z), (x + 1, y, z + 1), (x + 1, y + 1, z)], 0.88),
            ([(x, y, z), (x + 1, y, z), (x + 1, y + 1, z), (x, y + 1, z)], 0.74),
            ([(x, y, z + 1), (x + 1, y, z + 1), (x + 1, y + 1, z), (x, y + 1, z)], 1.08),
        ]
    # 'v'：靠下（z 大）一侧高
    return [
        ([(x, y, z), (x, y, z + 1), (x, y + 1, z + 1)], 0.88),
        ([(x + 1, y, z), (x + 1, y, z + 1), (x + 1, y + 1, z + 1)], 0.88),
        ([(x, y, z + 1), (x + 1, y, z + 1), (x + 1, y + 1, z + 1), (x, y + 1, z + 1)], 0.74),
        ([(x, y, z), (x + 1, y, z), (x + 1, y + 1, z + 1), (x, y + 1, z + 1)], 1.08),
    ]


def _inv_slope_faces(ch, x, y, z):
    """反斜坡楔形格的面片：顶面满（带凸点）+ 根部竖面 + 南北三角斜面（贴顶楔形）。"""
    top = ([(x, y + 1, z), (x + 1, y + 1, z), (x + 1, y + 1, z + 1), (x, y + 1, z + 1)], 1.08)
    if ch == "b":      # 根部在西：西面满高，东端贴顶收尖
        return [
            ([(x, y, z), (x, y + 1, z), (x, y + 1, z + 1), (x, y, z + 1)], 0.86),   # 西面（根）
            ([(x, y, z + 1), (x + 1, y + 1, z + 1), (x, y + 1, z + 1)], 0.74),      # 南三角
            ([(x, y, z), (x + 1, y + 1, z), (x, y + 1, z)], 0.88),                  # 北三角
            top,
        ]
    if ch == "d":      # 根部在东
        return [
            ([(x + 1, y, z), (x + 1, y + 1, z), (x + 1, y + 1, z + 1), (x + 1, y, z + 1)], 0.86),
            ([(x, y, z), (x + 1, y + 1, z), (x, y + 1, z)], 0.74),
            ([(x, y, z + 1), (x + 1, y + 1, z + 1), (x, y + 1, z + 1)], 0.88),
            top,
        ]
    if ch == "p":      # 根部在北（z 小）
        return [
            ([(x, y, z), (x + 1, y, z), (x + 1, y + 1, z), (x, y + 1, z)], 0.86),   # 北面（根）
            ([(x + 1, y, z), (x + 1, y + 1, z), (x + 1, y + 1, z + 1)], 0.74),      # 东三角
            ([(x, y, z), (x, y + 1, z), (x, y + 1, z + 1)], 0.88),                  # 西三角
            top,
        ]
    # 'q'：根部在南
    return [
        ([(x, y, z + 1), (x + 1, y, z + 1), (x + 1, y + 1, z + 1), (x, y + 1, z + 1)], 0.86),
        ([(x, y, z + 1), (x, y + 1, z + 1), (x, y + 1, z)], 0.74),
        ([(x + 1, y, z + 1), (x + 1, y + 1, z + 1), (x + 1, y + 1, z)], 0.88),
        top,
    ]


def _iso(vox, grid_w, grid_d, height, scale, vtypes=None):
    """等轴测视图：普通体素画顶面 + 左面 + 右面；斜面体素画斜面 + 高端竖面（画家算法）。"""
    import math
    vtypes = vtypes or {}
    cos30, sin30 = math.cos(math.pi / 6), math.sin(math.pi / 6)
    width_units = (grid_w + grid_d) * cos30 + 2
    height_units = (grid_w + grid_d) * sin30 + height + 2
    img = Image.new("RGB", (int(width_units * scale), int(height_units * scale)), _BG)
    draw = ImageDraw.Draw(img)
    ox = (grid_d * cos30 + 1) * scale
    oy = (height + 1) * scale

    def project(x, y, z):
        sx = (x - z) * cos30 * scale + ox
        sy = (x + z) * sin30 * scale - y * scale + oy
        return sx, sy

    for (x, y, z) in sorted(vox, key=lambda p: (p[0] + p[1] + p[2])):
        color = vox[(x, y, z)]
        ch = vtypes.get((x, y, z), "#")
        if ch in SLOPE_CHARS:
            for pts, factor in _slope_faces(ch, x, y, z):
                draw.polygon([project(*p) for p in pts], fill=_shade(color, factor))
            continue
        if ch in INV_SLOPE_CHARS:
            for pts, factor in _inv_slope_faces(ch, x, y, z):
                draw.polygon([project(*p) for p in pts], fill=_shade(color, factor))
            continue
        # 顶点必须按环绕顺序给出（否则多边形自交会出现锯齿/空洞）
        top = [project(x, y + 1, z), project(x + 1, y + 1, z),
               project(x + 1, y + 1, z + 1), project(x, y + 1, z + 1)]
        left = [project(x, y, z + 1), project(x + 1, y, z + 1),
                project(x + 1, y + 1, z + 1), project(x, y + 1, z + 1)]
        right = [project(x + 1, y, z), project(x + 1, y + 1, z),
                 project(x + 1, y + 1, z + 1), project(x + 1, y, z + 1)]
        # 先画侧面，再画顶面（顶面盖在最上面）；光照系数不宜过低，否则浅色会被误判成灰色
        draw.polygon(left, fill=_shade(color, 0.86))
        draw.polygon(right, fill=_shade(color, 0.74))
        draw.polygon(top, fill=_shade(color, 1.08))
    return img


def render_views(model, solution=None, out_dir=None, scale=14, name_prefix="view"):
    """渲染 4 个视角，返回 {view: png_path}。"""
    out_dir = out_dir or os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "artifacts", "views")
    os.makedirs(out_dir, exist_ok=True)
    vox = voxel_colors(model, solution)
    vtypes = vox_types(model)
    grid_w = model.get("grid", {}).get("w", 1)
    grid_d = model.get("grid", {}).get("d", 1)
    height = max((p[1] for p in vox), default=0) + 1
    paths = {}
    front = _orthographic(vox, "z", False, grid_w, grid_d, height, scale, 1.0, vtypes)
    side = _orthographic(vox, "x", True, grid_w, grid_d, height, scale, 0.90, vtypes)
    top = _orthographic(vox, "y", True, grid_w, grid_d, height, scale, 1.08, vtypes)
    iso = _iso(vox, grid_w, grid_d, height, scale, vtypes)
    for key, img in (("front", front), ("side", side), ("top", top), ("iso", iso)):
        path = os.path.join(out_dir, f"{name_prefix}_{key}.png")
        img.save(path)
        paths[key] = path
    return paths


def compose_sheet(paths, out_path=None, max_width=1200):
    """把多视角拼成一张 contact sheet（给视觉模型一次看全），确保所有图片文件句柄关闭。"""
    images = [Image.open(p) for p in paths]
    try:
        gap = 8
        total_w = sum(im.width for im in images) + gap * (len(images) + 1)
        total_h = max(im.height for im in images) + gap * 2
        sheet = Image.new("RGB", (total_w, total_h), (245, 245, 245))
        x = gap
        for im in images:
            sheet.paste(im, (x, gap))
            x += im.width + gap
        if sheet.width > max_width:
            ratio = max_width / sheet.width
            sheet = sheet.resize((int(sheet.width * ratio), int(sheet.height * ratio)))
        out_path = out_path or os.path.join(os.path.dirname(paths[0]), "view_sheet.png")
        sheet.save(out_path)
        return out_path
    finally:
        for im in images:
            im.close()
