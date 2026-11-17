# 共享 LLM 访问层：OpenAI 兼容接口（支持 SSE 流式）+ JSON 提取
#
# 统一约定：
# - chat() 统一返回 {"content","reasoning_content","finish","requests"}，流式与普通一致；
# - deadline 为 time.monotonic() 绝对时刻：连接、读取和流式等待都受剩余时间约束，
#   到点抛 LLMDeadline，截止或取消后不回退重发；
# - 流式已收到部分数据后中断不自动重发（LLMStreamBroken）；
# - requests 记录本次调用实际发出的 HTTP 请求数（流式失败回退普通 = 2），
#   由调用方并入「每阶段最多 2 次实际请求」的预算。
import json, os, re, time, urllib.request, urllib.error
from .paths import ENV_FILE

# 不内置任何第三方模型默认值：公开版要求用户显式配置 LEGOGOD_MODEL，
# 避免把某一服务商的模型名当成项目约定（不同端点支持的模型名不同）。
MODEL_DEFAULT = ""
_CONFIG = None
# 推理原文回调最小间隔（秒）：比正文的 1.0s 更密，逐字增长才看得出来
REASONING_MIN_INTERVAL = 0.35


def _load_env(path=ENV_FILE):
    if not os.path.exists(path):
        return
    with open(path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                k, _, v = line.partition("=")
                v = v.strip().strip('"').strip("'")
                os.environ.setdefault(k.strip(), v.strip())


def config():
    """LLM 配置（延迟到首次请求时读取并校验；import 本模块不再要求已配置）。

    - 环境变量：LEGOGOD_BASE_URL / LEGOGOD_API_KEY 必填，LEGOGOD_MODEL 可选；
    - 校验失败在首次调用时抛 RuntimeError，纯静态接口（如 /api/parts）不再被连坐。
    """
    global _CONFIG
    if _CONFIG is None:
        _load_env()
        base_url = os.environ.get("LEGOGOD_BASE_URL", "")
        api_key = os.environ.get("LEGOGOD_API_KEY", "")
        if not (base_url and api_key):
            raise RuntimeError(
                "请先设置环境变量 LEGOGOD_BASE_URL 与 LEGOGOD_API_KEY"
                "（本地 .env 已配好，勿提交；参见 .env.example）")
        model = os.environ.get("LEGOGOD_MODEL") or MODEL_DEFAULT
        if not model:
            raise RuntimeError(
                "请设置环境变量 LEGOGOD_MODEL 为你的服务端支持的对话模型名"
                "（OpenAI 兼容端点；参见 .env.example）")
        _CONFIG = {"base_url": base_url, "api_key": api_key, "model": model}
    return _CONFIG


class LLMCancelled(Exception):
    """on_progress 回调抛出此异常 = 外部要求中止本次 LLM 调用（会穿透 _safe_cb）"""


class LLMDeadline(Exception):
    """模型调用的绝对截止已到：不再发起新请求，也不回退重发"""


class LLMStreamBroken(Exception):
    """流式响应已收到部分数据后中断：按协议不得自动重发"""


def _remaining(deadline):
    """返回距截止的剩余秒数；已到截止则抛 LLMDeadline。deadline=None 表示不限。"""
    if deadline is None:
        return None
    rem = deadline - time.monotonic()
    if rem <= 0:
        raise LLMDeadline("模型调用截止已到，不再发起新请求")
    return rem


def _request(body, timeout):
    cfg = config()
    req = urllib.request.Request(
        cfg["base_url"] + "/chat/completions", data=json.dumps(body).encode(),
        headers={"Content-Type": "application/json", "Authorization": f"Bearer {cfg['api_key']}",
                 "User-Agent": "legogod/1.0",
                 "Accept": "text/event-stream" if body.get("stream") else "application/json"},
    )
    return urllib.request.urlopen(req, timeout=timeout)


def _chat_block(body, timeout, verbose):
    """普通（非流式）请求。返回 (content, reasoning_content, finish, requests)。"""
    t0 = time.time()
    with _request(body, timeout) as r:
        data = json.loads(r.read().decode())
    msg = data["choices"][0]["message"]
    if verbose:
        print(f"  [api] {time.time() - t0:.1f}s, finish={data['choices'][0].get('finish_reason')}, "
              f"usage={data.get('usage', {}).get('completion_tokens')} tokens")
    return (msg.get("content") or "", msg.get("reasoning_content") or "",
            data["choices"][0].get("finish_reason"), 1)


def _safe_cb(cb, *a):
    try:
        cb(*a)
    except LLMCancelled:
        raise
    except Exception:
        pass


def _chat_stream(body, timeout, verbose, on_progress, deadline=None, on_reasoning=None):
    """SSE 流式请求。返回 (content, reasoning_content, finish, requests)。

    - 每收到一条数据检查一次绝对截止；
    - 已收到任何增量数据后发生传输错误 → 抛 LLMStreamBroken（调用方不得重发）；
    - 未收到任何数据时的错误原样抛出，由调用方决定是否回退普通请求；
    - on_reasoning(text_so_far, elapsed_s)：推理原文增量回调，
      与 on_progress 各自独立节流；结束时补发一次完整推理，保证末尾不丢。
    """
    body = {**body, "stream": True}
    t0, chunks, reasoning, finish = time.time(), [], [], None
    received = False
    last_cb = 0.0
    last_rz = 0.0
    try:
        with _request(body, timeout) as r:
            for raw in r:
                if deadline is not None and time.monotonic() > deadline:
                    raise LLMDeadline("流式等待超出模型调用截止，中止本次请求")
                line = raw.decode("utf-8", "replace").strip()
                if not line.startswith("data:"):
                    continue
                payload = line[5:].strip()
                if payload == "[DONE]":
                    break
                try:
                    obj = json.loads(payload)
                except ValueError:
                    continue
                ch = (obj.get("choices") or [{}])[0]
                delta = ch.get("delta") or {}
                if delta.get("content"):
                    chunks.append(delta["content"])
                    received = True
                if delta.get("reasoning_content"):
                    reasoning.append(delta["reasoning_content"])
                    received = True
                if ch.get("finish_reason"):
                    finish = ch["finish_reason"]
                    received = True
                now = time.time()
                if on_progress and now - last_cb >= 1.0:
                    last_cb = now
                    _safe_cb(on_progress, "".join(chunks), now - t0)
                # 推理原文走独立节流：0.35s 一次，肉眼已是连续增长，又不至于刷爆回调
                if on_reasoning and now - last_rz >= REASONING_MIN_INTERVAL:
                    last_rz = now
                    _safe_cb(on_reasoning, "".join(reasoning), now - t0)
    except (LLMCancelled, LLMDeadline):
        raise
    except Exception:
        if received:
            raise LLMStreamBroken("流式已收到部分数据后中断，按协议不自动重发")
        raise
    text = "".join(chunks)
    if on_progress:
        _safe_cb(on_progress, text, time.time() - t0)
    if on_reasoning and reasoning:
        _safe_cb(on_reasoning, "".join(reasoning), time.time() - t0)
    if verbose:
        print(f"  [api] 流式 {time.time() - t0:.1f}s, finish={finish}, {len(text)} 字符")
    return text, "".join(reasoning), finish, 1


def _default_model():
    """读取配置的模型名（不强制校验 API Key，供组装请求体与无 .env 单测使用）。"""
    if _CONFIG is not None:
        return _CONFIG["model"]
    _load_env()
    return os.environ.get("LEGOGOD_MODEL") or MODEL_DEFAULT


def chat(messages, max_tokens=16384, temperature=0.2, timeout=600, verbose=True,
         on_progress=None, deadline=None, reasoning_effort=None, on_reasoning=None):
    """对话补全。返回 {"content", "reasoning_content", "finish", "requests"}。

    - on_progress(text_so_far, elapsed_s)：流式期间的节流回调（约 1s 一次）；
      传入 on_progress 时优先走 SSE 流式。
    - on_reasoning(text_so_far, elapsed_s)：推理原文的节流回调（约 0.35s 一次）。
      只传 on_reasoning 不传 on_progress 时也走流式（推理需要逐 delta 才有意义）；
      最后 1 个请求槽位调用方会同时关掉两个回调，非流式路径返回后仍补发一次完整推理。
    - deadline：time.monotonic() 绝对时刻。连接/读取/流式等待都受剩余时间约束；
      已到截止抛 LLMDeadline；流式收到部分数据后中断抛 LLMStreamBroken——两者都不回退重发。
      只有「未收到任何流数据 + 未到截止」的流式失败才回退一次普通请求（requests=2）。
    - reasoning_effort：透传给服务端（如 "low"），画图与补丁阶段用低推理预算。
    - 密钥校验延迟到真正发起 HTTP 请求的 _request() 内执行，保证无 .env 环境下全部单测可运行。
    """
    rem = _remaining(deadline)
    body = {"model": _default_model(), "messages": messages,
            "max_tokens": max_tokens, "temperature": temperature}
    if reasoning_effort:
        body["reasoning_effort"] = reasoning_effort
    eff_timeout = min(timeout, rem) if rem is not None else timeout
    if on_progress is not None or on_reasoning is not None:
        try:
            content, reasoning, finish, n = _chat_stream(
                body, eff_timeout, verbose, on_progress, deadline, on_reasoning)
            return {"content": content, "reasoning_content": reasoning,
                    "finish": finish, "requests": n}
        except (LLMCancelled, LLMDeadline, LLMStreamBroken):
            raise
        except Exception as e:
            rem = _remaining(deadline)  # 已到截止则直接抛 LLMDeadline，不回退
            print(f"  [api] 流式请求失败，回退普通模式：{e}")
            eff_timeout = min(timeout, rem) if rem is not None else timeout
            t_block = time.time()
            content, reasoning, finish, n = _chat_block(body, eff_timeout, verbose)
            _emit_block_reasoning(on_reasoning, reasoning, time.time() - t_block)
            # 首次流式 + 回退普通请求合并计数 = 2
            return {"content": content, "reasoning_content": reasoning,
                    "finish": finish, "requests": n + 1}
    t_block = time.time()
    content, reasoning, finish, n = _chat_block(body, eff_timeout, verbose)
    _emit_block_reasoning(on_reasoning, reasoning, time.time() - t_block)
    return {"content": content, "reasoning_content": reasoning,
            "finish": finish, "requests": n}


def _emit_block_reasoning(on_reasoning, reasoning, elapsed=0.0):
    """非流式路径：返回后一次性补发完整推理原文（无逐字过程但不丢内容）。"""
    if on_reasoning and reasoning:
        _safe_cb(on_reasoning, reasoning, elapsed)


def iter_json_objects(text):
    """按顺序产出文本中每个「顶层」完整 JSON 对象（容忍 markdown 代码块与前后杂质）。

    推理模型有时会把多个动作连在一起输出；恢复空输出时要求「恰好一个」候选，
    所以这里逐个产出而不是只取第一个。注意嵌套对象不算独立候选：
    顶层对象匹配后从其结尾继续扫描。
    """
    text = re.sub(r"```(?:json)?", "", text or "")
    start = text.find("{")
    while start >= 0:
        depth, in_str, escape = 0, False, False
        end = -1
        for k in range(start, len(text)):
            ch = text[k]
            if in_str:
                if escape:
                    escape = False
                elif ch == "\\":
                    escape = True
                elif ch == '"':
                    in_str = False
                continue
            if ch == '"':
                in_str = True
            elif ch == "{":
                depth += 1
            elif ch == "}":
                depth -= 1
                if depth == 0:
                    end = k
                    try:
                        yield json.loads(text[start:k + 1])
                    except json.JSONDecodeError:
                        pass
                    break
        start = text.find("{", (end + 1) if end >= 0 else start + 1)


def parse_json(text):
    """从模型输出中提取第一个完整 JSON 对象。

    容错：markdown 代码块、JSON 前后杂质、以及「一次输出多个 JSON 对象」（取第一个完整对象）。
    """
    text = re.sub(r"```(?:json)?", "", text or "").strip().strip("`")
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass
    for obj in iter_json_objects(text):
        return obj
    raise json.JSONDecodeError("no complete JSON object found", (text or "")[:200], 0)
