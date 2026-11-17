# ============================================================
# 工作流阶段实现（规划 / 造型 / 补标 / 视觉评审 / 有界修订）
# 由 workflow._Chain 委托调用（按职责拆分以控制单文件规模）。
# ============================================================
import json
import os

from . import design_contract as dc
from . import draw_budget as dbudget
from . import part_binding as pb
from . import revision_hints as rh
from . import revision_policy as rp
from . import structure_candidates as sc
from . import workflow_ops as wops
from .agent import FIDELITY_PASS, support_distance_allowed, validate_design_syntax
from .tiler_repair import analyze_disconnected


def run_plan_phase(chain, intro=None):
    """执行 plan_design 规划阶段（允许最多一次 ask_user 追问）。"""
    chain.begin_phase("plan", intro or (
        "阶段：plan_design。请先做规划（只规划不画图）：输出 {\"action\":\"plan_design\",\"args\":{…}}，"
        "必须包含 features、structure、grid、layers、estimatedVoxels 和 parts 部位清单"
        "（声明 id/name/required/source/role，source 抄需求原文；平面色点务必设 role=\"surface\"；"
        "整体材质、主色与大面积涂装分区是宿主立体部位的属性，不要声明成独立 surface 部位；"
        "不要写 boxes 或 coreBoxes）。"))
    while True:
        r = chain.model_turn({"plan_design", "ask_user"}, chain._check_plan_schema)
        if not r:
            continue
        action, args = r
        if action == "ask_user":
            _do_ask(chain, args)
            continue
        chain.plan = args
        chain.parts_norm = chain._parsed_parts
        chain._parsed_parts = None
        chain.emit("plan", f"规划确认：{args['grid']['w']}×{args['grid']['d']} × {args['layers']} 层，"
                           f"预估 {args['estimatedVoxels']} 体素；部位清单 "
                           + "、".join(f"{p['id']}({p['name']})" for p in chain.parts_norm),
                   {"plan": {k: v for k, v in args.items() if k != "parts"},
                    "parts": [{k: p[k] for k in dc.PART_KEYS} for p in chain.parts_norm]})
        return args


def _do_ask(chain, args):
    q = str(args.get("question", "")).strip()
    chain.emit("ask", q)
    if chain.used_ask:
        chain.observe("ask_user 只能使用一次。请直接按合理默认继续当前阶段。")
        return
    chain.used_ask = True
    if chain.interactive:
        try:
            ans = input("\n[Agent 提问] " + q + "\n你的回答 > ").strip() or "按合理默认即可。"
        except EOFError:
            ans = "（用户不在线）按合理默认继续。"
    else:
        ans = "（用户不在线）请按常见合理比例与造型直接决定，不要再问。"
    chain.emit("answer", ans)
    chain.observe(f"用户回答：{ans}")


def _note_draw_attempt(chain, t0, *, action, outcome, compiled=False, ops_n=0, voxels=0,
                       gate_n=0, failed_parts=(), invalid_ops=(), signature=None,
                       contract_n=None):
    """记录一次 draw 实际请求的尝试结果（算子数/编译结果/门禁错误数/耗时，可观测性）。

    contract_n 是候选稿的几何契约违规数（None=旧口径，不写键；动态预算据此判实质进展）。
    """
    entry = {
        "attempt": len(chain.draw_attempts) + 1,
        "request": chain.phase_requests, "action": action, "outcome": outcome,
        "elapsedS": round(chain.clock() - t0, 1),
        "compiled": compiled, "opCount": ops_n, "voxels": voxels,
        "gateErrorCount": gate_n, "failedPartCount": len(set(failed_parts)),
        "failedParts": sorted(set(failed_parts))[:8],
        "invalidOpCount": len(set(invalid_ops)),
        "invalidOps": sorted(set(invalid_ops), key=str)[:12],
        "signature": signature,
    }
    if contract_n is not None:
        entry["contractErrorCount"] = max(0, int(contract_n))
    chain.draw_attempts.append(entry)


def _note_candidate_attempt(chain, t0, action, outcome, draft_before):
    """按「草稿是否更新为最新候选」记录一次候选尝试（编译失败/门禁失败/契约失败/接受）。"""
    draft = chain.draft
    if draft is not None and draft is not draft_before:
        _note_draw_attempt(chain, t0, action=action, outcome=outcome, compiled=True,
                           ops_n=len(draft["ops"]), voxels=draft["model"].get("totalVoxels", 0),
                           gate_n=len(draft["gate_errors"]), failed_parts=draft["bad_part_ids"],
                           contract_n=len(draft.get("contract_errors") or []),
                           signature=draft["signature"])
        return
    fp = getattr(chain, "last_compile_reject", None)
    if fp:
        _note_draw_attempt(chain, t0, action=action, outcome="compile_retry", compiled=False,
                           invalid_ops=fp.get("ops") or [],
                           signature="compile:" + fp["digest"])
    else:
        # 配额超限/版本过期/重绘用尽等协议拒绝：不是编译结果，不得混记（评审 P2）
        _note_draw_attempt(chain, t0, action=action, outcome="protocol_retry", compiled=False)


def run_draw_phase(chain, max_redraws, intro=None):
    """执行造型阶段：主推 save_design3 三维算子，兼容回退 save_design 二维画稿。

    画图请求预算独立于通用阶段（workflow.MAX_DRAW_REQUESTS=3，复杂任务可放宽到 4）；
    编译成功但门禁未过的候选保存为草稿 r000，优先 revise_ops(r000) 局部纠错；
    请求耗尽而草稿仍未过门禁时，按既有规则带门禁记录降级。
    """
    from . import workflow as wf  # 循环依赖：仅取预算常量与结构化失败异常
    chain.max_redraws = max_redraws  # 草稿反馈里的重绘提示读真实余量
    parts_txt = "、".join(f"{p['id']}（{p['name']}）" for p in (chain.parts_norm or []))
    chain.begin_phase("draw", intro or (
        f"阶段：造型。网格严格 {chain.plan['grid']['w']}×{chain.plan['grid']['d']}、"
        f"恰好 {chain.plan['layers']} 层，逐条落实 {len(chain.plan.get('features') or [])} 条特征。"
        "**首选输出三维构造算子** {\"action\":\"save_design3\",\"args\":{…}}；"
        "无法使用算子时才降级为二维画稿 {\"action\":\"save_design\",\"args\":{…}}。"
        f"规划里的部位 id 只能用这些：{parts_txt}。"))
    while True:
        t0 = chain.clock()
        try:
            r = chain.model_turn(wops.draw_allowed_actions(chain),
                                 lambda a, act: wops.check_draw_schema(chain, a, act),
                                 reasoning_effort="low",
                                 request_limit=dbudget.draw_request_limit(
                                     chain, wf.MAX_DRAW_REQUESTS))
        except Exception as gf:  # noqa: BLE001 - 仅识别预算耗尽后降级，其余原样上抛
            from .workflow import GenerationFailure
            if isinstance(gf, GenerationFailure) and gf.kind == "protocol" and chain.draft is not None:
                draft = chain.best_draft or chain.draft
                chain.emit("info", "draw 纠错预算用尽，候选草稿带门禁/契约记录降级继续"
                           "（使用历史最佳草稿：门禁错误 "
                           f"{len(draft['gate_errors'])} 项、契约违规 "
                           f"{len(draft.get('contract_errors') or [])} 项，当前草稿 "
                           f"{len(chain.draft['gate_errors'])} 项）")
                wops.promote_candidate(
                    chain, draft["model"],
                    {"assign": draft["assign"], "parts": draft["parts_norm"]},
                    draft["ops"], draft["default_part"],
                    degraded_gate_errs=draft["gate_errors"])
                return None
            raise
        if not r:
            _note_draw_attempt(chain, t0, action=None, outcome="protocol_retry")
            continue
        action, args = r
        chain.last_compile_reject = None  # 仅本次尝试的编译失败才计入尝试签名
        draft_before = chain.draft
        if action == "revise_ops":
            if wops.apply_draft_revision(chain, args):
                _note_draw_attempt(chain, t0, action=action, outcome="accepted", compiled=True,
                                   ops_n=len(chain.ops or []), voxels=chain.model.get("totalVoxels", 0),
                                   contract_n=0)
                return args
            _note_candidate_attempt(chain, t0, action, "draft", draft_before)
            continue
        if action == "save_design3":
            if chain.draft is not None:
                if chain.redraws >= max_redraws:
                    chain.record_protocol_error("redraw_exhausted", "门禁失败后的完整重绘机会已用尽")
                    chain.observe("门禁失败后的完整重绘机会（每任务 1 次）已用尽：请基于当前草稿输出 "
                                  "revise_ops(r000) 局部纠错，完整 save_design3 不再受理。")
                    _note_draw_attempt(chain, t0, action=action, outcome="redraw_rejected")
                    continue
                chain.redraws += 1
            if wops.accept_design3(chain, args, max_redraws):
                _note_draw_attempt(chain, t0, action=action, outcome="accepted", compiled=True,
                                   ops_n=len(chain.ops or []), voxels=chain.model.get("totalVoxels", 0),
                                   contract_n=0)
                return args
            _note_candidate_attempt(chain, t0, action, "draft", draft_before)
            continue
        # save_design 二维画稿兼容回退（存在草稿时 allowed_actions 已排除该通道）
        errs, model, warns = validate_design_syntax(args)
        if errs:
            _note_draw_attempt(chain, t0, action=action, outcome="protocol_retry")
            continue
        for w in warns:
            chain.emit("error", "⚠ " + w)
        chain.track = "ascii"
        chain.design_meta = {"name": str(args.get("name") or "乐高模型"),
                             "slug": model["slug"], "notes": str(args.get("notes") or ""),
                             "features": model["features"]}
        chain.layers = [{"module": L["module"][0], "color": L.get("color"),
                         "rows": L["rows"], "colorRows": L.get("colorRows")}
                        for L in model["layers"]]
        chain.model = model
        _note_draw_attempt(chain, t0, action=action, outcome="accepted", compiled=True,
                           ops_n=0, voxels=model["totalVoxels"])
        chain.emit("design", f"{model['name']} 设计：{model['grid']['w']}×{model['grid']['d']}×{len(model['layers'])}",
                   {"design": model, "slug": model["slug"]})
        return args


def run_label_phase(chain, errs, warns, failure_cls):
    """二维画稿轨道下只补标注阶段（画稿保留不重画）。"""
    ignored = ("\n其中这些标注格被忽略：\n- " + "\n- ".join(warns[:6])) if warns else ""
    chain.begin_phase("label", "阶段：label_parts。初次画稿的部位标注不完整：\n- "
                      + "\n- ".join(errs[:8]) + ignored
                      + "\n画稿保留，只补部位标注：输出 {\"action\":\"label_parts\",\"args\":{…}}。")
    last = errs
    while True:
        try:
            r = chain.model_turn({"label_parts"}, chain._check_label_schema, reasoning_effort="low")
        except failure_cls as gf:
            if gf.kind != "protocol":
                raise
            raise failure_cls(
                "标注阶段请求用尽（每阶段 2 次），画稿仍缺必需部位归属：\n- " + "\n- ".join(last[:6]),
                kind="parts", stage="label", info={"errors": last[:8]},
            ) from None
        if not r:
            continue
        _, args = r
        label_errs, label_warns = chain._bind_parts(args)
        if not label_errs:
            return
        last = label_errs
        extra = ("\n被忽略的标注格：\n- " + "\n- ".join(label_warns[:6])) if label_warns else ""
        chain.observe("标注仍不完整：\n- " + "\n- ".join(label_errs[:8]) + extra)


def do_review_once(chain, artifacts_dir, max_phase_requests):
    """执行单次多视角渲染与多模态视觉评审（异常或超时安全降级返回 None）。"""
    if chain.remaining_model() <= 0:
        chain.emit("error", "距模型调用截止不足，跳过视觉评审（review_unavailable）")
        return None
    chain.begin_phase("review")
    prefix = f"{chain.run_id}_r{chain.revision:03d}"
    try:
        out = chain.review_fn(
            chain.desc, chain.model, None,
            spec=json.dumps({
                "plan": {k: v for k, v in (chain.plan or {}).items() if k != "parts"},
                "parts": [{k: p[k] for k in ("id", "name", "required", "source")}
                          for p in (chain.parts_norm or [])],
            }, ensure_ascii=False),
            out_dir=os.path.join(artifacts_dir, "views"), scale=22,
            deadline=chain.model_deadline, max_requests=max_phase_requests, name_prefix=prefix,
            should_stop=chain.cancel.is_set,
        )
    except Exception as e:
        chain.emit("error", f"视觉评审异常（{e}）——标记 review_unavailable，降级继续求解")
        return None
    chain.phase_requests += max(0, int((out or {}).get("requests", 0)))
    chain.review_state = out
    if (out or {}).get("stopped_by_cancel"):
        # 评审被用户取消：与模型/求解阶段统一转为取消异常，不得降级为 review_unavailable 继续跑
        chain.check_cancel()
        return None
    if not (out or {}).get("ok"):
        chain.emit("error", "视觉评审未返回可用结果——标记 review_unavailable，继续求解")
        return None
    # 评审记录被评审模型的哈希（task-2 的 review_stale 判定消费；惰性 import 防循环依赖）。
    # chain.review_state 与本 dict 同一对象，此处写入即进入评审记录，视觉回滚快照也随之一致。
    from .workflow_artifacts import model_hash
    out["modelHash"] = model_hash(chain.model) if chain.model is not None else None
    scores = (out.get("parsed") or {}).get("scores") or {}
    chain.emit("review", "视觉评审：" + json.dumps(scores, ensure_ascii=False),
               {"scores": scores, "sheet": out.get("sheet")})
    return out


def _visual_failure(review, scores):
    """把这一轮评审收成视觉修订的失败描述（带点名部位，供改动范围判断）。"""
    worst = "；".join(str(x) for x in (review.get("parsed") or {}).get("worst_parts") or [])[:200]
    return {
        "kind": "visual",
        "message": f"视觉评审不达标（overall={scores.get('overall')} < {FIDELITY_PASS}）：{worst}",
        "cells": [], "layer": None, "info": {"review": review.get("parsed") or {}},
    }


def run_visual_phase(chain, artifacts_dir, max_phase_requests, max_revise_visual):
    """高保真视觉评审。未达标时留最高分整模，不因修订用尽把整单判失败。"""
    review = do_review_once(chain, artifacts_dir, max_phase_requests)
    if review is None:
        chain.review_flag = "review_unavailable"
        return
    best, streak, rounds_left = None, 0, max_revise_visual
    while True:
        scores = (review.get("parsed") or {}).get("scores") or {}
        overall = scores.get("overall") or 0
        best, streak = rp.fold_visual_score(best, streak, rp.capture_design(chain, overall, review))
        chain.emit("info", f"视觉评审 overall={overall}，当前最高分 {best['score']}，连续未超过 {streak} 次")
        if overall >= FIDELITY_PASS:
            chain.emit("review", f"视觉评审达标（overall={overall} ≥ {FIDELITY_PASS}）")
            return
        if streak >= 2 or rounds_left <= 0:
            reason = rp.VISUAL_STREAK_REASON if streak >= 2 else rp.VISUAL_REQUEST_REASON
            rp.stop_visual(chain, best, reason)
            return
        rounds_left -= 1
        try:
            chain._apply_revision("visual", _visual_failure(review, scores))
        except rp.RevisionBudgetExhausted as ex:
            chain.emit("error", f"{ex.reason}：停止视觉修订")
            rp.stop_visual(chain, best, ex.reason)
            return
        review = do_review_once(chain, artifacts_dir, max_phase_requests)
        if review is None:
            chain.emit("error", "修订后的视觉评审不可用，回滚到已评分的最高分整模")
            rp.restore_design(chain, best)
            chain.review_flag = "review_unavailable"
            return


def revision_ctx(model, failure):
    """根据结构化失败生成错误格集合与允许修改邻域集合。

    工作包 B：allowedCells 可按「到最近可靠支撑的距离」有界扩展（默认不整模放开）；
    disconnected 追加组件界面格与可连接邻域；suspension 用锁扣/子组件坐标圈定范围。
    """
    kind = failure["kind"]
    solid = dc.solid_cells_of(model)
    gw, gd, nl = model["grid"]["w"], model["grid"]["d"], len(model["layers"])
    # window_cells 是全量种子；缺省时退回提示用的 cells（可能被截断）。
    raw = failure.get("window_cells")
    if raw is None:
        raw = failure.get("cells") or []
    error_cells = {c for c in raw}
    info = failure.get("info") or {}
    if kind == "visual":
        allowed = {(x, y, z) for x in range(gw) for y in range(nl) for z in range(gd)}
        error_cells = set()
    elif kind == "support":
        base = dc.cells_near_grid(error_cells, gw, gd, nl, max_dxz=2, dy=(0, -1)) | error_cells
        allowed = support_distance_allowed(model, base, k=3, cap=1200)
    elif kind in ("connectivity", "disconnected"):
        # 失败对象没带组件界面信息时按模型与全量窗口重算（不扩成整模）。
        if not info.get("connectableCells") and model is not None:
            info = analyze_disconnected(model, raw) or info
        allowed = dc.cells_near_grid(error_cells, gw, gd, nl, max_dxz=2, dy=(-1, 0, 1)) | error_cells
        connectable = {tuple(int(v) for v in c) for c in (info.get("connectableCells") or [])}
        allowed = support_distance_allowed(model, allowed | connectable, k=3, cap=1200)
    elif kind == "suspension":
        # 只围绕校验已算出的锁扣/子组件坐标展开，不默认整模放开。
        positions = {tuple(int(v) for v in c) for c in
                     (info.get("lockCells") or []) + (info.get("subassemblyCells") or [])
                     + (failure.get("window_cells") or [])}
        allowed = dc.cells_near_grid(positions, gw, gd, nl, max_dxz=1, dy=(-1, 0, 1)) | positions
        allowed = support_distance_allowed(model, allowed, k=2, cap=1200)
    elif kind in ("coverage", "inventory") and failure.get("layer") is not None:
        ly = failure["layer"]
        allowed = {(x, ly, z) for x in range(gw) for z in range(gd)}
        error_cells = {c for c in solid if c[1] == ly}
    else:
        allowed = {(x, y, z) for x in range(gw) for y in range(nl) for z in range(gd)}
    return {"kind": kind, "error_cells": error_cells, "allowed_cells": allowed,
            "info": info, "message": failure.get("message", "")}


MAX_REVISE_CALLS = 3  # 同一次修订的模型调用上限（含视觉）。画图和规划仍是 workflow.MAX_PHASE_REQUESTS。


def try_structural_candidates(chain, cls, failure):
    """结构候选完整验收入口（工作包 B，接口冻结）。

    返回 None=未接受（调用方走原修订）；{"accepted":True,"sol":sol}=solution 空间已救回且
    统一校验通过（调用方直接 finish_success）；{"accepted":True,"model_changed":True}=
    模型空间候选已应用且 class1 预检通过（调用方继续循环重求解）。
    候选尝试累计到 chain.structural_candidates，LEGOGOD_STRUCT_CANDIDATES=off 时与原行为一致。
    """
    return sc.try_candidates(chain, cls, failure)


def apply_revision(chain, cls, failure, budgets, gate_s, max_geo_ops, max_color_ops, failure_cls,
                   max_calls=MAX_REVISE_CALLS):
    """执行一次有界修订（优先接受 revise_ops 算子修订，兼容 revise_design 逐格补丁）。

    协议拒绝计入这 max_calls 次调用，不增加已接受修订次数。第 max_calls 次仍拒绝则结束。
    """
    chain.check_cancel()
    budget_key = budgets[cls]
    count_key = f"revise_{cls}"
    gate = gate_s if cls in ("class1", "class2") else 0
    if chain.remaining_model() < gate:
        raise failure_cls(
            f"距模型调用截止不足 {gate // 60} 分钟，无法发起第 {'1' if cls == 'class1' else '2'} 类修订",
            kind="deadline", stage="revise", info={"failure": failure},
        )
    if chain.counts[count_key] >= budget_key:
        raise rp.RevisionBudgetExhausted(cls, failure, rp.budget_reason(cls, "count"))

    ctx = revision_ctx(chain.model, failure)
    chain.pending_revision = {"cls": cls, "kind": ctx["kind"], "failure": failure}
    base_rev = f"r{chain.revision:03d}"
    allowed = ctx["allowed_cells"]
    eff_geo_ops = max(max_geo_ops, len(chain.ops or [])) if cls == "visual" else max_geo_ops
    structural = cls in ("class1", "class2") and ctx["kind"] in rp.STRUCTURAL_KINDS
    if structural:
        cap_txt = (f"（追加与改写上限以上面的计数规则为准，不再另按 {max_geo_ops} 个几何改动封顶；"
                   f"纯换色 ≤{max_color_ops} 个算子；")
    else:
        cap_txt = f"（几何参数改动 ≤{eff_geo_ops} 个算子，纯换色 ≤{max_color_ops} 个算子；"
    ops_hint = ""
    if chain.track == "ops" and chain.ops:
        cur_ops_json = json.dumps(chain.ops, ensure_ascii=False)
        ops_hint = (
            f"\n当前有效版本 {base_rev} 的算子列表 currentOps（共 {len(chain.ops)} 个）：\n{cur_ops_json}\n"
            f"首选算子级修订（注意 action 必须写 \"revise_ops\"，禁止写 \"save_design3\"）："
            f"输出 {{\"action\":\"revise_ops\",\"args\":{{\"baseRevision\":\"{base_rev}\","
            f"\"ops\":[基于上面 currentOps 原样复制并仅修改目标算子后的完整列表]}}}}{cap_txt}"
            f"其余无关算子必须一字不改原样保留；防删核心不得丢失；"
            "悬挑不稳时增设反斜坡托架或向主体内侧延伸锚定，严禁削平核心特征）。\n其次逐格补丁："
        )
    err_shown = dc.cells_to_lists(ctx["error_cells"], cap=64)
    allow_shown = dc.cells_to_lists(allowed, cap=400)
    instr = (
        f"阶段：revise_design（只接受 action=\"revise_ops\" 或 \"revise_design\"）。"
        f"当前有效版本 {base_rev}，baseRevision 必须写 \"{base_rev}\"。\n"
        f"失败类型 failureKind={ctx['kind']}：{ctx['message']}\n"
        f"错误格 errorCells（展示 {len(err_shown)} / 共 {len(ctx['error_cells'])}）："
        f"{json.dumps(err_shown, ensure_ascii=False)}。列表不全时以总格数为准。\n"
        f"结构化建议：\n{rh.format_for_prompt(failure, chain.model)}\n"
        f"{rp.revision_clause(cls, ctx['kind'])}\n{ops_hint}"
        f"allowedCells（展示 {len(allow_shown)} / 共 {len(allowed)} 格）："
        f"{json.dumps(allow_shown, ensure_ascii=False)}。列表不全，越界以拒收原因为准。\n"
        f"防删核心格（不可删除）：{json.dumps(dc.cells_to_lists(chain.frozen_cells, cap=64), ensure_ascii=False)}。"
    )
    patch_ctx = {
        "base_revision": base_rev, "layers": chain.layers,
        "allowed_cells": allowed, "frozen_cells": chain.frozen_cells,
        "assignment": chain.assignment or {},
        "part_ids": [p["id"] for p in chain.parts_norm],
        "default_part": chain.default_part or "",
    }
    chain.begin_phase("revise", instr)
    chain.emit("info", f"{cls} 修订最多 {max_calls} 次模型调用（协议拒绝计入调用，不计入已接受修订）")
    try:
        while True:
            r = chain.model_turn({"revise_design", "revise_ops"}, chain._check_revise_schema,
                                 reasoning_effort="low", request_limit=max_calls)
            if not r:
                continue
            action, patch = r
            if action == "revise_ops":
                if wops.apply_ops_revision(chain, patch, eff_geo_ops, max_color_ops):
                    chain.counts[count_key] += 1
                    chain.failures.append({"kind": ctx["kind"], "stage": f"revise_{cls}",
                                           "message": ctx["message"][:300]})
                    chain._version_design(note=f"{cls} 算子级修订（{ctx['kind']}）")
                    chain.emit("revise", f"{cls} 算子级修订已接受（{ctx['kind']}），当前版本 r{chain.revision:03d}")
                    return
                continue
            if chain.track == "ops":
                # ops 轨道的 chain.layers 是主链层的紧凑副本（没有 y 键）；edits 的 y 是层序号，
                # dc.apply_edits 也按序号索引。按 y 建映射会在真实 E2E 冒烟里抛 KeyError 'y'。
                layers_by_y = {i: L for i, L in enumerate(chain.layers)}
                for e in (patch.get("edits") or []):
                    if isinstance(e, dict) and e.get("color"):
                        L_ref = layers_by_y.get(e.get("y")) or {}
                        if not L_ref.get("colorRows") and not L_ref.get("color"):
                            e.pop("color", None)
            perrs, _meta = dc.patch_errors(patch, patch_ctx)
            if perrs:
                chain.record_protocol_error("patch_policy", perrs[0])
                chain.observe("补丁被拒收（保留上一有效版本，不计修订次数）：\n- " + "\n- ".join(perrs[:8]))
                continue
            aerrs, new_layers = dc.apply_edits(chain.layers, patch.get("edits") or [])
            if aerrs:
                chain.record_protocol_error("apply_edits", aerrs[0])
                chain.observe("补丁应用失败：\n- " + "\n- ".join(aerrs[:8]))
                continue
            errs, new_model, _warns = validate_design_syntax(
                {**(chain.design_meta or {}), "layers": new_layers},
                require_layer_color=(chain.track != "ops"),
            )
            if errs:
                chain.record_protocol_error("patch_syntax", errs[0])
                chain.observe("补丁后的设计未通过语法校验：\n- " + "\n- ".join(errs[:8]))
                continue
            new_solid = dc.solid_cells_of(new_model)
            new_assign = {c: pid for c, pid in (chain.assignment or {}).items() if c in new_solid}
            new_assign.update((_meta or {}).get("new_part_assign") or {})
            frozen = ({p["id"]: p["core_cells"] for p in chain.parts_norm if p["required"]}
                      if chain.cores_frozen else None)
            berrs, bound = pb.rebuild_parts(chain.parts_norm, new_assign, new_model, frozen=frozen)
            if berrs:
                chain.record_protocol_error("patch_parts", berrs[0])
                chain.observe("补丁后的设计破坏了部位契约：\n- " + "\n- ".join(berrs[:8]))
                continue
            chain.counts[count_key] += 1
            chain.layers = [{"module": L["module"][0], "color": L.get("color"),
                             "rows": L["rows"], "colorRows": L.get("colorRows")}
                            for L in new_model["layers"]]
            chain.assignment = bound["assign"]
            chain.parts_norm = bound["parts"]
            chain.model = new_model
            if chain.track == "ops":
                chain.ops = None
            chain._record_parts()
            rp.remember_cell_revision(chain, cls, ctx["kind"], len(patch.get("edits") or []))
            chain.failures.append({"kind": ctx["kind"], "stage": f"revise_{cls}",
                                   "message": ctx["message"][:300]})
            chain._version_design(note=f"{cls} 修订（{ctx['kind']}）")
            chain.emit("revise", f"{cls} 修订已接受（{ctx['kind']}），当前版本 r{chain.revision:03d}")
            return
    except failure_cls as gf:
        if gf.kind == "protocol":
            chain.emit("error", f"修订请求打满：{gf}")
            raise rp.RevisionBudgetExhausted(cls, failure, rp.budget_reason(cls, "request")) from gf
        raise
