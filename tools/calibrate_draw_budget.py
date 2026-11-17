# -*- coding: utf-8 -*-
"""复杂任务动态画图预算阈值标定（公开仓模式）。

历史版从 `artifacts/` 私有运行产物统计复杂度分布，并把 124 条含真实运行产物名的样本
冻结在 `test/fixtures/draw_budget_samples.json`。公开仓不发布该快照（含私有
`<slug>_rNNN_<run_id>` 标识），因此本工具改为**只读公开夹具清单**：

- 从 `test/fixtures/public-fixtures.json` 的公开 model 中收集带 `parts` 部位契约的样本；
- 公开样本数不足 `MIN_PUBLIC_SAMPLES` 时明确报告「不可用于重新标定」并 **exit 3**，
  绝不输出貌似有效的标定阈值/结论；
- 公开仓禁止 `--freeze` 重新冻结（快照来源为私有历史语料，去标识化后仍不发布）。

私有维护者如需重新标定，应在私有数据根用完整样本另行计算，再同步
`legogod/draw_budget.py` 冻结常量并更新测试。
"""
import argparse
import hashlib
import json
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from legogod import draw_budget  # noqa: E402

MANIFEST = os.path.join(ROOT, "test", "fixtures", "public-fixtures.json")
PUBLIC_ROOT = os.path.join(ROOT, "test", "fixtures", "public")
MIN_PUBLIC_SAMPLES = 20
METRIC_KEYS = ("requiredParts", "surfaceParts", "ops", "voxels")


class FixtureError(Exception):
    """公开夹具不满足硬性口径：exit 2，禁止把缺样本包装成可用标定。"""


def sha256_file(path):
    """返回文件字节的 SHA-256（十六进制）。"""
    digest = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _rel(path):
    """仓库内路径统一成 POSIX 相对路径。"""
    return os.path.relpath(os.path.abspath(path), ROOT).replace("\\", "/")


def collect_public_samples(manifest_path):
    """从公开清单收集带部位契约的模型样本（只保留数值统计字段，不含文件/任务名）。"""
    if not os.path.isfile(manifest_path):
        raise FixtureError("公开夹具清单缺失：%s" % _rel(manifest_path))
    try:
        with open(manifest_path, encoding="utf-8") as f:
            manifest = json.load(f)
    except (OSError, json.JSONDecodeError, UnicodeDecodeError) as e:
        raise FixtureError("公开夹具清单不是合法 JSON：%s" % e)
    entries = manifest.get("entries") if isinstance(manifest, dict) else None
    if not isinstance(entries, list) or not entries:
        raise FixtureError("公开夹具清单 entries 缺失或为空")
    root_norm = os.path.normpath(PUBLIC_ROOT) + os.sep
    samples = []
    for entry in entries:
        if entry.get("type") != "model" or entry.get("required") is not True:
            continue
        rel = str(entry.get("path") or "").replace("\\", "/")
        if not rel.startswith("test/fixtures/public/") or ".." in rel.split("/"):
            raise FixtureError("清单路径必须位于 test/fixtures/public/ 下：%r" % rel)
        abs_path = os.path.normpath(os.path.join(ROOT, *rel.split("/")))
        if not abs_path.startswith(root_norm):
            raise FixtureError("清单路径越出公开夹具目录：%r" % rel)
        if not os.path.isfile(abs_path):
            raise FixtureError("公开模型夹具缺失：%s" % rel)
        if os.path.getsize(abs_path) != entry.get("size"):
            raise FixtureError("公开模型夹具大小与清单不符：%s" % rel)
        if sha256_file(abs_path) != entry.get("sha256"):
            raise FixtureError("公开模型夹具 SHA-256 与清单不符：%s" % rel)
        try:
            with open(abs_path, encoding="utf-8") as f:
                model = json.load(f)
        except (OSError, json.JSONDecodeError, UnicodeDecodeError) as e:
            raise FixtureError("公开模型夹具不是合法 JSON：%s（%s）" % (rel, e))
        parts = model.get("parts") or []
        if not parts:
            continue  # 公开模型未带部位契约，不参与标定
        samples.append({
            "name": "sample-%03d" % (len(samples) + 1),
            "requiredParts": sum(1 for p in parts if p.get("required")),
            "surfaceParts": sum(1 for p in parts if (p.get("role") or "solid") == "surface"),
            "ops": len(model.get("ops") or []),
            "voxels": int(model.get("totalVoxels") or 0),
        })
    return samples


def percentile(sorted_vals, q):
    """取排序样本的 q 分位（与历史标定口径一致：向下取整索引）。"""
    if not sorted_vals:
        return 0
    return sorted_vals[min(len(sorted_vals) - 1, int(q * len(sorted_vals)))]


def derive_thresholds(samples):
    """按 P90 分位导出各指标投票阈值（口径与 legogod/draw_budget.py 冻结常量一致）。"""
    out = {}
    for key in METRIC_KEYS:
        vals = sorted(s[key] for s in samples)
        out[key] = percentile(vals, 0.90)
    return out


def main(argv=None):
    parser = argparse.ArgumentParser(
        description="动态画图预算阈值标定（公开仓只读公开夹具清单；样本不足 exit 3）。")
    parser.add_argument("--manifest", default=MANIFEST,
                        help="公开夹具清单路径（默认 test/fixtures/public-fixtures.json）")
    parser.add_argument("--freeze", action="store_true",
                        help="（禁止）公开仓不能重新冻结私有来源的样本快照")
    args = parser.parse_args(argv)
    if args.freeze:
        print("公开仓禁止 --freeze：冻结快照来源为私有历史语料，公开仓不提供该快照，"
              "不能重新生成。", file=sys.stderr)
        return 2
    try:
        samples = collect_public_samples(args.manifest)
    except FixtureError as e:
        print("标定失败：%s" % e, file=sys.stderr)
        return 2
    if len(samples) < MIN_PUBLIC_SAMPLES:
        print(f"公开语料带部位契约样本 {len(samples)} 个（< {MIN_PUBLIC_SAMPLES}），"
              "不可用于重新标定；公开仓不提供冻结样本快照，不输出标定阈值，"
              "冻结常量保持既有值不动。", file=sys.stderr)
        return 3
    thresholds = derive_thresholds(samples)
    print(f"公开样本集：{len(samples)} 个带 parts 契约模型")
    print("P90 分位标定阈值：" + json.dumps(thresholds, ensure_ascii=False))
    print(f"复杂判定：命中 ≥{draw_budget.COMPLEX_MIN_VOTES} 项（高保真配色计 1 项投票）")
    frozen = {
        "requiredParts": draw_budget.T_REQUIRED_PARTS,
        "surfaceParts": draw_budget.T_SURFACE_PARTS,
        "ops": draw_budget.T_OPS,
        "voxels": draw_budget.T_VOXELS,
    }
    ok = True
    for key, want in frozen.items():
        same = want == thresholds[key]
        ok = ok and same
        print(f"  {key}: {want} → " + ("一致" if same else "漂移"))
    if not ok:
        print("\n冻结阈值与公开样本重标结果不一致：请复核后同步 "
              "legogod/draw_budget.py 常量与测试。", file=sys.stderr)
        return 1
    print("\n冻结阈值核验一致。")
    return 0


if __name__ == "__main__":
    sys.exit(main())
