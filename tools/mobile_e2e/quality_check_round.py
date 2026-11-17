"""按「回合任务映射」复用 quality_check 的冻结断言流程（本脚本不放宽任何断言口径）。

背景：`quality_check.py` 里的任务 ID 是 2026-11-15 首轮真机取证的具体 job（任务存储只保留
最近 50 条，旧的会被淘汰）。新一轮真机验收仍然要用同一个冻结断言器 `check_run_m` 复核本轮
真实任务，因此用本脚本按映射文件把 QC 的 SPECS / NON_DONE_SPECS 键与重试血缘、评审链替换为
本轮 job id；断言器、阈值与结构一致性检查全部沿用 quality_check.py 原样逻辑。

用法：
    python tools/mobile_e2e/quality_check_round.py \
        --token-file artifacts/e2e-mobile/<stamp>/token.txt \
        --out-dir artifacts/e2e-mobile/<stamp>/quality \
        --map artifacts/e2e-mobile/<stamp>/quality-id-map.json

映射文件格式（只写需要替换的项；未列出的任务保留原 ID）：
{
  "specs": {"旧id": "本轮id", ...},
  "drop": ["需要从 SPECS 中移除的旧 id", ...],
  "nonDone": {"旧id": "本轮id", ...},
  "retryLineage": [["子任务id", "父任务id"], ...],
  "fidelity": [["任务id", "期望outcome"], ...]
}
"""

from __future__ import annotations

import argparse
import json
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from tools.mobile_e2e import quality_check as qc  # noqa: E402


def _remap(specs: dict, id_map: dict, drop: set) -> dict:
    """按映射替换字典键；未映射且未要求删除的项保持原样。"""
    out = {}
    for old_id, spec in specs.items():
        if old_id in drop:
            continue
        new_id = id_map.get(old_id, old_id)
        if new_id in out:
            raise SystemExit(f"映射冲突：{old_id} -> {new_id} 与本轮其它用例重复")
        out[new_id] = spec
    return out


def main() -> int:
    parser = argparse.ArgumentParser(description="按回合映射运行冻结质量断言")
    parser.add_argument("--token-file", required=True)
    parser.add_argument("--out-dir", required=True)
    parser.add_argument("--map", required=True, dest="map_file")
    args = parser.parse_args()

    with open(args.map_file, encoding="utf-8") as handle:
        mapping = json.load(handle)

    qc.SPECS = _remap(qc.SPECS, mapping.get("specs") or {}, set(mapping.get("drop") or []))
    qc.NON_DONE_SPECS = _remap(
        qc.NON_DONE_SPECS, mapping.get("nonDone") or {}, set(mapping.get("drop") or [])
    )
    if mapping.get("retryLineage"):
        qc.RETRY_LINEAGE = tuple(tuple(pair) for pair in mapping["retryLineage"])
    if mapping.get("fidelity"):
        qc.FIDELITY_EXPECT = tuple(tuple(pair) for pair in mapping["fidelity"])

    # quality_check.main() 自己解析 --token-file/--out-dir：这里只保留它认识的参数。
    sys.argv = [
        "quality_check_round.py",
        "--token-file",
        args.token_file,
        "--out-dir",
        args.out_dir,
    ]
    return qc.main()


if __name__ == "__main__":
    raise SystemExit(main())
