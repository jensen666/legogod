# -*- coding: utf-8 -*-
"""突显门禁阈值标定与零误判验证脚本。

在冻结正负样本集上真实调用 part_gate.check_parts 核验分类正确性（正样本零误杀、负样本 100% 拦截），
并标定暴露面占比/最小体量等分类间隔，输出落盘至 test/fixtures/gate_samples.json。
"""
import json
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from legogod.part_gate import (MIN_SOLID_VOLUME, SURFACE_VOLUME_CAP,  # noqa: E402
                               _faces_split, check_parts)


def _model_from_layers(rows_by_layer):
    layers = []
    for y, rows in enumerate(rows_by_layer):
        cells = [[x, z] for z, r in enumerate(rows) for x, c in enumerate(r) if c != "."]
        layers.append({"y": y, "rows": rows, "cells": cells, "module": ["层"],
                       "color": "浅灰", "colorRows": None, "count": len(cells)})
    return {"grid": {"w": len(rows_by_layer[0][0]), "d": len(rows_by_layer[0])},
            "totalVoxels": sum(len(L["cells"]) for L in layers), "layers": layers}


def build_samples():
    """构建冻结正负样本集并运行真实门禁 check_parts 验证零误判。"""
    samples = []

    def add(name, rows_by_layer, part_cells, positive):
        model = _model_from_layers(rows_by_layer)
        solid = {(x, y, z) for y, L in enumerate(model["layers"]) for (x, z) in L["cells"]}
        part_set = set(part_cells)
        rest = solid - part_set
        parts = [{"id": "target", "name": name, "required": True, "source": name,
                  "role": "solid", "cells": part_set}]
        if rest:
            parts.insert(0, {"id": "body", "name": "主体", "required": True, "source": "主体",
                             "role": "solid", "cells": rest})
        errs, _ = check_parts(model, parts)
        target_errs = [e for e in errs if "target" in e]
        passed_gate = len(target_errs) == 0
        faces = _faces_split(part_set, solid)
        air = sum(a for a, _c in faces.values())
        contact = sum(c for _a, c in faces.values())
        free_ratio = round(sum(1 for _c, (_a, ct) in faces.items() if ct == 0) / max(1, len(part_set)), 4)
        samples.append({
            "name": name, "positive": positive, "gate_passed": passed_gate,
            "air": air, "contact": contact, "volume": len(part_set),
            "air_share": round(air / max(1, air + contact), 4),
            "free_cell_ratio": free_ratio,
        })

    wall = ["######", "######", "######", "######"]
    wall_ext_2 = ["######", "######", "######", "######", "..#...", "..#..."]
    wall_arm = ["######", "######", "######", "######", "...#..", "...#.."]
    ring0 = ["#####", "#...#", "#...#", "#####"]

    # 正样本：真实外伸凸出 / 上下串联截面环阶跃 / 独立薄壁风帆
    add("悬伸旗板(探出2格)", [wall, wall_ext_2], {(2, 1, 4), (2, 1, 5)}, True)
    add("悬伸手臂(贴墙伸出2格)", [wall_arm, wall_arm], {(3, 0, 4), (3, 0, 5), (3, 1, 4), (3, 1, 5)}, True)
    add("塔身(截面环+阶跃)", [ring0, ring0, ["#####"] * 4],
        {(x, y, z) for y in range(3) for x in range(5) for z in range(4)
         if x in (0, 4) or z in (0, 3) or y == 2}, True)
    add("薄壁风帆(双侧露空)", ["..##.."] * 6,
        {(2, 0, z) for z in range(6)} | {(3, 0, z) for z in range(6)}, True)
    add("收分楼层(占满整层且上下阶跃)",
        [["#####"] * 5, [".....", ".###.", ".###.", ".###.", "....."], ["#####"] * 5],
        {(x, 1, z) for x in range(1, 4) for z in range(1, 4)}, True)

    # 负样本：局部异色贴花 / 同色画圈 / 单格突起 / 整面无阶跃 1 格厚墙皮贴花
    add("异色贴花2格(嵌墙面)", [wall] * 2, {(2, 0, 3), (3, 0, 3)}, False)
    add("同色画圈4格(嵌墙面)", [wall] * 2, {(2, 0, 3), (3, 0, 3), (2, 1, 3), (3, 1, 3)}, False)
    add("单格突起(套利)", [wall, ["######", "######", "######", "######", "..#..."]], {(2, 1, 4)}, False)
    add("大面积整面墙皮贴花(无阶跃1格厚)", [wall] * 2,
        {(x, 0, 3) for x in range(6)} | {(x, 1, 3) for x in range(6)}, False)
    return samples


def calibrate(samples):
    """验证正样本零误杀、负样本零漏检，并计算特征间隔。"""
    false_neg = [s["name"] for s in samples if s["positive"] and not s["gate_passed"]]
    false_pos = [s["name"] for s in samples if not s["positive"] and s["gate_passed"]]
    pos_protrude = [s["air_share"] for s in samples if s["positive"] and s["contact"] > 0]
    neg_embed = [s["air_share"] for s in samples if not s["positive"] and s["volume"] >= 2 and s["free_cell_ratio"] == 0 and s["air"] <= s["contact"]]
    margin = round(min(pos_protrude) - max(neg_embed), 4) if (pos_protrude and neg_embed) else 0.0
    return {
        "zero_false_negatives": len(false_neg) == 0,
        "zero_false_positives": len(false_pos) == 0,
        "false_negatives": false_neg,
        "false_positives": false_pos,
        "air_share_margin": margin,
        "min_solid_volume": MIN_SOLID_VOLUME,
        "surface_volume_cap": SURFACE_VOLUME_CAP,
        "positives": sum(1 for s in samples if s["positive"]),
        "negatives": sum(1 for s in samples if not s["positive"]),
    }


def main():
    samples = build_samples()
    cal = calibrate(samples)
    fixture = os.path.join(ROOT, "test", "fixtures", "gate_samples.json")
    os.makedirs(os.path.dirname(fixture), exist_ok=True)
    with open(fixture, "w", encoding="utf-8") as f:
        json.dump({"samples": samples, "calibration": cal}, f, ensure_ascii=False, indent=2)
    print(json.dumps({"fixture": os.path.relpath(fixture, ROOT), **cal}, ensure_ascii=False, indent=2))
    for s in samples:
        tag = "正" if s["positive"] else "负"
        verdict = "PASS" if s["gate_passed"] else "REJECT"
        print(f"  [{tag}->{verdict}] {s['name']}: air={s['air']} contact={s['contact']} "
              f"free={s['free_cell_ratio']}")
    if not (cal["zero_false_negatives"] and cal["zero_false_positives"]):
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
