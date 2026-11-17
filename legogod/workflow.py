# ============================================================
# 固定主链工作流编排：阶段逻辑在 workflow_phases.py，
# 终稿补评审在 workflow_review.py，算子辅助在 workflow_ops.py，产物/运行记录在 workflow_artifacts.py
# （生产文件 ≤500 行，接口兼容）。
# ============================================================
import json
import os
import subprocess
import threading
import time
import uuid

from . import design_contract as dc
from . import draw_budget as dbudget
from . import fallback as fb
from . import llm
from . import part_binding as pb
from . import tiler
from . import workflow_artifacts as wa
from . import workflow_log as wl
from . import workflow_ops as wops
from . import workflow_phases as wph
from .agent import AGENT_SYSTEM, FIDELITY_PROMPT, MAX_REVISE_COLOR_OPS, MAX_REVISE_OPS
from .paths import ARTIFACTS_DIR, VIZ_DIR
from .validate import validate_solution
from .workflow_log import (  # noqa: F401 （保留对外导出）
    _console_log, _default_chat, _default_review, solver_progress, wrap_review)
from .workflow_review import refresh_stale_review

TOTAL_BUDGET_S, MODEL_STOP_S = 1800, 90
SOLVE_RESERVE_S, ARTIFACT_RESERVE_S = 60, 30
SOLVE_BUDGET_S, REVISE_GATE_S = 60, 4 * 60

MAX_PHASE_REQUESTS = 2
MAX_DRAW_REQUESTS = 3   # 画图阶段独立预算：首次 + 至少两次有效纠错
MAX_REVISE_CLASS1 = 2
MAX_REVISE_CLASS2 = 2
MAX_REVISE_VISUAL = 2
MAX_REDRAWS = 1         # 已编译候选稿因门禁失败而触发的完整重绘上限（局部纠错不占此额度）

RETRY_HINT = "\n请立即只修正上面列出的问题，重新输出当前阶段要求的完整 JSON（不要改变策略、不要换成别的 action）。"


class GenerationFailure(Exception):
    def __init__(self, message, kind="internal", stage=None, info=None):
        super().__init__(message)
        self.kind = kind
        self.stage = stage
        self.info = info or {}


class CancelledError(Exception):
    """用户取消。"""


class _Chain:
    """单次生成任务的固定状态机，支持时钟、模型、评审与求解器全注入。"""

    def __init__(self, desc, mode="fast", log=None, cancel=None, clock=time.monotonic,
                 deadline_s=TOTAL_BUDGET_S, chat_fn=None, review_fn=None, solve_fn=None,
                 interactive=False, review_context=None):
        self.desc = desc
        self.mode = mode
        self.log_fn = log or _console_log
        self.cancel = cancel or threading.Event()
        self.clock = clock
        self.t_start = clock()
        self.hard_deadline = self.t_start + deadline_s
        self.model_deadline = self.hard_deadline - MODEL_STOP_S
        self.chat_fn = chat_fn or _default_chat
        self.review_fn = wrap_review(review_fn or _default_review, self.log_fn)
        self.solve_fn = solve_fn or tiler.solve_with_budget
        self.interactive = interactive
        self.run_id = uuid.uuid4().hex[:8]
        self.messages = [
            {"role": "system", "content": AGENT_SYSTEM + (FIDELITY_PROMPT if mode == "fidelity" else "")},
            {"role": "user", "content": desc},
        ]
        if review_context:  # 手动重试继承的评审反馈：独立用户消息，原始需求不变
            self.messages.append({"role": "user", "content": review_context})
        self.phase = "init"
        self.phase_requests = 0
        self.phase_started = self.t_start
        self.timeline = []
        self.counts = {"revise_class1": 0, "revise_class2": 0, "revise_visual": 0}
        self.failures = []
        self.protocol_errors = []
        self.rejections = []        # 统一候选拒绝记录（含门禁），lastRejection 取末项
        self.last_rejection = None
        self.draw_attempts = []     # 每次 draw 实际请求的算子数/编译结果/门禁错误数/耗时
        self.draw_dynamic = None    # 最近一次动态第 4 次请求判定明细
        self.contract_checks = []   # 几何契约检查记录（默认关，启用后每次检查落一条）
        self.last_compile_reject = None
        self.draft = None           # 编译通过但门禁未过的候选草稿（r000 基线）
        self.best_draft = None      # 历史最佳草稿（门禁错误最少）：预算耗尽降级用最佳而非最新
        self.used_ask = False
        self.plan = None
        self.parts_norm = None
        self.assignment = None
        self.default_part = None
        self.cores_frozen = False
        self.design_meta = None
        self.layers = None
        self.model = None
        self.revision = 0
        self.frozen_cells = set()
        self.solved = None
        self.review_state = None
        self.review_flag = None
        self.revision_entries = []       # 已接受修订的追加/改写/范围
        self.revision_incomplete = False
        self.revision_incomplete_reason = None
        self.pending_revision = None
        self.revision_skip_geo_cap = False
        self.artifacts = {}
        self.model_hashes = {}
        self._parsed_parts = None
        self.track = None
        self.ops = None
        self.redraws = 0
        self.gate_errors = None
        # A.2/A.3/D.2/F.1：版本链、评审哈希、顺序与额度记录状态
        self.max_revision = self.version_overwrite_count = 0
        self.revision_chain, self.rollback_pending = [], None
        self.reviewed_model_hash, self.final_model_hash, self.review_stale = None, None, False
        self.structural_candidates = {"attempted": 0, "accepted": 0, "rejected": 0, "results": []}
        self.quota_limits = {"class1": MAX_REVISE_CLASS1, "class2": MAX_REVISE_CLASS2}
        self.quota_requests = {"class1": 0, "class2": 0}
        self.gate_regressions = 0
        self.draft_ranking = self.gate_degraded_baseline = None
        self.order_events = []
        # 2026-11-03 D.2 单变量真实 E2E 结论：class1_front（视觉前只读预检/class1 修订、不提前冻结核心）
        # 旧 20 例交付 12→16、硬失败 8→4、耗时 -20.5%，视觉核心拒绝 0、必需外观损伤 0。
        # 因此默认顺序切换为 class1_front；显式 LEGOGOD_CHAIN_ORDER=default 仍可回到旧顺序（对照用）。
        self.chain_order = os.environ.get("LEGOGOD_CHAIN_ORDER", "").strip()
        # 合法值只有 default / class1_front；旧值 s0_readonly_front 与 class1_front 走同一实现，已移除。
        if self.chain_order not in ("default", "class1_front"):
            self.chain_order = "class1_front"

    def emit(self, kind, text, meta=None):
        m = dict(meta or {})
        m.setdefault("phase", self.phase)
        self.log_fn(kind, text, m)

    def live(self, text):
        self.log_fn("live", text)

    def observe(self, text):
        self.emit("tool", text)
        self.messages.append({"role": "user", "content": "OBSERVATION: " + text})

    def record_rejection(self, kind, summary, part_ids=None):
        entry = {"phase": self.phase, "request": self.phase_requests, "kind": kind,
                 "summary": str(summary)[:240], "partIds": [str(p) for p in (part_ids or [])]}
        self.rejections.append(entry)
        self.last_rejection = entry
        return entry

    def record_protocol_error(self, subkind, summary):
        self.protocol_errors.append({
            "phase": self.phase, "request": self.phase_requests,
            "kind": subkind, "summary": str(summary)[:240],
        })
        self.record_rejection(subkind, summary)

    def remaining_model(self):
        return self.model_deadline - self.clock()

    def remaining_hard(self):
        return self.hard_deadline - self.clock()

    def check_cancel(self):
        if self.cancel.is_set():
            raise CancelledError()

    def begin_phase(self, name, instruction=None):
        now = self.clock()
        self.timeline.append({"phase": self.phase, "ended": round(now - self.t_start, 1)})
        self.phase = name
        self.phase_requests = 0
        self.phase_started = now
        self.draw_dynamic = None
        self.timeline.append({"phase": name, "started": round(now - self.t_start, 1)})
        self.emit("phase", f"—— 阶段：{name} ——")
        if instruction:
            self.messages.append({"role": "user", "content": instruction})

    def _recover_from_reasoning(self, reasoning, allowed_actions):
        if not reasoning or not reasoning.strip():
            return None
        cands = [o for o in llm.iter_json_objects(reasoning) if isinstance(o, dict)]
        if len(cands) != 1 or cands[0].get("action") not in allowed_actions:
            return None
        raw = cands[0].get("args")
        return cands[0].get("action"), (raw if isinstance(raw, dict) else {})

    def model_turn(self, allowed_actions, schema_check, reasoning_effort=None, max_tokens=65536,
                   request_limit=None):
        """执行一次受预算与截止保护的模型交互。request_limit 缺省为阶段上限 2，修订可放宽；
        画图阶段传入可调用限额（基础 3 次，复杂任务可放宽到 4）。"""
        self.check_cancel()
        limit = MAX_PHASE_REQUESTS if request_limit is None else request_limit
        if callable(limit):
            limit = limit()
        if self.remaining_model() <= 0:
            raise GenerationFailure("距模型调用截止不足 90 秒余量，停止模型调用", kind="deadline", stage=self.phase)
        if self.phase_requests >= limit:
            rej = self.last_rejection or (self.protocol_errors[-1] if self.protocol_errors else None)
            tail = f"（最近打回原因：{rej['summary']}）" if rej else ""
            info = {"protocolErrors": self.protocol_errors[-4:], "reason": "request_budget"}
            if self.last_rejection:
                info["lastRejection"] = dict(self.last_rejection)
            if self.phase == "draw" and self.draw_dynamic:
                info["dynamicRequest"] = self.draw_dynamic
            raise GenerationFailure(
                f"阶段 {self.phase} 的实际请求已达 {limit} 次上限"
                f"（首次、流式转普通与重试合并计数）{tail}",
                kind="protocol", stage=self.phase,
                info=info,
            )
        t0 = self.clock()
        self.phase_requests += 1
        self._count_requests(1)
        thinking = wl.ThinkingFeed(self.emit, self.cancel.is_set)

        def on_progress(text, elapsed):
            if self.cancel.is_set():
                raise llm.LLMCancelled()
            if not text:
                self.live(f"阶段 {self.phase} · 模型思考中…… {elapsed:.0f}s")
                return
            tail_txt = text.strip()[-90:].replace("\n", " ")
            self.live(f"阶段 {self.phase} · 模型输出中 {len(text)} 字 / {elapsed:.0f}s ｜ …{tail_txt}")

        # 剩余额度只剩 1 次时直接走普通（非流式）请求：block 调用恒为 1 次 HTTP，
        # 避免「流式失败回退普通」把最后 1 个槽位变成 2 次实际请求、突破阶段上限
        # 实际 HTTP 请求不得绕过上限。代价仅是该次无实时进度。
        last_slot = self.phase_requests >= limit
        try:
            resp = self.chat_fn(self.messages, max_tokens=max_tokens,
                                on_progress=None if last_slot else on_progress,
                                on_reasoning=None if last_slot else thinking.on_reasoning,
                                deadline=self.model_deadline, reasoning_effort=reasoning_effort)
        except llm.LLMCancelled:
            thinking.close(partial=True)
            raise CancelledError() from None
        except llm.LLMDeadline:
            thinking.close(partial=True)
            raise GenerationFailure("模型调用截止已到（30 分钟硬墙钟内停止模型调用）",
                                    kind="deadline", stage=self.phase) from None
        except llm.LLMStreamBroken as e:
            thinking.close(partial=True)
            self.record_protocol_error("stream_broken", e)
            self.emit("error", f"流式输出中断：{e}")
            self.observe(f"上一次输出在传输中途中断（不会自动重发）。请重新完整输出当前阶段（{self.phase}）的 JSON。")
            return None
        except BaseException:  # noqa: BLE001 - 取消/回调异常都要先把已收到的半截思考落盘
            thinking.close(partial=True)
            raise
        # 非流式槽位没有实时回调：响应里带回的完整推理在这里补一次
        thinking.adopt(resp.get("reasoning_content"), self.clock() - t0)
        thinking.close(partial=False)
        self.live(None)
        extra = max(0, int(resp.get("requests", 1))) - 1
        self.phase_requests += extra
        self._count_requests(extra)
        self.emit("info", f"模型调用完成（HTTP 请求 {resp.get('requests', 1)} 次，"
                          f"阶段累计 {self.phase_requests}/{limit}，"
                          f"耗时 {self.clock() - t0:.0f}s，finish={resp.get('finish')}）")
        content = (resp.get("content") or "").strip()
        reasoning = resp.get("reasoning_content") or ""
        finish = resp.get("finish")
        if not content:
            if finish == "length":
                recovered = self._recover_from_reasoning(reasoning, allowed_actions)
                if recovered:
                    action, args = recovered
                    self.emit("info", f"正文为空（finish=length），从推理文本恢复唯一 1 个 {action} JSON")
                    errs = schema_check(args, action)
                    if not errs:
                        self.messages.append({"role": "assistant", "content": json.dumps({"action": action, "args": args}, ensure_ascii=False)})
                        return action, args
                    self.record_protocol_error("recovered_schema", errs[0])
                    self.observe("从推理文本恢复的 JSON 未通过校验：\n- " + "\n- ".join(errs[:8]) + RETRY_HINT)
                    return None
            self.record_protocol_error("empty_output", f"finish={finish}")
            self.observe(f"上一次输出为空（finish={finish}）。立即输出当前阶段（{self.phase}）要求的完整 JSON。")
            return None
        if finish and finish != "stop":
            self.emit("error", f"模型输出异常结束：finish={finish}（收到 {len(content)} 字符）")
        try:
            obj = llm.parse_json(content)
            if not isinstance(obj, dict):
                raise ValueError("顶层 JSON 必须是对象")
            action = obj.get("action")
            raw_args = obj.get("args")
            if raw_args is not None and not isinstance(raw_args, dict):
                raise ValueError("args 字段必须是对象")
            args = raw_args or {}
        except Exception as e:
            self.messages.append({"role": "assistant", "content": content[:2000]})
            self.record_protocol_error("json_parse", e)
            self.observe(f"JSON 解析失败（{e}）。请严格按协议重新输出当前阶段（{self.phase}）的 JSON。")
            return None
        if action not in allowed_actions:
            self.messages.append({"role": "assistant", "content": content[:2000]})
            self.record_protocol_error("wrong_action", f"got={action!r}")
            self.observe(f"非预期 action: {action!r}（不保存、不推进状态）。"
                         f"当前阶段只接受 {'/'.join(sorted(allowed_actions))}，请立即重新输出。")
            return None
        try:
            errs = schema_check(args, action)
        except (AttributeError, TypeError, KeyError, ValueError) as e:
            errs = [f"参数结构类型非法：{e}"]
        if errs:
            self.messages.append({"role": "assistant", "content": content[:2000]})
            self.record_protocol_error("schema_error", errs[0])
            self.observe("输出未通过校验：\n- " + "\n- ".join(errs[:8]) + RETRY_HINT)
            return None
        self.messages.append({"role": "assistant", "content": json.dumps({"action": action, "args": args}, ensure_ascii=False)})
        self.emit("thought", str(obj.get("thought", "")), {"action": action})
        return action, args

    def _check_plan_schema(self, args, action=None):
        errs = list(wops.check_plan_schema(self, args))
        try:
            from . import plan_scale
            errs += list(plan_scale.consistency_errors(args, self.desc) or [])
        except ImportError:
            pass
        except Exception as e:  # noqa: BLE001 - 一致性检查不得让规划阶段崩溃
            self.emit("error", f"规划一致性检查异常（不阻断）：{e}")
        return errs

    def _check_save_schema(self, args, action=None):
        return wops.check_save_schema(self, args)

    def _check_revise_schema(self, args, action=None):
        return wops.check_revise_schema(self, args)

    def _check_label_schema(self, args, action=None):
        return wops.check_label_schema(self, args)

    def _bind_parts(self, labels):
        errs, bound, warns = pb.bind_parts(self.parts_norm, labels, self.model)
        for w in warns:
            self.emit("error", "⚠ 标注被忽略：" + w)
        if errs:
            return errs, warns
        for pid in bound["removed"]:
            self.emit("info", f"可选部位 {pid} 在画稿里没有实体：删除该部位")
        self.default_part = str(labels.get("defaultPart") or "").strip()
        self.assignment = bound["assign"]
        self.parts_norm = bound["parts"]
        return [], warns

    def _plan_and_draw(self):
        wph.run_plan_phase(self)
        args = wph.run_draw_phase(self, MAX_REDRAWS)
        if self.track == "ops":
            self._record_parts()
            return
        errs, warns = self._bind_parts(args)
        if not errs:
            self._record_parts()
            return
        self.failures.append({"kind": "parts", "stage": "label", "errors": errs[:8]})
        wph.run_label_phase(self, errs, warns, GenerationFailure)
        self._record_parts()

    def _record_parts(self):
        self.model["parts"] = [{
            "id": p["id"], "name": p["name"], "required": p["required"], "source": p["source"],
            "role": p.get("role") or "solid", "voxels": len(p["cells"]),
            "boxes": p["boxes"], "coreCells": dc.cells_to_lists(p["core_cells"], cap=10000),
        } for p in self.parts_norm]

    def _version_design(self, note="", cause=None):
        return wa.version_design(self, ARTIFACTS_DIR, note=note, cause=cause)

    def _count_requests(self, n):
        """累计 class1/class2 修订阶段真实 HTTP 请求数（F.1 额度记录用）。"""
        cls = (self.pending_revision or {}).get("cls") if self.phase == "revise" else None
        if cls in ("class1", "class2") and n > 0:
            self.quota_requests[cls] = self.quota_requests.get(cls, 0) + n

    def _freeze_cores(self):
        self.cores_frozen = True
        self.frozen_cells = pb.frozen_core_cells(self.parts_norm)
        self.emit("info", f"防删除核心已冻结：{len(self.frozen_cells)} 格")

    def _apply_revision(self, cls, failure):
        """执行一次有界修订；class1/class2 额度走 draw_budget.quota_limit（F.1，默认 fixed）。"""
        base = {"class1": MAX_REVISE_CLASS1, "class2": MAX_REVISE_CLASS2,
                "visual": MAX_REVISE_VISUAL}[cls]
        limit, quota_fn = base, getattr(dbudget, "quota_limit", None)
        if cls in ("class1", "class2") and self.remaining_model() >= REVISE_GATE_S:
            self.check_cancel()
            if callable(quota_fn):
                try:
                    limit = int(quota_fn(self, cls, base))
                except Exception:  # noqa: BLE001 - 额度接口异常回退基础额度
                    limit = base
        budgets = {"class1": limit if cls == "class1" else MAX_REVISE_CLASS1,
                   "class2": limit if cls == "class2" else MAX_REVISE_CLASS2,
                   "visual": MAX_REVISE_VISUAL}
        self.quota_limits[cls] = limit
        try:
            return wph.apply_revision(self, cls, failure, budgets, REVISE_GATE_S,
                                      MAX_REVISE_OPS, MAX_REVISE_COLOR_OPS, GenerationFailure)
        except wph.rp.RevisionBudgetExhausted as ex:
            if cls == "visual":
                raise
            return wph.rp.solve_after_revision_exhausted(self, ex, GenerationFailure)

    def _solve_current(self):
        self.check_cancel()
        budget_end = min(self.clock() + SOLVE_BUDGET_S, self.hard_deadline - ARTIFACT_RESERVE_S)
        if budget_end <= self.clock():
            raise GenerationFailure("没有剩余求解时间（预留产物时间不足）", kind="deadline", stage="solve")
        self.begin_phase("solve")
        self.emit("tool", f"运行求解（预算 {SOLVE_BUDGET_S} 秒）")
        try:
            sol, failure = self.solve_fn(
                self.model, sorted(self.model["layers"], key=lambda l: l["y"]),
                deadline=budget_end, validate_fn=validate_solution,
                log=lambda s: self.emit("solver", s), should_stop=self.cancel.is_set,
                on_progress=solver_progress(self.log_fn),
            )
        except tiler.TilerCancelled:
            raise CancelledError() from None
        self.emit("tool", f"求解结束：{'成功' if sol is not None else '失败（' + (failure or {}).get('kind', '?') + '）'}")
        return sol, failure

    def _finish_success(self, sol):
        refresh_stale_review(self, ARTIFACTS_DIR)
        wa.finalize_review_trust(self)
        arts = wa.make_artifacts(self, sol, ARTIFACTS_DIR, VIZ_DIR, subprocess, GenerationFailure)
        self.solved = (sol, sol.get("validation") or {})
        self.emit("result", f"完成：{self.model['name']}，{len(sol['steps'])} 块零件（r{self.revision:03d}）",
                  {"slug": self.model["slug"], "revision": self.revision})
        return {"sol": sol, "artifacts": arts}

    def run(self):
        try:
            self._plan_and_draw()
            self._version_design(note="部位绑定通过")
            kept = fb.run_front_order(self)  # D.2 前置顺序：视觉前只读预检/class1（不冻结核心）
            if kept:
                return kept
            if self.mode == "fidelity":
                wph.run_visual_phase(self, ARTIFACTS_DIR, MAX_PHASE_REQUESTS, MAX_REVISE_VISUAL)
                reviewed = (self.review_state or {}).get("modelHash")
                if reviewed:
                    self.reviewed_model_hash = reviewed
            self._freeze_cores()
            return fb.structure_loop(self)
        except GenerationFailure as gf:
            if gf.kind == "deadline" and self.model is not None and self.parts_norm is not None:
                return fb.final_attempt(self, gf)
            raise


def run_generation(desc, interactive=False, log=None, cancel=None, deadline_s=TOTAL_BUDGET_S,
                   mode="fast", chat_fn=None, review_fn=None, solve_fn=None, clock=time.monotonic,
                   review_context=None):
    """固定生成主链。review_context 只注入手动重试；自动快速保底不传，始终全新运行。"""
    cancel = cancel or threading.Event()
    chain = _Chain(desc, mode=mode, log=log, cancel=cancel, clock=clock,
                   deadline_s=deadline_s, chat_fn=chat_fn, review_fn=review_fn,
                   solve_fn=solve_fn, interactive=interactive, review_context=review_context)
    result = {"ok": False, "error": None, "mode": mode, "run_id": chain.run_id, "deadline_s": deadline_s}
    status = "error"
    try:
        out = chain.run()
        result.update(wa.success_result(chain, out, clock() - chain.t_start))
        status = "done"
    except CancelledError:
        result.update({"error": "任务已取消", "failure": {"kind": "cancelled"}, "revision": chain.revision})
        status = "cancelled"
        chain.log_fn("error", "任务已取消")
    except GenerationFailure as gf:
        result.update({"error": str(gf), "failure": {"kind": gf.kind, "stage": gf.stage, **gf.info}})
        result.update(wa.failure_fields(chain, clock() - chain.t_start))
        chain.log_fn("error", f"生成失败（{gf.kind}，阶段 {gf.stage or chain.phase}）：{gf}")
    except Exception as e:
        import traceback
        result.update({
            "error": f"内部异常: {e}",
            "failure": {"kind": "internal", "stage": chain.phase, "traceback": traceback.format_exc()[-2000:]},
        })
        result.update(wa.failure_fields(chain, clock() - chain.t_start))
        chain.log_fn("error", result["error"])
    finally:
        result.update(wa.record_trust_fields(chain, result.get("pieces")))
        wa.build_run_record(chain, result, desc, mode, deadline_s, ARTIFACTS_DIR, subprocess)
    result["status"] = status
    return result
