# -*- coding: utf-8 -*-
"""离线可拼性基准（公开夹具清单驱动）。

对 `test/fixtures/public-fixtures.json` 登记的公开模型逐个复跑「带统一校验筛选的求解 +
最终统一校验」，与 `test/fixtures/public/offline-baseline.json` 对比：公开样本必须零退化。

公开模式硬性口径（方案 6.4 / 02 语料审计 7.4-7.5）：
- 只读公开清单，不 glob `artifacts/`；
- 清单/基线缺失、空清单、文件缺失、SHA-256 不符、样本数与集合不一致、基线不完整，
  一律 exit 2 并打印差异；空集绝不输出「原通过样本零退化 ✓」。

私有全量回归仍可用 `--full-baseline <私有基线>` 走 `artifacts/model_*.json`
（默认不含 `_r0` 运行产物），公开 CI 不执行该模式。
"""
import argparse
import glob
import hashlib
import json
import os
import sys
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from legogod import tiler  # noqa: E402
from legogod.validate import validate_solution  # noqa: E402

MANIFEST = os.path.join(ROOT, "test", "fixtures", "public-fixtures.json")
PUBLIC_ROOT = os.path.join(ROOT, "test", "fixtures", "public")
BASELINE = os.path.join(PUBLIC_ROOT, "offline-baseline.json")
BENCH_CONSUMER = "tools/benchmark_offline.py"
SCHEMA_VERSION = 1
SOLVE_DEADLINE_S = 20.0


class FixtureError(Exception):
    """公开夹具/基线不满足硬性口径：调用方必须 exit 2，禁止降级成零退化通过。"""


def sha256_file(path):
    """返回文件字节的 SHA-256（十六进制）。"""
    digest = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _rel(path):
    """仓库内路径统一成 POSIX 相对路径，供清单/基线字段比对。"""
    return os.path.relpath(os.path.abspath(path), ROOT).replace("\\", "/")


def load_manifest(path):
    """读取公开夹具清单；缺失或不是合法 JSON 即硬失败。"""
    if not os.path.isfile(path):
        raise FixtureError("公开夹具清单缺失：%s" % _rel(path))
    try:
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
    except (OSError, json.JSONDecodeError, UnicodeDecodeError) as e:
        raise FixtureError("公开夹具清单不是合法 JSON：%s" % e)
    entries = data.get("entries") if isinstance(data, dict) else None
    if not isinstance(entries, list) or not entries:
        raise FixtureError("公开夹具清单 entries 缺失或为空（禁止空集通过）")
    return data


def public_baseline_models(manifest):
    """从清单取出 benchmark 消费的必需 model 条目并校验文件/哈希。

    返回 [{"slug", "path", "sha256", "id"}]；空集合、路径非法、文件缺失、哈希不符均硬失败。
    """
    root_norm = os.path.normpath(PUBLIC_ROOT) + os.sep
    models, seen = [], set()
    for entry in manifest["entries"]:
        if entry.get("type") != "model":
            continue
        if BENCH_CONSUMER not in (entry.get("consumers") or []):
            continue
        if entry.get("required") is not True:
            continue
        rel = str(entry.get("path") or "").replace("\\", "/")
        if not rel.startswith("test/fixtures/public/") or ".." in rel.split("/"):
            raise FixtureError("清单路径必须位于 test/fixtures/public/ 下：%r" % rel)
        abs_path = os.path.normpath(os.path.join(ROOT, *rel.split("/")))
        if not abs_path.startswith(root_norm):
            raise FixtureError("清单路径越出公开夹具目录：%r" % rel)
        if not os.path.isfile(abs_path):
            raise FixtureError("公开基准模型缺失：%s" % rel)
        if os.path.getsize(abs_path) != entry.get("size"):
            raise FixtureError("公开基准模型大小与清单不符：%s" % rel)
        sha = sha256_file(abs_path)
        if sha != entry.get("sha256"):
            raise FixtureError("公开基准模型 SHA-256 与清单不符：%s（清单 %s，实际 %s）"
                               % (rel, entry.get("sha256"), sha))
        name = os.path.basename(abs_path)
        slug = name[len("model_"):-len(".json")] if name.startswith("model_") else name[:-5]
        if slug in seen:
            raise FixtureError("公开基准模型 slug 重复：%s" % slug)
        seen.add(slug)
        models.append({"id": entry.get("id"), "slug": slug, "path": abs_path, "sha256": sha})
    if not models:
        raise FixtureError("公开清单没有 required 的 benchmark 模型条目")
    return models


def collect_private_models():
    """私有全量回归：收集 artifacts 下已跟踪的存量 model_*.json（排除 run_id 版本产物）。"""
    paths = []
    for path in sorted(glob.glob(os.path.join(ROOT, "artifacts", "model_*.json"))):
        if "_r0" in os.path.basename(path):
            continue
        paths.append(path)
    return paths


def run_one(path):
    """复跑单个模型的完整预算求解与统一校验，返回结构化记录。"""
    try:
        with open(path, encoding="utf-8") as f:
            model = json.load(f)
    except (json.JSONDecodeError, UnicodeDecodeError, OSError) as e:
        return {"ok": False, "error": f"读取失败: {e}"}
    layers = sorted(model.get("layers") or [], key=lambda L: L.get("y", 0))
    t0 = time.monotonic()
    try:
        sol, failure = tiler.solve_with_budget(
            model, layers,
            deadline=time.monotonic() + SOLVE_DEADLINE_S,
            validate_fn=validate_solution,
            log=lambda s: None,
        )
    except Exception as e:  # 求解异常必须计为失败样本，不能吞掉
        return {"ok": False, "error": f"求解异常: {e}", "seconds": round(time.monotonic() - t0, 2)}
    seconds = round(time.monotonic() - t0, 2)
    if sol is None:
        return {"ok": False, "kind": (failure or {}).get("kind", "?"),
                "message": ((failure or {}).get("message") or "")[:140], "seconds": seconds}
    report = sol.get("validation") or validate_solution(model, sol)
    return {"ok": bool(report.get("ok")), "pieces": len(sol.get("steps") or []),
            "attempts": sol.get("attempts", 1),
            "kind": None if report.get("ok") else "validation",
            "message": "" if report.get("ok") else "；".join(report.get("errors") or [])[:140],
            "seconds": seconds}


def _load_json(path, what):
    """读取基线 JSON；缺失/非法即硬失败。"""
    if not os.path.isfile(path):
        raise FixtureError("%s缺失：%s" % (what, _rel(path)))
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except (OSError, json.JSONDecodeError, UnicodeDecodeError) as e:
        raise FixtureError("%s不是合法 JSON：%s" % (what, e))


def validate_public_baseline(baseline, models, manifest_path):
    """公开基线必须与清单绑定：样本数、slug 集合、逐样本 SHA 全部一致。"""
    if not isinstance(baseline, dict):
        raise FixtureError("公开基线顶层必须是对象")
    if baseline.get("schemaVersion") != SCHEMA_VERSION:
        raise FixtureError("公开基线 schemaVersion 必须为 %d" % SCHEMA_VERSION)
    want_manifest = _rel(manifest_path)
    if str(baseline.get("fixturesManifest") or "").replace("\\", "/") != want_manifest:
        raise FixtureError("公开基线绑定的清单路径不符：%r != %r"
                           % (baseline.get("fixturesManifest"), want_manifest))
    results = baseline.get("results")
    if not isinstance(results, dict) or not results:
        raise FixtureError("公开基线 results 为空（禁止空集通过）")
    expected = {m["slug"]: m["sha256"] for m in models}
    if baseline.get("total") != len(expected):
        raise FixtureError("公开基线样本数不符：基线 total=%r，清单 %d"
                           % (baseline.get("total"), len(expected)))
    missing = sorted(set(expected) - set(results))
    extra = sorted(set(results) - set(expected))
    if missing or extra:
        raise FixtureError("公开基线与清单 slug 集合不一致：缺失 %r，多余 %r" % (missing, extra))
    mismatched = sorted(slug for slug in expected
                        if results[slug].get("sha256") != expected[slug])
    if mismatched:
        raise FixtureError("公开基线逐样本 SHA-256 与清单不一致：%r" % mismatched)
    baseline_passed = sum(1 for r in results.values() if r.get("ok"))
    if baseline.get("passed") != baseline_passed:
        raise FixtureError("公开基线自相矛盾：passed=%r，results 中 ok 样本=%d"
                           % (baseline.get("passed"), baseline_passed))


def write_public_baseline(path, models, results, manifest_path):
    """把本次结果写成交付基线（维护者显式 --update 时调用）。"""
    passed = sum(1 for r in results.values() if r.get("ok"))
    data = {
        "schemaVersion": SCHEMA_VERSION,
        "corpusVersion": "2026-11-17",
        "fixturesManifest": _rel(manifest_path),
        "total": len(models),
        "passed": passed,
        "rate": round(passed / max(1, len(models)), 4),
        "results": results,
    }
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2, sort_keys=True)
        f.write("\n")


def _run_models(models):
    """逐个复跑并返回 {slug: 结果}（sha256 写入结果，供基线与清单双向核对）。"""
    results = {}
    for model in models:
        record = run_one(model["path"])
        record["sha256"] = model["sha256"]
        results[model["slug"]] = record
    return results


def _compare_and_report(baseline, results, allow_missing):
    """对比基线与本次结果，打印退化样本；返回退出码（0 零退化 / 1 退化或结构不符）。"""
    baseline_results = baseline.get("results") or {}
    if set(baseline_results) != set(results):
        missing = sorted(set(baseline_results) - set(results))
        extra = sorted(set(results) - set(baseline_results))
        if missing or not allow_missing:
            print("基准结构失败：结果集与基线不一致（缺失 %r，多余 %r）" % (missing, extra),
                  file=sys.stderr)
            return 2
    regressions = [slug for slug, r in results.items()
                   if baseline_results.get(slug, {}).get("ok") and not r.get("ok")]
    gained = [slug for slug, r in results.items()
              if not baseline_results.get(slug, {}).get("ok") and r.get("ok")]
    passed = sum(1 for r in results.values() if r.get("ok"))
    print(f"本次：{passed}/{len(results)} ({passed / max(1, len(results)):.1%}) 通过"
          f"（基线 {baseline.get('passed')}/{baseline.get('total')}，"
          f"新增通过 {len(gained)} 个，退化 {len(regressions)} 个）")
    if gained:
        print("新增转绿样本：", ", ".join(gained))
    if regressions:
        print("退化样本：")
        for slug in regressions:
            print(f"  - {slug}: {results[slug].get('kind')} "
                  f"{results[slug].get('message', '')[:80]}")
        return 1
    print("原通过样本零退化 ✓")
    return 0


def _private_main(baseline_path):
    """私有全量回归：artifacts/ 存量语料 vs 私有基线（不进入公开 CI）。"""
    paths = collect_private_models()
    if not paths:
        print("私有基准失败：artifacts/ 没有存量 model_*.json，不输出零退化结论",
              file=sys.stderr)
        return 2
    baseline = _load_json(baseline_path, "私有基线")
    models = [{"slug": os.path.basename(p)[len("model_"):-len(".json")],
               "path": p, "sha256": None} for p in paths]
    results = _run_models(models)
    for record in results.values():
        record.pop("sha256", None)
    return _compare_and_report(baseline, results, allow_missing=False)


def main(argv=None):
    parser = argparse.ArgumentParser(
        description="离线可拼性基准：公开清单驱动，默认零退化门（exit 0/1/2）。")
    parser.add_argument("--manifest", default=MANIFEST,
                        help="公开夹具清单路径（默认 test/fixtures/public-fixtures.json）")
    parser.add_argument("--baseline", default=BASELINE,
                        help="公开基线路径（默认 test/fixtures/public/offline-baseline.json）")
    parser.add_argument("--update", action="store_true",
                        help="按当前公开清单重跑并重写公开基线（维护者显式操作）")
    parser.add_argument("--full-baseline", default=None,
                        help="私有全量模式：用 artifacts/ 存量语料对比给定私有基线")
    args = parser.parse_args(argv)
    try:
        if args.full_baseline:
            return _private_main(args.full_baseline)
        manifest = load_manifest(args.manifest)
        models = public_baseline_models(manifest)
        print("公开基准：fixtures=%d expected=%d hash_ok=true"
              % (len(models), len(models)))
        results = _run_models(models)
        if args.update:
            write_public_baseline(args.baseline, models, results, args.manifest)
            passed = sum(1 for r in results.values() if r.get("ok"))
            print(f"公开基线已保存：{passed}/{len(models)} 通过 → {_rel(args.baseline)}")
            return 0
        baseline = _load_json(args.baseline, "公开基线")
        validate_public_baseline(baseline, models, args.manifest)
        all_ok = all(r.get("ok") for r in results.values())
        passed = sum(1 for r in results.values() if r.get("ok"))
        print(f"公开基线核验：samples={len(models)} matched=true passed={passed}/{len(models)}"
              f" baseline_all_ok={all_ok}")
        return _compare_and_report(baseline, results, allow_missing=False)
    except FixtureError as e:
        print("基准失败：%s" % e, file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
