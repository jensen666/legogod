# -*- coding: utf-8 -*-
"""新旧 40 例对比图表：新 20 例 vs 旧 20 例，以及本轮旧 20 例 vs 2026-11-03 最终轮。

数据源（只读本地证据）：
  - artifacts/e2e-20/20261104-report/report-data.json（两轮合并统计）
  - artifacts/e2e-20/20261104-old20/analysis40.json（含 compare.rows 逐例对照）

输出（默认写到本地证据目录，不入库）：
  10-old-vs-new-overview.png   交付率/四态/目标比分布/断言错误数分布
  11-assertion-compare.png     断言错误结构对比（占比 + 逐例条数）
  12-failure-compare.png       失败类别/阶段占比对比
  13-vs-previous-round.png     本轮旧 20 例 vs 11-03 最终轮（指标 dumbbell + 逐例翻盘矩阵）
  14-case-ratio-compare.png    逐例目标块数比前后对比（11-03 → 11-04）

用法：
    python -m tools.e2e_compare_charts \
        --data artifacts/e2e-20/20261104-report/report-data.json \
        --analysis artifacts/e2e-20/20261104-old20/analysis40.json \
        --out <本地证据目录>/charts/compare
"""
import argparse
import json
import os
import sys

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
import numpy as np  # noqa: E402
from matplotlib.patches import Patch  # noqa: E402

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from tools.e2e_report_charts import (  # noqa: E402
    COLOR_BAD, COLOR_DEGRADED, COLOR_FAILED, COLOR_FAST, COLOR_GOOD, COLOR_NEW,
    COLOR_OLD, COLOR_SUCCESS, COLOR_UNKNOWN, KIND_COLORS, KIND_LABELS, OUTCOME_LABELS,
    setup_font,
)


def _load(path):
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def _strip_points(ax, values, x_center, color, width=0.14):
    """在箱线图旁叠加抖动点。"""
    if not values:
        return
    rng = np.random.default_rng(20261104)
    xs = x_center + rng.uniform(-width, width, size=len(values))
    ax.scatter(xs, values, s=22, color=color, alpha=0.75, edgecolor="white", linewidth=0.5,
               zorder=3)


def _old_vs_new_overview(data, out_dir):
    old, new = data["old20"], data["new20"]
    fig, axes = plt.subplots(2, 2, figsize=(13, 9), dpi=150)

    # (a) 交付率/断言率
    ax = axes[0][0]
    groups = ["旧 20 例", "新 20 例"]
    delivery = [old["delivered"] / old["total"], new["delivered"] / new["total"]]
    assertion = [old["asserted"] / old["total"], new["asserted"] / new["total"]]
    x = range(2)
    ax.bar([i - 0.2 for i in x], delivery, width=0.36, color=[COLOR_OLD, COLOR_NEW],
           label="任务交付率")
    ax.bar([i + 0.2 for i in x], assertion, width=0.36, color=COLOR_FAILED, alpha=0.75,
           label="断言通过率")
    for i, (d, a) in enumerate(zip(delivery, assertion)):
        ax.annotate(f"{old['delivered'] if i == 0 else new['delivered']}/20\n{d:.0%}",
                    (i - 0.2, d), xytext=(0, 4), textcoords="offset points",
                    ha="center", fontsize=9)
        ax.annotate(f"{a:.0%}", (i + 0.2, a), xytext=(0, 4), textcoords="offset points",
                    ha="center", fontsize=9)
    ax.set_xticks(list(x), groups)
    ax.set_ylim(0, 0.9)
    ax.set_ylabel("比例")
    ax.set_title("交付率 vs 断言通过率：新集略高、断言同为 0",
                 fontsize=11, fontweight="bold")
    ax.legend(fontsize=8, frameon=False)
    ax.grid(axis="y", alpha=0.25)

    # (b) 四态占比
    ax = axes[0][1]
    for i, (label, summ) in enumerate((("旧 20 例", old), ("新 20 例", new))):
        left = 0
        for key, legend_label, color in OUTCOME_LABELS:
            value = summ["outcomes"].get(key, 0) / summ["total"]
            ax.barh(i, value, left=left, color=color,
                    label=legend_label if i == 0 else None)
            if value > 0.06:
                ax.annotate(f"{value:.0%}", (left + value / 2, i), ha="center",
                            va="center", fontsize=8,
                            color="white" if key != "fast_fallback" else "#333333")
            left += value
    ax.set_yticks([0, 1], ["旧 20 例", "新 20 例"])
    ax.set_xlim(0, 1)
    ax.set_xlabel("四态占比（100% 堆叠）")
    ax.set_title("四态构成：新集降级更多、极速保底更少",
                 fontsize=11, fontweight="bold")
    ax.legend(fontsize=7.5, ncol=4, frameon=False, loc="upper center",
              bbox_to_anchor=(0.5, -0.14))
    ax.invert_yaxis()
    ax.grid(axis="x", alpha=0.25)

    # (c) 目标块数比分布
    ax = axes[1][0]
    old_ratios = [r["bricksRatio"] for r in data["cases"]["old20"]
                  if r.get("taskOk") and isinstance(r.get("bricksRatio"), (int, float))]
    new_ratios = [r["bricksRatio"] for r in data["cases"]["new20"]
                  if r.get("taskOk") and isinstance(r.get("bricksRatio"), (int, float))]
    bp = ax.boxplot([old_ratios, new_ratios], widths=0.42, patch_artist=True,
                    medianprops=dict(color="#333333", linewidth=1.6),
                    showfliers=False)
    for patch, color in zip(bp["boxes"], (COLOR_OLD, COLOR_NEW)):
        patch.set_facecolor(color)
        patch.set_alpha(0.35)
    _strip_points(ax, old_ratios, 1, COLOR_OLD)
    _strip_points(ax, new_ratios, 2, COLOR_NEW)
    ax.axhline(0.5, color=COLOR_FAILED, linestyle="--", linewidth=1.4)
    ax.annotate("验收线 50%", (0.52, 0.52), fontsize=8, color=COLOR_FAILED)
    for i, values in enumerate((old_ratios, new_ratios), start=1):
        median = round(float(np.median(values)), 2)
        ax.annotate(f"中位 {median:.1%}\n达标 {sum(v >= 0.5 for v in values)}/"
                    f"{len(values)}", (i, 0.02), ha="center", fontsize=8,
                    color="#333333")
    ax.set_xticks([1, 2], ["旧 20 例（12 交付）", "新 20 例（13 交付）"])
    ax.set_ylim(0, 1)
    ax.set_ylabel("实际零件数 / 目标块数")
    ax.set_title("交付例目标块数比：旧 34.0% → 新 39.0%，新集达标 6/13",
                 fontsize=11, fontweight="bold")
    ax.grid(axis="y", alpha=0.25)

    # (d) 每交付例断言错误数
    ax = axes[1][1]
    old_err = [len(r.get("assertionErrors") or []) for r in data["cases"]["old20"]
               if r.get("taskOk")]
    new_err = [len(r.get("assertionErrors") or []) for r in data["cases"]["new20"]
               if r.get("taskOk")]
    bp = ax.boxplot([old_err, new_err], widths=0.42, patch_artist=True,
                    medianprops=dict(color="#333333", linewidth=1.6),
                    showfliers=False)
    for patch, color in zip(bp["boxes"], (COLOR_OLD, COLOR_NEW)):
        patch.set_facecolor(color)
        patch.set_alpha(0.35)
    _strip_points(ax, old_err, 1, COLOR_OLD)
    _strip_points(ax, new_err, 2, COLOR_NEW)
    for i, values in enumerate((old_err, new_err), start=1):
        ax.annotate(f"平均 {np.mean(values):.2f} 条/例\n共 {sum(values)} 条",
                    (i, max(values) + 0.7), ha="center", fontsize=8)
    ax.set_xticks([1, 2], ["旧 20 例", "新 20 例"])
    ax.set_ylabel("每交付例断言错误数（条）")
    ax.set_title("断言错误密度：4.17 条/例 → 2.69 条/例",
                 fontsize=11, fontweight="bold")
    ax.set_ylim(0, max(old_err + new_err) + 4)
    ax.grid(axis="y", alpha=0.25)

    fig.suptitle("新 20 例 vs 旧 20 例：同轮真实浏览器 E2E 横向对比", fontsize=14,
                 fontweight="bold")
    fig.tight_layout(rect=(0, 0, 1, 0.95))
    path = os.path.join(out_dir, "10-old-vs-new-overview.png")
    fig.savefig(path, bbox_inches="tight", facecolor="white")
    plt.close(fig)
    return path


def _assertion_compare(data, out_dir):
    old, new = data["old20"], data["new20"]
    categories = ["目标块数比<50%", "部位缺失/体量不足", "部位数<设计下限", "体素数<设计下限",
                  "其它特征/几何", "立体部位数<设计下限", "门禁重放失败",
                  "评审过期(reviewStale)", "算子数<设计下限"]
    short = ["目标比<50%", "部位缺失/体量", "部位数<下限", "体素数<下限", "其它特征/几何",
             "立体部位数<下限", "门禁重放失败", "评审过期", "算子数<下限"]
    fig = plt.figure(figsize=(14, 6.2), dpi=150)
    gs = fig.add_gridspec(1, 2, width_ratios=[1.25, 1])

    ax = fig.add_subplot(gs[0])
    y = np.arange(len(categories))
    for offset, summ, color, label in ((-0.2, old, COLOR_OLD, "旧 20 例（50 条）"),
                                       (0.2, new, COLOR_NEW, "新 20 例（35 条）")):
        values = [summ["assertionErrorCategories"].get(c, 0) for c in categories]
        total = sum(values) or 1
        left = 0
        for i, value in enumerate(values):
            share = value / total
            ax.barh(y[i] + offset, share, left=left, color=color,
                    alpha=0.9 if offset < 0 else 0.65, height=0.34)
            if share >= 0.07:
                ax.annotate(f"{value}", (left + share / 2, y[i] + offset), ha="center",
                            va="center", fontsize=7,
                            color="white" if offset < 0 else "#333333")
            left += share
    ax.set_yticks(y, short, fontsize=8.5)
    ax.invert_yaxis()
    ax.set_xlim(0, 1)
    ax.set_xlabel("占该组断言错误总数的比例（100% 堆叠，条内数字为条数）")
    ax.set_title("断言错误结构：旧集 62% 为规模/复杂度，新集部位数类占比更高",
                 fontsize=11, fontweight="bold")
    ax.legend(handles=[Patch(color=COLOR_OLD, label="旧 20 例（50 条）"),
                       Patch(color=COLOR_NEW, alpha=0.65, label="新 20 例（35 条）")],
              fontsize=8, frameon=False, loc="lower right")
    ax.grid(axis="x", alpha=0.22)

    ax = fig.add_subplot(gs[1])
    old_rows = [(r["case"], len(r.get("assertionErrors") or [])) for r in data["cases"]["old20"]
                if r.get("taskOk")]
    new_rows = [(r["case"], len(r.get("assertionErrors") or [])) for r in data["cases"]["new20"]
                if r.get("taskOk")]
    all_rows = sorted([(c, n, "旧") for c, n in old_rows] + [(c, n, "新") for c, n in new_rows],
                      key=lambda item: item[1])
    labels = [f"{c}（{g}）" for c, n, g in all_rows]
    values = [n for c, n, g in all_rows]
    colors = [COLOR_OLD if g == "旧" else COLOR_NEW for c, n, g in all_rows]
    ax.barh(range(len(labels)), values, color=colors, height=0.72)
    for i, value in enumerate(values):
        ax.annotate(str(value), (value, i), xytext=(3, 0), textcoords="offset points",
                    va="center", fontsize=8)
    ax.set_yticks(range(len(labels)), labels, fontsize=7.5)
    ax.axvline(np.mean([n for _, n, g in all_rows if g == "旧"]), color=COLOR_OLD,
               linestyle=":", linewidth=1.2)
    ax.axvline(np.mean([n for _, n, g in all_rows if g == "新"]), color=COLOR_NEW,
               linestyle=":", linewidth=1.2)
    ax.set_xlabel("该交付例的断言错误条数")
    ax.set_title("逐交付例断言错误条数（均值虚线：旧 4.17 / 新 2.69）",
                 fontsize=11, fontweight="bold")
    ax.grid(axis="x", alpha=0.22)

    fig.suptitle("断言错误对比：数量与结构", fontsize=14, fontweight="bold")
    fig.tight_layout(rect=(0, 0, 1, 0.94))
    path = os.path.join(out_dir, "11-assertion-compare.png")
    fig.savefig(path, bbox_inches="tight", facecolor="white")
    plt.close(fig)
    return path


def _failure_compare(data, out_dir):
    old, new = data["old20"], data["new20"]
    fig, axes = plt.subplots(1, 2, figsize=(13, 5.6), dpi=150)

    ax = axes[0]
    labels = [lab for _, lab in KIND_LABELS]
    old_vals = [old["attemptFailureKinds"].get(k, 0) for k, _ in KIND_LABELS]
    new_vals = [new["attemptFailureKinds"].get(k, 0) for k, _ in KIND_LABELS]
    old_total, new_total = sum(old_vals) or 1, sum(new_vals) or 1
    x = np.arange(len(labels))
    ax.bar(x - 0.2, [v / old_total for v in old_vals], width=0.36, color=COLOR_OLD,
           label=f"旧 20 例（{old_total} 次）")
    ax.bar(x + 0.2, [v / new_total for v in new_vals], width=0.36, color=COLOR_NEW,
           label=f"新 20 例（{new_total} 次）")
    for i, (a, b) in enumerate(zip(old_vals, new_vals)):
        ax.annotate(str(a), (i - 0.2, a / old_total), xytext=(0, 3),
                    textcoords="offset points", ha="center", fontsize=8)
        ax.annotate(str(b), (i + 0.2, b / new_total), xytext=(0, 3),
                    textcoords="offset points", ha="center", fontsize=8)
    ax.set_xticks(x, [lab.replace(" ", "\n") for lab in labels], fontsize=8)
    ax.set_ylabel("占该组失败尝试的比例")
    ax.set_ylim(0, 0.5)
    ax.set_title("失败类别占比：support 均为最大项；connectivity 仅新集出现",
                 fontsize=11, fontweight="bold")
    ax.legend(fontsize=8, frameon=False)
    ax.grid(axis="y", alpha=0.22)

    ax = axes[1]
    stages = ["revise", "solve", "draw"]
    stage_labels = ["修订 revise", "求解 solve", "画图 draw"]
    old_vals = [old["attemptFailureStages"].get(s, 0) for s in stages]
    new_vals = [new["attemptFailureStages"].get(s, 0) for s in stages]
    old_total, new_total = sum(old_vals) or 1, sum(new_vals) or 1
    x = np.arange(len(stages))
    ax.bar(x - 0.2, [v / old_total for v in old_vals], width=0.36, color=COLOR_OLD,
           label="旧 20 例")
    ax.bar(x + 0.2, [v / new_total for v in new_vals], width=0.36, color=COLOR_NEW,
           label="新 20 例")
    for i, (a, b) in enumerate(zip(old_vals, new_vals)):
        ax.annotate(f"{a}（{a / old_total:.0%}）", (i - 0.2, a / old_total), xytext=(0, 3),
                    textcoords="offset points", ha="center", fontsize=8)
        ax.annotate(f"{b}（{b / new_total:.0%}）", (i + 0.2, b / new_total), xytext=(0, 3),
                    textcoords="offset points", ha="center", fontsize=8)
    ax.set_xticks(x, stage_labels)
    ax.set_ylabel("占该组失败尝试的比例")
    ax.set_ylim(0, 0.72)
    ax.set_title("失败阶段占比：新集修订阶段占比更高（10/16=62.5%）",
                 fontsize=11, fontweight="bold")
    ax.legend(fontsize=8, frameon=False)
    ax.grid(axis="y", alpha=0.22)

    fig.suptitle("失败结构对比：新 20 例 vs 旧 20 例", fontsize=14, fontweight="bold")
    fig.tight_layout(rect=(0, 0, 1, 0.93))
    path = os.path.join(out_dir, "12-failure-compare.png")
    fig.savefig(path, bbox_inches="tight", facecolor="white")
    plt.close(fig)
    return path


def _vs_previous_round(data, analysis, out_dir):
    compare = analysis["compare"]
    before = data.get("compareOld20") or {}
    after = data["old20"]
    rows = [
        # (指标名, 11-03 最终轮, 本轮, 越大越好?)
        ("交付（/20）", before.get("delivered"), after.get("delivered"), True),
        ("双尝试失败", len(before.get("doubleAttemptFailedIds") or []),
         len(after.get("doubleAttemptFailedIds") or []), False),
        ("门禁降级", len(before.get("gateDegradedIds") or []),
         len(after.get("gateDegradedIds") or []), False),
        ("reviewStale", len(before.get("reviewStaleIds") or []),
         len(after.get("reviewStaleIds") or []), False),
        ("断言错误总数", before.get("assertionErrorTotal"), after.get("assertionErrorTotal"),
         False),
        ("断言错误/交付例", round((before.get("assertionErrorTotal") or 0)
                              / max(before.get("delivered") or 1, 1), 2),
         round((after.get("assertionErrorTotal") or 0)
               / max(after.get("delivered") or 1, 1), 2), False),
        ("目标比中位（%）", round((before.get("medianBricksRatio") or 0) * 100, 1),
         round((after.get("medianBricksRatio") or 0) * 100, 1), True),
        ("体素中位", before.get("medianVoxels"), after.get("medianVoxels"), True),
        ("耗时中位（s）", before.get("elapsedMedian"), after.get("elapsedMedian"), False),
    ]
    fig = plt.figure(figsize=(15, 7.2), dpi=150)
    gs = fig.add_gridspec(1, 2, width_ratios=[1, 1.15])
    ax = fig.add_subplot(gs[0])
    y = np.arange(len(rows))
    for i, (name, v_before, v_after, higher_better) in enumerate(rows):
        if v_before is None or v_after is None:
            continue
        max_value = max(abs(v_before), abs(v_after)) or 1
        xb, xa = v_before / max_value, v_after / max_value
        improved = (v_after > v_before) if higher_better else (v_after < v_before)
        line_color = COLOR_GOOD if improved else COLOR_FAILED
        ax.plot([xb, xa], [i, i], color=line_color, linewidth=2.2, alpha=0.75, zorder=1)
        ax.scatter([xb], [i], s=70, color=COLOR_OLD, zorder=3, label="11-03 最终轮"
                   if i == 0 else None)
        ax.scatter([xa], [i], s=70, color=COLOR_NEW, zorder=3, label="11-04 本轮"
                   if i == 0 else None)
        ax.annotate(f"{v_before}", (xb, i), xytext=(0, 8), textcoords="offset points",
                    ha="center", fontsize=8, color=COLOR_OLD)
        ax.annotate(f"{v_after}", (xa, i), xytext=(0, -14), textcoords="offset points",
                    ha="center", fontsize=8, color=COLOR_NEW)
    ax.set_yticks(y, [r[0] for r in rows], fontsize=9)
    ax.invert_yaxis()
    ax.set_xlim(-0.02, 1.1)
    ax.set_xticks([])
    ax.set_xlabel("每行按两组数值归一化到 0–1（线上数字为真实值；绿=向好，红=变差）")
    ax.set_title("本轮旧 20 例 vs 2026-11-03 最终冻结轮", fontsize=11, fontweight="bold")
    ax.legend(fontsize=8, frameon=False, loc="upper center",
              bbox_to_anchor=(0.5, -0.10), ncol=2)
    ax.grid(axis="x", alpha=0.2)

    ax = fig.add_subplot(gs[1])
    compare_rows = compare.get("rows") or []
    labels = [item["case"] for item in compare_rows]
    for i, item in enumerate(compare_rows):
        before_ok = (item.get("before") or {}).get("taskOk")
        after_ok = (item.get("after") or {}).get("taskOk")
        for j, ok in enumerate((before_ok, after_ok)):
            color = COLOR_GOOD if ok else (COLOR_BAD if ok is False else COLOR_UNKNOWN)
            ax.add_patch(plt.Rectangle((j - 0.5, i - 0.5), 1, 1, facecolor=color,
                                       edgecolor="white", linewidth=1.2))
            ratio = ((item.get("before") if j == 0 else item.get("after")) or {}).get(
                "bricksRatio")
            text = "√" if ok else "×"
            if isinstance(ratio, (int, float)):
                text += f" {ratio:.0%}"
            ax.text(j, i, text, ha="center", va="center", fontsize=7,
                    color="white" if ok else "white")
        changed = before_ok != after_ok
        if changed:
            ax.text(2.25, i, "↓ 丢失" if before_ok else "↑ 找回", va="center", fontsize=7.5,
                    color=COLOR_BAD if before_ok else COLOR_GOOD, fontweight="bold")
    ax.set_xlim(-0.5, 2.9)
    ax.set_ylim(len(labels) - 0.5, -0.5)
    ax.set_xticks([0, 1], ["11-03\n最终轮", "11-04\n本轮"], fontsize=8.5)
    ax.set_yticks(range(len(labels)), labels, fontsize=8)
    ax.tick_params(length=0)
    for spine in ax.spines.values():
        spine.set_visible(False)
    ax.set_title("逐例交付翻转：丢失 5 例、找回 1 例（16→12）",
                 fontsize=11, fontweight="bold")

    fig.suptitle("与「旧的」对比：同代码同 20 例，本轮 vs 11-03 最终轮", fontsize=14,
                 fontweight="bold")
    fig.text(0.5, 0.015,
             "对照轮：artifacts/e2e-20/20261103-0703-frozen2-full30（交付 16/20、断言 0/20）；"
             "本轮：artifacts/e2e-20/20261104-old20（交付 12/20、断言 0/20）。",
             ha="center", fontsize=8, color="#555555")
    fig.tight_layout(rect=(0, 0.04, 1, 0.95))
    path = os.path.join(out_dir, "13-vs-previous-round.png")
    fig.savefig(path, bbox_inches="tight", facecolor="white")
    plt.close(fig)
    return path


def _case_ratio_compare(analysis, out_dir):
    rows = analysis["compare"].get("rows") or []
    rows = sorted(rows, key=lambda item: item["case"])
    fig, ax = plt.subplots(figsize=(11, 8), dpi=150)
    y = np.arange(len(rows))
    for i, item in enumerate(rows):
        before = item.get("before") or {}
        after = item.get("after") or {}
        before_ratio = before.get("bricksRatio")
        after_ratio = after.get("bricksRatio")
        before_ok = bool(before.get("taskOk"))
        after_ok = bool(after.get("taskOk"))
        if isinstance(before_ratio, (int, float)) and before_ok:
            ax.scatter([before_ratio], [i], s=55, color=COLOR_OLD, zorder=3)
        else:
            ax.scatter([0.01], [i], s=45, color=COLOR_UNKNOWN, marker="x", zorder=3)
        if isinstance(after_ratio, (int, float)) and after_ok:
            ax.scatter([after_ratio], [i], s=55, color=COLOR_NEW, zorder=3)
        else:
            ax.scatter([0.01], [i], s=45, color=COLOR_UNKNOWN, marker="x", zorder=3)
        if before_ok and after_ok and isinstance(before_ratio, (int, float)) \
                and isinstance(after_ratio, (int, float)):
            color = COLOR_GOOD if after_ratio >= before_ratio else COLOR_FAILED
            ax.plot([before_ratio, after_ratio], [i, i], color=color, linewidth=1.6,
                    alpha=0.65, zorder=2)
    ax.set_yticks(y, [item["case"] for item in rows], fontsize=8)
    ax.invert_yaxis()
    ax.axvline(0.5, color=COLOR_FAILED, linestyle="--", linewidth=1.3)
    ax.annotate("验收线 50%", (0.505, -0.8), fontsize=8, color=COLOR_FAILED)
    ax.set_xlim(0, 0.95)
    ax.set_xlabel("实际零件数 / 目标块数（× = 该轮未交付）")
    ax.set_title("逐例目标块数比：11-03 最终轮（蓝）→ 11-04 本轮（橙）",
                 fontsize=12, fontweight="bold")
    ax.legend(handles=[plt.Line2D([], [], marker="o", color="none", markerfacecolor=COLOR_OLD,
                                  markersize=8, label="11-03 最终轮"),
                       plt.Line2D([], [], marker="o", color="none", markerfacecolor=COLOR_NEW,
                                  markersize=8, label="11-04 本轮"),
                       plt.Line2D([], [], marker="x", color=COLOR_UNKNOWN,
                                  markersize=7, label="该轮未交付")],
              fontsize=8, frameon=False, loc="lower right")
    ax.grid(axis="x", alpha=0.22)
    fig.tight_layout()
    path = os.path.join(out_dir, "14-case-ratio-compare.png")
    fig.savefig(path, bbox_inches="tight", facecolor="white")
    plt.close(fig)
    return path


def main(argv=None):
    ap = argparse.ArgumentParser(description="新旧 40 例对比图表")
    ap.add_argument("--data", required=True, help="report-data.json")
    ap.add_argument("--analysis", required=True, help="旧 20 例轮的 analysis40.json")
    ap.add_argument("--out", required=True, help="图表输出目录")
    args = ap.parse_args(argv)
    setup_font()
    data = _load(args.data)
    analysis = _load(args.analysis)
    out_dir = os.path.abspath(args.out)
    os.makedirs(out_dir, exist_ok=True)
    paths = [_old_vs_new_overview(data, out_dir), _assertion_compare(data, out_dir),
             _failure_compare(data, out_dir), _vs_previous_round(data, analysis, out_dir),
             _case_ratio_compare(analysis, out_dir)]
    for path in paths:
        print(f"[compare-charts] {path} ({os.path.getsize(path) // 1024} KB)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
