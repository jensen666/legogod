# -*- coding: utf-8 -*-
"""求解与修订参数标定脚本。

1. 真实修改 max_steps ∈ (0, 1, 2, 4, 6, 8)，在「含多个初始分离组件的局部顺缝断连样本」
   与「物理不可修分离样本」上实测修复率与耗时，验证 MAX_REPAIR_STEPS=6 的帕累托拐点；
2. 对典型部件级算子修订（加宽/换坡向/根部补合法 2 格反斜坡托架）同时验证编译 + 真实求解通过，
   并核验几何/颜色分档计数（workflow_ops.count_ops_changes）。
"""
import json
import os
import sys
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from legogod import tiler, voxel_ops as vo, workflow_ops as wops  # noqa: E402
from legogod.tiler_repair import components_of, local_repair  # noqa: E402
from legogod.parts_library import PART_MAP  # noqa: E402
from legogod.validate import validate_solution  # noqa: E402


def _make_multi_seam_broken_case(n_islands=3):
    """构造具有 n_islands 个初始顺缝分离组件、但几何上可由局部跨缝桥接修复的真实样本。"""
    w = 2 * (n_islands + 1)
    d = 4
    rows = ["#" * w for _ in range(d)]
    model = {
        "grid": {"w": w, "d": d},
        "totalVoxels": w * d * 2,
        "layers": [
            {"y": 0, "rows": list(rows), "cells": [[x, z] for z in range(d) for x in range(w)],
             "module": ["底"], "color": "浅灰", "colorRows": None, "count": w * d},
            {"y": 1, "rows": list(rows), "cells": [[x, z] for z in range(d) for x in range(w)],
             "module": ["顶"], "color": "浅灰", "colorRows": None, "count": w * d},
        ],
    }
    # 初始顺缝切条状态：每 2 列叠成独立柱子（共 n_islands + 1 个互不相连组件）
    parts, adj = [], []
    inv = {pid: p["count"] for pid, p in PART_MAP.items()}
    for col in range(n_islands + 1):
        x0 = col * 2
        cells = [(x0 + i, z) for i in range(2) for z in range(d)]
        p0_idx = len(parts)
        parts.append({"layer": 0, "piece": "B2x4_LGRAY", "rot": False,
                      "x": x0, "z": 0, "cells": cells, "parents": set()})
        adj.append(set())
        inv["B2x4_LGRAY"] -= 1
        p1_idx = len(parts)
        parts.append({"layer": 1, "piece": "B2x4_LGRAY", "rot": False,
                      "x": x0, "z": 0, "cells": cells, "parents": {p0_idx}})
        adj.append({p0_idx})
        adj[p0_idx].add(p1_idx)
        inv["B2x4_LGRAY"] -= 1
    return model, parts, adj, inv


def _make_unsolvable_gap_model():
    """体素级断开的双孤岛模型（物理不可修，测试拒绝开销上界）。"""
    rows = ["###.###"] * 4
    cells = [[x, z] for z, r in enumerate(rows) for x, c in enumerate(r) if c != "."]
    return {
        "grid": {"w": 7, "d": 4}, "totalVoxels": len(cells) * 2,
        "layers": [
            {"y": 0, "rows": list(rows), "cells": cells, "module": ["层"],
             "color": None, "colorRows": None, "count": len(cells)},
            {"y": 1, "rows": list(rows), "cells": cells, "module": ["层"],
             "color": None, "colorRows": None, "count": len(cells)},
        ],
    }


def repair_curve():
    """扫描 max_steps ∈ (0, 1, 2, 4, 6, 8) 的真实修复率与耗时曲线。"""
    out = []
    saved_steps = tiler.MAX_REPAIR_STEPS
    try:
        for steps in (0, 1, 2, 4, 6, 8):
            tiler.MAX_REPAIR_STEPS = steps
            t0 = time.monotonic()
            repaired_cnt = 0
            for n_islands in (1, 2, 3, 4):
                m, ps, ad, inv = _make_multi_seam_broken_case(n_islands=n_islands)
                ok = local_repair(ps, ad, m, m["layers"], inv, seed=0, max_steps=steps)
                if ok and len(set(components_of(ps, ad).values())) == 1:
                    repaired_cnt += 1
            unsolvable = _make_unsolvable_gap_model()
            sol_u, _ = tiler.solve_with_budget(unsolvable, unsolvable["layers"], rounds=2, log=lambda s: None)
            out.append({
                "max_repair_steps": steps,
                "repairable_solved": f"{repaired_cnt}/4",
                "repair_rate": round(repaired_cnt / 4, 2),
                "unsolvable_rejected": sol_u is None,
                "seconds": round(time.monotonic() - t0, 4),
            })
    finally:
        tiler.MAX_REPAIR_STEPS = saved_steps
    return out


def revise_ops_curve():
    """验证典型部件级算子修订（加宽/换坡向/补合法偶数跨度反斜坡托架/纯换色）的编译与真实求解。"""
    base = [
        {"op": "box", "x": 0, "y": 0, "z": 0, "w": 3, "d": 4, "h": 2, "part": "body", "color": "浅灰"},
        {"op": "box", "x": 1, "y": 2, "z": 0, "w": 3, "d": 4, "h": 1, "part": "eave", "color": "红色"},
    ]
    revisions = {
        "加宽主体承托": [
            {"op": "box", "x": 0, "y": 0, "z": 0, "w": 4, "d": 4, "h": 2, "part": "body", "color": "浅灰"},
            {"op": "box", "x": 1, "y": 2, "z": 0, "w": 4, "d": 4, "h": 1, "part": "eave", "color": "红色"},
        ],
        "挑檐改双格正斜坡": [
            base[0],
            {"op": "wedge", "dir": "+x", "x": 1, "y": 2, "z": 0, "w": 3, "d": 4, "h": 1,
             "part": "eave", "color": "红色"},
        ],
        "悬挑根部补反斜坡托架": [
            base[0],
            {"op": "wedge", "dir": "+x", "x": 2, "y": 1, "z": 0, "w": 2, "d": 4, "h": 1,
             "kind": "inverted", "part": "body", "color": "浅灰"},
            {"op": "box", "x": 1, "y": 2, "z": 0, "w": 3, "d": 4, "h": 1, "part": "eave", "color": "红色"},
        ],
        "整模纯换色不占几何配额": [
            {**base[0], "color": "深灰"},
            {**base[1], "color": "蓝色"},
        ],
    }
    cases = []
    for name, ops in revisions.items():
        geo_c, col_c = wops.count_ops_changes(base, ops)
        errs, res = vo.compile_ops(ops, 8, 8, 4, part_ids=["body", "eave"], required_ids=["body", "eave"])
        solved_ok = False
        if not errs:
            m = res["model"]
            sol, _fail = tiler.solve_with_budget(
                m, m["layers"], rounds=4, validate_fn=validate_solution, log=lambda s: None
            )
            solved_ok = sol is not None
        cases.append({
            "name": name, "geo_changed_ops": geo_c, "color_changed_ops": col_c,
            "compiles": not errs, "solves_and_validates": solved_ok,
        })
    return cases


def main():
    rc = repair_curve()
    vc = revise_ops_curve()
    report = {
        "repair_curve": rc,
        "revise_ops_cases": vc,
        "constants": {"MAX_REPAIR_STEPS": tiler.MAX_REPAIR_STEPS},
    }
    print(json.dumps(report, ensure_ascii=False, indent=2))
    if not all(c["compiles"] and c["solves_and_validates"] for c in vc):
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
