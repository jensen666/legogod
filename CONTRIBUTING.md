# 参与贡献

感谢你愿意改进 LEGOGOD。提交贡献前请先阅读本文件。

## 许可证

向本仓库提交的任何代码、文档、测试或素材，均视为在项目的 [MIT License](LICENSE) 下发布。项目不使用额外的 CLA 或 DCO 流程。

## 环境准备

- Python 3.10+；完整开发与测试依赖见 `requirements-dev.txt`。
- Flutter / Dart 用于 APP：版本以 `app/README.md` 记录的验证版本为准。
- Node.js 仅在运行部分前端测试时需要。

安装方式：

```bash
python -m pip install -e ".[pillow]"
python -m pip install -r requirements-dev.txt
```

## 提交建议

1. 从 `main` 新建分支，分支名说明改动范围。
2. 保持改动聚焦：一个 Pull Request 只做一件事，不混入无关重构。
3. 提交信息写清"改了什么、为什么改"。
4. 行为或接口变化必须同步更新相关文档与测试。

## 测试要求

提交 Pull Request 前，请至少运行与改动相关的测试：

```bash
python -m pytest test -q
```

涉及 APP 的改动：

```bash
cd app
flutter analyze
flutter test
```

真实 LLM 链路、真机 E2E 和长时间浏览器 E2E 不在默认 CI 中运行；涉及这些链路的改动请在 PR 描述中写明你实际执行过的验证步骤与证据。

## 文档要求

- 面向用户的行为、配置、启动方式、部署方式发生变化时，同步更新 README 或 `docs/` 下对应文档。
- 不要在代码注释、文档或提交信息中引用内部过程文档路径。

## 媒体与隐私

- 截图、GIF、视频必须来自真实运行结果，不得使用 mock 数据、拼接结果或人工伪造的成功状态。
- 提交前检查素材是否包含：真实密钥/令牌、个人路径、内网 IP、设备标识、账号信息、他人任务内容。
- 涉及界面的演示素材请说明所用版本与任务来源。

## 维护者的同步说明

合并到本仓库 `main` 的代码贡献会被维护者同步回主开发线，并在后续发布中保持一致。这意味着：

- 你的提交可能被 cherry-pick 或等价回流到其他开发环境；
- 回流后本仓库历史仍保留你的原始提交，不会被改写；
- 为避免冲突，PR 合并后请勿私自强推你的分支。

## 问题反馈

- 功能建议与使用问题：公共 Issue / Discussion。
- 安全漏洞：见 [SECURITY.md](SECURITY.md)，不要公开提交。
