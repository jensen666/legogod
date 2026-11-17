# ============================================================
# 规划规模一致性与实际/目标规模指标（工作包 C）
#
# - consistency_errors(plan_args, desc, observations=None)：规划阶段一致性检查，
#   不达标由主链重规划；非法输入返回错误字符串，绝不抛异常。
# - metrics(plan_args, model, pieces=None)：规划/求解后的规模指标，供运行记录
#   （scaleMetrics）与断言（targetBlocksRatio>=0.5 需求达标档）使用，绝不抛异常。
# - parse_target_blocks(desc)：从用户需求原文解析目标块数 N（「目标 N 块」与
#   「目标约 N 块」两种写法都认，是本项目目标块数解析的唯一入口）。
# - scale_observations(plan_args)：待标定提示（3.5–4 体素/块只作参考，不做硬失败）。
#
# 冻结口径（Lead/task-2 接线）：
#   * 目标块数 N 来自用户需求「目标 N 块」/「目标约 N 块」；targetBlocks 必须与 N 一致（容差内）。
#   * estimatedParts（预估积木块数）落在 [0.5N, 2.5N] 之外判为不一致——
#     这是标定前的提示级规则，不是最终达标公式。
#   * 体素/块 3.5–4 是待标定的规划提示，只进观测提示与日志，绝不进入硬失败。
#   * 求解后以 pieces（最终方案零件数）/targetBlocks 判规模是否达标（12.3：≥50%）。
# ============================================================
import re

from .prompts import MAX_LAYERS, MAX_VOX, MAX_WD

# 每块积木覆盖的体素区间（零件库最小 1x1=1 格，最大 2x8=16 格），用于几何硬边界。
MIN_VOXELS_PER_PART = 1
MAX_VOXELS_PER_PART = 16

# 需求目标块数与 targetBlocks 的容差：±max(5 块, 10%)。
TARGET_BLOCK_ABS_TOL = 5
TARGET_BLOCK_RATIO_TOL = 0.10
# estimatedParts 与目标块数的冻结容差（标定前提示级规则）。
EST_PARTS_RATIO_LO = 0.5
EST_PARTS_RATIO_HI = 2.5
# 待标定参考：交付模型实际体素/零件比基线中位约 7.98（范围 3.90–9.19），
# 「3.5–4 体素/块」只是规划提示，不是硬指标。
REFERENCE_VOXELS_PER_PART = 7.98
REFERENCE_VOXELS_PER_PART_RANGE = (3.90, 9.19)
HINT_VOXELS_PER_BLOCK = (3.5, 4.0)

# 目标块数句：同时接受「目标 N 块」与「目标约 N 块」（「约」可省略，块后有没有「积木」都算）。
# 例：目标 300 块、目标300块积木、目标约 200 块、目标约180块。
_TARGET_RE = re.compile(r"目标\s*(?:约\s*)?([0-9]{1,6})\s*块")


def _is_int(v):
    """严格整数（拒绝 bool 与浮点）。"""
    return isinstance(v, int) and not isinstance(v, bool)


def _as_int(v):
    """尽力解析整数（容忍整值 float / 数字字符串），失败返回 None。"""
    if _is_int(v):
        return v
    if isinstance(v, float) and v.is_integer():
        return int(v)
    if isinstance(v, str):
        s = v.strip()
        if re.fullmatch(r"[0-9]{1,6}", s):
            return int(s)
    return None


def parse_target_blocks(desc):
    """从用户需求原文解析目标块数 N；解析不到返回 None。

    唯一入口：同时接受「目标 N 块」与「目标约 N 块」（「约」可省略），
    只认需求原文里的显式目标块数，不按案例名/主题猜测。
    """
    if not isinstance(desc, str):
        return None
    m = _TARGET_RE.search(desc)
    if not m:
        return None
    try:
        n = int(m.group(1))
    except (TypeError, ValueError):
        return None
    return n if n > 0 else None


def _plan_numbers(plan_args):
    """解析规划里的 (targetBlocks, estimatedVoxels, estimatedParts)，缺项为 None。"""
    if not isinstance(plan_args, dict):
        return None, None, None
    return (_as_int(plan_args.get("targetBlocks")),
            _as_int(plan_args.get("estimatedVoxels")),
            _as_int(plan_args.get("estimatedParts")))


def _plan_grid(plan_args):
    """解析规划的 (w, d, layers)；缺项/非法为 None。"""
    if not isinstance(plan_args, dict):
        return None, None, None
    g = plan_args.get("grid")
    if not isinstance(g, dict):
        return None, None, None
    return _as_int(g.get("w")), _as_int(g.get("d")), _as_int(plan_args.get("layers"))


def _target_tolerance(n):
    """targetBlocks 与需求 N 的容差（块）。"""
    return max(TARGET_BLOCK_ABS_TOL, int(round(n * TARGET_BLOCK_RATIO_TOL)))


def consistency_errors(plan_args, desc, observations=None):
    """规划一致性检查，返回错误字符串列表（空列表表示一致）。

    覆盖（至少）：
      1) targetBlocks 与需求原文「目标 N 块」/「目标约 N 块」不一致；
      2) targetBlocks 与 estimatedVoxels / estimatedParts 互相矛盾
         （预估体素数不足以覆盖目标块数、预估零件数超出 [0.5N, 2.5N]）；
      3) targetBlocks 超过网格容量 / MAX_VOX（物理不可能）；
         estimatedVoxels 超过网格容量只作观测提示（估值噪声，不作硬失败）；
      4) estimatedVoxels 与 estimatedParts 的比例超出几何可行区间 [1, 16]；
      5) 必填规模字段缺失或非法。

    observations：可选列表；传入时把「3.5–4 体素/块」等待标定提示追加进去，
    不当作错误。非法输入不会抛异常。
    """
    try:
        return _consistency_errors(plan_args, desc, observations)
    except Exception as e:  # noqa: BLE001 - 契约要求绝不抛异常
        return [f"规划一致性检查无法完成（输入非法）：{type(e).__name__}: {e}"]


def _consistency_errors(plan_args, desc, observations):
    obs = observations if isinstance(observations, list) else None
    if not isinstance(plan_args, dict):
        return ["规划参数必须是对象"]
    errs = []
    target, est_vox, est_parts = _plan_numbers(plan_args)
    gw, gd, layers = _plan_grid(plan_args)
    capacity = None
    if gw and gd and layers and gw > 0 and gd > 0 and layers > 0:
        if not (2 <= gw <= MAX_WD and 2 <= gd <= MAX_WD and 2 <= layers <= MAX_LAYERS):
            errs.append(f"网格 {gw}x{gd}x{layers} 超出上限 {MAX_WD}x{MAX_WD}x{MAX_LAYERS}")
        else:
            capacity = gw * gd * layers

    # ---- 规模字段（2026-11-03 适配：C 组初稿规模策略效果未达标已回退，字段改为可选） ----
    # targetBlocks / estimatedParts 由提示词引导模型尽量给出；缺失不再拒绝规划（回退后
    # 提示词不再强制输出这两个字段），只在给出时做一致性检查。estimatedVoxels 仍按旧
    # Schema 必填（既定契约，缺失/非法都报错）。
    if target is not None and target <= 0:
        errs.append(f"targetBlocks 必须为正整数，实际 {target}")
    if est_vox is None:
        errs.append("规划缺少合法的 estimatedVoxels（预估体素总数，整数 >0）")
    elif est_vox <= 0:
        errs.append(f"estimatedVoxels 必须为正整数，实际 {est_vox}")
    if est_parts is not None and est_parts <= 0:
        errs.append(f"estimatedParts 必须为正整数，实际 {est_parts}")

    # ---- 需求原文目标块数与 targetBlocks 一致（字段可选：给出时必须一致） ----
    desc_target = parse_target_blocks(desc)
    if desc_target is not None and target is not None:
        if abs(target - desc_target) > _target_tolerance(desc_target):
            errs.append(f"targetBlocks={target} 与需求原文目标块数 {desc_target} 块"
                        f"不一致（容差 ±{_target_tolerance(desc_target)} 块）——"
                        f"targetBlocks 若填写必须照需求原文")

    # ---- 体素预估 vs 网格容量 / 全局上限 ----
    # estimatedVoxels 是「估值」而不是落位承诺：超网格容量只作提示，不拒绝规划。
    # 容量硬约束由 targetBlocks（每块至少 1 体素，见下）与最终实际落位/统一校验承担，
    # 否则估值噪声会把合法规划打成协议失败。
    if est_vox is not None and capacity is not None and est_vox > capacity:
        if obs is not None:
            obs.append(f"estimatedVoxels={est_vox} 超过网格容量 {gw}×{gd}×{layers}={capacity}："
                       f"体素估值只作参考，容量硬约束以 targetBlocks 与实际落位为准")
    if est_vox is not None and est_vox > MAX_VOX:
        errs.append(f"estimatedVoxels={est_vox} 超过全局体素上限 {MAX_VOX}")

    # ---- 预估体素/零件比例（每块 1..16 体素的几何硬边界） ----
    if est_vox is not None and est_parts is not None and est_parts > 0:
        ratio = est_vox / est_parts
        if ratio < MIN_VOXELS_PER_PART or ratio > MAX_VOXELS_PER_PART:
            errs.append(f"estimatedVoxels/estimatedParts={ratio:.2f} 超出几何可行区间 "
                        f"[{MIN_VOXELS_PER_PART}, {MAX_VOXELS_PER_PART}]（每块积木覆盖 1..16 体素）"
                        f"——体素预估与零件预估互相矛盾")

    # ---- 目标块数 vs 预估零件数（标定前提示级容差） ----
    n_ref = desc_target if desc_target is not None else target
    if n_ref is not None and n_ref > 0 and est_parts is not None and est_parts > 0:
        lo, hi = EST_PARTS_RATIO_LO * n_ref, EST_PARTS_RATIO_HI * n_ref
        if not (lo <= est_parts <= hi):
            errs.append(f"estimatedParts={est_parts} 与目标块数 N={n_ref} 明显矛盾"
                        f"（要求落在 [{lo:.0f}, {hi:.0f}] 内；这是标定前的提示级规则，"
                        f"不是最终达标公式）——按 N 重新规划体量与零件数")

    # ---- 目标块数的容量/上限 ----
    if target is not None and target > 0:
        if target > MAX_VOX:
            errs.append(f"targetBlocks={target} 超过全局体素上限 {MAX_VOX}（每块至少 1 体素）")
        if capacity is not None and target > capacity:
            errs.append(f"targetBlocks={target} 超过网格容量 {capacity}（每块至少 1 体素）")
        if est_vox is not None and est_vox > 0 and est_vox < target:
            errs.append(f"estimatedVoxels={est_vox} < targetBlocks={target}：每块积木至少覆盖 "
                        f"1 体素，实际零件数不可能达到目标")

    # ---- 待标定观测（不判失败） ----
    if obs is not None:
        obs.extend(scale_observations(plan_args, desc))
    return errs


def scale_observations(plan_args, desc=None):
    """待标定规划提示（只供提示词/日志/记录观测，绝不作为硬失败）。

    包含「3.5–4 体素/块」参考、基线实际体素/零件比、容量占用与复杂度自检提示。
    """
    try:
        return _scale_observations(plan_args, desc)
    except Exception:  # noqa: BLE001 - 观测失败不影响主链
        return []


def _scale_observations(plan_args, desc):
    obs = []
    if not isinstance(plan_args, dict):
        return obs
    target, est_vox, est_parts = _plan_numbers(plan_args)
    gw, gd, layers = _plan_grid(plan_args)
    if est_vox and est_parts:
        ratio = est_vox / est_parts
        lo, hi = REFERENCE_VOXELS_PER_PART_RANGE
        obs.append(f"预估体素/零件比 {ratio:.2f}（基线实际中位约 {REFERENCE_VOXELS_PER_PART}，"
                   f"范围 {lo}–{hi}）")
        if not (lo <= ratio <= hi):
            obs.append("预估体素/零件比不在基线范围内：只作参考，不作为硬失败")
    if est_vox and est_parts and est_parts > 0:
        hint_lo, hint_hi = HINT_VOXELS_PER_BLOCK
        hinted_vox = int(round(est_parts * hint_lo)), int(round(est_parts * hint_hi))
        obs.append(f"「{hint_lo}–{hint_hi} 体素/块」只是待标定的规划提示，不是硬指标："
                   f"按该提示 {est_parts} 块约 {hinted_vox[0]}–{hinted_vox[1]} 体素，仅供参考")
    capacity = gw * gd * layers if (gw and gd and layers) else None
    if capacity and est_vox:
        obs.append(f"预估体素占网格容量 {est_vox}/{capacity} = {est_vox / capacity:.1%}")
    if target and est_vox and est_vox >= target:
        obs.append(f"目标 {target} 块、预估 {est_vox} 体素：请让最终方案零件数接近 "
                   f"{target} 块，而不是只堆体素")
    desc_target = parse_target_blocks(desc)
    if desc_target is not None and target is not None and desc_target != target:
        obs.append(f"需求目标块数 N={desc_target} 与 targetBlocks={target} 不同（已按容差检查）")
    return obs


# ---------------- 规模指标（记录/断言侧） ----------------

_METRIC_KEYS = ("targetBlocks", "estimatedVoxels", "estimatedParts", "actualVoxels",
                "actualParts", "bricks", "targetBlocksRatio", "voxelsPerPiece", "partRatio")


def _empty_metrics():
    """全空指标（非法输入或无法计算时的兜底）。"""
    return {k: None for k in _METRIC_KEYS}


def _model_voxels(model):
    """从 model 取实际体素数：优先 totalVoxels，否则按 layers 的实体格重算。"""
    if not isinstance(model, dict):
        return None
    total = _as_int(model.get("totalVoxels"))
    if total is not None and total > 0:
        return total
    n = 0
    for L in model.get("layers") or []:
        if not isinstance(L, dict):
            continue
        rows = L.get("rows") or []
        n += sum(1 for r in rows if isinstance(r, str) for ch in r if ch != ".")
    return n or None


def metrics(plan_args, model, pieces=None, desc=None):
    """规划/求解后的规模指标；缺项为 None，绝不抛异常。

    冻结字段：
      targetBlocks     需求目标块数（规划 targetBlocks；C 策略回退后规划可缺省，
                       此时从需求原文「目标 N 块」/「目标约 N 块」补出，保证
                       run/job/页面/E2E 同源）
      estimatedVoxels  规划预估体素
      estimatedParts   规划预估积木块数
      actualVoxels     设计模型实际体素数（最终版本模型）
      actualParts      最终方案零件数（= pieces，求解后由主链传入）
      bricks           最终方案积木块数（= pieces，与 actualParts 同源）
      targetBlocksRatio  actualParts / targetBlocks（12.3 需求达标档：≥0.5）
      voxelsPerPiece     actualVoxels / pieces（基线口径实际体素/零件比）
      partRatio          actualParts / estimatedParts（预估准确度）
    """
    try:
        return _metrics(plan_args, model, pieces, desc)
    except Exception:  # noqa: BLE001 - 契约要求绝不抛异常
        return _empty_metrics()


def _metrics(plan_args, model, pieces, desc=None):
    target, est_vox, est_parts = _plan_numbers(plan_args)
    if target is None:
        target = parse_target_blocks(desc)
    actual_vox = _model_voxels(model)
    pieces_n = _as_int(pieces)
    if pieces_n is not None and pieces_n <= 0:
        pieces_n = None
    return {
        "targetBlocks": target,
        "estimatedVoxels": est_vox,
        "estimatedParts": est_parts,
        "actualVoxels": actual_vox,
        "actualParts": pieces_n,
        "bricks": pieces_n,
        "targetBlocksRatio": (pieces_n / target) if (pieces_n is not None and target) else None,
        "voxelsPerPiece": (actual_vox / pieces_n)
        if (actual_vox is not None and pieces_n) else None,
        "partRatio": (pieces_n / est_parts) if (pieces_n is not None and est_parts) else None,
    }
