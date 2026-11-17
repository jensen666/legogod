# ============================================================
# 初稿可验证几何契约
#
# 在画稿受理点（编译—绑定—门禁之后、视觉评审之前）对候选模型做三项程序检查，
# 拒绝时给数值级反馈进既有草稿 revise_ops(r000) 纠错循环，不新增请求预算：
#   1. 规模契约：首稿体素 / (目标块数 × 体素每块经验值) < 0.5 → 预判目标比不达标
#      （离线验证 80 例：tp=41 / fp=0 / fn=16，查准 100%；常数待 calibrate 冻结标定）；
#   2. 支撑契约：直接复用生产 precheck_details 的逐层 find_unsupported（与预检同源，
#      零语义漂移；离线验证对最终 support/connectivity 失败查全 40/42）；
#   3. 连通契约：复用 precheck_details 的模型级分量检查，并附桥接诊断
#      （分量间是否存在任何垂直相邻——乐高靠上下凸点咬合，无垂直相邻的分量
#       任何铺砖都连不成一体，必须并成一体或补竖向重叠）。
#
# 红线：本模块绝不放宽门禁/预检/物理校验；开关默认关（LEGOGOD_GEOMETRY_CONTRACT），
# 只有显式启用才改变行为，供同输入对照验收。
# ============================================================
import os
import time

from . import plan_scale

# 开关：默认关。设 LEGOGOD_GEOMETRY_CONTRACT=1（或 on/true）启用；0/false/off 保持关闭。
ENV_CONTRACT = "LEGOGOD_GEOMETRY_CONTRACT"

# 冻结常数（离线验证实测 3.5~4 体素/块，取中位 3.7）。
# 接入生产阈值前应经 tools/calibrate_* 同款冻结样本集标定，不在轮中调整。
VOXELS_PER_BRICK = 3.7
SCALE_RATIO_MIN = 0.5   # 与 12.3 需求达标档同口径（actualParts/targetBlocks ≥ 0.5）

_TRUTHY = ("1", "on", "true", "yes")


def contract_enabled():
    """契约开关：默认关闭，只有显式设置合法真值才启用（同输入对照用）。"""
    raw = (os.environ.get(ENV_CONTRACT) or "").strip().lower()
    return raw in _TRUTHY


def target_blocks_for(plan, desc):
    """目标块数解析（与 plan_scale.metrics 同源同优先级）：规划 targetBlocks 优先，
    缺省时从需求原文「目标 N 块」/「目标约 N 块」补出；都没有则返回 None（契约跳过规模检查）。"""
    target = plan_scale._as_int((plan or {}).get("targetBlocks"))
    if target is None:
        try:
            target = plan_scale.parse_target_blocks(desc)
        except Exception:  # noqa: BLE001 - 解析失败按缺目标处理，不阻塞主链
            target = None
    if target is not None and target > 0:
        return target
    return None


def _parts_of_cells(model, cells, cap=8):
    """把错误格映射到部位 id（按模型 parts 的 boxes 覆盖关系），供反馈指名部位。"""
    out = []
    for p in (model.get("parts") or []):
        pid = p.get("id")
        if not pid:
            continue
        for b in (p.get("boxes") or []):
            for (x, y, z) in cells[:64]:
                if (b.get("x1", -1) <= x <= b.get("x2", -1)
                        and b.get("y1", -1) <= y <= b.get("y2", -1)
                        and b.get("z1", -1) <= z <= b.get("z2", -1)):
                    out.append(pid)
                    break
            else:
                continue
            break
        if len(out) >= cap:
            break
    return out


def _solid_cells(model):
    cells = set()
    for L in (model.get("layers") or []):
        y = L.get("y")
        for z, row in enumerate(L.get("rows") or []):
            for x, ch in enumerate(row):
                if ch != ".":
                    cells.add((x, y, z))
    return cells


def _voxel_components(cells):
    comp, cid = {}, 0
    for v in cells:
        if v in comp:
            continue
        comp[v] = cid
        stack = [v]
        while stack:
            x, y, z = stack.pop()
            for nb in ((x + 1, y, z), (x - 1, y, z), (x, y + 1, z),
                       (x, y - 1, z), (x, y, z + 1), (x, y, z - 1)):
                if nb in cells and nb not in comp:
                    comp[nb] = cid
                    stack.append(nb)
        cid += 1
    return comp, cid


def bridge_diagnostics(model, minority_cells, cap=64):
    """连通契约的桥接诊断：少数分量与主体之间是否存在任何垂直相邻。

    乐高靠上下凸点咬合：一块砖只能覆盖同一层的一个实心矩形（同一分量），
    分量间的连接只能来自上下叠合。少数分量与任何其他分量都没有垂直相邻时，
    任何铺砖都连不成一体——反馈必须要求竖向重叠或并成一体，而不是补跨缝砖。
    """
    cells = _solid_cells(model)
    if not cells:
        return {"bridgeable": None, "unbridgeableParts": [], "note": "模型为空"}
    comp, n_comp = _voxel_components(cells)
    wanted = {tuple(c) for c in (minority_cells or [])[:cap] if isinstance(c, (list, tuple))}
    comp_ids = {comp[c] for c in cells if c in wanted} if wanted else set()
    if not comp_ids:
        return {"bridgeable": None, "unbridgeableParts": [], "note": "无法定位少数分量"}
    unbridgeable = []
    for cid in comp_ids:
        comp_cells = [c for c in cells if comp[c] == cid]
        has_vertical = False
        for (x, y, z) in comp_cells:
            if ((x, y + 1, z) in cells and comp[(x, y + 1, z)] != cid) or \
               ((x, y - 1, z) in cells and comp[(x, y - 1, z)] != cid):
                has_vertical = True
                break
        if not has_vertical:
            unbridgeable.append({
                "size": len(comp_cells),
                "parts": _parts_of_cells(model, comp_cells),
                "sampleCell": list(comp_cells[0]),
            })
    unbridgeable.sort(key=lambda d: -d["size"])
    return {"bridgeable": not unbridgeable, "unbridgeableParts": unbridgeable[:4]}


def check_design(model, target_blocks=None):
    """对候选模型执行几何契约检查，返回违规列表（空列表 = 通过；绝不抛异常）。

    每项违规 {"kind", "message", "cells", "detail"}：
      kind=scale        目标块数比例预判不达标（仅 target_blocks 有效时检查）；
      kind=support      逐层无支撑格（生产 precheck_details 同源判定 + 原因码）；
      kind=connectivity 模型级分量不连通（附桥接诊断：是否存在垂直相邻）。
    """
    out = []
    if not isinstance(model, dict) or not (model.get("layers")):
        return out
    try:
        from .agent import precheck_details  # 延迟导入避免环依赖（agent 较重）
        detail = precheck_details(model)
        if detail.get("errors"):
            kind = detail.get("kind") or "support"
            cells = [list(c) for c in (detail.get("error_cells") or [])[:64]]
            item = {"kind": kind, "message": str(detail["errors"][0])[:300],
                    "cells": cells, "detail": {}}
            if kind == "connectivity":
                item["detail"] = bridge_diagnostics(model, detail.get("error_cells"))
                unbr = (item["detail"] or {}).get("unbridgeableParts") or []
                if unbr:
                    item["message"] += ("；其中 " + "、".join(
                        f"{len(u.get('parts') or []) or 1} 个部位组成的独立块（{u['size']} 体素，"
                        f"样例 y={u['sampleCell'][1]}）与主体没有任何上下叠合格——"
                        "任何铺砖都连不进去，必须让它与主体竖向重叠 ≥1 格或并成一体"
                        for u in unbr[:2]))
            elif kind == "support":
                reasons = (detail.get("support_reasons") or {})
                codes = {c: v.get("count") for c, v in reasons.items() if isinstance(v, dict)}
                if codes:
                    item["detail"] = {"supportReasons": codes}
            out.append(item)
        target = target_blocks
        if target:
            voxels = int(model.get("totalVoxels") or 0)
            predicted = voxels / (target * VOXELS_PER_BRICK)
            if voxels > 0 and predicted < SCALE_RATIO_MIN:
                out.append({
                    "kind": "scale",
                    "message": (f"初稿规模契约：当前 {voxels} 体素 ≈ {voxels / VOXELS_PER_BRICK:.0f} 块，"
                                f"需求目标约 {target} 块（比例 {predicted:.0%} < "
                                f"{SCALE_RATIO_MIN:.0%}）——请整体放大造型：优先加高/加宽主体"
                                "与规划里体量最大的部位，不要用 1x1 碎砖凑数"),
                    "cells": [], "detail": {"voxels": voxels, "targetBlocks": target,
                                            "predictedBricks": round(voxels / VOXELS_PER_BRICK, 1),
                                            "ratio": round(predicted, 3)},
                })
    except Exception as e:  # noqa: BLE001 - 契约检查自身异常不得阻塞主链（fail-open 并留痕）
        out.append({"kind": "contract_error", "message": f"几何契约检查异常（按通过处理）：{e}",
                    "cells": [], "detail": {}})
    return out


def contract_check_record(chain, violations, model, target_blocks, started):
    """单次契约检查的运行记录条目（chain.contract_checks，纯构造）。"""
    return {
        "phase": getattr(chain, "phase", None),
        "revision": getattr(chain, "revision", None),
        "kinds": sorted({v.get("kind") for v in violations if v.get("kind")}),
        "violationCount": len([v for v in violations if v.get("kind") != "contract_error"]),
        "voxels": int((model or {}).get("totalVoxels") or 0),
        "targetBlocks": target_blocks,
        "elapsedMs": int((time.monotonic() - started) * 1000),
    }


def rejection_text(violations, base_revision):
    """契约打回的统一反馈文本：违规明细 + 数值 + 局部纠错要求（风格与门禁反馈一致）。"""
    items = []
    for v in violations:
        if v.get("kind") == "contract_error":
            continue
        line = f"- [{v.get('kind')}] {v.get('message')}"
        cells = v.get("cells") or []
        if cells:
            line += f"（错误格展示 {len(cells)} 格：{cells[:12]}…，以总数为准）"
        items.append(line)
    return (
        "几何契约未通过（编译与门禁通过，候选已存为草稿 r000，不整稿打回）：\n"
        + "\n".join(items)
        + f"\n请输出 {{\"action\":\"revise_ops\",\"args\":{{\"baseRevision\":\"{base_revision}\","
        + "\"ops\":[基于当前草稿算子原样复制并只修正上述问题后的完整列表]}}；"
        + "无关部位必须原样保留，防删核心不得丢失。"
    )