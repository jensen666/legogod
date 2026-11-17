# ============================================================
# 工作流算子轨道辅助：三维算子受理、突显门禁重绘与几何/颜色分档修订校验
#
# 候选草稿局部纠错：
# 编译与部位绑定成功、但门禁未过的候选保存为内存草稿（r000 基线，不递增正式
# revision、不生成产物），门禁打回优先反馈 currentOps 引导 revise_ops 局部纠错。
# 「编译—绑定—门禁」由 validate_ops_candidate 单源实现，accept_design3、
# apply_ops_revision 与草稿修订共用，避免两套分叉逻辑。
# ============================================================
from collections import Counter
import json
import re
import time

from . import design_contract as dc
from . import draw_budget as dbudget
from . import gate_replay
from . import geometry_contract as gc
from . import part_binding as pb
from . import part_gate
from . import revision_policy as rp
from . import voxel_ops as vo
from .agent import (MAX_LAYERS, MAX_REVISE_COLOR_OPS, MAX_REVISE_OPS, MAX_VOX, MAX_WD,
                    validate_design_syntax)

DRAFT_BASE_REVISION = "r000"   # 草稿基线：尚未成为正式版本的候选稿


def _run_contract(chain, model):
    """几何契约检查入口（开关关闭时返回空，不改行为；结果落 chain.contract_checks）。

    对测试用的最小 fake chain 兼容：plan/desc/clock/contract_checks 都走 getattr 缺省。
    """
    if not gc.contract_enabled():
        return []
    clock = getattr(chain, "clock", None) or time.monotonic
    started = clock()
    target = gc.target_blocks_for(getattr(chain, "plan", None), getattr(chain, "desc", None))
    violations = gc.check_design(model, target_blocks=target)
    checks = getattr(chain, "contract_checks", None)
    if checks is not None:
        checks.append(gc.contract_check_record(chain, violations, model, target, started))
    return [v for v in violations if v.get("kind") != "contract_error"]


def _reject_by_contract(chain, args, bundle, violations):
    """契约违规的统一打回：存草稿（门禁干净、契约未过）+ 数值反馈，不晋升、不计修订。"""
    msgs = [v.get("message", "") for v in violations]
    chain.record_rejection("contract", msgs[0], part_ids=[])
    chain.failures.append({"kind": "contract", "stage": "draw_contract",
                           "errors": [m[:200] for m in msgs[:8]]})
    _draft_contract_feedback(chain, save_draw_draft(chain, args, bundle, contract_errors=violations))
    return False


def _draft_contract_feedback(chain, draft):
    """契约打回的反馈（文本构造在 geometry_contract，与门禁反馈风格同源）。"""
    chain.observe(gc.rejection_text(draft.get("contract_errors") or [], DRAFT_BASE_REVISION))


def check_plan_schema(chain, args):
    """校验 plan_design 阶段的规划结构与部位声明。"""
    if not isinstance(args, dict):
        return ["args 必须是对象"]
    errs = []
    feats = [str(f).strip() for f in (args.get("features") or []) if str(f).strip()]
    if not feats:
        errs.append("features 几何特征清单缺失")
    g = args.get("grid") if isinstance(args.get("grid"), dict) else {}
    try:
        gw, gd = int(g.get("w")), int(g.get("d"))
    except (TypeError, ValueError):
        gw = gd = 0
    try:
        layers_n = int(args.get("layers"))
    except (TypeError, ValueError):
        layers_n = 0
    try:
        est = int(args.get("estimatedVoxels"))
    except (TypeError, ValueError):
        est = 0
    if not (2 <= gw <= MAX_WD and 2 <= gd <= MAX_WD):
        errs.append(f"grid {gw}x{gd} 不合法（2..{MAX_WD}）")
    if not (2 <= layers_n <= MAX_LAYERS):
        errs.append(f"层数 {layers_n} 不合法（2..{MAX_LAYERS}）")
    if not (50 <= est <= MAX_VOX):
        errs.append(f"estimatedVoxels {est} 不合理（50~{MAX_VOX}）")
    perrs, parts_norm = dc.parse_parts_decl(args.get("parts"), chain.desc)
    if perrs:
        errs += perrs
    else:
        chain._parsed_parts = parts_norm
    return errs


def check_save_schema(chain, args):
    """画图阶段双轨 Schema 校验（save_design3 算子协议 / save_design 二维画稿协议）。"""
    if isinstance(args, dict) and "ops" in args:
        return check_save3_schema(args, chain.plan, chain.parts_norm)
    errs, model, _warns = validate_design_syntax(args)
    if errs:
        return errs
    pg = (chain.plan or {}).get("grid") or {}
    if (model["grid"]["w"], model["grid"]["d"]) != (pg.get("w"), pg.get("d")):
        errs.append(f"网格 {model['grid']['w']}x{model['grid']['d']} 与规划 {pg.get('w')}x{pg.get('d')} 不一致")
    if len(model["layers"]) != (chain.plan or {}).get("layers"):
        errs.append(f"层数 {len(model['layers'])} 与规划 {(chain.plan or {}).get('layers')} 不一致")
    if chain.mode == "fidelity" and not model.get("hasVoxelColors"):
        errs.append("高保真模式要求逐体素配色：每层提供 colorRows 或 colorPatches")
    lerrs, _, _ = pb.parse_part_labels(args, chain.parts_norm, model)
    if lerrs:
        errs += lerrs
    return errs


def check_revise_schema(chain, args):
    """修订阶段双轨 Schema 校验（revise_ops 算子修订 / revise_design 逐格补丁）。"""
    if not isinstance(args, dict):
        return ["补丁必须是对象"]
    errs = []
    if "ops" in args:
        if not isinstance(args.get("ops"), list) or not args["ops"]:
            return ["revise_ops 的 ops 必须是非空列表（完整的新算子列表）"]
        part_ids = [p["id"] for p in (chain.parts_norm or [])]
        errs += vo.validate_ops_schema(args["ops"], chain.default_part, part_ids)
        base = str(args.get("baseRevision") or "").strip()
        if not re.fullmatch(r"r\d{3}", base):
            errs.append("baseRevision 必须形如 r001")
        return errs
    edits = args.get("edits")
    if not isinstance(edits, list) or not edits:
        errs.append("补丁缺少 edits（逐格修改）或 ops（算子级修订）：不能整模重画")
    for k in ("layers", "grid", "rows", "colorRows", "parts", "boxes", "coreBoxes"):
        if k in args:
            errs.append(f"补丁不能携带 {k}——逐格修改用 edits，按部件调整用 ops（revise_ops）")
    base = str(args.get("baseRevision") or "").strip()
    if not re.fullmatch(r"r\d{3}", base):
        errs.append("baseRevision 必须形如 r001")
    return errs


def check_label_schema(chain, args):
    """label_parts 只补标注阶段的 Schema 校验。"""
    errs, _, _ = pb.parse_part_labels(args, chain.parts_norm, chain.model)
    for k in ("layers", "grid", "rows", "colorRows", "edits", "parts"):
        if k in args:
            errs.append(f"标注阶段不能携带 {k}——画稿保留，不要重新 save_design")
    return errs


def check_save3_schema(args, plan, parts_norm):
    """校验 save_design3 的顶层结构与算子静态 Schema。"""
    if not isinstance(args, dict):
        return ["save_design3 的 args 必须是对象"]
    errs = []
    if not str(args.get("slug") or "").strip():
        errs.append("缺少 slug（ascii-id）")
    feats = [str(f).strip() for f in (args.get("features") or []) if str(f).strip()]
    if not feats:
        errs.append("features 几何特征清单缺失")
    ops = args.get("ops")
    if not isinstance(ops, list) or not ops:
        errs.append("ops 缺失或为空：至少需要一个构造算子")
        return errs
    part_ids = [p["id"] for p in (parts_norm or [])]
    default_part = str(args.get("defaultPart") or "").strip()
    if default_part and part_ids and default_part not in part_ids:
        errs.append(f"defaultPart「{default_part}」不是规划里的部位（可用：{'、'.join(part_ids)}）")
    errs += vo.validate_ops_schema(ops, default_part, part_ids)
    return errs


def draw_allowed_actions(chain):
    """画图阶段可接受的 action：有候选草稿时只接受算子轨道纠错（save_design3/revise_ops）。"""
    if chain.draft is not None:
        return {"save_design3", "revise_ops"}
    return {"save_design3", "save_design"}


def check_draw_schema(chain, args, action=None):
    """画图阶段 Schema 分发：按 action 区分草稿修订（revise_ops）与 save 协议。

    action 缺省时（兼容旧直接调用）按 args 键推断；显式 action 优先，
    避免 save_design3 带杂散 baseRevision 被误路由进草稿 Schema。
    """
    is_revise = action == "revise_ops" or (
        action is None and isinstance(args, dict) and "baseRevision" in args)
    if is_revise:
        if chain.draft is None:
            return ["当前没有已编译的候选草稿，draw 阶段不接受 revise_ops——请先输出 save_design3"]
        return check_draft_revise_schema(chain, args)
    return check_save_schema(chain, args)


def check_draft_revise_schema(chain, args):
    """草稿局部纠错（revise_ops，基线 r000）的 Schema 校验。"""
    if not isinstance(args, dict):
        return ["revise_ops 的 args 必须是对象"]
    if not isinstance(args.get("ops"), list) or not args["ops"]:
        return ["revise_ops 的 ops 必须是非空列表（完整的新算子列表）"]
    errs = []
    part_ids = [p["id"] for p in (chain.parts_norm or [])]
    errs += vo.validate_ops_schema(args["ops"], chain.draft["default_part"], part_ids)
    base = str(args.get("baseRevision") or "").strip()
    if base != DRAFT_BASE_REVISION:
        errs.append(f"草稿修订的 baseRevision 必须是 \"{DRAFT_BASE_REVISION}\""
                    f"（草稿尚未成为正式版本），实际 {base or '(空)'!r}")
    for k in ("edits", "layers", "grid", "rows", "colorRows"):
        if k in args:
            errs.append(f"草稿修订不能携带 {k}——只接受完整算子列表 ops")
    return errs


def _strip_color_for_geo(op):
    """剥离算子的纯颜色字段，提取纯几何结构指纹（用于区分几何改动与纯换色改动）。"""
    if not isinstance(op, dict):
        return op
    if op.get("op") == "mirror":
        return {"op": "mirror", "axis": op.get("axis"),
                "ops": [_strip_color_for_geo(sub) for sub in (op.get("ops") or [])]}
    return {k: v for k, v in op.items() if k != "color"}


def count_ops_changes(old_ops, new_ops):
    """分别统计算子修订中的 (几何变更算子数, 纯颜色/paint变更算子数)。

    采用多重集对称差（max(新增数, 删除数)），使修改 1 个算子的尺寸计为 1 次几何变更，
    仅修改算子 color 字段或调整 paint 算子计为颜色变更而不消耗几何改动配额。
    """
    old_geo = Counter(
        json.dumps(_strip_color_for_geo(op), ensure_ascii=False, sort_keys=True)
        for op in old_ops if isinstance(op, dict) and op.get("op") != "paint"
    )
    new_geo = Counter(
        json.dumps(_strip_color_for_geo(op), ensure_ascii=False, sort_keys=True)
        for op in new_ops if isinstance(op, dict) and op.get("op") != "paint"
    )
    geo_added = sum((new_geo - old_geo).values())
    geo_removed = sum((old_geo - new_geo).values())
    geo_changes = max(geo_added, geo_removed)

    old_full = Counter(json.dumps(op, ensure_ascii=False, sort_keys=True) for op in old_ops)
    new_full = Counter(json.dumps(op, ensure_ascii=False, sort_keys=True) for op in new_ops)
    total_changes = max(sum((new_full - old_full).values()), sum((old_full - new_full).values()))
    color_changes = max(0, total_changes - geo_changes)
    return geo_changes, color_changes


def validate_ops_candidate(chain, ops, *, name, slug, features, notes, default_part,
                           grid=None, n_layers=None, frozen_cells=None):
    """公共「编译—绑定—门禁」候选校验（accept_design3 / apply_ops_revision / 草稿修订共用）。

    返回 (errors, stage, bundle|None)：stage ∈ compile|fidelity_color|parts_bind|validated；
    bundle 携带 model/assign/bound/gate_errs/gate_cells/bad_part_ids（门禁错误不视为编译失败）。
    算子级 role 覆盖只在候选内部生效（写入局部 decl 参与 rebuild），不写回 chain.parts_norm——
    被拒候选不得向主链状态泄漏角色修正（评审 P2）。
    """
    if grid is None:
        pg = (chain.plan or {}).get("grid") or {}
        grid = (int(pg.get("w", 0)), int(pg.get("d", 0)))
        n_layers = int((chain.plan or {}).get("layers") or 0)
    elif n_layers is None:
        n_layers = len(chain.model["layers"])
    part_ids = [p["id"] for p in (chain.parts_norm or [])]
    errs, result = vo.compile_ops(
        ops, grid[0], grid[1], n_layers,
        default_part=default_part, part_ids=part_ids,
        required_ids=[p["id"] for p in (chain.parts_norm or []) if p["required"]],
        frozen_cells=frozen_cells, name=name, slug=slug, features=features, notes=notes,
    )
    if errs:
        return errs, "compile", None
    model = result["model"]
    if chain.mode == "fidelity" and not model.get("hasVoxelColors"):
        return ["高保真模式缺少显式算子颜色"], "fidelity_color", None
    role_overrides = result.get("role_overrides") or {}
    decl = chain.parts_norm
    if role_overrides:
        decl = []
        for p in chain.parts_norm:
            q = dict(p)
            if p["id"] in role_overrides and role_overrides[p["id"]] != (p.get("role") or "solid"):
                q["role"] = role_overrides[p["id"]]
                chain.emit("info", f"部位 {p['id']} 的角色按算子声明修正为 {q['role']}")
            decl.append(q)
    frozen_map = ({p["id"]: p["core_cells"] for p in chain.parts_norm if p["required"]}
                  if frozen_cells is not None else None)
    berrs, bound = pb.rebuild_parts(decl, result["assign"], model, frozen=frozen_map)
    if berrs:
        return berrs, "parts_bind", None
    gate_errs, gate_cells = part_gate.check_parts(model, bound["parts"])
    bad_ids = sorted({bound["assign"][c] for c in gate_cells if c in bound["assign"]})
    return [], "validated", {"model": model, "assign": bound["assign"], "ops": result["ops"],
                             "bound": bound, "gate_errs": gate_errs, "gate_cells": gate_cells,
                             "bad_part_ids": bad_ids}


def save_draw_draft(chain, args, bundle, contract_errors=None):
    """把编译通过但门禁/契约未过的候选保存为内存草稿（不递增正式 revision、不生成产物）。

    历史最佳草稿按冻结的结构化排序键选择（gate_replay.rank_key_gate：先受影响部位数、
    再错误格总数、再严重度；平手保留先出现的，稳定），不再只比较错误字符串条数；
    每次落草稿同步维护 chain.draft_ranking 审计记录。
    contract_errors 非空表示门禁干净但几何契约未过（签名前缀 contract:，供动态预算
    的重复检测与进展判定使用）。
    """
    if bundle["gate_errs"]:
        signature = "gate:" + dbudget.fingerprint("gate", bundle["gate_errs"],
                                                  bundle["bad_part_ids"])["digest"]
    elif contract_errors:
        signature = "contract:" + dbudget.fingerprint(
            "contract", [v.get("message", "") for v in contract_errors])["digest"]
    else:
        signature = dbudget.fingerprint("gate", [], [])["digest"]
    chain.draft = {
        "args": args, "ops": bundle["ops"], "model": bundle["model"],
        "assign": bundle["assign"], "parts_norm": bundle["bound"]["parts"],
        "default_part": str(args.get("defaultPart") or "").strip() or (
            chain.parts_norm[0]["id"] if chain.parts_norm else None),
        "gate_errors": list(bundle["gate_errs"]), "gate_cells": list(bundle["gate_cells"]),
        "bad_part_ids": bundle["bad_part_ids"],
        "contract_errors": [dict(v) for v in (contract_errors or [])],
        "rank": gate_replay.rank_key_gate(
            bundle["gate_errs"], bundle["gate_cells"],
            gate_replay.cells_part_map(bundle["bound"]["parts"])),
        "signature": signature,
    }
    gate_replay.record_draft_ranking(chain, chain.draft)
    return chain.draft


def _draft_gate_feedback(chain, draft, max_redraws=None):
    """门禁打回的统一反馈（文本构造在 gate_replay，与重放/排序规则同源）。"""
    if max_redraws is None:
        max_redraws = getattr(chain, "max_redraws", 0)
    chain.observe(gate_replay.draft_gate_feedback_text(
        draft, max_redraws, getattr(chain, "redraws", 0), DRAFT_BASE_REVISION, MAX_REVISE_OPS))


def promote_candidate(chain, model, bound, ops, default_part, degraded_gate_errs=None):
    """把通过门禁的候选（或预算耗尽后带门禁记录降级的草稿）写入主链状态。

    降级时先冻结门禁基线 chain.gate_degraded_baseline（受影响部位数/错误格总数/
    错误类型），供后续修订的回归检测与运行记录使用，再清空草稿状态。
    """
    chain.track = "ops"
    chain.ops = ops
    chain.default_part = default_part
    chain.assignment = bound["assign"]
    chain.parts_norm = bound["parts"]
    chain.design_meta = {"name": model["name"], "slug": model["slug"],
                         "notes": model["notes"], "features": model["features"]}
    chain.layers = [{"module": L["module"][0], "color": L.get("color"),
                     "rows": L["rows"], "colorRows": L.get("colorRows")}
                    for L in model["layers"]]
    chain.model = model
    if degraded_gate_errs:
        # 基线必须取真实降级稿的错误格/失败部位/完整错误，不能用 chain.gate_errors 的截断副本
        gate_replay.freeze_degraded_baseline(chain, degraded_gate_errs)
    chain.draft = None
    chain.best_draft = None
    if degraded_gate_errs:
        chain.gate_errors = [e[:200] for e in degraded_gate_errs[:8]]
        chain.failures.append({"kind": "gate", "stage": "draw_degraded",
                               "errors": chain.gate_errors})
        chain.emit("error", "⚠ draw 纠错预算用尽，门禁仍未全部通过，带门禁记录降级继续"
                   "（本次不计完整成功）：" + "；".join(degraded_gate_errs[:3]))
    ascii_lines = [f"{model['name']} 设计（三维算子 {len(chain.ops)} 个编译）："
                   f"{model['grid']['w']}×{model['grid']['d']}，{len(model['layers'])} 层，"
                   f"{model['totalVoxels']} 体素，斜面 {model['slopeVoxels']}"]
    for L in model["layers"]:
        ascii_lines.append(f"y={L['y']}")
        ascii_lines += ["  " + row for row in L["rows"]]
    chain.emit("design", "\n".join(ascii_lines), {"design": model, "slug": model["slug"]})


def accept_design3(chain, args, max_redraws):
    """编译并校验 save_design3：通过部位契约与双角色突显门禁后写入主链状态。

    门禁未过时不再直接整稿打回：候选保存为草稿并反馈局部纠错要求；
    完整重绘机会由 max_redraws 约束（redraws 在 run_draw_phase 按实际整模重绘计数）。
    """
    errs, stage, bundle = validate_ops_candidate(
        chain, args.get("ops"),
        name=str(args.get("name") or "乐高模型"),
        slug=re.sub(r"[^a-z0-9-]+", "-", str(args.get("slug") or "model").lower()).strip("-") or "model",
        features=args.get("features"), notes=str(args.get("notes") or ""),
        default_part=str(args.get("defaultPart") or "").strip() or None,
    )
    if errs:
        chain.record_protocol_error({"compile": "compile_ops", "fidelity_color": "fidelity_color",
                                     "parts_bind": "parts_bind"}[stage], errs[0])
        if stage == "compile":
            chain.last_compile_reject = dbudget.fingerprint("compile", errs)
            chain.observe("算子编译失败（不保存、不推进状态）：\n- " + "\n- ".join(errs[:8])
                          + "\n请立即修正上述算子并重新输出完整 save_design3。")
        elif stage == "fidelity_color":
            chain.observe("高保真模式要求逐体素配色：请给几何算子带 color 或用 paint 涂装表面细节，"
                          "重新输出完整 save_design3。")
        else:
            chain.observe("算子编译结果破坏了部位契约：\n- " + "\n- ".join(errs[:8])
                          + "\n请修正后重新输出完整 save_design3。")
        return False
    if bundle["gate_errs"]:
        chain.record_rejection("gate", bundle["gate_errs"][0], part_ids=bundle["bad_part_ids"])
        chain.failures.append({"kind": "gate", "stage": "draw_draft",
                               "errors": [e[:200] for e in bundle["gate_errs"][:8]]})
        _draft_gate_feedback(chain, save_draw_draft(chain, args, bundle), max_redraws)
        return False
    contract_violations = _run_contract(chain, bundle["model"])
    if contract_violations:
        return _reject_by_contract(chain, args, bundle, contract_violations)
    promote_candidate(chain, bundle["model"], bundle["bound"], bundle["ops"],
                      str(args.get("defaultPart") or "").strip() or (
                          chain.parts_norm[0]["id"] if chain.parts_norm else None))
    return True


def apply_draft_revision(chain, patch):
    """校验并应用针对当前草稿的 revise_ops(r000) 局部纠错。

    返回 True 表示候选已通过门禁并晋升为正式设计（draw 阶段随之结束）；
    返回 False 表示仍需纠错：补丁被拒（草稿不变）或草稿已更新为最新候选。
    草稿修订不调用正式版本递增逻辑，也不生成产物。
    """
    draft = chain.draft
    base = str(patch.get("baseRevision") or "").strip()
    if base != DRAFT_BASE_REVISION:
        chain.record_protocol_error("stale_revision", f"baseRevision != {DRAFT_BASE_REVISION}")
        chain.observe(f"草稿修订基于 {base or '(空)'!r}，但草稿基线是 \"{DRAFT_BASE_REVISION}\""
                      f"（草稿尚未成为正式版本）——请基于当前草稿重新提交。")
        return False
    new_ops = patch.get("ops") or []
    geo_changed, color_changed = count_ops_changes(draft["ops"], new_ops)
    if geo_changed > MAX_REVISE_OPS:
        chain.record_protocol_error("ops_geo_cap", f"几何改动 {geo_changed} > {MAX_REVISE_OPS}")
        chain.observe(f"草稿修订改动了 {geo_changed} 个几何算子，超过单次几何上限 {MAX_REVISE_OPS}"
                      f"——请原样复制无关算子，只修正门禁指出的相关算子。")
        return False
    if color_changed > MAX_REVISE_COLOR_OPS:
        chain.record_protocol_error("ops_color_cap", f"颜色改动 {color_changed} > {MAX_REVISE_COLOR_OPS}")
        chain.observe(f"草稿修订纯换色改动了 {color_changed} 个算子，超过单次上限 {MAX_REVISE_COLOR_OPS}。")
        return False
    model = draft["model"]
    errs, stage, bundle = validate_ops_candidate(
        chain, new_ops, name=model["name"], slug=model["slug"],
        features=model.get("features"), notes=model.get("notes") or "",
        default_part=draft["default_part"],
        grid=(model["grid"]["w"], model["grid"]["d"]), n_layers=len(model["layers"]),
    )
    if errs:
        chain.record_protocol_error("draft_compile", errs[0])
        if stage == "compile":
            chain.last_compile_reject = dbudget.fingerprint("compile", errs)
        chain.observe("草稿修订重编译失败（草稿未变）：\n- " + "\n- ".join(errs[:8])
                      + "\n请基于当前草稿修正后重新提交（不得删除必需部位体素）。")
        return False
    if bundle["gate_errs"]:
        # 已降级（chain.gate_errors 非空）时，草稿修订也不得把门禁改得比冻结基线更差
        reason = gate_replay.chain_regression_reason(chain, bundle["gate_errs"],
                                                     bundle["gate_cells"],
                                                     bundle["bad_part_ids"])
        if reason:
            gate_replay.reject_gate_regression(chain, reason)
            return False
        chain.record_rejection("gate", bundle["gate_errs"][0], part_ids=bundle["bad_part_ids"])
        chain.failures.append({"kind": "gate", "stage": "draw_draft",
                               "errors": [e[:200] for e in bundle["gate_errs"][:8]]})
        _draft_gate_feedback(chain, save_draw_draft(chain, draft["args"], bundle))
        return False
    contract_violations = _run_contract(chain, bundle["model"])
    if contract_violations:
        return _reject_by_contract(chain, draft["args"], bundle, contract_violations)
    promote_candidate(chain, bundle["model"], bundle["bound"], bundle["ops"],
                      draft["default_part"])
    return True


def apply_ops_revision(chain, patch, max_geo_ops, max_color_ops):
    """校验并应用 revise_ops 算子级修订（严格区分几何改动与纯换色改动配额，保护冻结核心）。"""
    base_rev = f"r{chain.revision:03d}"
    if str(patch.get("baseRevision") or "").strip() != base_rev:
        chain.record_protocol_error("stale_revision", f"baseRevision != {base_rev}")
        chain.observe(f"补丁基于 {patch.get('baseRevision')!r}，但当前有效版本是 {base_rev}"
                      f"——版本过期，请基于当前版本重新提交。")
        return False
    new_ops = patch.get("ops") or []
    old_ops = chain.ops or []
    policy_err = rp.enforce_ops_policy(chain, old_ops, new_ops)
    if policy_err:
        chain.record_protocol_error("ops_policy", policy_err)
        chain.observe(policy_err + "（上一有效版本未变，不计修订次数）")
        return False
    geo_changed, color_changed = count_ops_changes(old_ops, new_ops)
    if not chain.revision_skip_geo_cap and geo_changed > max_geo_ops:
        chain.record_protocol_error("ops_geo_cap", f"几何改动 {geo_changed} > {max_geo_ops}")
        chain.observe(f"算子级修订改动了 {geo_changed} 个几何算子，超过单次几何上限 {max_geo_ops}"
                      f"——请原样复制无关算子，只修改需要调整的部件。")
        return False
    if color_changed > max_color_ops:
        chain.record_protocol_error("ops_color_cap", f"颜色改动 {color_changed} > {max_color_ops}")
        chain.observe(f"算子级修订纯换色改动了 {color_changed} 个算子，超过单次上限 {max_color_ops}。")
        return False

    errs, stage, bundle = validate_ops_candidate(
        chain, new_ops, name=chain.model["name"], slug=chain.model["slug"],
        features=chain.model.get("features"), notes=chain.model.get("notes") or "",
        default_part=chain.default_part,
        grid=(chain.model["grid"]["w"], chain.model["grid"]["d"]),
        n_layers=len(chain.model["layers"]),
        frozen_cells=chain.frozen_cells if chain.cores_frozen else None,
    )
    if errs:
        kind = {"compile": "revise_compile", "fidelity_color": "revise_compile",
                "parts_bind": "revise_parts"}[stage]
        chain.record_protocol_error(kind, errs[0])
        if stage == "compile":
            chain.last_compile_reject = dbudget.fingerprint("compile", errs)
        chain.observe("算子修订重编译失败（上一有效版本未变）：\n- " + "\n- ".join(errs[:8])
                      + "\n请修正后重新提交（不得删除防删核心体素）。")
        return False
    if bundle["gate_errs"]:
        if not chain.gate_errors:
            chain.record_protocol_error("revise_gate", bundle["gate_errs"][0])
            chain.observe("算子修订触发了部位突显门禁（上一有效版本未变）：\n- "
                          + "\n- ".join(bundle["gate_errs"][:6]) + "\n请修正相关算子后重新提交。")
            return False
        # 已降级：允许继承既有门禁错误继续真实求解，但不得增加错误部位/错误格/严重度
        reason = gate_replay.chain_regression_reason(chain, bundle["gate_errs"],
                                                     bundle["gate_cells"],
                                                     bundle["bad_part_ids"])
        if reason:
            gate_replay.reject_gate_regression(chain, reason)
            return False

    # 几何契约回归拦截：基线干净而修订引入违规时打回（基线已违规的降级流不拦，避免死锁）。
    contract_violations = _run_contract(chain, bundle["model"])
    if contract_violations and not _run_contract(chain, chain.model):
        msgs = [v.get("message", "") for v in contract_violations]
        chain.record_protocol_error("contract", msgs[0])
        chain.observe("算子修订违反几何契约（上一有效版本未变，不计修订次数）：\n- "
                      + "\n- ".join(msgs[:4])
                      + "\n请修正相关算子后重新提交（其余算子原样保留）。")
        return False

    rp.note_accepted_geo(chain, geo_changed, len(old_ops))
    chain.ops = new_ops
    rp.remember_revision(chain)
    chain.model = bundle["model"]
    chain.assignment = bundle["assign"]
    chain.parts_norm = bundle["bound"]["parts"]
    chain.layers = [{"module": L["module"][0], "color": L.get("color"),
                     "rows": L["rows"], "colorRows": L.get("colorRows")}
                    for L in bundle["model"]["layers"]]
    chain._record_parts()
    return True
