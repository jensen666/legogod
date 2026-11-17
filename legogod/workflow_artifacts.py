# ============================================================
# 工作流产物与版本化辅助：模型哈希、版本落盘、步骤文档与 3D 页面生成、
# 成功结果组装与运行记录落盘（失败归因与可观测性；版本只增不减、评审哈希、记录可信度）
# ============================================================
import hashlib
import json
import os
import sys

from . import fallback as fb
from . import revision_policy as rp
from .agent import gen_viz
from .geometry import SCHEMA_VERSION
from .jsonutil import to_jsonable  # noqa: F401 - 同名导出保持兼容（实现见 jsonutil）
from .paths import ROOT, subprocess_env


def code_version(subprocess_mod):
    """读取当前仓库 HEAD 的 git 短哈希；不可用时返回 'unknown'。"""
    try:
        out = subprocess_mod.run(["git", "rev-parse", "--short", "HEAD"], cwd=ROOT,
                                 capture_output=True, text=True, timeout=5)
        if out.returncode == 0:
            return out.stdout.strip()
    except Exception:
        pass
    return "unknown"


def model_hash(model_json):
    """计算模型 JSON 规范化 SHA-256 哈希，防止旧方案配新模型。"""
    canon = json.dumps(model_json, ensure_ascii=False, sort_keys=True)
    return hashlib.sha256(canon.encode("utf-8")).hexdigest()


def version_design(chain, artifacts_dir, note="", cause=None):
    """递增版本号并落盘当前设计产物（只增不减），返回如 'r004'。

    新版本号 = max(chain.revision, chain.max_revision) + 1：视觉回滚后 revision 虽回到旧稿，
    再落盘仍取新号并记录 parentRevision/rolledBackTo；同号不同哈希计入 versionOverwriteCount。
    """
    prev, max_rev = int(getattr(chain, "revision", 0) or 0), int(getattr(chain, "max_revision", 0) or 0)
    rev_n = max(prev, max_rev) + 1
    rev_id = f"r{rev_n:03d}"
    record = {**chain.model, "schemaVersion": SCHEMA_VERSION,
              "revision": rev_id, "runId": chain.run_id, "revisionNote": note}
    if chain.track == "ops":
        record["track"], record["ops"] = "ops", chain.ops
    digest = model_hash(record)
    old = chain.model_hashes.get(rev_id)
    if old is not None and old != digest:
        chain.version_overwrite_count = int(getattr(chain, "version_overwrite_count", 0)) + 1
        chain.emit("error", f"⚠ 版本 {rev_id} 已存在且内容不同：计入版本覆盖（必须为 0）")
    chain.revision = chain.max_revision = rev_n
    chain.model_hashes[rev_id] = digest
    rollback = getattr(chain, "rollback_pending", None)
    rollback_cause = rollback.get("cause") if isinstance(rollback, dict) else None
    entry = {"revision": rev_n, "modelHash": digest,
             "parentRevision": prev or None,
             "rolledBackTo": (rollback or {}).get("rolledBackTo") if isinstance(rollback, dict) else None,
             "cause": cause or rollback_cause or note or "version"}
    chain.revision_chain.append(entry)
    chain.rollback_pending = None
    os.makedirs(artifacts_dir, exist_ok=True)
    path = os.path.join(artifacts_dir, f"model_{chain.model['slug']}_{rev_id}_{chain.run_id}.json")
    with open(path, "w", encoding="utf-8") as f:
        json.dump(record, f, ensure_ascii=False, indent=2)
    chain.artifacts[f"model_{rev_id}"] = path
    chain.emit("version", f"设计版本 {rev_id} 已保存（{note}）：{os.path.basename(path)}",
               {"revision": chain.revision, "revisionId": rev_id, "path": path})
    return rev_id


def review_trust(chain):
    """评审/最终模型哈希 → (reviewed, final, stale, missing)；无有效评审不判过期、不伪造。"""
    state = getattr(chain, "review_state", None)
    available = isinstance(state, dict) and bool(state.get("ok"))
    reviewed = (state.get("modelHash") or getattr(chain, "reviewed_model_hash", None)
                if available else None)
    model = getattr(chain, "model", None)
    try:
        final = model_hash(model) if isinstance(model, dict) else None
    except (TypeError, ValueError):
        final = None
    stale = bool(reviewed and final and reviewed != final)
    return reviewed, final, stale, not bool(reviewed)


def finalize_review_trust(chain):
    """落定评审/最终哈希；最终稿与评审稿不同则标 review_stale（不得给高保真成功）。"""
    reviewed, final, stale, _missing = review_trust(chain)
    chain.reviewed_model_hash = reviewed
    chain.final_model_hash = final
    chain.review_stale = stale
    if stale and getattr(chain, "review_flag", None) is None:
        chain.review_flag = "review_stale"
    elif not stale and getattr(chain, "review_flag", None) == "review_stale":
        chain.review_flag = None


_SCALE_KEYS = ("targetBlocks", "estimatedVoxels", "estimatedParts", "actualVoxels",
               "actualParts", "bricks", "targetBlocksRatio", "voxelsPerPiece", "partRatio")


def scale_metrics(chain, pieces=None):
    """C.1 规模指标（plan_scale.metrics 接线）；返回 (字段, 原因)。

    2026-11-03 复核修正：C 策略回退后规划不强制 targetBlocks，指标从需求原文补出目标块数，
    并用同一 actualParts 重算 targetBlocksRatio，保证 run/job/页面/E2E 同源。
    """
    plan = getattr(chain, "plan", None)
    if plan is None:
        return None, "没有规划，未计算规模指标"
    model = getattr(chain, "model", None)
    try:
        from . import plan_scale
    except ImportError:
        return None, "plan_scale 模块未就绪，未计算规模指标"
    desc = getattr(chain, "desc", "") or ""
    try:
        data = plan_scale.metrics(plan, model, pieces=pieces, desc=desc)
    except Exception as exc:  # noqa: BLE001 - 记录不得影响任务结果
        return None, f"规模指标计算异常：{type(exc).__name__}: {exc}"[:200]
    if not isinstance(data, dict):
        return None, "规模指标返回非对象"
    out = {key: data.get(key) for key in _SCALE_KEYS}
    out["bricks"] = pieces if out["bricks"] is None else out["bricks"]
    pieces_n = out["actualParts"] if out["actualParts"] is not None else out["bricks"]
    if out["targetBlocksRatio"] is None and out["targetBlocks"] and pieces_n is not None:
        out["targetBlocksRatio"] = pieces_n / out["targetBlocks"]
    return out, None


def record_trust_fields(chain, pieces=None):
    """A.2/A.3 记录可信度字段（run 记录与 job result 共用；缺数据 null + 原因，不猜测）。"""
    replay, replay_reason = fb.final_gate_replay(chain)
    ranking, ranking_reason = fb.draft_ranking(chain)
    metrics, metrics_reason = scale_metrics(chain, pieces)
    reviewed, final, stale, missing = review_trust(chain)
    quota, quota_mode = fb.quota_fields(chain)
    return {
        "finalGateReplay": replay, "finalGateReplayReason": replay_reason,
        "reviewedModelHash": reviewed, "finalModelHash": final,
        "reviewStale": stale, "reviewHashMissing": missing,
        "versionOverwriteCount": int(getattr(chain, "version_overwrite_count", 0) or 0),
        "revisionChain": [dict(e) for e in (getattr(chain, "revision_chain", None) or [])],
        "draftRanking": ranking, "draftRankingReason": ranking_reason,
        "gateDegradedBaseline": fb.gate_degraded_baseline(chain),
        "quotaMode": quota_mode, "quota": quota,
        "scaleMetrics": metrics, "scaleMetricsReason": metrics_reason,
        "chainOrder": str(getattr(chain, "chain_order", "default") or "default"),
        "structuralCandidates": fb.structural_candidate_record(chain)}


def make_artifacts(chain, sol, artifacts_dir, viz_dir, subprocess_mod, failure_cls):
    """落盘方案 JSON（含模型哈希回读校验）、生成拼装步骤 Markdown 与 3D 交互页面。"""
    chain.check_cancel()
    rev_id = f"r{chain.revision:03d}"
    slug = chain.model["slug"]
    mh = chain.model_hashes.get(rev_id) or model_hash(
        {**chain.model, "schemaVersion": SCHEMA_VERSION, "revision": rev_id, "runId": chain.run_id}
    )
    record = {**sol, "schemaVersion": SCHEMA_VERSION, "modelHash": mh, "runId": chain.run_id,
              "revision": rev_id, "validation": (sol.get("validation") or {})}
    os.makedirs(artifacts_dir, exist_ok=True)
    solution_path = os.path.join(artifacts_dir, f"solution_{slug}_{rev_id}_{chain.run_id}.json")
    with open(solution_path, "w", encoding="utf-8") as f:
        json.dump(record, f, ensure_ascii=False, indent=2)
    with open(solution_path, encoding="utf-8") as f:
        if json.load(f).get("modelHash") != mh:
            raise failure_cls("方案模型哈希校验失败（内部错误）", kind="internal", stage="artifacts")

    md_path = os.path.join(artifacts_dir, f"拼装步骤_{slug}_{rev_id}_{chain.run_id}.md")
    timeout = max(5.0, chain.remaining_hard() - 2)
    try:
        proc = subprocess_mod.run(
            [sys.executable, "-m", "legogod.make_steps",
             chain.artifacts[f"model_{rev_id}"], solution_path, md_path],
            check=False, cwd=ROOT, env=subprocess_env(), timeout=timeout,
            capture_output=True, text=True, encoding="utf-8", errors="replace",
        )
    except subprocess_mod.TimeoutExpired:
        raise failure_cls("步骤文档生成超时（产物预算 30 秒）", kind="artifact", stage="artifacts") from None
    if proc.returncode != 0:
        raise failure_cls(f"步骤文档生成失败：{(proc.stderr or proc.stdout or '')[-300:]}",
                          kind="artifact", stage="artifacts")

    viz_path = None
    if os.path.isfile(os.path.join(ROOT, "web", "shell.html")):
        viz_path = os.path.join(viz_dir, f"lego-{slug}_{rev_id}_{chain.run_id}.html")
        try:
            gen_viz(chain.model, record, viz_path)
        except Exception as e:
            chain.emit("error", f"⚠ 3D 可视化生成失败（不影响模型/方案/步骤产物）：{e}")
            viz_path = None

    for _key, path in (("solution", solution_path), ("md", md_path)):
        if not os.path.isfile(path) or os.path.getsize(path) == 0:
            raise failure_cls(f"产物缺失：{path}", kind="artifact", stage="artifacts")
    if viz_path and not os.path.isfile(viz_path):
        raise failure_cls("产物缺失：3D 可视化页面", kind="artifact", stage="artifacts")

    chain.artifacts[f"solution_{rev_id}"] = solution_path
    chain.artifacts[f"md_{rev_id}"] = md_path
    if viz_path:
        chain.artifacts[f"viz_{rev_id}"] = viz_path
    return {"solution": solution_path, "md": md_path, "viz": viz_path, "modelHash": mh}


def failure_fields(chain, elapsed_s):
    """失败结果里与成功结果对齐的修订、评审和计数（含 A.2/A.3 可信度字段）。"""
    finalize_review_trust(chain)
    fields = record_trust_fields(chain)
    return {
        "revision": chain.revision, "counts": dict(chain.counts),
        "failures": list(chain.failures), "protocol_errors": list(chain.protocol_errors),
        "review": (chain.review_state or {}).get("parsed") or {},
        "review_flag": chain.review_flag, "review_stale": bool(chain.review_stale),
        "revisionIncomplete": bool(getattr(chain, "revision_incomplete", False)),
        "revisionIncompleteReason": getattr(chain, "revision_incomplete_reason", None),
        "revisionAccounting": rp.accounting(chain),
        "elapsed_s": round(elapsed_s, 1),
        **fields,
    }


def success_result(chain, out, elapsed_s):
    """成功结果的对外字段组装（评审/门禁/修订计数、产物清单与可信度字段）。"""
    sol, arts = out["sol"], out["artifacts"]
    validation = sol.get("validation") or {}
    finalize_review_trust(chain)
    fields = record_trust_fields(chain, len(sol["steps"]))
    return {
        "ok": True, "error": None,
        "name": chain.model["name"], "slug": chain.model["slug"],
        "grid": chain.model["grid"], "layers": len(chain.model["layers"]),
        "voxels": chain.model["totalVoxels"], "revision": chain.revision,
        "pieces": len(sol["steps"]), "attempts": sol.get("attempts", 1),
        "usage": sol.get("usage") or {}, "colors": sol.get("colors") or {},
        "colorFallbacks": sol.get("colorFallbacks") or [],
        "validation": validation, "stability": validation.get("stability"),
        "model_path": os.path.basename(chain.artifacts.get(f"model_r{chain.revision:03d}") or ""),
        "solution_path": os.path.basename(arts["solution"]),
        "md_path": os.path.basename(arts["md"]),
        "viz_file": os.path.basename(arts["viz"]) if arts.get("viz") else None,
        "model_hash": arts.get("modelHash"),
        "artifacts": {k: os.path.basename(v) for k, v in chain.artifacts.items()},
        "review": (chain.review_state or {}).get("parsed") or {},
        "review_sheet": (chain.review_state or {}).get("sheet"),
        "review_unavailable": chain.review_flag == "review_unavailable",
        "review_failed": chain.review_flag == "review_failed",
        "review_flag": chain.review_flag,
        "review_stale": bool(chain.review_stale),
        "gate_failed": bool(chain.gate_errors), "gate_errors": chain.gate_errors or [],
        "track": chain.track, "counts": dict(chain.counts),
        "revisionIncomplete": bool(chain.revision_incomplete),
        "revisionIncompleteReason": chain.revision_incomplete_reason,
        "revisionAccounting": rp.accounting(chain),
        "failures": list(chain.failures), "protocol_errors": list(chain.protocol_errors),
        "elapsed_s": round(elapsed_s, 1),
        **fields,
    }


_STRUCTURAL_KINDS = frozenset({
    "support", "connectivity", "disconnected", "suspension", "coverage",
})


def _cell_list(raw):
    """把失败里的格子收成 (x,y,z) 列表。格式不对就返回 None，不猜测补齐。"""
    if not isinstance(raw, (list, tuple, set)):
        return None
    out = []
    for item in raw:
        if not isinstance(item, (list, tuple)) or len(item) != 3:
            return None
        try:
            out.append((int(item[0]), int(item[1]), int(item[2])))
        except (TypeError, ValueError):
            return None
    return out


def _full_cells(raw):
    """非空的合法格子才算全量窗口。空列表和截断提示都不是窗口。"""
    return _cell_list(raw) or None


def _as_lists(cells):
    return [list(c) for c in cells]


def _coverage_window(model, layer):
    """覆盖失败的允许范围是整层：窗口用该层全部实体格，不用截断提示格，缺层号不猜。"""
    if isinstance(layer, bool) or not isinstance(layer, int) or model is None:
        return None, None, "覆盖失败没有层号，不能把截断提示格当成全量窗口"
    try:
        from .workflow_phases import revision_ctx
        ctx = revision_ctx(model, {"kind": "coverage", "layer": layer, "cells": []})
    except (KeyError, TypeError, ValueError, IndexError) as exc:
        return None, None, f"覆盖失败无法按层算出允许范围：{exc}"
    solid = [tuple(c) for c in sorted(ctx["error_cells"])]
    allowed = _as_lists(sorted(ctx["allowed_cells"]))
    if not solid or not allowed:
        return None, None, "覆盖失败的层号在模型里没有实体格，不能把截断提示格当成全量"
    return solid, allowed, None


def structure_snapshot(chain, result):
    """结构失败当时的冻结输入：缺全量窗口/算子/核心/部位时 evaluable=false。

    提示 cells 可能被截断，不假装全量；覆盖有层号时按整层计算，悬吊只用已记录坐标。
    """
    failure = result.get("failure") or {}
    inner = failure.get("failure") if isinstance(failure.get("failure"), dict) else {}
    kind = inner.get("kind") or failure.get("kind")
    if kind not in _STRUCTURAL_KINDS:
        return None
    window = _full_cells(inner.get("window_cells"))
    cells = _cell_list(inner.get("cells")) or []
    layer = inner.get("layer") if isinstance(inner, dict) else None
    allowed = None
    reason = None
    model = getattr(chain, "model", None)
    if kind == "coverage":
        window, allowed, reason = _coverage_window(model, layer)
    elif kind == "suspension":
        if window is None:
            reason = "悬吊失败没有锁扣或子组件坐标，不猜测补齐"
        else:
            # revision_ctx 对悬吊会落到整模。这里只保留已经记录的坐标。
            allowed = _as_lists(window)
    elif window is not None and model is not None:
        try:
            from .workflow_phases import revision_ctx
            ctx = revision_ctx(model, {
                "kind": kind, "window_cells": window, "cells": window, "layer": layer,
            })
            allowed = _as_lists(sorted(ctx["allowed_cells"]))
        except (KeyError, TypeError, ValueError, IndexError) as exc:
            _emit_safely(chain, "error", f"结构快照未能计算 allowedCells：{exc}")
            allowed = None
            reason = f"结构快照未能计算 allowedCells：{exc}"
    elif window is None:
        reason = f"结构失败 {kind} 没有全量窗口，截断提示格不补齐"
    frozen = None
    if getattr(chain, "cores_frozen", False) and getattr(chain, "frozen_cells", None) is not None:
        frozen = [list(c) for c in sorted(chain.frozen_cells)]
    ops = getattr(chain, "ops", None)
    parts = []
    for part in getattr(chain, "parts_norm", None) or []:
        cores = part.get("core_cells") or set()
        parts.append({
            "id": part.get("id"),
            "voxels": len(part.get("cells") or []),
            "coreCells": [list(c) for c in sorted(cores)],
        })
    digest = None
    if model is not None:
        try:
            digest = model_hash(model)
        except (TypeError, ValueError) as exc:
            _emit_safely(chain, "error", f"结构快照模型哈希失败：{exc}")
    evaluable = (window is not None and isinstance(ops, list) and frozen is not None
                 and bool(parts) and digest is not None and allowed is not None)
    if not evaluable and reason is None:
        reason = f"结构失败 {kind} 快照不完整，记为不可评估"
    if not evaluable:
        _emit_safely(chain, "info", f"结构失败 {kind} 快照不完整，记为不可评估：{reason}")
    return {
        "kind": kind,
        "layer": layer,
        "windowCells": None if window is None else _as_lists(window),
        "promptCells": [list(c) for c in cells],
        "cellsTruncated": window is None,
        "allowedCells": allowed,
        "frozenCells": frozen,
        "opCount": len(ops) if isinstance(ops, list) else None,
        "parts": parts,
        "modelHash": digest,
        "evaluable": evaluable,
        "unevaluableReason": None if evaluable else reason,
    }


def _emit_safely(chain, kind, text):
    """记录落盘的旁路日志。emit 自己失败不得再把任务结果变成异常。"""
    emit = getattr(chain, "emit", None)
    if not callable(emit):
        return
    try:
        emit(kind, text)
    except Exception:
        pass


def build_run_record(chain, result, desc, mode, deadline_s, artifacts_dir, subprocess_mod):
    """组装并落盘 run_<id>.json 运行记录（拒绝、draw 尝试、结构快照与 A.2/A.3 可信度字段）。

    gateFailed 保持兼容语义=「门禁未全过」；序列化失败不得向外抛（set 收成 list，元组键
    收成 JSON 文本；仍失败时写 recordError，ok/error/failure/run_id 保持不动）。
    """
    finalize_review_trust(chain)
    draft = chain.draft
    best = chain.best_draft or draft
    gate_degraded = bool(chain.gate_errors)
    record = {
        "runId": chain.run_id, "mode": mode, "codeVersion": code_version(subprocess_mod),
        "desc": desc, "ok": result.get("ok", False), "error": result.get("error"),
        "failure": result.get("failure"), "counts": dict(chain.counts),
        "revisionIncomplete": bool(getattr(chain, "revision_incomplete", False)),
        "revisionIncompleteReason": getattr(chain, "revision_incomplete_reason", None),
        "revisionAccounting": rp.accounting(chain),
        "failures": list(chain.failures), "protocolErrors": list(chain.protocol_errors),
        "lastRejection": chain.last_rejection, "rejections": chain.rejections[-12:],
        "drawAttempts": chain.draw_attempts,
        "contractChecks": list(getattr(chain, "contract_checks", None) or []),
        "dynamicDrawRequest": chain.draw_dynamic,
        "timeline": chain.timeline, "revision": chain.revision,
        "reviewFlag": chain.review_flag,
        # 最终评审结构化结果：run 记录必须自带 review.parsed，
        # 浏览器断言/复算才能拿到真实视觉分；旧记录没有该字段时由断言侧用任务 result.review 补入。
        "review": (getattr(chain, "review_state", None) or {}).get("parsed") or {},
        "gateDegraded": gate_degraded,
        "gateRejectedDraft": draft is not None,
        "gateFailed": gate_degraded or bool(draft and draft["gate_errors"]),
        "gateErrors": chain.gate_errors or [], "track": chain.track,
        "artifacts": {k: os.path.basename(v) for k, v in chain.artifacts.items()},
        "elapsedS": result.get("elapsed_s"), "deadlineS": deadline_s,
        "orderEvents": list(getattr(chain, "order_events", None) or []),
        "gateRegressions": int(getattr(chain, "gate_regressions", 0) or 0)}
    record.update(record_trust_fields(chain, result.get("pieces")))
    snap = structure_snapshot(chain, result)
    if snap is not None:
        record["structureSnapshot"] = snap
    if draft is not None and not result.get("ok", False):
        # 失败候选稿只保留诊断哈希与门禁/契约错误，不伪装成正式有效版本
        record["draftDiagnostic"] = {
            "opCount": len(draft["ops"]),
            "opsHash": model_hash({"ops": draft["ops"]}),
            "modelHash": model_hash(draft["model"]),
            "gateErrors": [e[:200] for e in draft["gate_errors"][:8]],
            "contractErrors": [str(v.get("message", ""))[:200]
                               for v in (draft.get("contract_errors") or [])[:8]],
        }
        if best is not None and best is not draft:
            record["bestDraftDiagnostic"] = {
                "opCount": len(best["ops"]),
                "opsHash": model_hash({"ops": best["ops"]}),
                "gateErrorCount": len(best["gate_errors"]),
                "contractErrorCount": len(best.get("contract_errors") or []),
            }
    set_hits, key_hits = [], []
    record = to_jsonable(record, set_hits, key_hits)
    result["run_record"] = record
    for key, value in list(result.items()):
        if key == "run_record":
            continue
        result[key] = to_jsonable(value, set_hits, key_hits)
    if set_hits:
        _emit_safely(chain, "info", f"序列化前已把 {len(set_hits)} 处 set 收成 list")
    if key_hits:
        _emit_safely(chain, "info", f"序列化前已把 {len(key_hits)} 处元组键收成 JSON 文本")
    try:
        payload = json.dumps(record, ensure_ascii=False, indent=2)
        os.makedirs(artifacts_dir, exist_ok=True)
        with open(os.path.join(artifacts_dir, f"run_{chain.run_id}.json"), "w", encoding="utf-8") as f:
            f.write(payload)
    except Exception as exc:
        result["recordError"] = {"type": type(exc).__name__, "message": str(exc)}
        _emit_safely(chain, "error",
                     f"运行记录未能落盘（{type(exc).__name__}: {exc}），任务结果已保留")
    return result["run_record"]
