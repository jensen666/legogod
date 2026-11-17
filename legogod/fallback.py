# ============================================================
# 生成任务编排：快速/高保真双模式、高保真硬失败快速保底、评审意见继承，
# 以及主链前置顺序（D.2）、结构候选 hook（B）、运行记录可信度辅助字段（A.2/A.3）的实现。
# 本模块不在顶层 import workflow（workflow 会 import 本模块），调用时惰性导入。
# ============================================================
import json
import re
import time

# 发起快速保底所需的最少剩余时间（秒）：模型调用需保留 90s 截止余量，
# 求解与产物生成各留 60s/30s——低于该值时保底注定跑不完，直接如实失败
MIN_FALLBACK_S = 240

OUTCOME_FIDELITY_SUCCESS = "fidelity_success"    # 高保真成功：可拼方案 + 视觉评审达标
OUTCOME_FIDELITY_DEGRADED = "fidelity_degraded"  # 高保真产物已交付，但评审未完全通过
OUTCOME_FAST_FALLBACK = "fast_fallback"          # 快速保底成功（高保真硬失败后）
OUTCOME_FAST_SUCCESS = "fast_success"            # 显式快速模式直接成功
OUTCOME_FAILED = "failed"                        # 生成失败（保底后仍未产出有效方案）
OUTCOME_CANCELLED = "cancelled"                  # 用户取消（不触发保底）

_DEGRADED_REASON = {
    "review_failed": "视觉评审修订后仍未达标（整体分低于验收线）",
    "review_unavailable": "视觉评审不可用（渲染/依赖/评审请求失败）",
    "review_stale": "最终模型与评审稿哈希不一致（评审已过期，最终稿未复审）",
}


def _noop_log(kind, text, meta=None):
    pass


def _short(text, cap=160):
    text = str(text or "").strip().replace("\n", " ")
    return text[:cap] + ("…" if len(text) > cap else "")


def degraded_reason(res):
    """降级交付的原因：视觉未达标、评审不可用、最终稿与评审稿不一致，或修订未完成。

    视觉未达标仍用原来的原因文案；只有视觉已经过线、仅仅是结构修订没做完时，
    才改用 revisionIncompleteReason。None 表示可以算高保真成功（评审哈希必须一致）。
    """
    visual_failed = res.get("review_failed") or res.get("review_flag") == "review_failed"
    visual_down = res.get("review_unavailable") or res.get("review_flag") == "review_unavailable"
    if res.get("revisionIncomplete") and not visual_failed and not visual_down:
        return res.get("revisionIncompleteReason") or "修订未完成，降级交付"
    if res.get("review_stale") or res.get("review_flag") == "review_stale":
        return _DEGRADED_REASON["review_stale"]
    if visual_failed:
        return _DEGRADED_REASON["review_failed"]
    if visual_down:
        return _DEGRADED_REASON["review_unavailable"]
    return None


def attempt_detail(res, mode):
    """单次尝试的失败追溯明细（两类失败记录均可追溯）。"""
    return {"mode": mode, "ok": bool(res.get("ok")), "run_id": res.get("run_id"),
            "error": res.get("error"), "failure": res.get("failure"),
            "review_flag": res.get("review_flag"), "status": res.get("status"),
            "elapsed_s": res.get("elapsed_s")}


def review_context_from_result(res):
    """从一次任务结果提取可继承的评审意见，供手动重试注入。

    字段与视觉评审协议一一对应：整体与分项评分 / 缺失或失真特征 / 最差部位 / 修改建议 /
    要求保留的部位；另附 flag 与清洗后的真实失败原因（只保留事实，剥离面向模型的
    几何改法指令）。评审不可用或没有有效意见时如实标记 reviewAvailable=False（不得编造反馈），
    只带真实失败原因作为补充信息；完全无信息时返回 None。
    """
    res = res or {}
    if res.get("review_context") is not None:
        return res.get("review_context")
    parsed = res.get("review") or {}
    scores = parsed.get("scores") if isinstance(parsed.get("scores"), dict) else None
    failure_summary = _failure_summary(res)
    failure_kind = (res.get("failure") or {}).get("kind") or None
    if not scores:
        return ({"reviewAvailable": False, "failureKind": failure_kind,
                 "failureSummary": failure_summary}
                if failure_summary else None)
    flag = res.get("review_flag") or (
        "review_failed" if res.get("review_failed")
        else "review_unavailable" if res.get("review_unavailable") else None)
    return {
        "reviewAvailable": True,
        "scores": scores,
        "missingFeatures": [str(x) for x in (parsed.get("missing_features") or [])][:8],
        "worstParts": [str(x) for x in (parsed.get("worst_parts") or [])][:8],
        "suggestions": [str(x) for x in (parsed.get("suggestions") or [])][:8],
        "keepParts": [str(x) for x in (parsed.get("keep") or [])][:8],
        "flag": flag,
        "failureKind": failure_kind,
        "failureSummary": None if res.get("ok") else failure_summary,
    }


# 失败文本里面向模型的具体改法指令（对下一次次生成不成立或不可达，注入前剥离）
_INSTRUCTION_RES = tuple(re.compile(p) for p in (
    r"请立即修正[^。\n]*。?",
    r"请将其画成[^。\n）]*",
    r"请调整算子顺序[^。\n]*。?",
))


def _strip_model_instructions(text):
    """剥离失败文本里的具体几何改法指令，只保留事实（失败类别/阶段/部位/原因类别）。"""
    for pat in _INSTRUCTION_RES:
        text = pat.sub("", text)
    text = re.sub(r"[—:：]\s*(?=[）)]|$)", "", text)
    return text.strip().rstrip("—-：:，,；; ")


def _failure_summary(res):
    if res.get("ok"):
        return None
    failure = res.get("failure") or {}
    kind, stage = failure.get("kind"), failure.get("stage")
    if not kind and not res.get("error"):
        return None
    detail = _short(_strip_model_instructions(res.get("error")), 200)
    head = "失败类别 " + str(kind or "?") + (f"（阶段 {stage}）" if stage else "")
    return f"{head}：{detail}" if detail else head


def format_review_message(ctx):
    """把继承的评审意见格式化为注入消息（修正依据，不取代原始需求）。

    失败原因在注入前再过一遍清洗（兼容历史任务里未清洗的存量意见）：
    剥离面向模型的具体几何改法指令；结构门禁类失败补充可行替代路径，避免重试
    去追"把嵌入机构画成外凸"这类不可达目标。
    """
    if not ctx:
        return None
    lines = [
        "以下是同一需求上一次尝试的真实评审反馈与失败原因，供本次生成针对性修正；"
        "它不是新需求：原始需求（你的第一条用户消息）仍然完全有效，"
        "视觉验收线与结构校验标准不放宽。",
    ]
    if ctx.get("reviewAvailable"):
        lines.append("上次视觉评审评分（整体与分项）：" +
                     json.dumps(ctx.get("scores") or {}, ensure_ascii=False))
        for key, label in (("missingFeatures", "缺失或失真特征（必须出现在正确位置）"),
                           ("worstParts", "最差部位（优先修正）"),
                           ("suggestions", "具体修改建议"),
                           ("keepParts", "评审要求保留的部位（不得破坏）")):
            vals = ctx.get(key) or []
            if vals:
                lines.append(f"{label}：" + "；".join(vals))
        if ctx.get("flag") == "review_failed":
            lines.append("上次产物已交付但视觉评审未完全通过：请重点解决以上仍未解决的问题。")
    else:
        lines.append("上次尝试没有可用的视觉评审意见（如实记录，不编造评审反馈）。")
    if ctx.get("failureSummary"):
        lines.append("上次真实失败原因：" + _strip_model_instructions(ctx["failureSummary"]))
        kind = ctx.get("failureKind")
        if kind in ("gate", "protocol") or "几何独立判据" in (ctx.get("failureSummary") or ""):
            lines.append("结构门禁拒绝只说明该部位此前的几何编码未过检，不是必须照搬的改法："
                         "窗内观察/嵌入机构类部位可改用 role=\"surface\" 表面涂装或并入宿主部位着色，"
                         "需要独立呈现的结构件则真实外凸于主体轮廓、做截面阶跃或薄壁斜面。")
    lines.append("请以原始需求为目标生成，并避免破坏评审要求保留的部位。")
    return "\n".join(lines)


def run_with_fallback(desc, interactive=False, log=None, cancel=None,
                      deadline_s=None, mode="fidelity", chat_fn=None,
                      review_fn=None, solve_fn=None, clock=time.monotonic,
                      review_context=None):
    """Web 生成任务总编排：按模式单次执行；高保真硬失败时自动快速保底恰好一次。

    - mode == "fast"：单次轻量主链，不调用视觉评审、不触发自动保底；成功 outcome=fast_success，
      失败 outcome=failed。
    - mode == "fidelity"：高保真成功且评审达标（最终稿哈希==评审哈希）→ 直接交付
      （fidelity_success）；
    - 高保真有可拼方案但评审未完全通过/最终稿被修订（review_stale）→ 降级交付，不重跑快速；
    - 高保真硬失败（无有效产物）→ 剩余时间足够且未取消时，用同一原始需求快速保底一次
      （全新轻量运行，不注入历史评审意见与失败原因）；合并结果仍带 review_context；
    - 用户取消 / 总时限耗尽 / 剩余时间不足 → 不再发起保底，如实报告。

    两种尝试共享同一任务总时限与取消事件；每次尝试各自落盘 run_<id>.json 运行记录。
    review_context：手动重试继承的结构化评审意见 dict（server 层从原任务提取下发），
    只影响重试首轮与显式快速重试；本次评审不可用时合并结果的保底意见回退到它。
    """
    from .workflow import TOTAL_BUDGET_S, run_generation
    deadline_s = TOTAL_BUDGET_S if deadline_s is None else deadline_s
    log = log or _noop_log
    t0 = clock()
    inherited_msg = format_review_message(review_context)
    attempt_kw = dict(interactive=interactive, cancel=cancel, chat_fn=chat_fn,
                      review_fn=review_fn, solve_fn=solve_fn, clock=clock)
    if mode != "fidelity":
        res = run_generation(desc, mode=mode, deadline_s=deadline_s, log=log,
                             review_context=inherited_msg, **attempt_kw)
        res["outcome"] = OUTCOME_FAST_SUCCESS if res.get("ok") else OUTCOME_FAILED
        return res

    if inherited_msg:
        log("info", "已继承上一次任务的评审意见与失败原因，注入本次生成；原始需求保持不变")
    res1 = run_generation(desc, mode="fidelity", deadline_s=deadline_s, log=log,
                          review_context=inherited_msg, **attempt_kw)
    if res1.get("ok"):
        reason = degraded_reason(res1)
        res1["outcome"] = OUTCOME_FIDELITY_DEGRADED if reason else OUTCOME_FIDELITY_SUCCESS
        if reason:
            res1["degraded_reason"] = reason
            log("error", f"高保真产物已交付，但评审未完全通过（{reason}）：明确标注状态，不重跑快速保底")
        return res1

    kind = (res1.get("failure") or {}).get("kind")
    if kind == "cancelled" or res1.get("status") == "cancelled" or (cancel and cancel.is_set()):
        res1["outcome"] = OUTCOME_CANCELLED
        log("error", "任务已取消：不再触发快速保底")
        return res1
    if kind == "deadline":
        res1["outcome"] = OUTCOME_FAILED
        log("error", "高保真尝试因任务总时限耗尽失败：不再发起快速保底，直接报告失败")
        return res1
    remaining = deadline_s - (clock() - t0)
    if remaining < MIN_FALLBACK_S:
        res1["outcome"] = OUTCOME_FAILED
        log("error", f"高保真尝试失败（{_short(res1.get('error'))}），但剩余时间不足 "
                     f"{MIN_FALLBACK_S}s（剩 {remaining:.0f}s），不再发起快速保底")
        return res1

    rctx = review_context_from_result(res1)
    if rctx and not rctx.get("reviewAvailable") and isinstance(review_context, dict):
        # 本次尝试没有可用评审：意见回退到继承的最新有效意见，失败原因仍用本次真实原因
        rctx = dict(review_context,
                    failureSummary=rctx.get("failureSummary") or review_context.get("failureSummary"))
    log("info", f"高保真尝试硬失败（{_short(res1.get('error'))}）；"
                f"自动发起一次快速保底（剩余 {remaining:.0f}s，最多一次）")
    log("info", "快速保底为全新轻量运行：不注入历史评审意见与失败原因，"
                "避免把高保真完整度压力与失败措辞带入兜底")
    res2 = run_generation(desc, mode="fast", deadline_s=remaining, log=log,
                          review_context=None, **attempt_kw)
    return _combine(desc, res1, res2, rctx, log)


def _combine(desc, res1, res2, rctx, log):
    """合并两次尝试的结果：成功以保底尝试产物为准，失败保留双方原因。"""
    attempts_detail = [attempt_detail(res1, "fidelity"), attempt_detail(res2, "fast")]
    combined = dict(res2)
    combined.update({
        "mode": "fidelity",  # 总流程模式；单次尝试的模式看 attempts_detail
        "outcome": OUTCOME_FAST_FALLBACK if res2.get("ok") else OUTCOME_FAILED,
        "attempts_detail": attempts_detail,
        "fidelity_attempt_error": res1.get("error"),
        "review_context": rctx,
    })
    if res2.get("ok"):
        combined["fallback_note"] = "高保真生成失败，已提供快速保底方案"
        combined["status"] = "done"
        log("result", "快速保底成功：高保真生成失败，已提供快速保底方案（不计高保真成功）")
    else:
        cancelled = any(a.get("status") == "cancelled" for a in attempts_detail)
        combined["status"] = OUTCOME_CANCELLED if cancelled else "error"
        if cancelled:
            combined["outcome"] = OUTCOME_CANCELLED
        combined["error"] = (f"生成失败：高保真尝试失败（{_short(res1.get('error'))}）；"
                             f"快速保底失败（{_short(res2.get('error'))}）")
        log("error", combined["error"] + "（两次尝试的失败原因已分别保留）")
    return combined


# ============================================================
# 主链前置顺序（D.2）、结构候选 hook 与最终尝试（A.3/第五节 B）
# ============================================================


def _precheck(chain):
    """预检详情（惰性导入，避免模块级循环依赖）。"""
    from .agent import precheck_details
    return precheck_details(chain.model)


def structural_fallback(chain, cls, failure):
    """调用 workflow_phases.try_structural_candidates：提前成功产物 / "retry" / None。

    候选尝试由 task-3 的实现累计到 chain.structural_candidates（不在这里重复计数）；
    hook 未就绪（未接线）时返回 None，调用方走原 _apply_revision。
    """
    from . import workflow_phases as wph
    hook = getattr(wph, "try_structural_candidates", None)
    if not callable(hook):
        return None
    try:
        res = hook(chain, cls, failure)
    except Exception as exc:  # noqa: BLE001 - 候选 hook 异常不得吞掉主链结果
        record = getattr(chain, "structural_candidates", None)
        if isinstance(record, dict) and isinstance(record.get("results"), list):
            record["results"].append({"cls": cls, "accepted": False, "outcome": "rejected",
                                      "reason": f"{type(exc).__name__}: {exc}"[:200]})
            record["attempted"] = len(record["results"])
            record["rejected"] = int(record.get("rejected") or 0) + 1
        chain.emit("error", f"结构候选执行异常（按原修订继续）：{exc}")
        return None
    if not isinstance(res, dict) or not res.get("accepted"):
        return None
    if isinstance(res.get("sol"), dict):
        return chain._finish_success(res["sol"])
    return "retry"


def precheck_class1(chain, before_visual=False):
    """预检 + class1 修订循环；通过返回 None、提前成功返回产物，失败按既定规则抛出。"""
    while True:
        chain.check_cancel()
        detail = _precheck(chain)
        if before_visual:
            chain.order_events.append({
                "order": chain.chain_order, "revision": chain.revision,
                "clean": not detail["errors"], "kind": detail.get("kind"),
                "windowCellCount": len(detail.get("error_cells") or [])})
        if not detail["errors"]:
            return None
        failure = {"kind": detail["kind"], "message": detail["errors"][0],
                   "cells": detail["error_cells"], "window_cells": detail["error_cells"],
                   "layer": None, "info": {"supportReasons": detail.get("support_reasons")}}
        hit = structural_fallback(chain, "class1", failure)
        if isinstance(hit, dict):
            return hit
        if hit != "retry":
            kept = chain._apply_revision("class1", failure)
            if kept:
                return kept


def run_front_order(chain):
    """D.2 前置顺序：视觉前只读预检 / class1 修订（不冻结核心）；default 直接返回 None。"""
    if getattr(chain, "chain_order", "default") == "default":
        return None
    return precheck_class1(chain, before_visual=True)


def structure_loop(chain):
    """冻结核心后的原循环：预检/class1 → 求解 → class2 修订，直到成功或如实失败。"""
    from . import tiler
    while True:
        kept = precheck_class1(chain)
        if kept:
            return kept
        sol, failure = chain._solve_current()
        if sol is not None:
            return chain._finish_success(sol)
        chain.failures.append({"kind": failure["kind"], "stage": "solve",
                               "message": failure["message"][:300],
                               "budget_exhausted": failure.get("budget_exhausted", False)})
        if failure["kind"] == "internal":
            from .workflow import GenerationFailure
            raise GenerationFailure(f"求解器内部错误：{failure['message']}", kind="internal",
                                    stage="solve",
                                    info={"failure": tiler.public_failure(failure)})
        note = ("注意：这是预算内未找到有效铺法，不是造型无解——请只针对具体失败类型补支撑或跨缝连接。"
                if failure.get("budget_exhausted") else "")
        rev_failure = {"kind": failure["kind"], "message": failure["message"] + note,
                       "cells": failure.get("cells") or [], "layer": failure.get("layer"),
                       "window_cells": failure.get("window_cells") or failure.get("cells") or [],
                       "info": failure.get("info") or {}}
        hit = structural_fallback(chain, "class2", rev_failure)
        if isinstance(hit, dict):
            return hit
        if hit == "retry":
            continue
        kept = chain._apply_revision("class2", rev_failure)
        if kept:
            return kept


def final_attempt(chain, original):
    """模型调用截止后的最终尝试：绑定与预检都通过才做最后一次真实求解与产物。"""
    from . import part_binding as pb
    from . import tiler
    from .agent import precheck_details
    from .validate import validate_solution
    from .workflow import (ARTIFACT_RESERVE_S, SOLVE_RESERVE_S, CancelledError,
                           GenerationFailure)
    if chain.model is None or chain.parts_norm is None or chain.revision < 1:
        raise original
    if (pb.parts_binding_errors(chain.parts_norm, chain.model)
            or precheck_details(chain.model)["errors"]):
        raise original
    budget_end = chain.clock() + min(SOLVE_RESERVE_S,
                                     max(0, chain.remaining_hard() - ARTIFACT_RESERVE_S))
    if budget_end <= chain.clock():
        raise GenerationFailure("没有剩余求解时间，如实失败", kind="deadline", stage="final")
    chain.emit("phase", "—— 最终阶段（模型调用已停止）：最终求解 + 产物 ——")
    try:
        sol, failure = chain.solve_fn(
            chain.model, sorted(chain.model["layers"], key=lambda l: l["y"]),
            deadline=budget_end, validate_fn=validate_solution,
            log=lambda s: chain.emit("solver", s), should_stop=chain.cancel.is_set,
            on_progress=lambda info: chain.log_fn("progress", "", dict(info or {})))
    except tiler.TilerCancelled:
        raise CancelledError() from None
    if sol is None:
        raise GenerationFailure(
            f"最终求解未通过（{(failure or {}).get('kind', '?')}）："
            f"{(failure or {}).get('message', '')[:300]}",
            kind=(failure or {}).get("kind", "internal"), stage="final",
            info={"failure": tiler.public_failure(failure)})
    return chain._finish_success(sol)


# ============================================================
# 运行记录可信度辅助字段（A.2/A.3）：门禁重放 / 结构化选稿 / 降级基线 / 额度
# ============================================================

_QUOTA_CLASSES = ("class1", "class2")


def final_gate_replay(chain):
    """重放最终模型部位门禁（task-7 gate_replay）；返回 (字段, 原因)。"""
    model, parts = getattr(chain, "model", None), getattr(chain, "parts_norm", None)
    if model is None or parts is None:
        return None, "没有最终模型或部位绑定，无法重放最终门禁"
    try:
        from . import gate_replay
        replay = gate_replay.replay_final_gate(model, parts)
    except ImportError:
        return None, "gate_replay 模块未就绪，未重放最终门禁"
    except Exception as exc:  # noqa: BLE001 - 重放异常不得影响任务结果
        return None, f"最终门禁重放异常：{type(exc).__name__}: {exc}"[:200]
    if not isinstance(replay, dict):
        return None, "最终门禁重放返回非对象"
    if replay.get("ok") is None:
        return None, str(replay.get("error") or "最终门禁重放不可用")[:200]
    return {"ok": bool(replay.get("ok")),
            "errors": [str(e) for e in (replay.get("errors") or [])],
            "affectedPartCount": int(replay.get("affectedPartCount") or 0),
            "errorCellCount": int(replay.get("errorCellCount") or 0)}, None


def draft_ranking(chain):
    """task-7 的结构化草稿排序记录；缺失返回 (None, 原因)。"""
    rec = getattr(chain, "draft_ranking", None)
    if not isinstance(rec, dict):
        return None, "没有草稿结构化排序记录"
    selected = rec.get("selected") if rec.get("selected") in ("best", "latest") else None
    return {"rule": str(rec.get("rule") or "parts>cells>types"),
            "candidates": [dict(c) for c in (rec.get("candidates") or [])
                           if isinstance(c, dict)],
            "selected": selected}, None


def gate_degraded_baseline(chain):
    """降级时冻结的门禁基线指标（task-7 workflow_ops 写入）；非降级路径为 None。"""
    base = getattr(chain, "gate_degraded_baseline", None)
    if not isinstance(base, dict):
        return None
    return {"affectedPartCount": int(base.get("affectedPartCount") or 0),
            "errorCellCount": int(base.get("errorCellCount") or 0),
            "errorTypes": [str(t) for t in (base.get("errorTypes") or [])]}


def quota_fields(chain):
    """F.1 额度记录 (mode, {class1/class2: limit/accepted/requests})：requests 用真实 HTTP 计数。"""
    from . import draw_budget as dbudget
    counts = getattr(chain, "counts", None) or {}
    requests = getattr(chain, "quota_requests", None) or {}
    limits = dict(getattr(chain, "quota_limits", None) or {})
    mode = None
    try:
        state = dbudget.quota_state(chain)
    except Exception:  # noqa: BLE001 - 记录不得影响任务结果
        state = None
    if isinstance(state, dict):
        mode = state.get("mode")
        for cls in _QUOTA_CLASSES:
            item = state.get(cls) if isinstance(state.get(cls), dict) else {}
            limits[cls] = limits.get(cls) or item.get("limit") or 0
    if mode not in ("cross", "off", "fixed"):
        mode_fn = getattr(dbudget, "dynamic_quota_mode", None)
        try:
            mode = mode_fn() if callable(mode_fn) else "off"
        except Exception:  # noqa: BLE001
            mode = "off"
    quota = {cls: {"limit": int(limits.get(cls) or 0),
                   "accepted": int(counts.get(f"revise_{cls}", 0) or 0),
                   "requests": int(requests.get(cls, 0) or 0)} for cls in _QUOTA_CLASSES}
    return quota, ("cross" if mode == "cross" else "fixed")


def structural_candidate_record(chain):
    """结构候选累计记录（无尝试时字段完整为 0，不写猜测结果）。"""
    record = getattr(chain, "structural_candidates", None)
    if not isinstance(record, dict):
        record = {}
    return {"attempted": int(record.get("attempted") or 0),
            "accepted": int(record.get("accepted") or 0),
            "rejected": int(record.get("rejected") or 0),
            "results": list(record.get("results") or [])}
