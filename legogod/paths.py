"""项目路径统一出口：所有模块都从这里取路径，不依赖启动时的工作目录。"""
import os

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
ARTIFACTS_DIR = os.path.join(ROOT, "artifacts")
WEB_DIR = os.path.join(ROOT, "web")
EXAMPLES_DIR = os.path.join(ROOT, "examples")
ENV_FILE = os.path.join(ROOT, ".env")

# 3D 可视化页面（独立 lego-*.html）的输出目录：默认落在仓库内 artifacts/viz
# （换机可交付，不再写死个人绝对路径），可用环境变量 LEGOGOD_VIZ_DIR 覆盖。
VIZ_DIR = os.environ.get("LEGOGOD_VIZ_DIR") or os.path.join(ARTIFACTS_DIR, "viz")

# 子进程运行包内模块时需要的环境：保证从任意目录启动入口都能 import legogod
def subprocess_env():
    env = {**os.environ, "PYTHONIOENCODING": "utf-8"}
    old = env.get("PYTHONPATH")
    env["PYTHONPATH"] = ROOT + (os.pathsep + old if old else "")
    return env
