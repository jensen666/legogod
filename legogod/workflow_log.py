# -*- coding: utf-8 -*-
"""工作流默认日志与真实模型/评审入口（从 workflow.py 拆出，保持行为不变）。

拆分原因：workflow.py 曾超过 500 行生产文件上限。
这里只放无状态的小函数；_Chain 等主链逻辑仍在 workflow.py，导入后仍以
`workflow._console_log` / `workflow._default_chat` / `workflow._default_review` 对外可用。
"""
from . import llm


def _console_log(kind, text, meta=None):
    """默认控制台日志：GBK 等受限编码的控制台上 ⚠ 表情会抛 UnicodeEncodeError，
    用 replace 降级输出，保证任务不因日志打印中断（评审 P2）。

    progress / views 不进日志列表，命令行只补一句进度，避免再刷出逐层墙。
    """
    if kind == "views":
        return
    if kind == "progress" and isinstance(meta, dict):
        text = text or (f"铺砖 第 {meta.get('layer')} 层 / 共 {meta.get('total')} 层，"
                        f"第 {meta.get('round')} 轮")
    line = f"[{kind}] {text}"
    try:
        print(line)
    except UnicodeEncodeError:
        import sys
        enc = getattr(sys.stdout, "encoding", None) or "ascii"
        print(line.encode(enc, "replace").decode(enc, "replace"))


def _default_chat(messages, **kw):
    """默认对话入口（真实 LLM；测试/降级时由 chat_fn 注入覆盖）。"""
    return llm.chat(messages, **kw)


def _default_review(desc, model, solution=None, **kw):
    """默认视觉评审入口（真实多视角渲染 + 评审模型）。"""
    from .review import review_design
    return review_design(desc, model, solution, **kw)


def solver_progress(log_fn):
    """把求解器的层进度送到 progress 通道，不写进日志正文。"""
    def on_progress(info):
        if isinstance(info, dict):
            log_fn("progress", "", dict(info))
    return on_progress


def wrap_review(review_fn, log_fn):
    """渲染图一落盘就通知 views 通道，不等评审模型返回，也不改产物写入。"""
    def _review(desc, model, solution=None, **kw):
        def _shot(views, sheet):
            log_fn("views", "", {"views": views, "sheet": sheet})
        kw.setdefault("on_rendered", _shot)
        return review_fn(desc, model, solution, **kw)
    return _review


class ThinkingFeed:
    """一个模型回合的思考通道。

    - 流式期间每次回调覆盖实时通道（done=False），前端逐字展示；
    - 回合结束或取消/流断时落一条日志条目（done=True），实时通道由 job_feed 清空；
    - 没有推理（服务商不返回 reasoning_content）时一个事件都不发，界面完全隐藏。
    """

    def __init__(self, emit, should_stop):
        self.emit = emit
        self.should_stop = should_stop
        self.text = ""
        self.elapsed = 0.0

    def on_reasoning(self, text, elapsed):
        """流式推理回调：取消检查与正文进度同口径（抛 LLMCancelled 穿透 _safe_cb）。"""
        if self.should_stop():
            raise llm.LLMCancelled()
        self.text, self.elapsed = text or "", elapsed
        if self.text:
            self.emit("thinking", "", {"text": self.text, "elapsed": elapsed,
                                       "done": False, "partial": False})

    def adopt(self, reasoning, elapsed):
        """非流式槽位没有实时回调：响应里带回的完整推理在这里补一次。"""
        if not self.text and reasoning:
            self.text, self.elapsed = reasoning, elapsed

    def close(self, partial=False):
        """回合结束：落一条 thinking 日志。清空内部状态，避免同一回合重复落盘。"""
        if not self.text:
            return
        self.emit("thinking", "", {"text": self.text, "elapsed": self.elapsed,
                                   "done": True, "partial": partial})
        self.text = ""
