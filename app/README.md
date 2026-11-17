# LEGOGOD 手机 APP（Flutter）

Android 优先的 LEGOGOD 客户端：连接真实服务端（Web API v1）完成
「描述需求 → 真实 LLM 生成 → 实时查看阶段/设计稿/思考 → 3D 成品与拼装指导 → 步骤与产物文件 →
生成记录 → 作品检索 → 零件目录 → 生命周期恢复」的完整闭环。

- 不使用 WebView 包整站；3D 为 Flutter 原生软渲染（`CustomPainter` + `drawVertices`）。
- 默认「明亮积木工坊」浅色主题：暖浅灰页面、白色卡片、乐高黄主按钮、深黄选中文字与浅色 3D 舞台。
- 信息架构采用 2026-11-15 简化重构后的三入口结构。
- 不内置任何服务地址、令牌、模型密钥或离线假数据；所有作品由用户配置的真实服务端生成。
- 访问令牌只保存在系统安全存储（Android Keystore 加密的 `flutter_secure_storage`），
  不写日志、不进 URL、不出现在截图说明中。

## 环境与版本

| 项 | 版本 |
|---|---|
| Flutter / Dart | 3.38.7 / 3.10.7（开发与构建机） |
| Android SDK | compileSdk 36 / targetSdk 36；minSdk 26 |
| Gradle / AGP | Gradle 8.14.2 / Android Gradle Plugin 8.x |
| 主要依赖 | `http`、`shared_preferences`、`flutter_secure_storage`、`share_plus`、`file_picker`、`path_provider`、`url_launcher` |
| 服务端 API | `/api/*` v1（请求头 `X-LEGOGOD-API-Version: 1`）；非回环监听需 `Authorization: Bearer` |

> 需求基线为 Android 10（API 29）及以上。本轮唯一可用真机为 MI 5 / Android 8.0（API 26），
> 为完成真机验收临时将 `minSdk` 降到 26，偏差说明见 `app/android/app/build.gradle.kts` 注释。

## 信息架构（导航与页面）

底部三入口：**创作 / 作品 / 我的**（作品入口显示真实进行中数量角标，0 时隐藏）。

| 入口 | 页面 | 职责 |
|---|---|---|
| 创作 | `pages/create/create_page.dart` | 需求输入、3 个示例、快速/高保真紧凑分段、模式说明、默认收起的生成规则、主按钮「生成作品」、进行中数量摘要、最近 3 个已完成作品（整卡单一跳转） |
| 作品 | `pages/works/*` | 进行中 / 已完成 / 全部记录三段；进行中卡「查看进度」+ 次要菜单取消；全部记录含搜索、执行状态/交付结果筛选、服务端分页（单页时隐藏分页） |
| 我的 | `pages/mine/*` | 零件目录、服务连接与令牌、生成规则、诊断与高级（默认收起）、关于；离线横幅只显示「连接已断开，当前为缓存数据」+ 重试 |

独立页面（`Navigator` 路由，统一由 `core/route_nav.dart` 判定落点）：

| 页面 | 文件 | 说明 |
|---|---|---|
| 生成进度 | `pages/progress/generation_progress_page.dart` | 真实阶段/耗时/求解进度；设计稿为主视觉（未产生时紧凑空态）；思考默认收起；取消为次要危险操作；完成后显示「查看作品」 |
| 作品详情 | `pages/work/work_detail_page.dart` | 3D 成品优先 → 最多 3 项核心规格 → 真实警告摘要 → 零件清单/分享与导出；底部「开始拼装」；「更多」含原始需求/作品信息/再次生成/生成记录/分享与导出 |
| 拼装指导 | `pages/work/assembly_guide_page.dart` | 3D 常驻 + 模拟/分层步骤同页联动；重置/上一步/播放暂停/下一步/滑块/目标轮廓/减少动态效果；当前步骤卡（零件、颜色、层、区域、坐标、旋转、子模块）；可拼性检查摘要与明细 |
| 零件清单 | `pages/work/part_list_page.dart` | 本作品用量（合计与步骤数一致性提示）、未知零件 ID 报错、查看全部库存入口 |
| 生成记录 | `pages/record/generation_record_page.dart` | 复盘集中化：首屏结果横幅+原因摘要，8 个分组默认收起（运行与需求、两次尝试、视觉评审与评审图、版本与求解轨迹、颜色回退与产物统计、全部思考回合、完整运行日志、技术信息与文件入口） |
| 分享与导出 | `ui/share_export.dart` + `ui/structured_steps_page.dart` | 常用（拼装步骤结构化内容、独立 3D 页）与高级文件（设计/方案 JSON、运行日志 MD）；系统保存、系统分享、系统浏览器打开、取消与重试 |
| 零件目录 | `pages/parts/parts_page.dart` | `/api/parts` 唯一数据源；形状分组、坡向、库存、变体详情可查零件 ID |

落点规则（`core/route_nav.dart`）：进行中 → 生成进度；已完成且有 model/solution 产物 → 作品详情；
失败/取消/中断/无可用产物 → 生成记录。后台任务完成只更新角标与列表，不抢占当前页面。

## 目录结构

```
app/
  lib/
    main.dart / app.dart / app_scope.dart   应用入口、生命周期、依赖注入（InheritedNotifier）
    core/
      api_client.dart      唯一网络入口：健康/零件/任务分页/详情/取消/重试/3D 产物/文件文本与字节
      app_state.dart       服务配置、缓存、每任务快照、轮询调度、历史筛选分页、作品分段、
                           3D 产物缓存、拼装指导视图与步数恢复
      route_nav.dart       任务默认落点判定与全部页面跳转入口（进行中/作品/记录）
      job_snapshot.dart    单任务快照（阶段/日志/设计稿/思考/评审/进度），互不串台
      storage.dart         SharedPreferences + 可注入 TokenStore（测试用 MemoryTokenStore）
      service_address.dart 地址解析（主机/端口/http/https、未写协议按 http、非回环令牌要求）
      format.dart          文案与状态格式化（模式/阶段/交付结果/失败原因/作品警告）
      thinking.dart / logs.dart / log_export.dart / theme.dart / studio_helpers.dart
    models/                JSON 解析与领域模型（job/result/design/artifacts/part/api_error）
    three_d/               原生 3D 引擎（相机、场景、几何、顶点渲染；无 WebView）
    ui/
      share_export.dart    分享与导出统一面板（五类真实产物）
      structured_steps_page.dart 拼装步骤的结构化预览（可切换原始 Markdown）
      widgets/             通用组件（分段控件/可展开区块/底部主操作栏/状态标签/思考面板/日志/评审图…）
    pages/
      boot/                BootGate：首启引导 / 缓存启动 / 服务不可达不出白屏
      shell/               底部 3 Tab（创作 / 作品 / 我的）+ 进行中角标 + 简化离线横幅
      settings/            服务表单（首次连接与「我的 → 服务连接」共用）
      create/              创作页
      progress/            生成进度页（含设计稿主视觉组件）
      work/                作品详情 / 拼装指导 / 零件清单 / 作品信息弹层
      record/              生成记录（复盘）
      works/               作品页（进行中 / 已完成 / 全部记录）
      mine/                我的 / 服务连接 / 生成规则 / 诊断与高级 / 关于
      parts/               完整零件目录
    services/file_actions.dart  系统分享、系统文件选择器保存、系统浏览器打开
  test/                    194 个单元/组件测试（页面、导航落点、3D 引擎、模型、API、存储、主题）
  android/                 Android 工程（network_security_config 仅放行 localhost/10.0.2.2 明文）
tools/
  mobile_e2e/uia.ps1       ADB + UiAutomation 驱动的真机 E2E 辅助脚本（证据目录可用 LEGO_E2E_DIR 覆盖）
  mobile_e2e/quality_check.py        真实产物结构化质量断言（模型/方案/步骤/用量/配色/需求特征）
  mobile_e2e/quality_check_round.py  按回合任务 ID 映射复用同一冻结断言器（不放宽口径）
  uiauto/                  设备端 UiAutomation 驱动 APK（测试工具，不入库构建产物）
artifacts/e2e-mobile/<stamp>/   真机 E2E 原始证据（本地产物，不入库）
```

## 构建与运行

```bash
cd app
flutter pub get
flutter analyze                 # 当前：No issues found
flutter test                    # 当前：194 passed
flutter build apk --release     # 产物：app/build/app/outputs/flutter-apk/app-release.apk
```

安装到真机（MIUI 对 `adb install` 有限制时）：

```bash
adb push app-release.apk /data/local/tmp/legogod.apk
adb shell pm install -r /data/local/tmp/legogod.apk
adb shell am start -n com.legogod.app/.MainActivity
```

release 签名：本地 `app/android/key.properties` + `app/android/*.jks`（测试签名，`.gitignore` 忽略，
不入库）；缺失时回退 debug 签名，便于本机构建。

## 首次连接配置

> 安全约束：公网服务必须使用 `https://`，仅回环/局域网地址（RFC1918、链路本地、`.local` 等主机名）允许 `http`；回环判断按 IP 解析，`127.example.com` 不会被当作回环。该校验在 Dart 层执行（Android network_security_config 不约束 Dart socket）。

1. 在本机启动真实服务端（详见仓库根 README）：

   ```bash
   # Windows PowerShell 示例
   $env:LEGOGOD_API_TOKEN="<你的令牌>"
   python -m legogod api --host 0.0.0.0 --port 8600
   ```

2. APP 首次启动进入「首次连接设置」：填写 `http://<电脑局域网 IP>:8600` 与访问令牌，
   点「测试连接」会分别显示服务健康、API 版本、零件目录与**任务接口鉴权**结果；通过后「保存并进入」。
3. 之后可在「我的 → 服务连接与令牌」修改地址/令牌、测试连接、断开连接（断开不会删除服务端任务）。
4. 局域网纯 HTTP 仅对用户填写的服务地址生效；公网必须 HTTPS。

令牌安全：仅安全存储；不写日志/URL/证据；服务端日志也不会打印令牌。

## 测试

```bash
cd app
flutter analyze
flutter test
```

服务端契约相关（仓库根目录）：

```bash
python -m pytest test/test_api_contract.py test/test_server_tasks.py test/test_server_history.py test/test_job_service.py -q
```

真机 E2E 辅助（需要真实设备、真实服务端）：

```bash
# 1) 构建并安装 UiAutomation 驱动（测试工具）
gradle -p tools/uiauto assembleDebug
adb push tools/uiauto/app/build/outputs/apk/debug/app-debug.apk /data/local/tmp/uiauto.apk
adb shell pm install -r /data/local/tmp/uiauto.apk

# 2) PowerShell 中使用驱动（示例：读取当前界面无障碍节点并点击）
$env:LEGO_E2E_DIR = "<仓库路径>\artifacts\e2e-mobile\<stamp>"
Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass -Force
. tools/mobile_e2e/uia.ps1
Run-UiAction -Action dump
Click-UiText -Text '生成作品'

# 3) 真实产物质量断言（服务端需运行、令牌从本地证据目录读取）
python tools/mobile_e2e/quality_check.py --token-file <token.txt> --out-dir <quality>
# 或按回合任务映射（推荐：任务存储只保留最近 50 条）
python tools/mobile_e2e/quality_check_round.py --token-file <token.txt> --out-dir <quality> --map <quality-id-map.json>
```

真机 E2E 验收结论：APP 功能/信息架构通过（未覆盖项逐条列出）；
**真实生成质量未通过（冻结 M 组断言 2/5）**，两者分开判定。

## 已知限制与偏差

- **iOS**：本项目当前产品范围仅 Android，本期不新增 iOS 工程、签名、构建与验收；
  Flutter 代码具备跨平台基础不等同于已支持 iPhone。
- **Android 基线**：唯一真机为 Android 8.0（API 26，MIUI V10），低于需求 Android 10 基线；
  `minSdk=26` 为完成真机验收的临时放宽，需在 API 29+ 设备回归。
- **真机自动化输入**：MIUI 阻止 `adb shell input` 注入（触摸/键盘事件被系统丢弃），
  E2E 使用设备内 UiAutomation 驱动完成无障碍点击/滚动/文本设置，文本输入通过 Flutter 语义
  `ACTION_SET_TEXT` 落到真实输入框（需先聚焦）；少数手势（3D 旋转/缩放、滑块拖动、锁屏、
  读屏、系统减少动画开关）无法自动化覆盖。
- **高保真/生成质量**：真实模型产出存在降级交付/快速保底/失败；按仓库冻结 M 组断言器复核，
  最新一轮 5 个冻结案例 2/5 通过，属真实内容质量问题（非 APP 页面缺陷），未做放宽或重跑筛选。
- **大文件拆分**：`core/app_state.dart` 等仍接近或超过 500 行软约束，后续如需继续演进应独立拆分
  并全量回归（本轮已把旧 `pages/job/*` 拆分为作品/拼装/记录三个独立页面）。
