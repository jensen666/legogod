# ============================================================
# 复杂任务动态画图预算与失败签名
#
# 复杂度只使用结构化指标（必需部位数 / surface 部位数 / 实际算子数 / 编译体素数 / 高保真配色），
# 阈值由冻结样本集分布标定（tools/calibrate_draw_budget.py；样本快照
# test/fixtures/draw_budget_samples.json，124 个带部位契约的存量模型，P90 分位），
# 不按物体名称或品类设置特例。高保真只是其中一个投票条件，不自动放大其他阶段预算。
#
# 动态额度：
# 默认 LEGOGOD_DYNAMIC_QUOTA=off（固定额度，行为与旧版一致）；显式 cross 时才启用
# class1/class2 交叉 +1（另一类已接受修订 ≥1 时本类额度 base+1），只放宽已接受修订次数，
# 不改变单阶段请求槽位、墙钟与取消语义。
# ============================================================
import hashlib
import json
import os
import re

# 冻结标定阈值（2026-10-31，样本=artifacts 中 124 个带部位契约模型，P90 分位）：
#   required: P75=8  P90=12 | surface: P75=1 P90=3 | ops: P75=18 P90=33 | voxels: P75=1324 P90=2354
# 取 P90 为投票线（而非 P75）——帕累托复核：P75+2票 判复杂 37.1%，额度面过宽；
# P90+2票 判复杂 11.3%（最难十分位，最保守切点），简单任务（两层房等）0-1 票不入复杂。
COMPLEX_MIN_VOTES = 2
T_REQUIRED_PARTS = 12
T_SURFACE_PARTS = 3
T_OPS = 33
T_VOXELS = 2354

# 复杂任务在基础 3 次 draw 请求之外，可按四条件放宽到的上限。
DYNAMIC_DRAW_EXTRA = 1

# 供同输入前后对照验收：设为 off/0/false/no 关闭动态第 4 次请求（固定 3 次策略）。
ENV_DYNAMIC_DRAW = "LEGOGOD_DYNAMIC_DRAW_BUDGET"

# 关闭值（与其它开关语义一致，避免 =off 反而开启的误用）
_DISABLED_VALUES = ("off", "0", "false", "no")

# ---------------- 动态额度：class1/class2 交叉 +1 ----------------
# 冻结：默认 off（固定额度），只有显式 LEGOGOD_DYNAMIC_QUOTA=cross 才启用交叉 +1。
ENV_DYNAMIC_QUOTA = "LEGOGOD_DYNAMIC_QUOTA"
QUOTA_MODE_OFF = "off"
QUOTA_MODE_CROSS = "cross"
_QUOTA_MODES = (QUOTA_MODE_OFF, QUOTA_MODE_CROSS)

# 基础修订额度（与 workflow.MAX_REVISE_CLASS1/MAX_REVISE_CLASS2 一致；为避免环依赖在此镜像，
# 由 test/test_draw_budget.py 断言两者同步，主链接线时必须把原始 base 传进 quota_limit）。
BASE_REVISE_LIMITS = {"class1": 2, "class2": 2}
QUOTA_CROSS_TRIGGER = 1    # 另一类「已接受修订」达到该次数才给本类 +1
QUOTA_CROSS_EXTRA = 1      # 交叉额度增量（上限 base+1，不得叠加）

_COORD_RE = re.compile(r"\(x=-?\d+,y=-?\d+,z=-?\d+\)")
_OP_RE = re.compile(r"算子#([0-9A-Za-z.]+)")

# draw 请求耗尽后需保留给最终求解与产物的硬墙钟余量（与 workflow 常量一致，避免环依赖）。
_RESERVE_HARD_S = 90.0


def dynamic_draw_enabled():
    """动态第 4 次画图请求开关：默认开，off/0/false/no 关闭（与其它开关语义一致）。"""
    raw = (os.environ.get(ENV_DYNAMIC_DRAW) or "").strip().lower()
    return raw not in _DISABLED_VALUES


def dynamic_quota_mode():
    """动态额度开关：只读 env LEGOGOD_DYNAMIC_QUOTA，默认 "off"，非法值按 "off"。"""
    raw = (os.environ.get(ENV_DYNAMIC_QUOTA) or "").strip().lower()
    return raw if raw in _QUOTA_MODES else QUOTA_MODE_OFF


def _class_accepted(chain, cls):
    """该类已接受的修订次数（chain.counts["revise_class1"/"revise_class2"]，纯读取）。"""
    counts = getattr(chain, "counts", None)
    if not isinstance(counts, dict):
        return 0
    try:
        return max(0, int(counts.get(f"revise_{cls}") or 0))
    except (TypeError, ValueError):
        return 0


def _extra_quota_allowed(chain):
    """额外额度只在未取消、且仍有模型调用余量时发放（不改变既有取消/截止语义）。"""
    cancel = getattr(chain, "cancel", None)
    if cancel is not None:
        try:
            if cancel.is_set():
                return False
        except AttributeError:
            pass
    remaining = getattr(chain, "remaining_model", None)
    if callable(remaining):
        try:
            if float(remaining()) <= 0:
                return False
        except (TypeError, ValueError):
            pass
    return True


def quota_limit(chain, cls, base):
    """某一类修订的「已接受修订次数」额度（纯读取，不改状态）。

    固定模式（默认/非法 env/非 class1/class2）原样返回 base；
    cross 模式：另一类已接受修订 ≥QUOTA_CROSS_TRIGGER 且未取消/未到模型截止时返回 base+1，
    否则返回 base——上限恒为 base+1，不随已用次数继续放大。
    注意：本函数只放宽已接受修订次数，**不得**用于放大单次修订阶段的请求槽位或墙钟/取消
    上限；接线方必须把主链原始 base（workflow.MAX_REVISE_CLASS1/2）传入，不得传已放大值。
    """
    base = int(base)
    if cls not in BASE_REVISE_LIMITS or dynamic_quota_mode() != QUOTA_MODE_CROSS:
        return base
    other = "class2" if cls == "class1" else "class1"
    if _class_accepted(chain, other) >= QUOTA_CROSS_TRIGGER and _extra_quota_allowed(chain):
        return base + QUOTA_CROSS_EXTRA
    return base


def _requests_map(chain):
    """真实请求数记录（主链由 _count_requests 写入 chain.quota_requests）。"""
    mapping = getattr(chain, "quota_requests", None)
    return mapping if isinstance(mapping, dict) else None


def quota_state(chain):
    """额度审计快照（纯读取，供运行记录）：模式 + 每类 {limit, accepted, requests}。

    accepted 取 chain.counts["revise_class1"/"revise_class2"]；
    requests 取 chain.quota_requests（真实 HTTP 请求数），缺失时以已接受修订数作下界
    （每次已接受修订至少发出一次真实请求）。
    """
    mode = dynamic_quota_mode()
    bases = dict(BASE_REVISE_LIMITS)
    override = getattr(chain, "revise_base_limits", None)
    if isinstance(override, dict):
        for cls in bases:
            try:
                bases[cls] = int(override.get(cls, bases[cls]))
            except (TypeError, ValueError):
                pass
    requests_map = _requests_map(chain)
    state = {"mode": mode}
    for cls in ("class1", "class2"):
        accepted = _class_accepted(chain, cls)
        requests = accepted
        if isinstance(requests_map, dict):
            try:
                requests = max(0, int(requests_map.get(cls) or 0))
            except (TypeError, ValueError):
                requests = 0
            requests = max(requests, accepted)  # 已接受修订至少对应一次真实请求
        state[cls] = {"limit": quota_limit(chain, cls, bases[cls]),
                      "accepted": accepted, "requests": requests}
    return state


def complexity_votes(required_parts, surface_parts, op_count, voxels, fidelity):
    """按冻结阈值逐项投票，返回命中的条件名列表。"""
    votes = []
    if required_parts >= T_REQUIRED_PARTS:
        votes.append("required_parts")
    if surface_parts >= T_SURFACE_PARTS:
        votes.append("surface_parts")
    if op_count >= T_OPS:
        votes.append("ops")
    if voxels >= T_VOXELS:
        votes.append("voxels")
    if fidelity:
        votes.append("fidelity")
    return votes


def chain_metrics(chain):
    """当前可观测复杂度指标：部位来自规划，算子/体素来自最新已编译候选草稿（没有则为 0）。"""
    parts = chain.parts_norm or []
    draft = chain.draft
    return {
        "requiredParts": sum(1 for p in parts if p.get("required")),
        "surfaceParts": sum(1 for p in parts if (p.get("role") or "solid") == "surface"),
        "ops": len(draft["ops"]) if draft else 0,
        "voxels": int((draft["model"].get("totalVoxels") or 0)) if draft else 0,
        "fidelity": chain.mode == "fidelity",
    }


def fingerprint(kind, errors, part_ids=()):
    """失败签名：错误类别 + 算子序号 + 部位 id + 规范化错误类型。

    坐标从消息中抹除用于归一化；签名覆盖完整错误集合（不是展示截断集），
    相同签名 = 同一失败的简单重发。
    """
    ops_idx = sorted({m.group(1) for e in errors for m in [_OP_RE.search(str(e))] if m}, key=str)
    types = tuple(_COORD_RE.sub("", str(e)).strip() for e in errors)
    parts = sorted({str(p) for p in part_ids})
    src = json.dumps({"kind": kind, "ops": ops_idx, "parts": parts, "types": types},
                     ensure_ascii=False, sort_keys=True)
    return {"kind": kind, "ops": ops_idx, "parts": parts,
            "digest": hashlib.sha1(src.encode("utf-8")).hexdigest()[:12]}


def progress_between(prev, cur):
    """相邻两次候选尝试之间的实质进展（条件 3 的四种形态），返回进展名或 None。

    门禁/部位/非法算子指标只在「当前候选也编译成功」时比较——从编译成功退回编译失败
    （此时门禁指标恒为 0）不是进展；反向退化同样不得放行。
    """
    if not prev.get("compiled") and cur.get("compiled"):
        return "compile_fixed"
    if not cur.get("compiled"):
        return None
    if not prev.get("compiled"):
        return None
    if cur.get("gateErrorCount", 0) < prev.get("gateErrorCount", 0):
        return "gate_errors_down"
    if cur.get("failedPartCount", 0) < prev.get("failedPartCount", 0):
        return "failed_parts_down"
    if cur.get("invalidOpCount", 0) < prev.get("invalidOpCount", 0):
        return "invalid_ops_down"
    if (cur.get("contractErrorCount") is not None and prev.get("contractErrorCount") is not None
            and cur.get("contractErrorCount", 0) < prev.get("contractErrorCount", 0)):
        return "contract_violations_down"
    return None


def dynamic_request_state(chain):
    """复杂任务第 4 次 draw 请求判定，返回 (allowed, detail)。

    四条件：
      1. 总请求与墙钟仍有额度（剩余模型时间 > 0，硬墙钟留出求解与产物余量）；
      2. 上一次候选输出是可纠正的新结果，而不是与上一次完全相同的重复；
      3. 历史上至少出现过一种实质进展（编译转成功 / 门禁错误数下降 /
         失败部位数下降 / 非法算子数下降）；
      4. 最新失败签名与之前所有失败签名都不同（不是同一失败的简单重发）。
    """
    metrics = chain_metrics(chain)
    votes = complexity_votes(metrics["requiredParts"], metrics["surfaceParts"],
                             metrics["ops"], metrics["voxels"], metrics["fidelity"])
    detail = {"metrics": metrics, "votes": votes, "complex": len(votes) >= COMPLEX_MIN_VOTES}
    if not dynamic_draw_enabled():
        return False, {**detail, "reason": "dynamic_disabled"}
    if len(votes) < COMPLEX_MIN_VOTES:
        return False, {**detail, "reason": "not_complex"}
    if chain.remaining_model() <= 0 or chain.remaining_hard() <= _RESERVE_HARD_S:
        return False, {**detail, "reason": "no_time_budget"}

    cands = [a for a in chain.draw_attempts if a.get("signature")]
    if not cands:
        return False, {**detail, "reason": "no_candidate"}
    last = cands[-1]
    if len(cands) >= 2 and cands[-2]["signature"] == last["signature"]:
        return False, {**detail, "reason": "repeat_of_previous"}
    if any(a["signature"] == last["signature"] for a in cands[:-1]):
        return False, {**detail, "reason": "resend_of_earlier"}
    pairs = list(zip(cands, cands[1:]))
    progress = [p for a, b in pairs if (p := progress_between(a, b))]
    if not progress:
        return False, {**detail, "reason": "no_progress",
                       "progressSeen": [a.get("outcome") for a in cands]}
    return True, {**detail, "reason": "allowed", "progress": progress}


def draw_request_limit(chain, base_limit):
    """draw 阶段的请求上限闭包：基础 base_limit 次；复杂任务满足四条件时 +DYNAMIC_DRAW_EXTRA。

    返回可调用对象，供 workflow._Chain.model_turn 在每次请求前求值；
    不放行时返回 base_limit，由统一的「请求耗尽」路径携带 reason 与最新拒绝收尾。
    """
    def limit():
        if chain.phase_requests < base_limit:
            return base_limit
        allowed, detail = dynamic_request_state(chain)
        chain.draw_dynamic = detail
        if allowed:
            return base_limit + DYNAMIC_DRAW_EXTRA
        return base_limit
    return limit
