# -*- coding: utf-8 -*-
"""公开夹具清单自检（公开 CI 第一步）。

覆盖方案 6.4 的硬性口径：
1. 清单 schema、id/path 唯一、必需语料数（design 2 / model 14 / solution 10 = 26）；
2. 每个登记文件存在、大小与 SHA-256 一致；
3. `test/fixtures/public/` 下没有清单外文件（防偷偷多带私有语料）；
4. 公开离线基线与清单绑定：样本数、slug 集合、逐样本 SHA 一致，且非空集；
5. 公开基准工具可跑通（fixtures=12、零退化），大图预算标定工具在公开语料下明确
   报告「不可用于重新标定」并 exit 3（不输出阈值）；
6. 公开夹具文本不含真实运行产物标识/本机路径/内部文档引用；
7. 语料相关测试不得使用 skipTest 跳过（双保险，防止重新引入假绿）。
"""
import contextlib
import io
import json
import os
import re
import subprocess
import sys
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "test"))

from _public_fixtures import (  # noqa: E402
    MANIFEST, PUBLIC_ROOT, all_entries, fixture_entries, get_fixture, load_manifest,
    read_json, sha256_file, verify_all,
)
from tools import benchmark_offline, check_public_fixtures  # noqa: E402

EXPECTED_REQUIRED = {"design-plan": 2, "model": 14, "solution": 10}
EXPECTED_REQUIRED_TOTAL = 26
EXPECTED_BASELINE_FIXTURES = 12
# 真实运行产物名（<slug>_rNNN_<8位run_id>）、本机绝对路径、内部过程文档引用。
PRIVATE_PATTERNS = (
    re.compile(r"_r\d{3}_[0-9a-f]{8}"),
    re.compile(r"[A-Za-z]:[\\/]"),
    re.compile(r"(?:^|[^A-Za-z])/(?:Users|home)/"),
    re.compile(r"AppData"),
    re.compile(r"e2e-evidence"),
    re.compile(r"docs/(?:方案|报告|开源整改)"),
    re.compile(r"process\.md"),
)
CORPUS_TEST_FILES = (
    "test/test_design_support.py",
    "test/test_parts_api.py",
    "test/test_e2e_cases_g.py",
    "test/test_e2e_cases_new20.py",
    "test/test_e2e_cases_r.py",
    "test/test_e2e_cases_batch2.py",
)


def _run_module(module, args=(), timeout=180):
    """以真实命令行方式跑工具模块，返回 CompletedProcess（UTF-8 输出）。"""
    env = dict(os.environ)
    env["PYTHONIOENCODING"] = "utf-8"
    return subprocess.run([sys.executable, "-m", module] + list(args), cwd=ROOT, env=env,
                          capture_output=True, timeout=timeout)


class ManifestSchemaTest(unittest.TestCase):
    def test_manifest_required_counts_and_types(self):
        manifest = load_manifest()
        entries = manifest["entries"]
        self.assertEqual(manifest["schemaVersion"], 1)
        self.assertTrue(manifest["note"].strip())
        required = [e for e in entries if e["required"]]
        self.assertEqual(len(required), EXPECTED_REQUIRED_TOTAL)
        for fixture_type, count in EXPECTED_REQUIRED.items():
            actual = sum(1 for e in required if e["type"] == fixture_type)
            self.assertEqual(actual, count, "%s 必需夹具数应为 %d" % (fixture_type, count))
        # 派生基线可选，不计入必需语料，但必须登记并唯一。
        baselines = [e for e in entries if e["type"] == "baseline"]
        self.assertEqual(len(baselines), 1)
        self.assertFalse(baselines[0]["required"])

    def test_entry_ids_and_paths_unique(self):
        entries = all_entries()
        self.assertEqual(len({e["id"] for e in entries}), len(entries))
        self.assertEqual(len({e["path"] for e in entries}), len(entries))

    def test_every_entry_file_matches_hash_and_size(self):
        entries, paths = verify_all()
        self.assertEqual(len(entries), len(paths))
        for entry, path in zip(entries, paths):
            self.assertEqual(os.path.getsize(path), entry["size"], entry["path"])
            self.assertEqual(sha256_file(path), entry["sha256"], entry["path"])

    def test_public_dir_has_no_unlisted_files_and_checker_passes(self):
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            code = check_public_fixtures.main([])
        output = buf.getvalue()
        self.assertEqual(code, 0, output)
        self.assertIn("ok=true", output)
        self.assertIn("missing=0", output)
        # 反向检查：清单外文件数必须为 0（由校验器统计）。
        errors, stats = check_public_fixtures.check()
        self.assertEqual(errors, [], errors)
        self.assertEqual(stats["unlisted"], 0)
        self.assertEqual(stats["missing"], 0)
        self.assertEqual(stats["hash_mismatch"], 0)

    def test_public_dir_fixture_files_are_all_registered(self):
        registered = {os.path.normpath(os.path.join(ROOT, *e["path"].split("/")))
                      for e in all_entries()}
        actual = set()
        for dirpath, _dirnames, filenames in os.walk(PUBLIC_ROOT):
            for name in filenames:
                if name.endswith(".json"):
                    actual.add(os.path.normpath(os.path.join(dirpath, name)))
        self.assertEqual(actual, registered)


class OfflineBaselineBindingTest(unittest.TestCase):
    def test_public_baseline_binds_manifest(self):
        baseline_entry = fixture_entries(type="baseline", required_only=False)[0]
        baseline = read_json(baseline_entry)
        models = benchmark_offline.public_baseline_models(load_manifest())
        self.assertEqual(len(models), EXPECTED_BASELINE_FIXTURES)
        self.assertEqual(baseline["total"], EXPECTED_BASELINE_FIXTURES)
        self.assertGreater(baseline["total"], 0)
        # 与工具同一口径的硬校验（数量/集合/逐样本 SHA，空集或缺失直接抛错）。
        benchmark_offline.validate_public_baseline(baseline, models, MANIFEST)
        self.assertEqual(set(baseline["results"]), {m["slug"] for m in models})
        self.assertEqual(baseline["passed"], EXPECTED_BASELINE_FIXTURES)

    def test_baseline_rejects_empty_or_extra_samples(self):
        models = benchmark_offline.public_baseline_models(load_manifest())
        baseline = read_json(fixture_entries(type="baseline", required_only=False)[0])
        broken = json.loads(json.dumps(baseline))
        broken["results"].pop(sorted(broken["results"])[0])
        with self.assertRaises(benchmark_offline.FixtureError):
            benchmark_offline.validate_public_baseline(broken, models, MANIFEST)
        broken_empty = json.loads(json.dumps(baseline))
        broken_empty["results"] = {}
        broken_empty["total"] = 0
        with self.assertRaises(benchmark_offline.FixtureError):
            benchmark_offline.validate_public_baseline(broken_empty, models, MANIFEST)


class PublicToolsTest(unittest.TestCase):
    def test_benchmark_cli_zero_regression(self):
        proc = _run_module("tools.benchmark_offline")
        out = proc.stdout.decode("utf-8", "replace")
        self.assertEqual(proc.returncode, 0, out + proc.stderr.decode("utf-8", "replace"))
        self.assertIn("fixtures=12 expected=12 hash_ok=true", out)
        self.assertIn("12/12", out)
        self.assertIn("零退化", out)
        self.assertNotIn("0/0", out)

    def test_benchmark_rejects_empty_manifest(self):
        tmp = os.path.join(ROOT, "test", "fixtures", "_tmp_empty_manifest.json")
        try:
            with open(tmp, "w", encoding="utf-8") as f:
                json.dump({"schemaVersion": 1, "note": "空清单", "entries": []}, f)
            proc = _run_module("tools.benchmark_offline",
                               ["--manifest", tmp])
        finally:
            if os.path.isfile(tmp):
                os.remove(tmp)
        self.assertEqual(proc.returncode, 2)
        text = proc.stdout.decode("utf-8", "replace") + proc.stderr.decode("utf-8", "replace")
        self.assertIn("空", text)
        self.assertNotIn("零退化", text)

    def test_calibrate_reports_not_calibratable_and_exit_3(self):
        proc = _run_module("tools.calibrate_draw_budget")
        out = proc.stdout.decode("utf-8", "replace")
        err = proc.stderr.decode("utf-8", "replace")
        self.assertEqual(proc.returncode, 3, out + err)
        self.assertIn("不可用于重新标定", out + err)
        self.assertNotIn("冻结阈值核验一致", out)
        self.assertNotIn("P90 分位标定阈值", out)


class PublicFixturesPrivacyTest(unittest.TestCase):
    def test_draw_budget_snapshot_not_registered_and_deidentified(self):
        paths = {e["path"] for e in all_entries()}
        self.assertNotIn("test/fixtures/draw_budget_samples.json", paths)
        snapshot = os.path.join(ROOT, "test", "fixtures", "draw_budget_samples.json")
        if os.path.isfile(snapshot):
            with open(snapshot, encoding="utf-8") as f:
                text = f.read()
            self.assertIsNone(re.search(r"_r\d{3}_[0-9a-f]{8}", text),
                              "draw_budget 快照仍含真实运行产物名")
            data = json.loads(text)
            for sample in data["samples"]:
                self.assertRegex(sample["name"], r"^sample-\d{3}$")
                self.assertEqual(set(sample),
                                 {"name", "requiredParts", "surfaceParts", "ops", "voxels"})

    def test_public_fixture_text_has_no_private_identifiers(self):
        for entry in all_entries():
            path = os.path.join(ROOT, *entry["path"].split("/"))
            with open(path, encoding="utf-8") as f:
                text = f.read()
            for pattern in PRIVATE_PATTERNS:
                self.assertIsNone(pattern.search(text),
                                  "%s 命中隐私/内部引用模式：%r"
                                  % (entry["path"], pattern.pattern))
        # 私有标定快照不得作为公开夹具路径登记（清单 note 中允许说明其排除口径）。
        self.assertNotIn("test/fixtures/draw_budget_samples.json",
                         {e["path"] for e in all_entries()})

    def test_corpus_tests_do_not_skip(self):
        for rel in CORPUS_TEST_FILES:
            path = os.path.join(ROOT, *rel.split("/"))
            self.assertTrue(os.path.isfile(path), "语料相关测试文件缺失：%s" % rel)
            with open(path, encoding="utf-8") as f:
                text = f.read()
            self.assertNotIn("skipTest", text, "%s 不允许用 skipTest 跳过公开语料用例" % rel)


if __name__ == "__main__":
    unittest.main()
