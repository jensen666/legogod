#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""公开仓库内容闸门：禁止内容、路径、地址、密钥与公开夹具完整性检查。

子命令：
    policy   扫描仓库内所有发布文件，检查禁止路径、内部文档引用、本机绝对路径、
             真实内网地址、疑似密钥，以及必需文件与 README 相对链接是否完整。
    fixtures 校验 test/fixtures/public-fixtures.json：文件存在、SHA-256 匹配、
             必需夹具齐全、数量大于 0。
    tests    解析 pytest 的 JUnit XML，确认没有跳过用例（公开 CI 禁止静默 skip）。

全部通过退出码 0；任何违规退出码 1，并逐条打印 path:line: reason。
仅使用 Python 标准库，不联网。
"""
import hashlib
import json
import os
import re
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# ---- 禁止出现的文件/目录（相对仓库根的路径前缀或命名规则）----
FORBIDDEN_PREFIXES = (
    ".claude/",
    ".agents/",
    ".review/",
    "docs/需求/",
    "docs/方案/",
    "docs/报告/",
    "docs/e2e-evidence/",
    "artifacts/e2e-mobile/",
    "artifacts/viz/",
    "artifacts/jobs_store.json",
)
FORBIDDEN_NAMES = ("process.md", "idea.md", "next.md", ".env")
FORBIDDEN_SUFFIXES = (".pyc", ".log", ".jks", ".keystore")
FORBIDDEN_NAME_PARTS = ("__pycache__", ".pytest_cache", ".dart_tool", "build/", ".gradle/")

# ---- 文本内容规则：正则 + 说明 + 允许的最小例外 ----
CONTENT_RULES = [
    (
        "内部过程文档引用",
        re.compile(r"docs/(?:需求|方案|报告|e2e-evidence)/"),
        (),
    ),
    (
        "内部过程文档引用",
        re.compile(r"(?<![\w/.-])(?:process|idea|next)\.md"),
        (),
    ),
    (
        "本机 Windows 绝对路径",
        re.compile(r"\b[A-Za-z]:[\\/](?:code|sdk|Users|work|dev)[\\/]"),
        (),
    ),
    (
        "本机用户目录路径",
        re.compile(r"(?:C:/Users/|/Users/[A-Za-z]|/home/[a-z])"),
        (),
    ),
    (
        "真实内网/设备地址",
        re.compile(r"\b192\.168\.(?!0\.2\b)\d{1,3}\.\d{1,3}\b"),
        (),
    ),
    (
        "真实内网/设备地址",
        re.compile(r"\b10\.(?!0\.2\b)\d{1,3}\.\d{1,3}\.\d{1,3}\b"),
        (),
    ),
    (
        "真实内网/设备地址",
        re.compile(r"\b172\.(?:1[6-9]|2\d|3[01])\.\d{1,3}\.\d{1,3}\b"),
        (),
    ),
    (
        "疑似真实密钥",
        re.compile(r"\b(?:sk|ghp|gho|ghs|ghu)_[A-Za-z0-9]{20,}"),
        (),
    ),
    (
        "疑似真实密钥",
        re.compile(r"\bgithub_pat_[A-Za-z0-9_]{20,}"),
        (),
    ),
    (
        "疑似真实密钥",
        re.compile(r"\bAKIA[0-9A-Z]{16}\b"),
        (),
    ),
    (
        "私钥内容",
        re.compile(r"-----BEGIN (?:RSA|OPENSSH|EC|DSA|PGP) PRIVATE KEY-----"),
        (),
    ),
    (
        "硬编码凭据赋值",
        # 排除全大写+下划线的环境变量名常量（如 ENV_API_TOKEN = "LEGOGOD_API_TOKEN"），
        # 它们不是凭据值；真正的假 token 由 CONTENT_ALLOWLIST 逐条说明。
        re.compile(r"(?i)(?:api[_-]?key|token|secret|password)\s*[:=]\s*['\"]"
                   r"(?![A-Z][A-Z0-9_]*['\"])[A-Za-z0-9_\-]{16,}['\"]"),
        (),
    ),
]

# 内容规则的最小白名单：每条必须有明确理由，不允许整类关闭规则。
CONTENT_ALLOWLIST = {
    ".github/scripts/check_public.py": "公开内容检查器自身必须包含禁止模式定义字符串",
    "app/test/service_address_test.dart": "RFC1918 各网段范围覆盖的测试示例地址，非真实环境地址",
    "test/test_api_security.py": "测试用假 token（仅验证鉴权逻辑，非真实凭据）",
    "tools/e2e_arch_accept.py": "E2E 工具的显式假 token（标注 do-not-log，非真实凭据）",
}

# ---- 需要存在的公开文件 ----
REQUIRED_PATHS = (
    "README.md",
    "LICENSE",
    "THIRD-PARTY-NOTICES.md",
    "SECURITY.md",
    "CONTRIBUTING.md",
    ".gitignore",
    ".gitattributes",
    ".env.example",
    "pyproject.toml",
    "requirements-dev.txt",
    "test/fixtures/public-fixtures.json",
    ".github/workflows/ci.yml",
    ".github/scripts/check_public.py",
    ".github/PULL_REQUEST_TEMPLATE.md",
    ".github/ISSUE_TEMPLATE/bug_report.yml",
    "docs/README.md",
    "docs/quickstart.md",
    "docs/deployment.md",
    "assets/hero-web.png",
    "assets/demo-workflow.gif",
    "assets/demo-video-cover.png",
    "assets/web-3d.png",
    "assets/web-steps.png",
    "assets/app-create.png",
    "assets/app-assembly.png",
)

TEXT_SUFFIXES = (
    ".py", ".md", ".txt", ".html", ".css", ".js", ".json", ".yml", ".yaml",
    ".toml", ".ps1", ".dart", ".kts", ".gradle", ".xml", ".properties", ".sh",
    ".cfg", ".ini", ".example", ".gitignore", ".gitattributes",
)
SKIP_DIRS = {".git", "__pycache__", ".pytest_cache", ".dart_tool", "build", ".gradle", "node_modules"}


def _iter_files():
    """递归列出仓库内需要检查的文件（跳过 .git 与构建缓存目录）。"""
    for dirpath, dirnames, filenames in os.walk(ROOT):
        dirnames[:] = [d for d in dirnames if d not in SKIP_DIRS]
        for name in filenames:
            full = os.path.join(dirpath, name)
            yield os.path.relpath(full, ROOT).replace("\\", "/"), full


def _rel_posix(path):
    return os.path.relpath(path, ROOT).replace("\\", "/")


def check_paths():
    """检查禁止路径与必需文件。"""
    problems = []
    present = {rel for rel, _ in _iter_files()}
    for rel in sorted(present):
        name = rel.rsplit("/", 1)[-1]
        if any(rel == p or rel.startswith(p) for p in FORBIDDEN_PREFIXES):
            problems.append(f"{rel}: 禁止发布该路径")
            continue
        if name in FORBIDDEN_NAMES:
            problems.append(f"{rel}: 禁止发布该文件名为 {name} 的文件")
        if rel.endswith(FORBIDDEN_SUFFIXES):
            problems.append(f"{rel}: 禁止发布构建产物/日志/签名文件")
        if any(part in rel for part in FORBIDDEN_NAME_PARTS):
            problems.append(f"{rel}: 禁止发布缓存/构建目录内容")
    for rel in REQUIRED_PATHS:
        if rel not in present:
            problems.append(f"{rel}: 缺少必需公开文件")
    return problems


def _iter_text_files():
    """只返回文本类文件，避免对图片/视频做内容正则。"""
    for dirpath, dirnames, filenames in os.walk(ROOT):
        dirnames[:] = [d for d in dirnames if d not in SKIP_DIRS]
        for name in filenames:
            full = os.path.join(dirpath, name)
            lower = name.lower()
            if lower.endswith(TEXT_SUFFIXES) or lower in (".gitignore", ".gitattributes", ".env.example"):
                yield _rel_posix(full), full


def check_content():
    """逐行扫描文本内容，命中内部引用/路径/地址/密钥规则即违规。"""
    problems = []
    for rel, full in _iter_text_files():
        if rel in CONTENT_ALLOWLIST:
            continue
        try:
            with open(full, encoding="utf-8", errors="replace") as f:
                lines = f.read().splitlines()
        except OSError as exc:
            problems.append(f"{rel}: 读取失败 {exc}")
            continue
        for lineno, line in enumerate(lines, 1):
            for reason, pattern, allowlist in CONTENT_RULES:
                if not pattern.search(line):
                    continue
                if any(rel == allowed for allowed in allowlist):
                    continue
                problems.append(f"{rel}:{lineno}: {reason} -> {line.strip()[:160]}")
    return problems


def _strip_anchor(target):
    return target.split("#", 1)[0].strip()


def check_readme_links():
    """检查 README 与 docs 中相对 Markdown 链接/图片目标是否存在。"""
    problems = []
    link_re = re.compile(r"!?\[[^\]]*\]\(([^)\s]+)")
    for rel in ("README.md", "CONTRIBUTING.md", "SECURITY.md"):
        path = os.path.join(ROOT, rel)
        if not os.path.isfile(path):
            continue
        with open(path, encoding="utf-8", errors="replace") as f:
            text = f.read()
        for target in link_re.findall(text):
            if target.startswith(("http://", "https://", "mailto:", "#", "data:")):
                continue
            clean = _strip_anchor(target)
            if not clean:
                continue
            candidate = os.path.normpath(os.path.join(ROOT, clean))
            if not os.path.exists(candidate):
                problems.append(f"{rel}: 链接目标不存在 -> {target}")
    return problems


def policy():
    """执行全部内容策略检查。"""
    problems = check_paths() + check_content() + check_readme_links()
    if problems:
        print(f"公开内容闸门失败：{len(problems)} 项")
        for item in problems:
            print(" -", item)
        return 1
    print("公开内容闸门通过：路径、禁止内容、内网地址、密钥与 README 链接均正常")
    return 0


def fixtures():
    """校验公开夹具清单：存在性、SHA-256、必需项与数量。"""
    manifest_path = os.path.join(ROOT, "test", "fixtures", "public-fixtures.json")
    if not os.path.isfile(manifest_path):
        print("FAIL: 缺少 test/fixtures/public-fixtures.json")
        return 1
    with open(manifest_path, encoding="utf-8") as f:
        manifest = json.load(f)
    items = manifest.get("fixtures") or manifest.get("entries") or []
    problems = []
    missing_required = []
    for item in items:
        rel = (item.get("path") or "").replace("\\", "/")
        if not rel:
            problems.append("清单条目缺少 path")
            continue
        full = os.path.join(ROOT, rel)
        if not os.path.isfile(full):
            (missing_required if item.get("required") else problems).append(f"{rel}: 文件不存在")
            continue
        expect = (item.get("sha256") or "").lower()
        if not expect:
            problems.append(f"{rel}: 清单缺少 sha256")
            continue
        with open(full, "rb") as f:
            actual = hashlib.sha256(f.read()).hexdigest()
        if actual != expect:
            problems.append(f"{rel}: SHA-256 不符（清单 {expect[:12]}… 实际 {actual[:12]}…）")
    required_count = sum(1 for item in items if item.get("required"))
    if not items:
        problems.append("公开夹具清单为空（公开 CI 必须至少包含一个必需夹具）")
    if missing_required:
        problems.append("必需夹具缺失：" + "、".join(missing_required))
    if problems:
        print(f"公开夹具校验失败：{len(problems)} 项")
        for item in problems:
            print(" -", item)
        return 1
    print(f"公开夹具校验通过：共 {len(items)} 个（必需 {required_count} 个，"
          f"可选 {len(items) - required_count} 个）")
    return 0


def tests(report_path):
    """解析 pytest JUnit XML：公开 CI 不允许任何 skip。"""
    import xml.etree.ElementTree as ET

    if not os.path.isfile(report_path):
        print(f"FAIL: 找不到测试报告 {report_path}")
        return 1
    tree = ET.parse(report_path)
    root = tree.getroot()
    suite = root.find("testsuite") if root.tag == "testsuites" else root
    total = int(suite.get("tests", 0))
    skipped = int(suite.get("skipped", 0))
    failures = int(suite.get("failures", 0)) + int(suite.get("errors", 0))
    print(f"公开测试统计：共 {total} 个，失败 {failures} 个，跳过 {skipped} 个")
    if failures:
        print("FAIL: 存在失败用例")
        return 1
    if skipped:
        names = []
        for case in suite.iter("testcase"):
            if case.find("skipped") is not None:
                names.append(f"{case.get('classname', '')}.{case.get('name', '')}")
        print("FAIL: 公开 CI 不允许静默跳过用例：")
        for name in names:
            print(" -", name)
        return 1
    if total == 0:
        print("FAIL: 没有执行任何用例")
        return 1
    print("公开测试校验通过")
    return 0


def main(argv=None):
    argv = list(sys.argv[1:] if argv is None else argv)
    if not argv or argv[0] in ("-h", "--help"):
        print(__doc__)
        return 0 if argv else 2
    command = argv[0]
    if command == "policy":
        return policy()
    if command == "fixtures":
        return fixtures()
    if command == "tests":
        return tests(argv[1] if len(argv) > 1 else "test-report.xml")
    print(f"未知子命令：{command}")
    print(__doc__)
    return 2


if __name__ == "__main__":
    sys.exit(main())
