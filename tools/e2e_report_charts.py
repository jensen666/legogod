# -*- coding: utf-8 -*-
"""把 2026-11-04 的 40 例真实 E2E 验收数据画成图表（只读本地证据，不发起模型/网络请求）。

数据源：
  - artifacts/e2e-20/20261104-report/report-data.json（两轮合并统计，tools/e2e_report_stats 产物）
  - artifacts/analysis-20261104/old20-history.json（旧 20 例历史轮次聚合）

输出（默认写到本地证据目录，不入库）：
  00-dashboard.png       总览仪表盘（交付/断言、四态、失败类别、断言错误、目标比、视觉分）
  01-failure-analysis.png 失败尝试类别与失败阶段
  02-target-ratio.png    25 个交付例的目标块数比 vs 50% 线
  03-stress-groups.png   新 20 例按压力类别的交付率
  04-history-trend.png   旧 20 例历史完整轮交付/断言趋势 + 本轮
  05-case-matrix.png     40 例逐例状态矩阵（任务/断言/目标比/视觉/最终门禁）

用法：
    python -m tools.e2e_report_charts \
        --data artifacts/e2e-20/20261104-report/report-data.json \
        --history artifacts/analysis-20261104/old20-history.json \
        --out <本地证据目录>/charts
"""
import argparse
import json
import os
import sys

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
from matplotlib import font_manager  # noqa: E402
from matplotlib.patches import Patch  # noqa: E402

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

# ---------------------------------------------------------------- 样式
COLOR_OLD = "#4C72B0"
COLOR_NEW = "#DD8452"
COLOR_TOTAL = "#7F7F7F"
COLOR_FAILED = "#C44E52"
COLOR_DEGRADED = "#DD8452"
COLOR_FAST = "#8172B3"
COLOR_SUCCESS = "#55A868"
COLOR_GOOD = "#55A868"
COLOR_BAD = "#C44E52"
COLOR_UNKNOWN = "#D9D9D9"

OUTCOME_LABELS = [("fidelity_success", "高保真成功", COLOR_SUCCESS),
                  ("fidelity_degraded", "降级交付", COLOR_DEGRADED),
                  ("fast_fallback", "极速保底", COLOR_FAST),
                  ("failed", "任务失败", COLOR_FAILED)]
KIND_LABELS = [("support", "支撑 support"), ("disconnected", "断连 disconnected"),
               ("coverage", "覆盖 coverage"), ("connectivity", "连通 connectivity"),
               ("protocol", "协议 protocol"), ("suspension", "悬吊 suspension")]
KIND_COLORS = ["#C44E52", "#DD8452", "#8172B3", "#64B5CD", "#B5BD61", "#8C8C8C"]
ASSERT_LABELS = [
    ("目标块数比<50%", "目标块数比<50%"), ("部位缺失/体量不足", "部位缺失/体量不足"),
    ("部位数<设计下限", "部位数<下限"), ("体素数<设计下限", "体素数<下限"),
    ("其它特征/几何", "其它特征/几何"), ("立体部位数<设计下限", "立体部位数<下限"),
    ("门禁重放失败", "门禁重放失败"), ("评审过期(reviewStale)", "评审过期"),
    ("算子数<设计下限", "算子数<下限"),
]


def setup_font():
    """注册中文字体，避免图中中文变方块。

    默认在常见系统字体位置探测；可用环境变量 LEGO_CHART_FONT 指定自己的字体文件。
    """
    candidates = [os.environ.get("LEGO_CHART_FONT"),
                  r"C:\Windows\Fonts\msyh.ttc", r"C:\Windows\Fonts\simhei.ttf",
                  r"C:\Windows\Fonts\msyhbd.ttc",
                  "/System/Library/Fonts/PingFang.ttc",
                  "/usr/share/fonts/truetype/wqy/wqy-zenhei.ttc",
                  "/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc"]
    installed = []
    for path in candidates:
        if path and os.path.isfile(path):
            try:
                font_manager.fontManager.addfont(path)
                installed.append(font_manager.FontProperties(fname=path).get_name())
            except Exception:  # noqa: BLE001 - 字体注册失败不影响其它候选
                continue
    plt.rcParams["font.family"] = installed or ["DejaVu Sans"]
    plt.rcParams["axes.unicode_minus"] = False


def load_json(path):
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def _pct(value):
    return f"{value:.1%}" if isinstance(value, (int, float)) else "—"


# ---------------------------------------------------------------- 各图
def _dashboard(data, out_dir):
    old, new, total = data["old20"], data["new20"], data["total40"]
    fig = plt.figure(figsize=(18, 10), dpi=140)
    gs = fig.add_gridspec(2, 3, hspace=0.42, wspace=0.30)

    # (1) 记录/交付/断言
    ax = fig.add_subplot(gs[0, 0])
    groups = ["旧 20 例", "新 20 例", "合计 40 例"]
    recorded = [old["recorded"], new["recorded"], total["recorded"]]
    delivered = [old["delivered"], new["delivered"], total["delivered"]]
    asserted = [old["asserted"], new["asserted"], total["asserted"]]
    x = range(len(groups))
    width = 0.26
    bars1 = ax.bar([i - width for i in x], recorded, width, label="记录", color="#B0B0B0")
    bars2 = ax.bar(list(x), delivered, width, label="任务交付", color=COLOR_OLD)
    bars3 = ax.bar([i + width for i in x], asserted, width, label="断言通过", color=COLOR_FAILED)
    for bars in (bars1, bars2, bars3):
        for bar in bars:
            ax.annotate(f"{int(bar.get_height())}", (bar.get_x() + bar.get_width() / 2,
                                                     bar.get_height()), ha="center", va="bottom",
                        fontsize=9)
    ax.set_xticks(list(x), groups)
    ax.set_ylim(0, 46)
    ax.set_title("整体结果：记录 / 任务交付 / 断言通过", fontsize=11, fontweight="bold")
    ax.legend(fontsize=8, frameon=False)
    ax.grid(axis="y", alpha=0.25)

    # (2) 四态堆叠
    ax = fig.add_subplot(gs[0, 1])
    groups_order = [("旧 20 例", old), ("新 20 例", new), ("合计 40 例", total)]
    for i, (label, summ) in enumerate(groups_order):
        left = 0
        for key, legend_label, color in OUTCOME_LABELS:
            value = summ["outcomes"].get(key, 0)
            ax.barh(i, value, left=left, color=color,
                    label=legend_label if i == 0 else None)
            left += value
    ax.set_yticks(range(len(groups_order)), [g for g, _ in groups_order])
    ax.invert_yaxis()
    ax.set_title("交付四态分布（合计 40 例）", fontsize=11, fontweight="bold")
    ax.legend(fontsize=8, ncol=4, frameon=False, loc="upper center",
              bbox_to_anchor=(0.5, -0.08))
    ax.set_xlim(0, 40)
    ax.grid(axis="x", alpha=0.25)

    # (3) 失败尝试 kind
    ax = fig.add_subplot(gs[0, 2])
    labels = [lab for _, lab in KIND_LABELS]
    old_vals = [old["attemptFailureKinds"].get(k, 0) for k, _ in KIND_LABELS]
    new_vals = [new["attemptFailureKinds"].get(k, 0) for k, _ in KIND_LABELS]
    y = range(len(labels))
    ax.barh([i + 0.2 for i in y], old_vals, height=0.36, color=COLOR_OLD, label="旧 20 例")
    ax.barh([i - 0.2 for i in y], new_vals, height=0.36, color=COLOR_NEW, label="新 20 例")
    for i, (a, b) in enumerate(zip(old_vals, new_vals)):
        ax.annotate(str(a), (a, i + 0.2), xytext=(2, 0), textcoords="offset points",
                    va="center", fontsize=8)
        ax.annotate(str(b), (b, i - 0.2), xytext=(2, 0), textcoords="offset points",
                    va="center", fontsize=8)
    ax.set_yticks(list(y), labels, fontsize=8)
    ax.invert_yaxis()
    ax.set_title("任务失败尝试类别（旧 22 次 / 新 16 次）", fontsize=11, fontweight="bold")
    ax.legend(fontsize=8, frameon=False)
    ax.grid(axis="x", alpha=0.25)

    # (4) 断言错误分类
    ax = fig.add_subplot(gs[1, 0])
    old_cat = old["assertionErrorCategories"]
    new_cat = new["assertionErrorCategories"]
    labels = [lab for _, lab in ASSERT_LABELS]
    old_vals = [old_cat.get(k, 0) for k, _ in ASSERT_LABELS]
    new_vals = [new_cat.get(k, 0) for k, _ in ASSERT_LABELS]
    y = range(len(labels))
    ax.barh([i + 0.2 for i in y], old_vals, height=0.36, color=COLOR_OLD, label="旧 20 例（50 条）")
    ax.barh([i - 0.2 for i in y], new_vals, height=0.36, color=COLOR_NEW, label="新 20 例（35 条）")
    for i, (a, b) in enumerate(zip(old_vals, new_vals)):
        if a:
            ax.annotate(str(a), (a, i + 0.2), xytext=(2, 0), textcoords="offset points",
                        va="center", fontsize=8)
        if b:
            ax.annotate(str(b), (b, i - 0.2), xytext=(2, 0), textcoords="offset points",
                        va="center", fontsize=8)
    ax.set_yticks(list(y), labels, fontsize=8)
    ax.invert_yaxis()
    ax.set_title("25 个交付例的断言错误分类（共 85 条）", fontsize=11, fontweight="bold")
    ax.legend(fontsize=8, frameon=False)
    ax.grid(axis="x", alpha=0.25)

    # (5) 目标块数比
    ax = fig.add_subplot(gs[1, 1])
    old_rows = [r for r in data["cases"]["old20"] if r.get("taskOk")]
    new_rows = [r for r in data["cases"]["new20"] if r.get("taskOk")]
    for rows, color, ypos, label in ((old_rows, COLOR_OLD, 1, "旧 20 例"), (new_rows, COLOR_NEW, 0, "新 20 例")):
        xs = [r["bricksRatio"] for r in rows if isinstance(r.get("bricksRatio"), (int, float))]
        ys = [ypos + (i % 5 - 2) * 0.035 for i in range(len(xs))]
        ax.scatter(xs, ys, s=42, color=color, alpha=0.85, label=label, edgecolor="white", linewidth=0.6)
    ax.axvline(0.5, color=COLOR_FAILED, linestyle="--", linewidth=1.4)
    ax.annotate("验收线 50%", (0.5, 1.38), color=COLOR_FAILED, fontsize=8, rotation=90, va="top")
    ax.set_yticks([0, 1], ["新 20 例", "旧 20 例"])
    ax.set_xlim(0, 1.0)
    ax.set_xlabel("实际零件数 / 目标块数")
    ax.set_title("交付例目标块数比（旧 2/12 达标，新 6/13 达标）", fontsize=11, fontweight="bold")
    ax.legend(fontsize=8, frameon=False, loc="lower right")
    ax.grid(alpha=0.25)

    # (6) 视觉分分布
    ax = fig.add_subplot(gs[1, 2])
    bins = [4, 5, 6]
    old_counts = [sum(1 for r in old_rows if r.get("reviewOverall") == s) for s in bins]
    new_counts = [sum(1 for r in new_rows if r.get("reviewOverall") == s) for s in bins]
    x = range(len(bins))
    ax.bar([i - 0.2 for i in x], old_counts, width=0.36, color=COLOR_OLD, label="旧 20 例")
    ax.bar([i + 0.2 for i in x], new_counts, width=0.36, color=COLOR_NEW, label="新 20 例")
    ax.set_xticks(list(x), [str(b) for b in bins])
    ax.set_xlim(-0.6, 2.6)
    ax.text(0.98, 0.70, "验收线 7 分\n≥7：0 / 17 个有分交付", transform=ax.transAxes,
            fontsize=8.5, color=COLOR_FAILED, ha="right", va="top",
            bbox=dict(boxstyle="round,pad=0.3", facecolor="#FFF5F5", edgecolor=COLOR_FAILED,
                      linewidth=0.8))
    ax.set_xlabel("视觉评审 overall（历史中位 5）")
    ax.set_ylabel("案例数")
    ax.set_ylim(0, 9)
    ax.set_title("高保真视觉分分布（17 例有分）", fontsize=11, fontweight="bold")
    ax.legend(fontsize=8, frameon=False, loc="upper left")
    ax.grid(axis="y", alpha=0.25)

    fig.suptitle("LEGOGOD 40 例真实浏览器 E2E 验收总览（2026-11-04，旧 20 + 全新 20，真实 LLM）",
                 fontsize=15, fontweight="bold")
    fig.text(0.5, 0.015,
             "机制硬指标：交付统一校验失败 0｜版本覆盖 0｜internal 0｜deadline 0｜页面 JS 错误 0｜"
             "门禁降级旧 4 / 新 0｜最终门禁重放失败旧 3 / 新 0",
             ha="center", fontsize=9, color="#555555")
    path = os.path.join(out_dir, "00-dashboard.png")
    fig.savefig(path, bbox_inches="tight", facecolor="white")
    plt.close(fig)
    return path


def _failure_analysis(data, out_dir):
    old, new = data["old20"], data["new20"]
    fig, axes = plt.subplots(1, 2, figsize=(14, 5.6), dpi=150)

    ax = axes[0]
    labels = [lab for _, lab in KIND_LABELS]
    old_vals = [old["attemptFailureKinds"].get(k, 0) for k, _ in KIND_LABELS]
    new_vals = [new["attemptFailureKinds"].get(k, 0) for k, _ in KIND_LABELS]
    y = range(len(labels))
    ax.barh([i + 0.2 for i in y], old_vals, height=0.36, color=COLOR_OLD,
            label=f"旧 20 例（{sum(old_vals)} 次）")
    ax.barh([i - 0.2 for i in y], new_vals, height=0.36, color=COLOR_NEW,
            label=f"新 20 例（{sum(new_vals)} 次）")
    for i, (a, b) in enumerate(zip(old_vals, new_vals)):
        if a:
            ax.annotate(str(a), (a, i + 0.2), xytext=(2, 0), textcoords="offset points",
                        va="center", fontsize=8)
        if b:
            ax.annotate(str(b), (b, i - 0.2), xytext=(2, 0), textcoords="offset points",
                        va="center", fontsize=8)
    ax.set_yticks(list(y), labels, fontsize=9)
    ax.invert_yaxis()
    ax.set_xlabel("失败尝试次数（一次任务最多 2 次尝试）")
    ax.set_title("失败尝试类别：support 占 39.5%，connectivity 为新失败类", fontsize=11,
                 fontweight="bold")
    ax.legend(fontsize=8, frameon=False)
    ax.grid(axis="x", alpha=0.25)

    ax = axes[1]
    stages = ["revise", "solve", "draw"]
    stage_labels = ["修订阶段 revise", "求解阶段 solve", "画图阶段 draw"]
    old_vals = [old["attemptFailureStages"].get(s, 0) for s in stages]
    new_vals = [new["attemptFailureStages"].get(s, 0) for s in stages]
    x = range(len(stages))
    ax.bar([i - 0.2 for i in x], old_vals, width=0.36, color=COLOR_OLD, label="旧 20 例")
    ax.bar([i + 0.2 for i in x], new_vals, width=0.36, color=COLOR_NEW, label="新 20 例")
    for i, (a, b) in enumerate(zip(old_vals, new_vals)):
        ax.annotate(str(a), (i - 0.2, a), xytext=(0, 3), textcoords="offset points",
                    ha="center", fontsize=9)
        ax.annotate(str(b), (i + 0.2, b), xytext=(0, 3), textcoords="offset points",
                    ha="center", fontsize=9)
    ax.set_xticks(list(x), stage_labels)
    ax.set_ylabel("失败尝试次数")
    ax.set_ylim(0, max(old_vals + new_vals) + 4)
    ax.set_title("失败阶段：修订 18 次 / 求解 18 次 / 画图 2 次（合计 38 次）",
                 fontsize=11, fontweight="bold")
    ax.legend(fontsize=8, frameon=False)
    ax.grid(axis="y", alpha=0.25)

    fig.suptitle("40 例任务失败的结构性原因（15/40 任务失败，38 次失败尝试）",
                 fontsize=13, fontweight="bold")
    fig.tight_layout(rect=(0, 0, 1, 0.94))
    path = os.path.join(out_dir, "01-failure-analysis.png")
    fig.savefig(path, bbox_inches="tight", facecolor="white")
    plt.close(fig)
    return path


def _target_ratio(data, out_dir):
    rows = []
    for round_key, label, color in (("old20", "旧 20 例", COLOR_OLD), ("new20", "新 20 例", COLOR_NEW)):
        for r in data["cases"][round_key]:
            if r.get("taskOk") and isinstance(r.get("bricksRatio"), (int, float)):
                rows.append({"label": f"{r['case']} {r['name']}", "ratio": r["bricksRatio"],
                             "group": label, "color": color})
    rows.sort(key=lambda item: item["ratio"])
    fig, ax = plt.subplots(figsize=(12, 8.2), dpi=150)
    y = range(len(rows))
    bars = ax.barh(list(y), [r["ratio"] for r in rows], color=[r["color"] for r in rows],
                   height=0.7)
    for i, row in enumerate(rows):
        ax.annotate(f"{row['ratio']:.1%}", (row["ratio"], i), xytext=(3, 0),
                    textcoords="offset points", va="center", fontsize=8)
    ax.set_yticks(list(y), [r["label"] for r in rows], fontsize=8)
    ax.axvline(0.5, color=COLOR_FAILED, linestyle="--", linewidth=1.5)
    ax.annotate("验收线 50%", (0.5, len(rows) - 0.3), color=COLOR_FAILED, fontsize=9,
                xytext=(0.505, len(rows) - 0.5))
    ax.set_xlim(0, 0.95)
    ax.set_xlabel("实际零件数 / 目标块数")
    ax.set_title("25 个交付例的目标块数比（旧集 2/12 达标，新集 6/13 达标）",
                 fontsize=13, fontweight="bold")
    ax.legend(handles=[Patch(color=COLOR_OLD, label="旧 20 例"),
                       Patch(color=COLOR_NEW, label="新 20 例")],
              fontsize=9, frameon=False, loc="lower right")
    ax.grid(axis="x", alpha=0.25)
    fig.tight_layout()
    path = os.path.join(out_dir, "02-target-ratio.png")
    fig.savefig(path, bbox_inches="tight", facecolor="white")
    plt.close(fig)
    return path


def _stress_groups(data, out_dir):
    groups = data.get("stressGroups") or {}
    rows = []
    for tag, s in groups.items():
        total = s.get("total") or 0
        delivered = s.get("delivered") or 0
        rows.append({"tag": tag, "rate": delivered / total if total else 0,
                     "delivered": delivered, "total": total,
                     "ratio": s.get("medianBricksRatio")})
    rows.sort(key=lambda item: item["rate"])
    fig, ax = plt.subplots(figsize=(12, 7), dpi=150)
    colors = [COLOR_FAILED if r["rate"] < 0.5 else COLOR_DEGRADED if r["rate"] < 0.7
              else COLOR_GOOD for r in rows]
    y = range(len(rows))
    ax.barh(list(y), [r["rate"] for r in rows], color=colors, height=0.68)
    for i, row in enumerate(rows):
        ax.annotate(f"{row['delivered']}/{row['total']}（{row['rate']:.0%}）",
                    (row["rate"], i), xytext=(4, 0), textcoords="offset points",
                    va="center", fontsize=9)
    ax.set_yticks(list(y), [r["tag"] for r in rows], fontsize=9)
    ax.set_xlim(0, 1.12)
    ax.set_xlabel("交付率（交付数 / 该压力类别例数；一例可属多类）")
    ax.set_title("新 20 例按压力类别交付率：support/thin_parts/paired_symmetry 最低",
                 fontsize=13, fontweight="bold")
    ax.legend(handles=[Patch(color=COLOR_FAILED, label="<50%"),
                       Patch(color=COLOR_DEGRADED, label="50%–70%"),
                       Patch(color=COLOR_GOOD, label="≥70%")],
              fontsize=9, frameon=False, loc="lower right")
    ax.grid(axis="x", alpha=0.25)
    fig.tight_layout()
    path = os.path.join(out_dir, "03-stress-groups.png")
    fig.savefig(path, bbox_inches="tight", facecolor="white")
    plt.close(fig)
    return path


def _history_trend(history, data, out_dir):
    rounds = {r["round"]: r for r in history.get("aggregates", {}).get("rounds", [])}
    order = history.get("meta", {}).get("mainSequence") or []
    short_names = {"batch2": "11-02 基线", "dev": "11-03 开发轮",
                   "frozen1": "11-03 确认#1", "d2order": "11-03 顺序实验",
                   "frozen2": "11-03 确认#2"}
    labels, delivered, asserted = [], [], []
    for key in order:
        r = rounds.get(key) or {}
        labels.append(short_names.get(key, key))
        delivered.append(r.get("delivered", 0))
        asserted.append(r.get("asserted", 0))
    old = data["old20"]
    labels.append("11-04 本轮")
    delivered.append(old["delivered"])
    asserted.append(old["asserted"])
    x = list(range(len(labels)))
    fig, ax = plt.subplots(figsize=(13, 6), dpi=150)
    ax.plot(x, delivered, marker="o", markersize=8, linewidth=2.2, color=COLOR_OLD,
            label="旧 20 例任务交付")
    ax.plot(x, asserted, marker="s", markersize=7, linewidth=1.8, color=COLOR_FAILED,
            linestyle="--", label="断言通过")
    ax.scatter([x[-1]], [delivered[-1]], s=210, facecolor="none", edgecolor="#333333",
               linewidth=1.4, zorder=5)
    for i, value in enumerate(delivered):
        ax.annotate(str(value), (i, value), xytext=(0, 9), textcoords="offset points",
                    ha="center", fontsize=9, color=COLOR_OLD, fontweight="bold")
    for i, value in enumerate(asserted):
        ax.annotate(str(value), (i, value), xytext=(0, -15), textcoords="offset points",
                    ha="center", fontsize=8, color=COLOR_FAILED)
    ax.axhspan(12, 16, color=COLOR_OLD, alpha=0.08)
    ax.annotate("历史交付区间 12–16（单轮波动 ±4 例）", (0.02, 16.3), fontsize=8,
                color=COLOR_OLD)
    ax.set_xticks(x, labels, fontsize=9)
    ax.set_ylim(-0.8, 20)
    ax.set_ylabel("案例数（共 20）")
    ax.set_title("旧 20 例跨轮交付趋势：16→12 属于随机波动区间，断言始终为 0",
                 fontsize=13, fontweight="bold")
    ax.legend(fontsize=9, frameon=False, loc="center left")
    ax.grid(axis="y", alpha=0.25)
    fig.text(0.5, 0.005,
             "注：F.1 动态额度单变量轮仅 8 例（部分轮），未纳入本趋势；本轮 = 2026-11-04 旧 20 例复跑（HEAD f63d573）。",
             ha="center", fontsize=8, color="#666666")
    fig.tight_layout(rect=(0, 0.04, 1, 1))
    path = os.path.join(out_dir, "04-history-trend.png")
    fig.savefig(path, bbox_inches="tight", facecolor="white")
    plt.close(fig)
    return path


def _case_matrix(data, out_dir):
    fig, axes = plt.subplots(1, 2, figsize=(14, 9), dpi=150,
                             gridspec_kw={"wspace": 0.42})
    columns = ["任务\n交付", "断言\n通过", "目标比\n≥50%", "视觉\n≥7", "最终门禁\n通过"]
    for ax, key, title in ((axes[0], "old20", "旧 20 例"),
                           (axes[1], "new20", "新 20 例（N01–N20）")):
        rows = data["cases"][key]
        cells = []
        labels = []
        for r in rows:
            labels.append(f"{r['case']}")
            task_ok = bool(r.get("taskOk"))
            assert_ok = bool(r.get("assertOk"))
            ratio = r.get("bricksRatio")
            review = r.get("reviewOverall")
            gate = r.get("finalGateOk")
            row = []
            row.append(COLOR_GOOD if task_ok else COLOR_BAD)
            row.append(COLOR_GOOD if assert_ok else (COLOR_BAD if task_ok else COLOR_UNKNOWN))
            if not task_ok or not isinstance(ratio, (int, float)):
                row.append(COLOR_UNKNOWN)
            else:
                row.append(COLOR_GOOD if ratio >= 0.5 else COLOR_BAD)
            if isinstance(review, (int, float)):
                row.append(COLOR_GOOD if review >= 7 else COLOR_BAD)
            else:
                row.append(COLOR_UNKNOWN)
            if task_ok:
                row.append(COLOR_GOOD if gate is not False else COLOR_BAD)
            else:
                row.append(COLOR_UNKNOWN)
            cells.append(row)
        # 直接用矩形绘制（自定义颜色），避免 imshow 与离散色标不匹配
        for yi, row in enumerate(cells):
            for xi, color in enumerate(row):
                ax.add_patch(plt.Rectangle((xi - 0.5, yi - 0.5), 1, 1, facecolor=color,
                                           edgecolor="white", linewidth=1.2))
        ax.set_xlim(-0.5, len(columns) - 0.5)
        ax.set_ylim(len(rows) - 0.5, -0.5)
        ax.set_xticks(range(len(columns)), columns, fontsize=8)
        ax.set_yticks(range(len(rows)), labels, fontsize=8)
        ax.tick_params(length=0)
        for spine in ax.spines.values():
            spine.set_visible(False)
        ax.set_title(f"{title}：逐例状态", fontsize=11, fontweight="bold")
    fig.legend(handles=[Patch(color=COLOR_GOOD, label="通过 / 达标"),
                        Patch(color=COLOR_BAD, label="未通过 / 未达标"),
                        Patch(color=COLOR_UNKNOWN, label="无产物或未评估")],
               loc="lower center", ncol=3, frameon=False, fontsize=10)
    fig.suptitle("40 例逐例状态矩阵：任务交付 25/40、断言通过 0/40、视觉≥7 为 0、最终门禁通过 37/40",
                 fontsize=13, fontweight="bold")
    fig.subplots_adjust(left=0.08, right=0.98, top=0.90, bottom=0.10)
    path = os.path.join(out_dir, "05-case-matrix.png")
    fig.savefig(path, bbox_inches="tight", facecolor="white")
    plt.close(fig)
    return path


def main(argv=None):
    ap = argparse.ArgumentParser(description="40 例真实 E2E 验收数据可视化")
    ap.add_argument("--data", required=True, help="report-data.json 路径")
    ap.add_argument("--history", default=None, help="old20-history.json 路径（可选）")
    ap.add_argument("--out", required=True, help="图表输出目录")
    args = ap.parse_args(argv)
    setup_font()
    data = load_json(args.data)
    out_dir = os.path.abspath(args.out)
    os.makedirs(out_dir, exist_ok=True)
    paths = [_dashboard(data, out_dir), _failure_analysis(data, out_dir),
             _target_ratio(data, out_dir), _stress_groups(data, out_dir),
             _case_matrix(data, out_dir)]
    if args.history:
        paths.append(_history_trend(load_json(args.history), data, out_dir))
    for path in paths:
        print(f"[charts] {path} ({os.path.getsize(path) // 1024} KB)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
