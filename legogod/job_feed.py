# ============================================================
# 任务馈送：日志 / 最新设计稿 / 求解进度 / 评审图 四条通道分开存放。
#
# 运行日志只做展示与复盘证据。设计稿和进度每次覆盖，不进日志列表，
# 因此不会被日志配额挤掉。
# 关键事件（阶段 / 评审 / 结果 / 错误，以及规划、版本、修订里程碑）永不淘汰；
# 求解明细等噪音只保留最近若干条。内存里的列表已经整理过，落盘不得再截断一次。
# ============================================================
import hashlib
import json
import os

from .parts_library import CHAR_COLORS, COLORS, PART_MAP

# 阶段、评审、结果、错误必须在超长运行后仍然完整。
# 规划确认、版本落盘、修订接受同样是复盘里程碑，条数很少，一并视为关键事件。
KEY_KINDS = frozenset({
    "phase", "review", "result", "error", "plan", "version", "revise",
})
# 求解器逐层明细、模型思考、工具观察是噪音：可以淘汰，不能挤掉关键事件。
NOISE_KINDS = frozenset({
    "solver", "thought", "info", "tool", "ask", "answer",
})
NOISE_CAP = 240
# 模型思考原文不共用噪音配额：它按自己的条数上限淘汰。
# 长任务里 solver 明细能刷满 240 条噪音，共用配额会把早期思考当最旧噪音删掉，
# 「已完成任务能回看每一轮思考」就不成立了。
THINKING_KIND = "thinking"
THINKING_KEEP = 60
THINKING_MAX_CHARS = 12000   # 单条上限（头 9000 + 尾 3000）
THINKING_HEAD_CHARS = 9000
THINKING_TAIL_CHARS = 3000
THINKING_LIVE_TAIL = 4000    # 实时通道只保留末尾，避免每次轮询搬全量
_VIEW_KEYS = ("front", "side", "top", "iso")


def empty_stage():
    """阶段徽标的初始状态：还没有任何真实阶段。"""
    return {"current": None, "seen": [], "revise": 0}


def fresh_feed():
    """新任务的五条通道。logs 仍是列表；除 logs 外每次覆盖（thinking 由 apply_event 管理）。"""
    return {"design": None, "progress": None, "stage": empty_stage(), "views": None,
            "thinking": None}


def apply_event(job, kind, text, meta=None, now=None):
    """把一条回调写进对应通道。调用方必须已持有任务锁。

    live / progress / views / design / thinking 不进入日志列表。其余条目追加，
    噪音超出配额时只删最旧的噪音；thinking 完成时另追加一条日志条目。
    """
    import time
    meta = dict(meta or {})
    if kind == "live":
        job["live"] = text
        return
    job["live"] = None
    if kind == "progress":
        parsed = _progress(meta)
        if parsed:
            job["progress"] = parsed
        return
    if kind == "views":
        urls = urls_from_sheet(meta.get("sheet"), meta.get("views"))
        if urls:
            job["views"] = urls
            print(f"[job_feed] 评审图已暴露：{','.join(urls)}", flush=True)
        return
    if kind == "design":
        compact = compact_design(meta.get("design"), meta.get("revision"))
        if compact:
            job["design"] = compact
            print(f"[job_feed] 设计稿已覆盖 stamp={compact.get('stamp')} "
                  f"layers={len(compact.get('layers') or [])}", flush=True)
        return
    if kind == THINKING_KIND:
        if _apply_thinking(job, text, meta, now):
            return
    if kind == "phase":
        _note_phase(job, meta.get("phase"))
    entry = {"kind": kind, "text": text, "ts": round(now if now is not None else time.time(), 3)}
    # 整份模型不进日志。阶段名等小字段可以留下，供复盘里程碑使用。
    slim = {k: v for k, v in meta.items() if k != "design"}
    entry.update(slim)
    logs = job.setdefault("logs", [])
    logs.append(entry)
    if kind not in KEY_KINDS:
        _trim_noise(job)


def truncate_thinking(text, max_chars=None):
    """思考原文截断：保留开头与结尾，中间标注被截掉多少字。

    开头通常给整体方案、结尾通常给最终决定，中间最容易丢。返回 (正文, 是否截断)。
    """
    text = text or ""
    limit = THINKING_MAX_CHARS if max_chars is None else max_chars
    if len(text) <= limit:
        return text, False
    head, tail = THINKING_HEAD_CHARS, THINKING_TAIL_CHARS
    if head + tail >= limit:  # 上限被调小时按比例收口，仍然头尾都留
        head = max(0, limit * 3 // 4)
        tail = max(0, limit - head)
    marker = f"\n……（已截断，原文 {len(text)} 字）……\n"
    return text[:head] + marker + (text[-tail:] if tail else ""), True


def _apply_thinking(job, text, meta, now):
    """thinking 通道：未完成时覆盖实时通道；完成时追加日志条目并清空实时通道。

    返回 True 表示已完全处理（不再走通用日志追加）。done=True 时文本按头尾规则截断，
    原始字数记在 chars，截断与否记在 truncated。正文既可走 text 参数，也可放 meta["text"]
    （调用方 emit 时把正文放元数据里，日志正文留空）。
    """
    import time
    text = text or meta.get("text") or ""
    if not text:
        # 服务商不返回推理：不发事件、不建实时通道，界面与现状完全一致
        if meta.get("done"):
            job["thinking"] = None
        return True
    if not meta.get("done"):
        job["thinking"] = {
            "phase": meta.get("phase"),
            "text": text[-THINKING_LIVE_TAIL:] if text else "",
            "elapsed": meta.get("elapsed"), "done": False,
            "partial": False, "chars": len(text),
        }
        return True
    body, truncated = truncate_thinking(text)
    entry = {"kind": THINKING_KIND, "text": body,
             "ts": round(now if now is not None else time.time(), 3),
             "phase": meta.get("phase"), "done": True,
             "partial": bool(meta.get("partial")),
             "chars": len(text), "truncated": truncated,
             "elapsed": meta.get("elapsed")}
    job.setdefault("logs", []).append(entry)
    job["thinking"] = None
    _trim_thinking(job)
    return True


def _trim_thinking(job):
    """思考条目只按自身条数上限淘汰最旧的一条，不占关键事件、也不占噪音配额。"""
    logs = job.get("logs") or []
    at = [i for i, entry in enumerate(logs) if entry.get("kind") == THINKING_KIND]
    extra = len(at) - THINKING_KEEP
    if extra <= 0:
        return
    drop = set(at[:extra])
    job["logs"] = [entry for i, entry in enumerate(logs) if i not in drop]
    print(f"[job_feed] 思考条目淘汰 {extra} 条，保留最近 {THINKING_KEEP} 条", flush=True)


def compact_design(model, revision=None):
    """收成预览所需的体素与配色，丢掉算子和部位绑定等大字段。"""
    if not isinstance(model, dict):
        return None
    layers = []
    for layer in model.get("layers") or []:
        if not isinstance(layer, dict) or not isinstance(layer.get("rows"), list):
            continue
        item = {"y": layer.get("y"), "rows": [str(row) for row in layer["rows"]]}
        if isinstance(layer.get("color"), str):
            item["color"] = layer["color"]
        if isinstance(layer.get("colorRows"), list):
            item["colorRows"] = [str(row) for row in layer["colorRows"]]
        layers.append(item)
    grid = model.get("grid") if isinstance(model.get("grid"), dict) else {}
    rev = revision if revision is not None else model.get("revision")
    compact = {
        "name": model.get("name") if isinstance(model.get("name"), str) else None,
        "slug": model.get("slug") if isinstance(model.get("slug"), str) else None,
        "grid": {"w": grid.get("w"), "d": grid.get("d")},
        "layers": layers,
        "totalVoxels": model.get("totalVoxels") if isinstance(model.get("totalVoxels"), int) else None,
        "revision": rev,
        # 配色表随设计稿下发，前端不硬编码零件清单，也不自己猜颜色字符。
        "palette": {name: spec["hex"] for name, spec in COLORS.items()},
        "chars": dict(CHAR_COLORS),
    }
    raw = json.dumps(layers, ensure_ascii=False, sort_keys=True)
    compact["stamp"] = hashlib.sha1(raw.encode("utf-8")).hexdigest()[:12]
    return compact


def color_distribution(result):
    """历史摘要用的颜色分布。没有方案颜色时返回 None，界面留空。"""
    if not isinstance(result, dict):
        return None
    raw = result.get("colors")
    if not isinstance(raw, dict) or not raw:
        return None
    items, total = [], 0
    for name, cnt in raw.items():
        if isinstance(cnt, bool) or not isinstance(cnt, (int, float)) or cnt <= 0:
            continue
        if not isinstance(name, str):
            continue
        items.append((name, int(cnt)))
        total += int(cnt)
    if total <= 0:
        return None
    out = []
    for name, cnt in items:
        out.append({
            "name": name, "count": cnt,
            "hex": (COLORS.get(name) or {}).get("hex"),
            "share": round(cnt / total, 4),
        })
    return out or None


def fill_missing_colors(items, snapshots, artifacts_dir):
    """列表项没有颜色时，从已落盘的方案统计。调用方不要在全局锁里读这些文件。

    方案 colors 为空，是因为旧求解器跳过了只有逐体素色的层。零件 id 里仍然有颜色。
    全部都是默认色旧 id 的历史模型不当成配色，摘要继续留空。
    """
    for item in items or []:
        if item.get("colors"):
            continue
        snap = snapshots.get(item.get("id")) or {}
        dist = color_distribution({"colors": snap.get("colors")})
        if not dist and snap.get("solution_path"):
            dist = _distribution_from_solution(artifacts_dir, snap.get("solution_path"))
        if dist:
            item["colors"] = dist


def _distribution_from_solution(artifacts_dir, name):
    """从方案文件统计颜色。文件不存在或全是旧默认 id 时返回 None。"""
    base = os.path.basename(str(name or ""))
    if not base or base != str(name) or base.startswith("."):
        return None
    path = os.path.join(artifacts_dir, base)
    try:
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
    except (OSError, json.JSONDecodeError, UnicodeError):
        return None
    if not isinstance(data, dict):
        return None
    dist = color_distribution(data)
    if dist:
        return dist
    counts = {}
    explicit = False
    for step in data.get("steps") or []:
        if not isinstance(step, dict):
            continue
        part = PART_MAP.get(step.get("piece"))
        if not part:
            continue
        if part.get("id") != part.get("shape"):
            explicit = True
        color_name = part.get("colorName")
        if color_name:
            counts[color_name] = counts.get(color_name, 0) + 1
    if not explicit:
        return None
    return color_distribution({"colors": counts})


def color_snapshots(jobs_by_id, items):
    """在锁内抄出补色所需的最小字段，避免锁外再碰任务对象。"""
    out = {}
    for item in items or []:
        job = jobs_by_id.get(item.get("id")) or {}
        result = job.get("result") if isinstance(job.get("result"), dict) else {}
        out[item.get("id")] = {
            "colors": result.get("colors"),
            "solution_path": result.get("solution_path"),
        }
    return out


def urls_from_sheet(sheet, views=None):
    """把已落盘的评审图路径收成 /views/<文件名>。文件不存在就不暴露。"""
    found = {}
    if isinstance(views, dict):
        for key in _VIEW_KEYS:
            url = _png_url(views.get(key))
            if url:
                found[key] = url
    sheet_url = _png_url(sheet)
    if sheet_url:
        found["sheet"] = sheet_url
    if isinstance(sheet, str) and os.path.basename(sheet).endswith("_sheet.png"):
        prefix = os.path.basename(sheet)[:-len("_sheet.png")]
        folder = os.path.dirname(sheet)
        for key in _VIEW_KEYS:
            if key in found:
                continue
            url = _png_url(os.path.join(folder, f"{prefix}_{key}.png"))
            if url:
                found[key] = url
    return found or None


def persist_record(job):
    """落盘快照。logs 已按分桶整理过，这里原样写入，不再二次截断。"""
    return {
        "status": job.get("status"),
        "logs": list(job.get("logs") or []),
        "result": job.get("result"),
        "desc": job.get("desc"),
        "mode": job.get("mode"),
        "retryOf": job.get("retryOf"),
        "reviewContext": job.get("reviewContext"),
        "startedAt": job.get("startedAt"),
        "design": job.get("design"),
        "progress": job.get("progress"),
        "stage": job.get("stage") or empty_stage(),
        "views": job.get("views"),
        "thinking": job.get("thinking"),
    }


def restore_record(jid, raw):
    """从磁盘恢复。不重新截断日志。重启前的 running 由调用方改成 interrupted。"""
    logs = raw.get("logs") or []
    started = raw.get("startedAt") or (
        logs[0].get("ts") if logs and isinstance(logs[0], dict) and logs[0].get("ts") else None)
    stage = raw.get("stage") if isinstance(raw.get("stage"), dict) else empty_stage()
    return {
        "id": jid, "status": raw.get("status"), "logs": logs, "live": None,
        "result": raw.get("result"), "desc": raw.get("desc"), "mode": raw.get("mode"),
        "retryOf": raw.get("retryOf"), "reviewContext": raw.get("reviewContext"),
        "startedAt": started, "design": raw.get("design"), "progress": raw.get("progress"),
        "stage": stage, "views": raw.get("views"),
        # 重启后不存在「正在流式」的现场：实时通道一律置空，落盘的 thinking 日志条目照常显示
        "thinking": None,
    }


def public_view(job):
    """单任务查询返回的馈送字段。历史任务没有 views 时，从结果里的评审图路径补。"""
    views = job.get("views")
    if not views:
        result = job.get("result") if isinstance(job.get("result"), dict) else {}
        views = urls_from_sheet((result or {}).get("review_sheet"))
    return {
        "design": job.get("design"),
        "progress": job.get("progress"),
        "stage": job.get("stage") or empty_stage(),
        "views": views,
        "thinking": job.get("thinking"),
    }


def _note_phase(job, name):
    """记录真实阶段名。修订每开始一次，角标加一。不从日志正文猜测。"""
    if not isinstance(name, str) or not name or name == "init":
        return
    stage = job.setdefault("stage", empty_stage())
    if not isinstance(stage.get("seen"), list):
        stage["seen"] = []
    stage["current"] = name
    if name == "revise":
        stage["revise"] = int(stage.get("revise") or 0) + 1
    if name not in stage["seen"]:
        stage["seen"].append(name)
    print(f"[job_feed] 阶段 {name} revise={stage.get('revise')}", flush=True)


def _progress(meta):
    """求解器显式上报的层号 / 总层数 / 轮次。缺字段就不当成进度，避免伪进度。"""
    if not isinstance(meta, dict):
        return None
    try:
        layer, total, rnd = int(meta.get("layer")), int(meta.get("total")), int(meta.get("round"))
    except (TypeError, ValueError):
        return None
    if layer < 1 or total < 1 or rnd < 1:
        return None
    out = {"layer": layer, "total": total, "round": rnd}
    if meta.get("y") is not None:
        try:
            out["y"] = int(meta["y"])
        except (TypeError, ValueError):
            pass
    if meta.get("rounds") is not None:
        try:
            out["rounds"] = int(meta["rounds"])
        except (TypeError, ValueError):
            pass
    return out


def _trim_noise(job):
    """只删除最旧的噪音。关键事件的相对顺序和内容都保持不变。

    thinking 不参与噪音配额（它有独立的 THINKING_KEEP 上限）：否则长任务里
    solver 明细会先把早期思考当最旧噪音删掉。
    """
    logs = job.get("logs") or []
    # 未列入 KEY 的种类按噪音淘汰；KEY 与 thinking 永不进入待删下标。
    noise_at = [i for i, entry in enumerate(logs)
                if entry.get("kind") not in KEY_KINDS and entry.get("kind") != THINKING_KIND]
    extra = len(noise_at) - NOISE_CAP
    if extra <= 0:
        return
    drop = set(noise_at[:extra])
    job["logs"] = [entry for i, entry in enumerate(logs) if i not in drop]
    print(f"[job_feed] 噪音日志淘汰 {extra} 条，保留关键事件 {sum(1 for e in job['logs'] if e.get('kind') in KEY_KINDS)} 条",
          flush=True)


def _png_url(path):
    """只暴露真实存在的 png 文件名，不把本机绝对路径送给前端。"""
    if not isinstance(path, str) or not path.lower().endswith(".png"):
        return None
    name = os.path.basename(path)
    if not name or name.startswith(".") or "/" in name or "\\" in name:
        return None
    if not os.path.isfile(path):
        return None
    return "/views/" + name
