# 生成 tree.json —— 用与 house.json 完全相同的"逐层 ASCII"格式定义一棵小树
# 树干 2x2 ×2 层，树冠 4x4 ×2 层，顶 2x2 ×1 层（44 体素）
import json, os

W, D = 6, 6
LAYERS = [
    ("树干", [
        "......",
        "......",
        "..##..",
        "..##..",
        "......",
        "......",
    ]),
    ("树干", [
        "......",
        "......",
        "..##..",
        "..##..",
        "......",
        "......",
    ]),
    ("树冠", [
        "......",
        ".####.",
        ".####.",
        ".####.",
        ".####.",
        "......",
    ]),
    ("树冠", [
        "......",
        ".####.",
        ".####.",
        ".####.",
        ".####.",
        "......",
    ]),
    ("树冠", [
        "......",
        "......",
        "..##..",
        "..##..",
        "......",
        "......",
    ]),
]

layers = []
total = 0
for y, (module, rows) in enumerate(LAYERS):
    assert len(rows) == D and all(len(r) == W for r in rows)
    cells = [[x, z] for z, r in enumerate(rows) for x, c in enumerate(r) if c == "#"]
    total += len(cells)
    layers.append({"y": y, "rows": rows, "cells": cells, "module": [module], "count": len(cells)})

tree = {
    "name": "小树",
    "grid": {"w": W, "d": D},
    "totalVoxels": total,
    "modules": ["树干", "树冠"],
    "openings": [],
    "layers": layers,
}
out = os.path.join(os.path.dirname(os.path.abspath(__file__)), "tree.json")
json.dump(tree, open(out, "w", encoding="utf-8"), ensure_ascii=False, indent=2)
print(f"小树: {W}x{D}，共 {total} 个体素，{len(layers)} 层")
