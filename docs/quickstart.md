# 快速开始

LEGOGOD 把一句自然语言需求变成可查看、可校验、可一步步拼装的 3D 积木作品。本页给出最短可运行路径。

## 1. 环境要求

| 项 | 要求 |
|---|---|
| Python | 3.10 及以上 |
| LLM 服务 | 任意兼容 OpenAI Chat Completions 协议的端点（必须由你自行提供） |
| Pillow | 渲染、高保真视觉评审与全量测试需要；基础/快速链路不需要 |
| Node.js | 仅运行部分前端测试时需要（Node 20 验证过） |
| Flutter / Dart | 仅构建 Android APP 时需要，版本见 [app/README.md](../app/README.md) |

## 2. 安装

按使用方式选择其一，三种安装不要混用：

```bash
# A. 基础安装：只跑快速链路（不渲染、不视觉评审）
python -m pip install -e .

# B. 完整功能安装：包含 Pillow，启用渲染与高保真模式
python -m pip install -e ".[pillow]"

# C. 开发与测试安装：完整功能 + pytest
python -m pip install -e ".[pillow]"
python -m pip install -r requirements-dev.txt
```

图表类分析工具（`tools/e2e_report_charts.py`、`tools/e2e_compare_charts.py`）另需 matplotlib/numpy，真实浏览器 E2E 另需 Playwright，均属可选依赖：

```bash
python -m pip install -e ".[charts]"
python -m pip install -e ".[e2e-browser]"
```

未安装时这些脚本会直接报缺少模块，不影响核心生成链路。

## 3. 配置模型

1. 复制配置模板：

   ```bash
   cp .env.example .env      # Windows PowerShell: Copy-Item .env.example .env
   ```

2. 填入你的服务地址、密钥与模型名：

   ```dotenv
   LEGOGOD_BASE_URL=https://your-llm-endpoint/v1
   LEGOGOD_API_KEY=<YOUR_API_KEY>
   LEGOGOD_MODEL=<YOUR_MODEL_NAME>
   ```

   配置在首次真实请求时才校验：没有 `.env` 也能启动服务、打开页面和运行测试。

3. `.env` 已被 `.gitignore` 忽略，不要提交；令牌不要写进页面、URL 查询参数或截图。

## 4. 启动

```bash
python -m legogod
```

打开 <http://127.0.0.1:8600>，在创作台输入需求，例如“一座中世纪城堡”，选择生成模式后点击「生成作品」。

默认监听回环地址，不需要访问令牌。监听非回环地址前请先阅读[部署与安全](deployment.md)。

## 5. 命令行

```bash
# 快速模式，自动完成（Agent 不提问）
python -m legogod build --desc "一座小桥" --yes

# 高保真模式：多视角渲染 + 视觉评审 + 有界外观修订
python -m legogod build --desc "一只垂耳小狗" --yes --fidelity

# 交互式输入需求
python -m legogod build
```

生成产物写到仓库内 `artifacts/`（模型、方案、拼装步骤 Markdown、3D 页面）与 `artifacts/viz/`（独立 3D HTML）。服务启动时会自检这些目录可写，不可写会直接报错退出。

## 6. 验证安装是否正常

```bash
python -m pytest test -q
```

不调用真实模型；Pillow 已安装时覆盖渲染相关用例。只想验证基础链路时：

```bash
python -m pytest test/test_geometry.py test/test_validation.py -q
```

## 7. 常见问题

| 现象 | 处理 |
|---|---|
| 启动报「artifacts 不可写」 | 确认项目目录可写，或从可写位置运行 |
| 生成时提示缺少 Pillow | 改用完整功能安装：`python -m pip install -e ".[pillow]"` |
| 连不上模型服务 | 检查 `LEGOGOD_BASE_URL` 是否包含 `/v1` 等路径前缀、密钥是否有效、网络是否可达 |
| 页面能开但没有数据 | 确认 API 与页面同源，或独立部署时 `--api-url`/`LEGOGOD_API_BASE_URL` 配置正确 |
| 端口被占用 | `python -m legogod 8601` 或 `--port` 指定其他端口 |
