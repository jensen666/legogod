# -*- coding: utf-8 -*-
"""终稿评审刷新（从 workflow_phases.py 拆出，使生产文件保持 ≤500 行）。"""
from .prompts import FIDELITY_PASS


def refresh_stale_review(chain, artifacts_dir):
    """终稿与已评审模型不一致时补一次评审（review_stale 治理，2026-11-07）。

    视觉回滚后的结构修订/结构候选会改动模型，最终稿不再是被评审的那一稿；
    求解成功后、落盘前补一次评审刷新 review_state。评审失败/超时/取消时恢复
    原评审状态，stale 如实保留，不伪造评审结果。

    2026-11-14 双模式真实 E2E 发现的缺陷修复：补评审只刷新哈希、不重判验收线，
    会出现「视觉阶段 7 分达标 → 结构候选改稿 → 终稿补评审 6 分仍判 fidelity_success」。
    终稿补评审低于 `FIDELITY_PASS` 时必须标记 `review_failed` 降级交付（视觉不达标但已有可拼产物
    → 降级交付，不冒充高保真成功）；补评审未返回有效分数时
    恢复原评审状态（不得用空结果冒充达标评审）。
    """
    if chain.mode != "fidelity":
        return
    state = getattr(chain, "review_state", None)
    if not (isinstance(state, dict) and state.get("ok")):
        return
    from .workflow_artifacts import model_hash
    from .workflow_phases import do_review_once
    reviewed = state.get("modelHash") or getattr(chain, "reviewed_model_hash", None)
    try:
        final = model_hash(chain.model) if chain.model is not None else None
    except (TypeError, ValueError):
        return
    if not (reviewed and final) or reviewed == final:
        return
    prev_state, prev_flag = chain.review_state, chain.review_flag
    out = do_review_once(chain, artifacts_dir, 1)
    if not (out or {}).get("ok"):
        chain.review_state = prev_state
        chain.review_flag = prev_flag
        chain.emit("info", "终稿补评审未返回可用结果，保留原评审记录（review_stale 如实保留）")
        return
    scores = ((out.get("parsed") or {}).get("scores") or {})
    if not isinstance(scores, dict) or not scores:
        # 补评审成功但没有有效分数：不能作为「评审达标」证据，恢复原评审状态
        chain.review_state = prev_state
        chain.review_flag = prev_flag
        chain.emit("error", "终稿补评审未返回有效评分，保留原评审记录（不冒充达标评审）")
        return
    chain.reviewed_model_hash = out.get("modelHash")
    overall = scores.get("overall")
    if isinstance(overall, (int, float)) and overall < FIDELITY_PASS:
        # 终稿确实被复审过（哈希已刷新），但分数未达验收线：如实降级，不判高保真成功
        chain.review_flag = "review_failed"
        chain.emit("error", f"终稿补评审未达验收线（overall={overall} < {FIDELITY_PASS}）："
                            "标记 review_failed，按降级交付；不冒充高保真成功")
        return
    chain.emit("info", "终稿与已评审模型不一致：已补一次评审刷新评审哈希"
               f"（终稿 overall={overall}，review_stale 治理）")
