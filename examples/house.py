# ============================================================
# 小房子 3D 体素模型（乐高网格）
# 网格：x: 0..7（宽 8 studs），z: 0..5（深 6 studs），y: 砖层（0 为底层）
# 每个 # 体素 = 1 stud 见方 × 1 砖层高，必须被一块乐高零件占据
# ============================================================
import json, os

W, D = 8, 6        # 占地 8x6 studs
WALL_LAYERS = 3    # 墙体 3 层（y=0..2）

voxels = {}        # (x,y,z) -> 模块名

def sett(x, y, z, module):
    voxels[(x, y, z)] = module

# ---- 模块A：四面墙（y=0..2 的边框环） ----
for y in range(WALL_LAYERS):
    for x in range(W):
        sett(x, y, 0, "前墙")
        sett(x, y, D - 1, "后墙")
    for z in range(1, D - 1):
        sett(0, y, z, "左墙")
        sett(W - 1, y, z, "右墙")

# ---- 开洞：前墙门洞（x=3..4, y=0..1，宽2高2），左右墙窗洞（z=2..3, y=1） ----
for y in range(2):
    for x in (3, 4):
        voxels.pop((x, y, 0), None)
for wx in (0, W - 1):
    for z in (2, 3):
        voxels.pop((wx, 1, z), None)

# ---- 模块B：阶梯人字屋顶（屋脊沿 x 方向，y=3..5 逐层内收） ----
ROOF_LAYERS = [
    {"y": 3, "z0": 0, "z1": 5},
    {"y": 4, "z0": 1, "z1": 4},
    {"y": 5, "z0": 2, "z1": 3},
]
for L in ROOF_LAYERS:
    for x in range(W):
        for z in range(L["z0"], L["z1"] + 1):
            sett(x, L["y"], z, "屋顶")

# ---- 汇总输出 ----
max_y = max(v[1] for v in voxels)
layers = []
for y in range(max_y + 1):
    rows, cells = [], []
    for z in range(D):
        row = ""
        for x in range(W):
            if (x, y, z) in voxels:
                row += "#"
                cells.append([x, z])
            else:
                row += "."
        rows.append(row)
    mods = sorted({m for (xx, yy, zz), m in voxels.items() if yy == y})
    layers.append({"y": y, "rows": rows, "cells": cells, "module": mods, "count": len(cells)})

house = {
    "name": "小房子",
    "grid": {"w": W, "d": D},
    "totalVoxels": len(voxels),
    "modules": sorted(set(voxels.values())),
    "openings": [
        {"type": "门洞", "desc": "前墙 z=0，x=3..4，y=0..1（宽2×高2）"},
        {"type": "窗洞", "desc": "左墙 x=0 与右墙 x=7，z=2..3，y=1（各宽2×高1）"},
    ],
    "layers": layers,
}

out = os.path.join(os.path.dirname(os.path.abspath(__file__)), "house.json")
with open(out, "w", encoding="utf-8") as f:
    json.dump(house, f, ensure_ascii=False, indent=2)

print(f"房子: {W}x{D} studs，共 {len(voxels)} 个体素，{max_y + 1} 层")
for L in layers:
    print(f"\n== y={L['y']}（{'+'.join(L['module'])}，{L['count']} 体素）==")
    for z, r in enumerate(L["rows"]):
        print(f"  z{z}: {r}")
