# 部署与安全

本页说明 LEGOGOD 的三种部署形态、访问控制要求与实例边界。默认配置面向本机使用；对外提供服务前请逐项确认。

## 三种部署形态

三种形态业务语义完全相同，只是进程职责不同：

| 形态 | 启动命令 | 进程职责 |
|---|---|---|
| 组合部署（默认） | `python -m legogod` 或 `python -m legogod 8600` | 同一进程提供页面静态资源与 `/api`、`/files`、`/views`、`/viz` |
| 独立 API | `python -m legogod api --host <地址> --port <端口>` | 只提供 API 与产物路由，不读取页面应用壳 |
| 独立 Web 静态 | `python -m legogod web --port <端口> --api-url <API 地址>` | 只提供页面与静态资源、`/runtime-config.js`，不持有任务状态 |

独立部署示例：

```bash
# 终端 1：API
python -m legogod api --host 127.0.0.1 --port 8600

# 终端 2：Web 静态
python -m legogod web --host 127.0.0.1 --port 8601 --api-url http://127.0.0.1:8600
```

跨源部署需要把 Web 的精确 Origin 加入 API 的 allowlist：

```bash
python -m legogod api --port 8600 --allowed-origins http://127.0.0.1:8601
```

## 配置优先级

命令行参数 > 环境变量 > 缺省值。`web` 子命令在没有 `--api-url`、也没有 `LEGOGOD_API_BASE_URL` 时保持组合部署行为。

主要环境变量见 `.env.example`；部署相关：

| 变量 | 作用 |
|---|---|
| `LEGOGOD_API_TOKEN` | API Bearer 令牌；非回环监听时必须配置 |
| `LEGOGOD_ALLOWED_ORIGINS` | 逗号分隔的精确 Origin allowlist，不接受 `*` |
| `LEGOGOD_API_BASE_URL` | 独立 Web 静态服务指向的 API 地址 |
| `LEGOGOD_VIZ_DIR` | 独立 3D 页面输出目录，默认 `artifacts/viz` |

## 安全门槛

- **监听地址**：默认 `127.0.0.1`。监听 `0.0.0.0`、局域网 IP 等非回环地址时，如果没有配置令牌，服务拒绝启动并打印原因。
- **Bearer 认证**：配置令牌后，任务写操作与敏感读接口（`/api/build`、`/api/retry`、`/api/job/*`、`/api/jobs`）要求 `Authorization: Bearer <令牌>`。`/api/health`、`/api/parts` 与产物文件保持开放——浏览器 `<img>` 与下载链接无法携带请求头，如需严格保护产物请在反向代理层加访问控制。令牌只接受请求头，不接受 URL 查询参数。
- **Origin 与 CORS**：写操作要求同源，或命中 allowlist 中的精确 Origin，否则返回 403。CORS 只决定浏览器能否读取响应，不是鉴权；令牌绝不能写进静态资源、`runtime-config.js`、URL 或仓库。
- **公网部署**：只支持 HTTPS 同源反向代理——把页面路径交给静态服务，把 `/api`、`/files`、`/views`、`/viz` 交给 API。不要把服务直接暴露到公网，不要忽略证书校验，不要放开所有 Origin。
- **密钥管理**：模型服务密钥只放在本地 `.env` 或环境变量中。`.env` 已被忽略规则排除，不要提交、不要截图、不要写进前端产物。

## 实例边界

当前目标形态是**一个 API 进程 + 一个任务历史文件**：不支持多个 API 进程同时读写同一 `jobs_store.json`。任务历史保留最近 50 条。需要横向扩展前应先做存储层改造。

## 运行产物与可写目录

服务会写入仓库内 `artifacts/`（模型、方案、拼装步骤、运行记录、任务历史）与 `artifacts/viz/`（独立 3D 页面）。启动时自检目录可写，不可写会直接报错退出。独立 Web 静态服务不写产物，不做该自检。
