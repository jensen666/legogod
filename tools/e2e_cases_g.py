# -*- coding: utf-8 -*-
"""新增独立确认集 G01–G10 的案例单源。

口径：
  1. 需求原文与专项断言开跑前冻结；G 组只用于最终确认，不参与阈值/提示词/
     候选规则/模型选择调参。一旦用 G 组结果改规则，G 组即转为开发集。
  2. 每例以「目标约 N 块积木」为规模目标，验收 bricks_ratio = 实际零件数/目标块数，
     统一容差 >= 0.5 才算达标（「中位 ≥50%」的逐例口径）；不设强制
     cylinder / 算子数量，min_voxels / min_ops 只作回归档参考记录。
  3. 复杂度两层：需求达标档（部位/特征/目标块数，硬失败）+ 当前能力回归档
     （体素/层数/颜色数等，只记录不判失败，见 tools/e2e_assert_g.py）。
  4. 主题新颖性：开跑前用 `python -m tools.e2e_cases_g --audit` 对历史需求与
     模型名称/特征审计（基准与 tools/e2e_cases_20._load_history_corpus 同源）。
     本组自己的历史产物按 _campaign_scope 口径排除，避免跑过一次后自我撞题。

字段约定（与 tools/e2e_cases_20.py 相同）：
  id/name/subject/desc、complexity、min_parts/min_solid_parts/min_voxels/min_ops、
  require_parts、checks；另加 target_blocks（从需求原文「目标约 N 块积木」解析，
  冻结值必须与原文一致；模糊需求 G10 无目标块数，取 None）。
"""
from __future__ import annotations

from legogod.plan_scale import parse_target_blocks as _parse_target_blocks

# 统一规模容差：bricks_ratio >= 0.5 才算「目标块数达标」（中位 ≥50% 的逐例口径）
G_TARGET_TOLERANCE = 0.5


def parse_target_blocks(desc):
    """从需求原文解析目标块数 N（单源：legogod.plan_scale.parse_target_blocks）。

    与生产口径完全一致：同时接受「目标 N 块」与「目标约 N 块」；
    没有该句返回 None（G10 模糊需求）。
    """
    return _parse_target_blocks(desc)


G_CASES = [
    {
        "id": "G01", "name": "罗马斗兽场", "subject": "罗马斗兽场",
        "desc": "一座罗马斗兽场：椭圆形多层石质外墙，逐层排列贯通拱洞，部分外墙残缺，"
                "内部有环形座位和中央表演场地，底部有石台基，目标约 420 块积木",
        "complexity": "椭圆环形外墙 + 逐层真实贯通拱洞（负空间）+ 多层退台 + 内部环形座位/中央场地"
                      " + 一处残墙缺口 + 石台基",
        "target_blocks": 420,
        # 块数→量级换算（规划提示 3.5–4 体素/块；统一容差 50%）：
        #   体素下限 = N/2 块 × 4 体素/块 = 2N = 840；部位下限按可辨识特征清单取 10；
        #   算子下限仅作回归档参考（10.1 不设强制算子数量），取 N/20≈21 的保守值 18。
        "min_parts": 10, "min_solid_parts": 8, "min_voxels": 840, "min_ops": 18,
        "require_parts": [
            ("石质外墙", ("外墙", "墙", "wall")),
            ("贯通拱洞", ("拱洞", "拱券", "拱", "arch")),
            ("石台基", ("台基", "基座", "base")),
            ("环形座位", ("座位", "看台", "seat")),
            ("中央表演场地", ("场地", "中央", "arena", "floor")),
        ],
        "checks": [
            ["g_ellipse_ring", ("外墙", "墙", "wall")],
            ["g_arch_holes_min", 6],
            ["tiered_min", 3],
            ["g_seating_arena", ("座位", "看台", "seat")],
            ["g_ruined_gap"],
        ],
    },
    {
        "id": "G02", "name": "港口龙门吊", "subject": "港口龙门吊",
        "desc": "一座港口龙门吊：四根支腿支撑双根主梁，主梁一端外伸，上方有行走小车和驾驶室，"
                "下方用吊索悬挂吊钩，带配重、爬梯和货物平台，目标约 400 块积木",
        "complexity": "四腿分立 + 双主梁长跨真实悬挑 + 小车/驾驶室 + 吊索吊钩合法悬吊子组件（≥2 锁扣）"
                      " + 配重反向 + 爬梯梯级 + 货物平台",
        "target_blocks": 400,
        # 体素下限 = 400/2 × 4 = 800；部位下限按特征清单 10；算子下限取 400/20=20 的保守值 18。
        "min_parts": 10, "min_solid_parts": 9, "min_voxels": 800, "min_ops": 18,
        "require_parts": [
            ("支腿", ("支腿", "腿", "leg")),
            ("主梁", ("主梁", "梁", "beam")),
            ("行走小车", ("小车", "trolley", "cart")),
            ("驾驶室", ("驾驶室", "cab")),
            ("吊索", ("吊索", "吊绳", "sling", "cable")),
            ("吊钩", ("吊钩", "钩", "hook")),
            ("配重", ("配重", "counterweight")),
            ("爬梯", ("爬梯", "梯", "ladder")),
            ("货物平台", ("货物", "平台", "platform")),
        ],
        "checks": [
            ["g_legs_separate_min", ("支腿", "腿", "leg"), 4],
            ["g_double_beam", ("主梁", "梁", "beam"), 2, 10, 2],
            ["g_parts_contact", ("小车", "trolley", "cart"), ("主梁", "梁", "beam")],
            ["g_suspension_hanging", ("吊钩", "钩", "hook"), ("吊索", "吊绳", "sling", "cable"), 2],
            ["g_opposite_side", ("配重", "counterweight"), ("主梁", "梁", "beam"), 1],
            ["g_ladder_rungs", ("爬梯", "梯", "ladder"), 3],
        ],
    },
    {
        "id": "G03", "name": "落地竖琴", "subject": "落地竖琴",
        "desc": "一台落地竖琴：金色与木色的三角框架立在地面上，前侧弧形琴柱向上收分，"
                "三角框架内张着不少于 8 根竖向琴弦，底部有底座与踏板，整体落地摆放，目标约 320 块积木",
        "complexity": "三角框架真实成型（非实心三角块）+ 弧形收分琴柱 + ≥8 根竖向连续细弦"
                      " + 共鸣箱/底座/踏板 + 整体落地",
        "target_blocks": 320,
        # 体素下限 = 320/2 × 4 = 640；部位下限按特征清单 8；算子下限取 320/20=16。
        "min_parts": 8, "min_solid_parts": 7, "min_voxels": 640, "min_ops": 16,
        "require_parts": [
            ("三角框架", ("三角框架", "框架", "frame")),
            ("琴柱", ("琴柱", "柱", "pillar", "column")),
            ("琴弦", ("琴弦", "弦", "string")),
            ("共鸣箱", ("共鸣箱", "琴箱", "soundbox")),
            ("底座", ("底座", "base")),
            ("踏板", ("踏板", "pedal")),
        ],
        "checks": [
            ["g_triangle_frame", ("三角框架", "框架", "frame"), 0.6],
            ["g_strings_vertical_min", ("琴弦", "弦", "string"), 8],
            ["g_curved_taper_body", ("琴柱", "柱", "pillar", "column")],
            ["g_grounded_min", ("底座", "base")],
        ],
    },
    {
        "id": "G04", "name": "蜻蜓", "subject": "蜻蜓",
        "desc": "一只蜻蜓：细长腹部、明显胸部和头部，四片轻薄翅膀向两侧展开，六条细腿，"
                "复眼用异色小色点，目标约 280 块积木",
        "complexity": "细长腹部纵向长跨 + 四片真实几何翅膀左右成对 + 六腿可分组 + 胸腹比例差异"
                      " + 复眼外露异色",
        "target_blocks": 280,
        # 体素下限 = 280/2 × 4 = 560；部位下限按特征清单 8；算子下限取 280/20=14。
        "min_parts": 8, "min_solid_parts": 7, "min_voxels": 560, "min_ops": 14,
        "require_parts": [
            ("腹部", ("腹部", "abdomen")),
            ("胸部", ("胸部", "thorax", "chest")),
            ("头部", ("头部", "头", "head")),
            ("翅膀", ("翅膀", "翼", "wing")),
            ("腿", ("腿", "leg")),
            ("复眼", ("复眼", "眼", "eye")),
        ],
        "checks": [
            ["part_span_min", ("腹部", "abdomen"), 6],
            ["g_wings_four_paired", ("翅膀", "翼", "wing"), 2, 3],
            ["g_part_clusters_min", ("腿", "leg"), 6],
            ["g_part_ratio_diff", ("腹部", "abdomen"), ("胸部", "thorax", "chest"), 1.3],
            ["g_exposed_contrast_color", ("复眼", "眼", "eye"), 2],
        ],
    },
    {
        "id": "G05", "name": "双峰骆驼", "subject": "双峰骆驼",
        "desc": "一头双峰骆驼：棕色身体上有两个分开的驼峰，长颈抬头，四条长腿落地，"
                "带尾巴和耳朵，目标约 320 块积木",
        "complexity": "两个独立驼峰中间低凹（不得合并成大方块）+ 长颈真实长度与抬升 + 四腿分立足"
                      " + 尾巴/耳朵",
        "target_blocks": 320,
        # 体素下限 = 320/2 × 4 = 640；部位下限按特征清单 8；算子下限取 320/20=16 的保守值 15。
        "min_parts": 8, "min_solid_parts": 7, "min_voxels": 640, "min_ops": 15,
        "require_parts": [
            ("身体", ("身体", "躯干", "body")),
            ("驼峰", ("驼峰", "峰", "hump")),
            ("长颈", ("长颈", "颈", "neck")),
            ("腿", ("腿", "leg")),
            ("尾巴", ("尾巴", "尾", "tail")),
            ("耳朵", ("耳朵", "耳", "ear")),
        ],
        "checks": [
            ["g_twin_peaks", ("驼峰", "峰", "hump"), 2, 2],
            ["g_neck_raise", ("长颈", "颈", "neck"), ("身体", "躯干", "body"), 4, 2],
            ["g_legs_separate_min", ("腿", "leg"), 4],
        ],
    },
    {
        "id": "G06", "name": "土星展示模型", "subject": "土星",
        "desc": "一个土星展示模型：米黄色球形土星，外侧一圈倾斜的宽环，环与球体之间留有空隙，"
                "下方有支架和深色展示底座，目标约 300 块积木",
        "complexity": "多截面球形轮廓 + 环带几何连续且中央留空 + 环宽大于球体直径且有倾角"
                      " + 球体-支架/底座连接 + 球环之间真实空隙（不得实心圆盘填满）",
        "target_blocks": 300,
        # 体素下限 = 300/2 × 4 = 600；部位下限按特征清单 7；算子下限取 300/20=15 的保守值 14。
        "min_parts": 7, "min_solid_parts": 6, "min_voxels": 600, "min_ops": 14,
        "require_parts": [
            ("球体", ("球体", "土星", "sphere")),
            ("环带", ("环带", "环", "ring")),
            ("支架", ("支架", "支撑", "stand", "support")),
            ("底座", ("底座", "基座", "base")),
        ],
        "checks": [
            ["g_sphere_profile", ("球体", "土星", "sphere")],
            ["g_ring_geometry", ("环带", "环", "ring"), ("球体", "土星", "sphere")],
            ["g_parts_contact", ("球体", "土星", "sphere"), ("支架", "支撑", "stand", "support")],
        ],
    },
    {
        "id": "G07", "name": "雪地摩托", "subject": "雪地摩托",
        "desc": "一辆雪地摩托：前部两块分开的滑雪板，后部宽履带，车身有座椅、挡风玻璃、车把和前灯，"
                "目标约 320 块积木",
        "complexity": "两块滑雪板真实分立并超出车身前缘 + 后部履带长跨且与车轮区分 + 座椅/车把/前灯"
                      " + 挡风玻璃外露异色或真实斜面（不得用固定车轮代替滑雪板）",
        "target_blocks": 320,
        # 体素下限 = 320/2 × 4 = 640；部位下限按特征清单 8；算子下限取 320/20=16。
        "min_parts": 8, "min_solid_parts": 7, "min_voxels": 640, "min_ops": 16,
        "require_parts": [
            ("滑雪板", ("滑雪板", "滑板", "ski")),
            ("履带", ("履带", "track")),
            ("车身", ("车身", "车体", "body")),
            ("座椅", ("座椅", "座位", "seat")),
            ("挡风玻璃", ("挡风", "windshield")),
            ("车把", ("车把", "把手", "handlebar")),
            ("前灯", ("前灯", "灯", "light")),
        ],
        "checks": [
            ["g_skis_two_extend", ("滑雪板", "滑板", "ski"), ("车身", "车体", "body"), 1],
            ["g_track_long_distinct", ("履带", "track"), ("车轮", "轮", "wheel"), 6],
            ["g_exposed_contrast_color", ("挡风", "windshield"), 3, ("车身", "车体", "body"), True],
        ],
    },
    {
        "id": "G08", "name": "老式手推独轮车", "subject": "手推独轮车",
        "desc": "一辆老式手推独轮车：只有单个圆形车轮架在木制轮轴上，左右成对两根长把手向后伸出，"
                "上方斗体有内腔、顶部敞开，底部两根支脚分立落地，车轮与车架轮轴相连，目标约 300 块积木",
        "complexity": "单个圆形车轮（截面近似圆）+ 左右成对把手 + 斗体内腔顶部敞开（不得填实）"
                      " + 两根分立足落地 + 车轮-轮轴-车架连接",
        "target_blocks": 300,
        # 体素下限 = 300/2 × 4 = 600；部位下限按特征清单 8；算子下限取 300/20=15。
        "min_parts": 8, "min_solid_parts": 7, "min_voxels": 600, "min_ops": 15,
        "require_parts": [
            ("车轮", ("车轮", "轮", "wheel")),
            ("轮轴", ("轮轴", "轴", "axle")),
            ("把手", ("把手", "扶手", "handle")),
            ("斗体", ("斗体", "斗", "tub")),
            ("支脚", ("支脚", "脚", "leg", "stand")),
        ],
        "checks": [
            ["g_round_wheels", ("车轮", "轮", "wheel"), 1, 1],
            ["g_paired_across_axis", ("把手", "扶手", "handle"), "x"],
            ["g_cup_open_top", ("斗体", "斗", "tub")],
            ["g_cup_cavity_min", ("斗体", "斗", "tub"), 4],
            ["g_legs_separate_min", ("支脚", "脚", "leg", "stand"), 2],
            ["g_parts_contact", ("车轮", "轮", "wheel"), ("轮轴", "轴", "axle")],
        ],
    },
    {
        "id": "G09", "name": "极简笔筒", "subject": "极简笔筒",
        "desc": "一个极简笔筒：圆角方形空心杯体，顶部完全敞开，底部封闭，里面插三支不同颜色和不同高度的笔，"
                "目标约 180 块积木",
        "complexity": "杯壁有厚度且顶部负空间贯通（顶部封死侧面有洞不算）+ 杯底封闭 + 内部空腔不得填实"
                      " + 三支笔颜色/高度可区分 + 小模型不得堆成实心大方块",
        "target_blocks": 180,
        # 体素下限 = 180/2 × 4 = 360；部位下限按特征清单 5（杯体 + 三支笔 + 底部）；算子下限取 180/20=9 的 10。
        "min_parts": 5, "min_solid_parts": 4, "min_voxels": 360, "min_ops": 10,
        "require_parts": [
            ("杯体", ("杯体", "笔筒", "杯", "cup")),
            ("笔", ("笔", "pen")),
        ],
        "checks": [
            ["g_cup_open_top", ("杯体", "笔筒", "杯", "cup")],
            ["g_cup_bottom_closed", ("杯体", "笔筒", "杯", "cup")],
            ["g_cup_cavity_min", ("杯体", "笔筒", "杯", "cup"), 4],
            ["g_pens_three_distinct", ("笔", "pen"), 3, 3],
            ["g_not_solid_block", ("杯体", "笔筒", "杯", "cup"), 0.75],
        ],
    },
    {
        "id": "G10", "name": "模糊需求小鸟", "subject": "小鸟",
        "desc": "一只小鸟",
        "complexity": "模糊需求：系统自行采用合理比例并继续（不得反复追问）；小鸟至少具备"
                      "身体/头/喙/双翼/尾巴/两腿，双翼左右成对、喙外露异色、两腿落地；不得生成无特征方块",
        "target_blocks": None,  # 原文没有「目标约 N 块积木」，模糊需求不设规模目标
        # 无目标块数：按小模型「约 60 块 × 4 体素/块 = 240 体素」作回归档参考下限；部位清单 7。
        "min_parts": 7, "min_solid_parts": 6, "min_voxels": 240, "min_ops": 12,
        "require_parts": [
            ("身体", ("身体", "躯干", "body")),
            ("头部", ("头部", "头", "head")),
            ("喙", ("喙", "嘴", "beak")),
            ("翅膀", ("翅膀", "翼", "wing")),
            ("尾巴", ("尾巴", "尾", "tail")),
            ("腿", ("腿", "leg")),
        ],
        "checks": [
            ["both_sides", ("翅膀", "翼", "wing")],
            ["g_exposed_contrast_color", ("喙", "嘴", "beak"), 2],
            ["g_legs_separate_min", ("腿", "leg"), 2],
            ["g_not_solid_block", (), 0.75],
            ["g_bird_geometry"],
        ],
    },
]


def all_g_cases():
    """G01–G10 全部案例（独立确认集单源，不与 C/H 组混放）。"""
    return list(G_CASES)


def find_g_case(case_id=None, desc=None):
    """按案例编号或需求原文查找 G 组案例；语义与 tools.e2e_cases_20.find_case 一致。

    编号大小写不敏感（先 strip 再 upper）；原文必须逐字相等；同一原文命中多个案例时
    要求显式给编号（返回 None），避免区间/初始化解析误配。
    """
    if case_id:
        cid = str(case_id).strip().upper()
        for c in G_CASES:
            if c["id"] == cid:
                return c
        return None
    if desc is not None:
        hits = [c for c in G_CASES if c["desc"] == desc]
        if len(hits) == 1:
            return hits[0]
    return None


def summary_target_from_desc(desc):
    """供审计/测试核对：从原文解析的块数目标必须与 target_blocks 冻结值一致。"""
    return parse_target_blocks(desc)


# ---------------------------------------------------------------- 主题新颖性审计
def _g_campaign_scope(root):
    """本组自己的运行产物范围：({需求原文集合}, {run_id 集合})。

    与 tools.e2e_cases_20._campaign_scope 同口径：G 组跑过之后 artifacts/ 与
    jobs_store 里会出现自己的需求与模型，审计必须把它们排除，否则自己跑过的案例
    会被自己判成「已存在」。排除只针对本组原文/run，历史基线其余部分照常审计。
    """
    import glob
    import json
    import os

    descs = {c["desc"] for c in G_CASES}
    runs = set()
    for path in glob.glob(os.path.join(root, "artifacts", "e2e-20", "**", "*.json"), recursive=True):
        try:
            with open(path, encoding="utf-8") as f:
                data = json.load(f)
        except (OSError, ValueError):
            continue
        if not isinstance(data, dict):
            continue
        # 只有明确属于 G 组原文的产物才纳入本组排除范围；E2E 目录里其他批次
        # 的 run 一律不动，否则会把历史基线的模型名误删（曾导致语料少 273 条）。
        own = data.get("desc") in descs
        own_case_runs = [str(item["runId"]) for item in (data.get("cases") or [])
                         if isinstance(item, dict) and item.get("desc") in descs and item.get("runId")]
        if not (own or own_case_runs):
            continue
        if data.get("runId"):
            runs.add(str(data["runId"]))
        runs.update(own_case_runs)
        result = data.get("result") if isinstance(data.get("result"), dict) else {}
        if result.get("run_id"):
            runs.add(str(result["run_id"]))
        for attempt in result.get("attempts_detail") or []:
            if isinstance(attempt, dict) and attempt.get("run_id"):
                runs.add(str(attempt["run_id"]))
    store = os.path.join(root, "artifacts", "jobs_store.json")
    if os.path.isfile(store):
        try:
            with open(store, encoding="utf-8") as f:
                for job in json.load(f).values():
                    if not isinstance(job, dict) or job.get("desc") not in descs:
                        continue
                    result = job.get("result") if isinstance(job.get("result"), dict) else {}
                    if result.get("run_id"):
                        runs.add(str(result["run_id"]))
                    for attempt in result.get("attempts_detail") or []:
                        if isinstance(attempt, dict) and attempt.get("run_id"):
                            runs.add(str(attempt["run_id"]))
        except (OSError, ValueError):
            pass
    # 运行记录兜底：E2E 轮次被中断时，单例 JSON 可能没写出来，但 run_<id>.json、模型与
    # 方案已经落盘（孤儿运行）。只按本组需求原文精确匹配 run 记录，把它们也纳入排除范围，
    # 否则中断的自家运行会被审计当历史语料误判撞题（2026-11-03 最终确认轮中断暴露）。
    for path in glob.glob(os.path.join(root, "artifacts", "run_*.json")):
        try:
            with open(path, encoding="utf-8") as f:
                rec = json.load(f)
        except (OSError, ValueError):
            continue
        if not isinstance(rec, dict) or rec.get("desc") not in descs:
            continue
        if rec.get("runId"):
            runs.add(str(rec["runId"]))
    return descs, runs


def _load_g_history_corpus():
    """基准语料：e2e_cases_20._load_history_corpus 同源（历史需求 + 模型名称/特征），
    再剔除本组自己的历史产物（需求原文与模型名/特征）。

    20 例的历史语料函数只排除 C 组 campaign 范围；G 组跑过之后必须自己排除自己的，
    否则审计会自我撞题。剔除按逐条字符串精确匹配，不做子串放宽。
    """
    import collections
    import glob
    import json
    import os

    from tools.e2e_cases_20 import _load_history_corpus

    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    g_descs, g_runs = _g_campaign_scope(root)
    # 公开仓没有运行产物时 _load_history_corpus 回退到 public/history-corpus.json；
    # 传入本组 G 以排除自己的案例，避免自我撞题。
    descs, names = _load_history_corpus(exclude_groups=("G",))
    descs = [d for d in descs if d not in g_descs]

    own_vals = collections.Counter()
    if g_runs:
        for path in glob.glob(os.path.join(root, "artifacts", "model_*.json")):
            try:
                with open(path, encoding="utf-8") as f:
                    model = json.load(f)
            except (OSError, ValueError):
                continue
            if not isinstance(model, dict) or str(model.get("runId")) not in g_runs:
                continue
            own_vals.update([str(model.get("name") or ""), str(model.get("slug") or "")]
                            + [str(x) for x in (model.get("features") or [])])
    filtered = []
    for n in names:
        if own_vals.get(n, 0) > 0:
            own_vals[n] -= 1
            continue
        filtered.append(n)
    return descs, filtered


def _audit_one(case, descs, names):
    """对单个案例做主题/原文撞题判定，返回冲突原因列表（与 20 例审计同口径）。"""
    conflicts = []
    if any(case["desc"] == d for d in descs):
        conflicts.append("需求原文与历史任务完全相同")
    subject = case["subject"]
    for d in descs:
        if subject and subject in d:
            conflicts.append(f"主题词「{subject}」出现在历史需求：{d[:40]}…")
            break
    for n in names:
        if subject and subject in n:
            conflicts.append(f"主题词「{subject}」出现在历史模型名称/特征：{n[:40]}")
            break
    return conflicts


def audit_g_cases(cases=None, corpus=None):
    """G 组主题新颖性审计，返回结构化报告 dict：
    {"cases": [{id,name,subject,conflicts}], "conflicts": [{id,reasons}], "ok": bool,
     "corpus": {"descs":N,"names":N}, "used_clean_baseline": bool}

    corpus 参数仅供测试注入 (descs, names)；默认取 _load_g_history_corpus()。
    历史语料为空（干净检出）时 used_clean_baseline=True 并在 cases 里照常逐例审计。
    撞题必须 ok=False 且逐条列出原因，不得改名/放宽冒充新颖。
    """
    pool = list(cases if cases is not None else G_CASES)
    descs, names = corpus if corpus is not None else _load_g_history_corpus()
    descs, names = list(descs or []), list(names or [])
    rows, conflicts = [], []
    for case in pool:
        reasons = _audit_one(case, descs, names)
        rows.append({"id": case["id"], "name": case["name"], "subject": case["subject"],
                     "conflicts": reasons})
        if reasons:
            conflicts.append({"id": case["id"], "name": case["name"], "reasons": reasons})
    return {
        "cases": rows,
        "conflicts": conflicts,
        "ok": not conflicts,
        "corpus": {"descs": len(descs), "names": len(names)},
        "used_clean_baseline": not descs and not names,
    }


def main(argv=None):
    import json
    import sys

    argv = list(sys.argv[1:] if argv is None else argv)
    if "--audit" in argv:
        report = audit_g_cases()
        if report["used_clean_baseline"]:
            print("未执行完整新颖性审计：缺少历史语料（公开仓应存在 "
                  "test/fixtures/public/history-corpus.json）。")
            return 0 if "--allow-empty" in argv else 2
        print(f"基准语料：历史需求 {report['corpus']['descs']} 条、"
              f"模型名称/特征 {report['corpus']['names']} 条\n")
        for row in report["cases"]:
            if row["conflicts"]:
                print(f"❌ {row['id']} {row['name']}：")
                for c in row["conflicts"]:
                    print("   -", c)
            else:
                print(f"✅ {row['id']} {row['name']}：主题与历史语料无冲突")
        print(f"\n共 {len(report['cases'])} 例，冲突 {len(report['conflicts'])} 例")
        return 0 if report["ok"] else 1
    if "--list" in argv:
        for c in G_CASES:
            target = c.get("target_blocks")
            tgt = f"目标≈{target:3d}块" if target else "目标:模糊需求"
            print(f"{c['id']} {c['name']:8s} {tgt} 部位≥{c['min_parts']:2d} "
                  f"体素回归参考≥{c['min_voxels']:4d}  {c['desc'][:40]}…")
        print(f"\n共 {len(G_CASES)} 例")
        return 0
    print(json.dumps([{k: c[k] for k in ("id", "name", "subject", "desc", "target_blocks")}
                      for c in G_CASES], ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    import sys
    sys.exit(main())
