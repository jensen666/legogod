# -*- coding: utf-8 -*-
"""公开夹具清单严格校验器（公开 CI 第一步）。

校验口径（方案 6.4 / 02 语料审计 7.6）：
1. 清单 schema、id/path 唯一、required 布尔、sha256 为 64 位十六进制、path 在
   `test/fixtures/public/` 下（由 test/_public_fixtures.py 统一校验）；
2. 每个条目文件存在、大小与 SHA-256 一致；
3. 反向检查：`test/fixtures/public/` 下不允许清单外文件；
4. 每个条目声明的消费方文件必须存在；必需语料类型下限 design>=2 / model>=12 /
   solution>=10，必需语料数 == 26（派生基线为可选，不计入必需语料）；
5. 输出一行机器可读日志：
   `public-fixtures: total=28 required=26 optional=2 missing=0 hash_mismatch=0 unlisted=0 ok=true`

退出码：0 全部通过；2 任一失败。禁止 `--allow-missing` 之类的放水开关。
"""
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "test"))

from _public_fixtures import (  # noqa: E402
    MANIFEST, PUBLIC_ROOT, all_entries, load_manifest, public_path, sha256_file,
)

MIN_REQUIRED_BY_TYPE = {"design-plan": 2, "model": 12, "solution": 10}
EXPECTED_REQUIRED_CORPUS = 26


def check(manifest_path=MANIFEST):
    """执行全部校验，返回 (errors, stats)。errors 非空即失败。"""
    errors = []
    manifest = load_manifest() if os.path.abspath(manifest_path) == os.path.abspath(MANIFEST) \
        else _load_manifest_at(manifest_path, errors)
    if manifest is None:
        return errors, {}
    entries = manifest["entries"]
    stats = {"total": len(entries), "required": 0, "optional": 0,
             "missing": 0, "hash_mismatch": 0, "unlisted": 0}
    listed_abs = set()
    for entry in entries:
        stats["required" if entry["required"] else "optional"] += 1
        try:
            abs_path = public_path(entry["path"])
        except AssertionError as e:
            errors.append(str(e))
            continue
        listed_abs.add(os.path.normpath(abs_path))
        if not os.path.isfile(abs_path):
            stats["missing"] += 1
            errors.append("清单条目文件缺失：%s" % entry["path"])
            continue
        if os.path.getsize(abs_path) != entry["size"]:
            errors.append("清单条目大小不符：%s" % entry["path"])
        if sha256_file(abs_path) != entry["sha256"]:
            stats["hash_mismatch"] += 1
            errors.append("清单条目 SHA-256 不符：%s" % entry["path"])
        for consumer in entry["consumers"]:
            consumer_path = os.path.join(ROOT, *str(consumer).replace("\\", "/").split("/"))
            if not os.path.isfile(consumer_path):
                errors.append("清单条目消费方不存在：%s（%s）" % (consumer, entry["path"]))
    # 反向检查：公开目录下不允许清单外文件。
    for dirpath, _dirnames, filenames in os.walk(PUBLIC_ROOT):
        for name in sorted(filenames):
            full = os.path.normpath(os.path.join(dirpath, name))
            if full in listed_abs:
                continue
            if name.endswith(".pyc") or "__pycache__" in full:
                continue
            stats["unlisted"] += 1
            errors.append("公开夹具目录存在清单外文件：%s"
                          % os.path.relpath(full, ROOT).replace("\\", "/"))
    # 必需语料下限与总数。
    for fixture_type, minimum in MIN_REQUIRED_BY_TYPE.items():
        count = sum(1 for e in entries if e["type"] == fixture_type and e["required"])
        if count < minimum:
            errors.append("必需 %s 夹具数量不足：%d < %d" % (fixture_type, count, minimum))
    required_corpus = sum(1 for e in entries
                          if e["required"] and e["type"] in MIN_REQUIRED_BY_TYPE)
    if required_corpus != EXPECTED_REQUIRED_CORPUS:
        errors.append("必需语料条目数应为 %d，实际 %d"
                      % (EXPECTED_REQUIRED_CORPUS, required_corpus))
    return errors, stats


def _load_manifest_at(manifest_path, errors):
    """非默认路径时的兜底加载（测试注入坏清单用）；失败写入 errors 并返回 None。"""
    from _public_fixtures import _fail  # 复用统一失败信息格式
    try:
        import json
        if not os.path.isfile(manifest_path):
            _fail("公开夹具清单缺失：%s" % manifest_path)
        with open(manifest_path, encoding="utf-8") as f:
            data = json.load(f)
        if not isinstance(data, dict) or not isinstance(data.get("entries"), list):
            _fail("公开夹具清单结构非法")
        return data
    except (AssertionError, ValueError, OSError) as e:
        errors.append(str(e))
        return None


def main(argv=None):
    argv = list(sys.argv[1:] if argv is None else argv)
    path = MANIFEST
    for arg in argv:
        if arg.startswith("--manifest="):
            path = arg.split("=", 1)[1]
        else:
            print("未知参数：%s（校验器不接受放水开关）" % arg, file=sys.stderr)
            return 2
    try:
        errors, stats = check(path)
    except AssertionError as e:
        errors, stats = [str(e)], {}
    ok = not errors
    if stats:
        print("public-fixtures: total=%d required=%d optional=%d missing=%d "
              "hash_mismatch=%d unlisted=%d ok=%s"
              % (stats.get("total", 0), stats.get("required", 0), stats.get("optional", 0),
                 stats.get("missing", 0), stats.get("hash_mismatch", 0),
                 stats.get("unlisted", 0), "true" if ok else "false"))
    for err in errors:
        print("  - " + err, file=sys.stderr)
    if not ok:
        print("公开夹具校验失败：%d 项问题" % len(errors), file=sys.stderr)
        return 2
    print("公开夹具校验通过（零缺失、零空 glob、零哈希不符、零清单外文件）。")
    return 0


if __name__ == "__main__":
    sys.exit(main())
