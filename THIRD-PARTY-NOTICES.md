# 第三方软件与素材声明（THIRD-PARTY NOTICES）

> 适用仓库：LEGOGOD 公开源码仓库
> 对应版本：v1.0.0（APP `legogod_app 1.0.0+1`）
> 核验日期：2026-11-17（+08:00）
> 维护要求：第三方依赖或素材变更时必须同步更新本文件，见第 8 节

## 1. 总则

1. 本项目主体以 **MIT 许可证**发布，全文见根目录 [LICENSE](LICENSE)。
2. 第三方组件**不因本项目采用 MIT 而改变许可**：各组件保留其原始许可证，本文件不构成对任何第三方许可条款的修改或替代。
3. 本文件覆盖四类对象：
   - 随源码仓分发的内容（以项目自写代码为主，第三方源码是否入仓逐项标注）；
   - 运行时从 CDN 加载的 Web 组件（Three.js）；
   - 随 Android APK 二进制分发的组件（Flutter SDK、pub 依赖、字体）；
   - 构建期工具链（Gradle / AGP / Kotlin），不随源码或产物分发。
4. 本文件只列**许可证归属与署名义务**；各组件的完整许可全文以其上游发行包或官方仓库为准，本文件给出可取得原文的固定入口。
5. 本文件不构成法律意见。

## 2. Python 依赖（用户环境安装，不随源码仓分发）

基础/快速链路只依赖 Python 标准库（Python 3.10+）。下列组件由用户按需安装：

| 组件 | 版本（本机核验） | 用途与使用方式 | 许可证 | 随仓分发 |
|---|---|---|---|---|
| Pillow | 11.3.0 | 高保真渲染与视觉评审；`legogod/render.py` 顶层导入，由视觉评审链路惰性加载；安装入口为可选 extra `pillow` | HPND / PIL（本机元数据 `MIT-CMU`） | 否 |
| pytest | 9.0.2 | 测试运行器（开发与 CI）；`requirements-dev.txt` / `dev` extra | MIT | 否 |
| matplotlib | 3.10.6 | 可选图表工具（`tools/` 下 E2E 报告图表）；`charts` extra | matplotlib PSF-based License | 否 |
| numpy | 1.26.3 | 可选图表工具的数值计算（matplotlib 依赖）；`charts` extra | BSD-3-Clause | 否 |
| playwright | 1.60.0 | 可选浏览器真实 E2E；函数内惰性导入，不进入默认 CI；`e2e-browser` extra | Apache-2.0 | 否 |

说明：

- 未安装 Pillow 时，视觉评审链路会降级并返回 `ok=False`，基础链路不因此崩溃。
- 许可证判定依据本机发行包内 `dist-info/licenses/` 原文：Pillow 声明 `Like PIL, Pillow is licensed under the open source MIT-CMU License`；pytest 为 `The MIT License (MIT) Copyright (c) 2004 Holger Krekel and others`；matplotlib 为 `License agreement for matplotlib versions 1.3.0 and later`（分类器 `Python Software Foundation License`）；numpy 为 `Copyright (c) 2005-2023, NumPy Developers` 的 BSD-3-Clause；playwright 为 Apache License 2.0。
- 上述组件不随源码仓复制分发，其许可要求在对应分发场景（PyPI 安装包、用户环境）中由上游文件保留。

## 3. Web 依赖：Three.js 0.160.0（MIT，CDN 运行时加载）

| 项 | 内容 |
|---|---|
| 组件 | Three.js（npm 包 `three`）**0.160.0** |
| 来源 | jsDelivr npm 镜像 `https://cdn.jsdelivr.net/npm/three@0.160.0/` |
| 引用位置 | `web/index.html`、`web/shell.html` 的 import map；`web/viewer.js`、`web/preview.js` 导入 `three` 与 `three/addons/controls/OrbitControls.js` |
| 是否随仓分发 | **否**。`web/` 无 vendor 副本、无 node_modules；浏览器在首次使用 3D 功能时联网加载 |
| 许可证 | **MIT**（已核验） |
| 版权声明 | Three.js — `Copyright © 2010-2023 three.js authors` |
| 许可入口 | 包内原文 `https://cdn.jsdelivr.net/npm/three@0.160.0/LICENSE`；上游 `https://github.com/mrdoob/three.js/blob/dev/LICENSE` |

说明：

1. 上述版权行与 MIT 文本于 2026-11-17 通过 `https://cdn.jsdelivr.net/npm/three@0.160.0/LICENSE` 联网取得并逐行核对；`0.160.0` 包内 LICENSE 的版权行为 `2010-2023`（以原文为准，不同版本版权行可能变化）。
2. 版本通过 import map 的 URL 固定为 `0.160.0`；Web 端不使用打包器，import map **无法声明 SRI 校验**，完整性依赖 HTTPS 与 CDN 可用性。
3. 首次打开 Web 3D 页面需要能够访问 `cdn.jsdelivr.net`；离线环境下 Web 3D 不可用（Python API 主链不受影响）。
4. 升级 Three.js 时必须同步更新 `web/index.html`、`web/shell.html` 的 import map，并重新核验版权行与许可文本后更新本节。

## 4. Flutter / Android 依赖（随 APK 二进制分发）

### 4.1 Flutter SDK / Dart

- Flutter SDK **3.38.7**（stable），Dart **3.10.7**。
- 许可证：**BSD-3-Clause**，版权行 `Copyright 2014 The Flutter Authors. All rights reserved.`，含 `Neither the name of Google Inc.` 条款。
- `app/pubspec.lock` 中 7 个 SDK 来源包（`flutter`、`flutter_driver`、`flutter_test`、`flutter_web_plugins`、`fuchsia_remote_debug_protocol`、`integration_test`、`sky_engine`）：`flutter` 包自带 LICENSE（BSD-3-Clause）；其余 5 个包目录内无独立 LICENSE，由 Flutter SDK 根 LICENSE（BSD-3-Clause）覆盖；`sky_engine` 见下条。
- `sky_engine` 的 license 文件为**多许可证汇编**（含 Flutter engine 的第三方组件），随引擎生成，由构建期 `NOTICES.Z` 汇总，不在本文件逐项展开。

### 4.2 Dart pub 依赖（94 个 hosted 包）

来源：`pub.flutter-io.cn`；版本以 `app/pubspec.lock` 锁定。**完整依赖清单（101 个锁文件条目的名称/版本/关系/来源）见 `app/pubspec.lock`**，本节按许可证分组列代表包：

| 许可证 | 数量 | 代表包 |
|---|---|---|
| BSD-3-Clause | 77 | `http`、`shared_preferences*`、`url_launcher*`、`path_provider*`、`flutter_secure_storage*`、`share_plus*`、`file`、`meta`、`collection`、`path`、`crypto`、`web`、`win32`、`vector_math` 等 |
| MIT | 12 | `file_picker` 及 `file_picker_*`、`android_file_picker`、`windows_file_picker`、`cupertino_icons`、`petitparser`、`xml`、`yaml`、`uuid` |
| Apache-2.0 | 4 | `clock`、`fake_async`、`material_color_utilities`、`webdriver` |
| MPL-2.0 | 1 | `dbus`（仅 Linux 桌面实现，Android 产物不包含该实现） |

- 逐包 LICENSE 全文位于各 pub 包内；Flutter 构建会自动把**实际进入 APK 的包与被引用组件**的许可汇总到 `flutter_assets/NOTICES.Z`，APK 二进制分发以该文件为权威许可汇总。
- 源码仓保留 `app/pubspec.lock` 用于复现依赖版本；本项目不复制上述包源码。

### 4.3 打包字体

| 字体 | 来源 | 随 APK 分发 | 许可证 | 署名与说明 |
|---|---|---|---|---|
| Material Icons（`fonts/MaterialIcons-Regular.otf`） | Flutter SDK `material_fonts`（`uses-material-design: true` 自动打包） | 是（release 构建经 tree-shake 的子集） | **CC BY 4.0** | 署名：**Material Icons by Google**，依 [CC BY 4.0](https://creativecommons.org/licenses/by/4.0/) 使用；构建期按实际使用图标裁剪字形（属修改）。Flutter 构建的 `NOTICES.Z` 未包含该 CC BY 条目，故在此单独署名。 |
| CupertinoIcons（`packages/cupertino_icons/assets/CupertinoIcons.ttf`） | pub 包 `cupertino_icons` 1.0.9 | 是 | **MIT** | 版权行 `Copyright (c) 2016 Vladimir Kharlampidi` |
| Roboto | Flutter SDK `material_fonts` | 否（当前 release 产物未包含） | Apache-2.0 | 若将来显式打包，需补入本表 |

说明：Material Icons 的**图标源码仓库**（`google/material-design-icons`）以 Apache-2.0 提供，而 Flutter SDK 随附的**字体许可文件**为 CC BY 4.0（`materialicons_license.txt` 首行 `Attribution 4.0 International`）；本项目实际分发的对象是字体文件，故按 CC BY 4.0 署名（两者均已核验）。

### 4.4 APK 分发的许可义务

- Android APP 二进制分发时：`flutter_assets/NOTICES.Z`（Flutter 构建自动生成）+ 本文件 + APP 内开源许可入口共同构成许可声明。
- 若 APP 内许可页与本文件冲突，以 `NOTICES.Z` 与各上游 LICENSE 原文为准。

## 5. Android 构建组件（构建期使用，不随源码或产物分发）

| 组件 | 版本 | 许可证 | 说明 |
|---|---|---|---|
| Gradle | 8.14.2 | Apache-2.0 | Gradle Wrapper 固定版本；构建期工具 |
| Android Gradle Plugin（AGP） | 8.11.1 | Apache-2.0 | `app/android/settings.gradle.kts` 固定版本；构建期工具 |
| Kotlin Gradle Plugin | 2.2.20 | Apache-2.0 | 构建期工具 |

- 三者均为**构建工具链**，不随源码仓分发，也不进入 APK 产物，实际分发物中不包含其代码。
- AGP 的传递 Maven 依赖（如 `aapt2`、`bundletool` 等）同在构建期使用，未逐项列示；构建文档记录版本即可。
- Flutter Gradle Plugin 属 Flutter SDK 组件，按 Flutter SDK 的 BSD-3-Clause 分发。

## 6. 数据来源与权利声明

### 6.1 零件库数据

- 零件库为**项目自建的简化数据**（当前规模：31 种形状 × 16 种颜色 = 496 个零件变体），用于本项目生成与展示，不是任何第三方数据集的复制。
- **形状**：采用积木行业通用的矩形、斜坡等基础几何约定（如 stud 间距 8mm、标准砖高 9.6mm 等通用尺寸），由项目独立实现几何与连接算法。
- **颜色**：为项目自建的简化色值，用于可视化与近似配色，不对应也不复制任何厂商的色板数据。
- **不复制第三方零件数据库**：本项目不使用、不打包、不转录 LDraw、Rebrickable、BrickLink 等第三方零件数据库的数据结构、字段组织、文本或数据文件；零件编号若出现在兼容性说明中，仅用于说明尺寸兼容关系。
- 本文件与项目文档不声称尺寸、配色取自任何品牌方的标准；对尺寸与配色的描述仅为兼容性/近似说明。

### 6.2 示例、测试夹具与媒体

- `examples/` 下的示例模型与文档、`test/` 下的测试夹具为项目自产。
- `assets/` 下的截图/GIF 为项目真实运行产物，与仓库同一版本对应；演示 GIF/视频对长等待过程做了加速，不挑选结果冒充普遍成功率（README 已说明）。
- 项目不使用第三方音乐/音效；如未来引入，须取得可公开再分发的授权并在本文件记录。
- APP 启动图标为项目自绘素材（Pillow 绘制的积木砖块图形，不含任何厂商 Logo 或品牌标识），按 MIT 许可证随本项目发布；原始设计不依赖 Flutter SDK 模板图标。

### 6.3 不使用官方素材

- 本项目**不使用、不打包 LEGO Group 的官方 Logo、官方产品图、官方说明书**或其他品牌素材。
- Web/APP 中出现的积木视觉为程序按自建数据生成的渲染结果，不是官方素材的复制。

## 7. 商标与非隶属声明

LEGOGOD 是一个**独立开源项目**，与 LEGO Group（乐高集团）**无隶属、赞助、授权或背书关系**。

- **LEGO®** 是 LEGO Group 的商标；文中出现的“LEGO/乐高”仅用于说明积木规格兼容性，不表示任何官方关系。
- 本项目不使用 LEGO Group 的 Logo 与品牌素材，也不得被描述为品牌方的官方产品或授权服务。
- 英文版：*LEGOGOD is an independent open-source project and is not affiliated with, sponsored by, authorized by, or endorsed by the LEGO Group. LEGO® is a trademark of the LEGO Group. References to “LEGO” describe brick-compatibility only.*

## 8. 核验状态与维护

| 项 | 状态 |
|---|---|
| 核验日期 | 2026-11-17（+08:00） |
| 清单规模 | 103 个第三方包：Python 5 + Web 1 + Dart hosted 94 + Android 构建组件 3；另含 Flutter SDK 7 个 sdk 包（工具链）与 3 项字体资源（其中 2 项实际打包） |
| 已核验组件 | Python 5 个、Web 1 个、Dart hosted 94 个 + SDK 7 个、字体 3 项、Android 构建组件 3 个 |
| Three.js 许可原文 | **核验成功**：jsDelivr `three@0.160.0/LICENSE`，MIT，版权行 `Copyright © 2010-2023 three.js authors` |
| 待核验组件 | **无**。本文件列出的组件均有许可证证据；新增依赖或升级版本时必须重新核验并更新本文件。 |

- 维护规则：新增/升级/移除第三方依赖、替换字体或媒体素材、变更 CDN 版本时，同步更新本文件对应小节与本节核验状态。
- 许可疑问或勘误请通过仓库 Issue 反馈。
