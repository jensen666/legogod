# ============================================================
# 乐高 Agent 命令行入口（固定主链见 workflow.py）
# 用法（在项目根目录执行）:
#   python -m legogod build                        # 交互式（Agent 可提问）
#   python -m legogod build --desc "一只小狗"      # 直接给描述
#   python -m legogod build --desc "..." --yes     # 自动模式（Agent 不提问）
#   python -m legogod build --desc "..." --fidelity  # 高保真（视觉评审 + 逐体素配色）
# ============================================================
import argparse
import sys
import threading

from .workflow import run_generation


def _run_cancelable(desc, **kw):
    """后台线程跑主链，主线程等待期间支持 Ctrl+C 取消。

    第一次 Ctrl+C：设置取消事件，主链在模型/评审/求解回调点抛出 CancelledError，
    如实返回「任务已取消」并照常写运行记录（直接杀进程则什么都留不下）；
    第二次 Ctrl+C：不再等待，以 130 强退（残留后台线程随进程退出）。
    """
    cancel = threading.Event()
    done = threading.Event()
    box = {}

    def worker():
        try:
            box["result"] = run_generation(desc, cancel=cancel, **kw)
        finally:
            done.set()

    threading.Thread(target=worker, daemon=True).start()
    try:
        while not done.wait(0.2):
            pass
    except KeyboardInterrupt:
        cancel.set()
        print("\n收到取消信号，正在停止任务……（再次按 Ctrl+C 强制退出）", file=sys.stderr)
        try:
            while not done.wait(0.2):
                pass
        except KeyboardInterrupt:
            raise SystemExit(130)
    return box.get("result") or {"ok": False, "error": "任务已取消",
                                 "failure": {"kind": "cancelled"}, "status": "cancelled"}


def main(argv=None):
    """命令行主流程：解析参数 → 跑固定主链 → 打印结果；返回进程退出码。"""
    ap = argparse.ArgumentParser(description="乐高拼装 Agent（命令行入口）")
    ap.add_argument("--desc", help="直接给出需求描述")
    ap.add_argument("--yes", action="store_true", help="自动模式：Agent 不提问，按合理默认执行")
    ap.add_argument("--fidelity", action="store_true",
                    help="高保真模式：外观契约 → 逐体素配色 → 多视角渲染评审 → 局部修改 → 求解")
    args = ap.parse_args(argv)

    desc = args.desc
    if not desc:
        desc = input("\n描述你想拼的东西（例如：一座小桥 / 一只小狗 / 一辆小汽车）> ").strip()
        while not desc:
            desc = input("描述不能为空，请再输入 > ").strip()

    print()
    result = _run_cancelable(desc, interactive=not args.yes,
                             mode="fidelity" if args.fidelity else "fast",
                             log=lambda kind, text, meta=None: print(f"[{kind}] {text}"))

    print("\n================= 结果 =================")
    if result["ok"]:
        print(f"模型: {result['name']}  |  {result['grid']['w']}×{result['grid']['d']} × {result['layers']} 层，"
              f"{result['voxels']} 体素  |  {result['pieces']} 块零件，求解 {result['attempts']} 轮"
              f"  |  run {result['run_id']} 版本 r{result['revision']:03d}")
        print("产出文件:")
        for k, label in (("md_path", "拼装指南"), ("model_path", "设计数据"),
                         ("solution_path", "方案数据"), ("viz_file", "3D 可视化")):
            if result.get(k):
                print(f"  - {result[k]}  ({label})")
        return 0

    print("未能完成：", result.get("error"))
    failure = result.get("failure") or {}
    if failure:
        print(f"失败类别: {failure.get('kind')}（阶段 {failure.get('stage')}）")
    return 1


if __name__ == "__main__":
    sys.exit(main())
