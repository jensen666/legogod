"""python -m legogod 统一入口（Web 工坊 / 独立 API / 独立 Web 静态服务 / 命令行构建）。

用法（在项目根目录执行）:
    python -m legogod                     # 组合部署：Web 工坊 + API，默认端口 8600
    python -m legogod web [port]          # 组合部署（同上，兼容旧用法）
    python -m legogod [port]              # 快捷形式：直接给端口
    python -m legogod api [--host --port --api-token --allowed-origins]
                                          # 独立 API：不读取 Web 应用壳
    python -m legogod web --api-url <URL> [--host --port]
                                          # 独立 Web 静态服务：不持有任务状态
    python -m legogod build [参数...]     # 命令行构建（参数见 legogod.cli）

"""
import sys

USAGE = """用法:
  python -m legogod                       组合部署（Web + API），默认 127.0.0.1:8600
  python -m legogod [port]                组合部署，指定端口
  python -m legogod web [port]            组合部署（兼容旧用法）
  python -m legogod api [选项]            独立 API 服务
  python -m legogod web --api-url <URL>   独立 Web 静态服务（指向真实 API）
  python -m legogod build [参数...]       命令行构建

服务选项:
  --host <地址>            监听地址（缺省 127.0.0.1；非回环必须配置令牌）
  --port <端口>            监听端口（缺省 8600）
  --api-url <URL>          仅 web 模式：独立 Web 静态服务要指向的 API Base URL
  --api-token <令牌>       API Bearer 令牌（也可用环境变量 LEGOGOD_API_TOKEN）
  --allowed-origins <列表> 逗号分隔的精确 Origin allowlist（不接受 *）
"""


def _utf8_console():
    """Windows 控制台默认 GBK，日志里的 ⚠ 等字符会抛 UnicodeEncodeError 中断任务：
    统一入口把 stdout/stderr 重配为 UTF-8（reconfigure 不可用时无害跳过）。"""
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
        except (AttributeError, ValueError, OSError):
            pass


def main(argv=None):
    """按子命令分发：无子命令/web/数字端口 → 服务；api → 独立 API；build → 命令行构建。"""
    _utf8_console()
    argv = list(sys.argv[1:] if argv is None else argv)
    cmd = argv[0] if argv else "web"
    if cmd in ("-h", "--help", "help"):
        print(USAGE)
        return 0
    if cmd == "build":
        from .cli import main as cli_main
        return cli_main(argv[1:])
    if cmd in ("web", "api"):
        from .server import main as server_main
        # 保留子命令本身：server 依据 "web --api-url" 判断是否进入独立静态服务模式
        return server_main([cmd] + argv[1:])
    if cmd.isdigit():
        from .server import main as server_main
        return server_main(argv)
    print(f"未知子命令: {cmd}")
    print(USAGE)
    return 2


if __name__ == "__main__":
    sys.exit(main())
