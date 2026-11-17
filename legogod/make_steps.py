# 生成拼装步骤 Markdown：python -m legogod.make_steps [model.json] [solution.json] [输出.md]
import json
import os
import sys

from .parts_library import PART_MAP
from .paths import EXAMPLES_DIR
from .validate import validate_solution


def _model_path():
    return sys.argv[1] if len(sys.argv) > 1 else os.path.join(EXAMPLES_DIR, "house.json")


def _sol_path():
    return sys.argv[2] if len(sys.argv) > 2 else os.path.join(EXAMPLES_DIR, "solution.json")


def _out_path():
    return sys.argv[3] if len(sys.argv) > 3 else os.path.join(EXAMPLES_DIR, "assembly-steps.md")


def build_steps_markdown(house, sol, report=None):
    """纯函数：根据校验通过的 model 与 solution 生成拼装步骤 Markdown 文本。"""
    if report is None:
        report = validate_solution(house, sol)
    W, D = house["grid"]["w"], house["grid"]["d"]

    def zone(s):
        x, z, w, d, layer = s["x"], s["z"], s["w"], s["d"], s["layer"]
        mods = house["layers"][layer].get("module") or ["模型"]
        if any("墙" in str(m) for m in mods):
            if z == 0 and z + d < D:
                return "前墙"
            if z + d == D and z > 0:
                return "后墙"
            if x == 0 and x + w < W:
                return "左墙"
            if x + w == W and x > 0:
                return "右墙"
            if z == 0:
                return "前墙/左墙转角" if x == 0 else "前墙/右墙转角"
            if z + d == D:
                return "后墙/左墙转角" if x == 0 else "后墙/右墙转角"
            return "侧墙"
        return "+".join(str(m) for m in mods)

    def rng(s):
        return f"x={s['x']}..{s['x'] + s['w'] - 1}, z={s['z']}..{s['z'] + s['d'] - 1}"

    usage = sol["usage"]
    name = house.get("name", "乐高模型")
    lines = [
        f"# {name} · 乐高拼装指南\n",
        f"> 由 **{sol.get('model', 'exact-tiler')}** 生成，并通过统一校验：{report['summary']}。\n",
    ]
    if sol.get("strategy"):
        lines.append(f"> 模型策略：{sol['strategy']}\n")

    subs = report.get("subassemblies") or sol.get("subassemblies") or []
    sub_of_step = {}
    sub_last_step = {}
    for i, sub in enumerate(subs):
        s_nums = sorted(sub.get("steps") or [])
        for sn in s_nums:
            sub_of_step[sn] = i + 1
        if s_nums:
            sub_last_step[i + 1] = s_nums[-1]
    if subs:
        lines.append("## 预拼子模块（先桌面预拼成整体，再一次扣入主结构）\n")
        for i, sub in enumerate(subs):
            s_nums = sorted(sub.get("steps") or [])
            step_list = "、".join(f"第 {sn} 步" for sn in s_nums)
            dock = s_nums[-1] if s_nums else "?"
            lines.append(
                f"- **子模块 sub{i + 1}**（共 {len(s_nums)} 块，含 {step_list}）："
                f"先在桌面将下方悬吊砖与上方跨接锁扣砖拼成刚性整体（已通过 ≥2 凸点消旋、"
                f"抗倾覆力矩平衡与竖直无卡口校验），拼至 **第 {dock} 步** 时整体从上方扣入主结构。\n"
            )

    lines.append("## 目标模型\n")
    lines.append(f"- {name}：占地 {W}×{D} studs，共 {house['totalVoxels']} 个体素、{len(house['layers'])} 层"
                 f"（模块：{'、'.join(house.get('modules', []))}）")
    for o in (house.get("openings") or []):
        lines.append(f"- {o['type']}：{o['desc']}")
    lines.append("\n## 零件清单\n")
    lines.append("| 零件 | 颜色 | 需要 | 库存 |")
    lines.append("|---|---|---|---|")
    total = 0
    for pid, n in sorted(usage.items()):
        p = PART_MAP[pid]
        lines.append(f"| {p['name']} | {p['colorName']} | {n} | {p['count']} |")
        total += n
    lines.append(f"| **合计** | | **{total}** | | \n")

    cur_layer = None
    for s in sol["steps"]:
        if s["layer"] != cur_layer:
            cur_layer = s["layer"]
            mod = "/".join(house["layers"][cur_layer].get("module") or ["模型"])
            lines.append(f"\n## 第 {cur_layer + 1} 层（y={cur_layer}，{mod}）\n")
        p = PART_MAP[s["piece"]]
        sid = sub_of_step.get(s["step"])
        if sid:
            tag = (f"（子模块 sub{sid} 跨接锁扣砖 —— 将预拼好的 sub{sid} 整体扣入主结构）"
                   if s["step"] == sub_last_step.get(sid)
                   else f"（子模块 sub{sid} 预拼件 —— 先在桌面预拼，待第 {sub_last_step.get(sid)} 步整组扣入）")
        else:
            tag = ""
        lines.append(f"{s['step']}. **{p['colorName']} {p['name']}** ×1 —— 放在 {zone(s)}：覆盖 {rng(s)}"
                     f"{'（旋转 90°）' if s['rotate'] else ''}{tag}")

    lines.append("\n## 完成检查\n")
    lines.append(f"- 统一校验：{report['summary']}")
    stability = report.get("stability") or {}
    if stability.get("checked"):
        lines.append(f"- 稳定性：{stability.get('detail')}")
    else:
        lines.append(f"- 稳定性：未验证（{stability.get('detail') or '未做完整抗倾覆/摩擦分析'}）")
    lines.append("- 说明：常规砖逐块承托就位，悬吊部位通过预拼子模块整体扣入；不包含摩擦老化等完整连续介质力学模拟。\n")
    return "\n".join(lines)


def main():
    """CLI 入口：读取 model 与 solution JSON，校验通过后写出步骤 Markdown。"""
    model_path, sol_path, out_path = _model_path(), _sol_path(), _out_path()
    with open(sol_path, encoding="utf-8") as f:
        sol = json.load(f)
    with open(model_path, encoding="utf-8") as f:
        house = json.load(f)
    report = validate_solution(house, sol)
    if not report["ok"]:
        print("方案未通过统一校验，拒绝生成步骤文档：")
        for err in report["errors"][:10]:
            print(" -", err)
        return 2
    md = build_steps_markdown(house, sol, report=report)
    with open(out_path, "w", encoding="utf-8") as f:
        f.write(md)
    print(f"已生成 {out_path}，共 {len(sol['steps'])} 步（统一校验：{report['summary']}）")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
