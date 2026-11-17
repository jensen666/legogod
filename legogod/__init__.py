"""LEGOGOD 核心包：体素设计 → 拼装求解 → 步骤文档 + 3D 可视化。

统一入口（在项目根目录执行）：
    python -m legogod                    # 组合部署（Web 工坊 + API）
    python -m legogod api --port 8600     # 独立 API（不读取 Web 应用壳）
    python -m legogod web --api-url URL   # 独立 Web 静态服务（不持有任务状态）
    python -m legogod build --desc "..." --yes   # 命令行
"""

__version__ = "1.0.0"
