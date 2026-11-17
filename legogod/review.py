"""视觉评审：把多视角渲染图交给多模态模型，返回结构化评分与局部修改建议。

渲染异常或缺少 Pillow 时如实返回 ok=False（附带 error），由主链降级为 review_unavailable，
不让可选依赖异常冒泡为整任务 internal 崩溃。
"""
import base64
import json
import os
import time

from . import llm
from .paths import ARTIFACTS_DIR

REVIEW_PROMPT = """你是乐高模型的视觉评审员。用户目标：{desc}

图中是一个 LEGO 体素模型的四个视角（从左到右：正视图、侧视图、俯视图、等轴测图）。
请严格按以下标准评审，并用 JSON 回复（不要输出其他内容，不要长篇推理）：

{{"scores": {{"overall": 0-10, "proportion": 0-10, "features": 0-10, "color": 0-10, "detail": 0-10}},
 "missing_features": ["用户要求但图中看不到或严重失真的特征"],
 "worst_parts": ["最差的部位，指出视角和位置，如 '正视图左侧车头比例偏短'"],
 "suggestions": ["具体可执行的局部修改，如 '把车头 x=12..15 两层各前伸 1 格'"],
 "keep": ["不要改动的部位"]}}

评分标准：
- proportion：整体长宽高比例与目标是否一致；
- features：必须存在的辨识特征是否真实出现在正确位置；
- color：颜色分区是否符合目标；
- detail：轮廓、收分、层次是否足够精细；
- overall：整体像不像用户描述的东西。
只基于图片中真实可见的内容打分，不要猜测。
注意：图中侧面/顶面有简单明暗（同一颜色在不同面会深浅不同），判断颜色请以正面和顶面为准。
正/反斜坡部位会按坡向渲染成斜面/三角面，请按真实坡向检查。"""


def _image_b64(path):
    """读取 PNG 文件并编码为 Base64 字符串。"""
    with open(path, "rb") as f:
        data = f.read()
    return base64.b64encode(data).decode("ascii"), "image/png"


def _parse_json(text):
    """从模型输出里提取完整 JSON 对象（复用 llm.parse_json 的括号平衡容错逻辑）。"""
    if not text:
        return None
    try:
        obj = llm.parse_json(text)
        return obj if isinstance(obj, dict) else None
    except Exception:
        return None


def review_design(desc, model, solution=None, spec=None, out_dir=None, scale=22, verbose=True,
                  deadline=None, max_requests=2, name_prefix="view", should_stop=None,
                  on_rendered=None):
    """渲染四视图并调用多模态模型评审；渲染/依赖不可用时返回 ok=False 供主链降级。

    should_stop() 返回 True（用户取消）时立即中止评审：已发出的请求通过流式进度回调
    （约 1s 一次）抛 LLMCancelled 打断，重试间隙与发起新请求前也各检查一次；
    结果标记 stopped_by_cancel=True，由主链转为任务取消（不得当作评审不可用降级继续跑）。
    """
    out_dir = out_dir or os.path.join(ARTIFACTS_DIR, "views")
    try:
        from .render import compose_sheet, render_views
        views = render_views(model, solution, out_dir, scale=scale, name_prefix=name_prefix)
        sheet = compose_sheet(list(views.values()), os.path.join(out_dir, f"{name_prefix}_sheet.png"))
        if callable(on_rendered):
            # 图已经写好。先交给界面，再等评审模型，避免「评审阶段不出图」。
            try:
                on_rendered(views, sheet)
            except Exception as exc:  # noqa: BLE001 - 通知失败不改变评审结果
                print(f"[review] 渲染图通知失败（不影响评审）：{exc}", flush=True)
        b64, mime = _image_b64(sheet)
    except Exception as e:
        if verbose:
            print(f"[review] 多视角渲染不可用，降级跳过评审：{e}")
        return {"ok": False, "error": str(e), "raw": "", "finish": None, "parsed": {},
                "views": {}, "sheet": None, "requests": 0, "stopped_by_deadline": False,
                "stopped_by_cancel": False}

    prompt = REVIEW_PROMPT.format(desc=desc)
    if spec:
        prompt += "\n\n用户给出的外观契约（必须逐条对照检查）：\n" + str(spec)[:4000]
    messages = [
        {"role": "system", "content": "你是严格的乐高模型视觉评审员，只输出 JSON。"},
        {"role": "user", "content": [
            {"type": "text", "text": prompt},
            {"type": "image_url", "image_url": {"url": f"data:{mime};base64,{b64}"}},
        ]},
    ]
    parsed = {}
    text, finish = "", None
    requests = 0
    stopped_by_deadline = False
    stopped_by_cancel = False

    def on_progress(_text, _elapsed):
        # 流式期间约 1s 一次的取消检查：命中即抛 LLMCancelled 打断 in-flight 请求
        if should_stop is not None and should_stop():
            raise llm.LLMCancelled()

    for attempt in range(max(1, max_requests)):
        if should_stop is not None and should_stop():
            stopped_by_cancel = True
            if verbose:
                print("[review] 收到取消信号，停止评审请求")
            break
        if deadline is not None and time.monotonic() >= deadline:
            stopped_by_deadline = True
            if verbose:
                print("[review] 距模型调用截止不足，停止评审请求")
            break
        try:
            resp = llm.chat(messages, max_tokens=20000, temperature=0.2, verbose=verbose,
                            deadline=deadline, on_progress=on_progress if should_stop else None)
        except llm.LLMDeadline:
            stopped_by_deadline = True
            break
        except llm.LLMCancelled:
            stopped_by_cancel = True
            break
        requests += max(1, resp.get("requests", 1))
        text = resp.get("content") or ""
        finish = resp.get("finish")
        parsed = _parse_json(text) or {}
        if parsed:
            break
        if attempt < max_requests - 1 and verbose:
            print(f"[review] 第 {attempt + 1} 次评审未获得结构化 JSON（finish={finish}），在预算内重试")
    result = {
        "ok": bool(parsed),
        "raw": text,
        "finish": finish,
        "parsed": parsed,
        "views": views,
        "sheet": sheet,
        "requests": requests,
        "stopped_by_deadline": stopped_by_deadline,
        "stopped_by_cancel": stopped_by_cancel,
    }
    try:
        with open(os.path.join(out_dir, f"{name_prefix}_review.json"), "w", encoding="utf-8") as f:
            json.dump(result, f, ensure_ascii=False, indent=2)
    except OSError:
        pass
    return result
