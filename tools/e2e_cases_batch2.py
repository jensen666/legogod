# -*- coding: utf-8 -*-
"""第二批 20 例浏览器 E2E 的案例单源：10 个全新主题 + 10 个历史失败重跑。

设计口径：

1. 全新主题 10 例（H01–H10）必须是历史语料里从没出现过的对象。基准语料取
   `artifacts/jobs_store.json` 的历史需求与 `artifacts/model_*.json` 的模型名称/特征；
   `python -m tools.e2e_cases_batch2 --audit` 在开跑**之前**执行，用于证明没有撞题。
2. 历史失败重跑 10 例直接引用 2026-11-01 批次里两次尝试都失败的案例原文，
   编号沿用 C02/C03/C05/C06/C07/C10/C11/C13/C14/C16，不复制描述，避免两套原文漂移。
3. 每例都带「结果正确性」断言（require_parts + checks + 复杂度下限），由
   tools/e2e_assert_20.py 执行；checks 只引用已注册检查，且不新增 slope_min。
4. 颜色只用零件库 16 色，无透明材质、无文字、无超长无支撑悬臂。

字段约定与 tools/e2e_cases_20.py 相同：
  id/name/subject/desc、complexity、min_parts/min_solid_parts/min_voxels/min_ops、
  require_parts、checks。
"""
from __future__ import annotations

# 2026-11-01 批次里两次尝试均失败、如实记为 failed 的 10 例。
# 编号对应 tools/e2e_cases_20.CASES 的原定义（原文单源，不在这里复制）。
HIST_FAILED_IDS = ["C02", "C03", "C05", "C06", "C07", "C10", "C11", "C13", "C14", "C16"]

NEW_CASES = [
    {
        "id": "H01", "name": "埃菲尔铁塔", "subject": "埃菲尔铁塔",
        "desc": "一座埃菲尔铁塔：深棕色锻铁结构，四根向外张开的斜腿立在浅灰色石砌基础上，"
                "四条腿在底部围出贯通的大拱门，向上逐渐收拢汇合，塔身中部和上部各有一层方形观景平台，"
                "平台四周有栏杆，塔身由交叉横梁与斜撑桁架连接成镂空结构，顶部是尖塔与天线，目标约 380 块积木",
        "complexity": "四腿张开+底部贯通大拱门 + 逐层收分汇合 + 两层平台栏杆 + 交叉桁架 + 顶部尖塔",
        "min_parts": 8, "min_solid_parts": 6, "min_voxels": 1200, "min_ops": 20,
        "require_parts": [
            ("石砌基础", ("基础", "基座", "base")),
            ("斜腿", ("斜腿", "腿", "leg")),
            ("大拱门", ("拱门", "拱", "arch")),
            ("观景平台", ("平台", "platform", "deck")),
            ("栏杆", ("栏杆", "rail")),
            ("桁架", ("桁架", "truss", "bracing")),
            ("尖塔", ("尖塔", "尖顶", "spire")),
        ],
        "checks": [["ground_components_min", 4],
                   ["part_box_count_min", ("斜腿", "腿", "leg"), 4],
                   ["enclosed_interior_min", 1],
                   ["layers_min", 10],
                   ["op_count_min", 20]],
    },
    {
        "id": "H02", "name": "悉尼歌剧院", "subject": "悉尼歌剧院",
        "desc": "一座悉尼歌剧院：浅灰色宽阔基座，基座正面有大台阶，基座上是三组层叠的白色贝壳形屋顶，"
                "每组屋顶由多片向上翘起的壳片层叠而成，壳片用斜面砖收出弧形轮廓，"
                "屋顶下方露出深灰色玻璃幕墙（幕墙为表面涂装），屋顶前缘有连续拱形门廊，"
                "基座右侧有广场平台与栏杆，目标约 360 块积木",
        "complexity": "三组层叠贝壳屋顶 + 弧形壳片斜面 + 幕墙表面涂装 + 大台阶 + 拱形门廊 + 广场栏杆",
        # min_parts 8→7：需求原文点名 7 组特征——宽阔基座、大台阶、三组贝壳形屋顶、
        # 深灰色玻璃幕墙（surface 涂装）、连续拱形门廊、广场平台、栏杆；没有第 8 组。
        # min_solid_parts 复核后维持 6：7 组里幕墙是 surface，其余 6 组均为立体特征；
        # 广场平台与栏杆是两组独立需求（都点名了），不能靠合并成一个部位凑数。
        "min_parts": 7, "min_solid_parts": 6, "min_voxels": 1400, "min_ops": 20,
        "require_parts": [
            ("基座", ("基座", "底座", "base")),
            ("贝壳屋顶", ("贝壳", "壳", "shell", "roof")),
            ("玻璃幕墙", ("幕墙", "玻璃", "curtain")),
            ("台阶", ("台阶", "step")),
            ("门廊", ("门廊", "廊", "porch")),
            ("广场平台", ("广场", "平台", "plaza")),
            ("栏杆", ("栏杆", "rail")),
        ],
        # 圆柱算子改为结果几何：屋顶区域必须有斜面砖且各层截面尺寸有弧形/层叠收分档位。
        "checks": [["part_box_count_min", ("贝壳", "壳", "shell"), 3],
                   ["curved_roof_profile", ("贝壳", "壳", "shell", "roof"), 8, 3],
                   ["surface_parts_min", 1],
                   ["layers_min", 8],
                   ["colors_distinct_min", 2]],
    },
    {
        "id": "H03", "name": "自由女神像", "subject": "自由女神像",
        "desc": "一座自由女神像：方形浅灰色石基座，基座上方是深灰色多层台座，台座上是绿色铜像，"
                "铜像身穿垂坠长袍、右臂高举火炬、左臂抱书板，头戴七道尖芒冠冕，冠冕尖芒向外辐射，"
                "长袍下摆向两侧展开形成稳定轮廓，火炬火焰为表面涂装的金黄色，目标约 340 块积木",
        "complexity": "石基座+多层台座 + 绿色长袍主体 + 高举火炬 + 七道尖芒冠冕 + 书板 + 火炬表面涂装",
        "min_parts": 8, "min_solid_parts": 6, "min_voxels": 1200, "min_ops": 18,
        "require_parts": [
            ("石基座", ("基座", "底座", "base")),
            ("台座", ("台座", "pedestal")),
            ("长袍", ("长袍", "袍", "robe")),
            ("火炬", ("火炬", "torch")),
            ("冠冕", ("冠冕", "冠", "crown")),
            ("书板", ("书板", "书", "tablet")),
            ("手臂", ("手臂", "臂", "arm")),
        ],
        # 「高举火炬」用姿态几何检查：火炬整体必须高于手臂最高层（替代无意义的轴向跨度）。
        "checks": [["layers_min", 10],
                   ["part_raised_above", ("火炬", "torch"), ("手臂", "臂", "arm"), 1],
                   ["surface_parts_min", 1],
                   ["colors_distinct_min", 3],
                   ["parts_min", 8]],
    },
    {
        "id": "H04", "name": "中国石狮子", "subject": "石狮子",
        "desc": "一座蹲坐的中国石狮子：浅灰色整石雕成，下方是方形石底座，狮子后腿蹲坐、前腿直立撑地，"
                "前胸挺起，头部鬃毛卷曲成多个圆球环绕，双目圆睁、张口露牙，左前爪搭着一颗绣球，"
                "右侧爪下按着一只小石狮，尾巴贴背向上卷起，目标约 320 块积木",
        "complexity": "蹲坐体态 + 卷曲鬃毛成组圆球 + 绣球与小石狮两个子件 + 前后腿分立 + 尾巴上卷",
        "min_parts": 8, "min_solid_parts": 6, "min_voxels": 1100, "min_ops": 16,
        "require_parts": [
            ("石底座", ("底座", "base")),
            ("鬃毛", ("鬃毛", "鬃", "mane")),
            ("绣球", ("绣球", "球", "ball")),
            # 需求点名「前爪搭着绣球」：爪可并入前腿部位建模，故与前爪同一关键词组；
            # 是否真的搭在绣球上用 parts_adjacent_min 做体素 6-邻接判定。
            ("前腿/前爪", ("前腿", "前爪", "leg", "paw")),
            ("小石狮", ("小石狮", "小狮", "cub")),
            ("尾巴", ("尾巴", "尾", "tail")),
            ("头部", ("头部", "头", "head")),
        ],
        "checks": [["layers_min", 8],
                   ["part_box_count_min", ("鬃毛", "鬃", "mane"), 2],
                   ["parts_adjacent_min", ("前腿", "前爪", "leg", "paw"), ("绣球", "球", "ball"), 2],
                   ["colors_distinct_min", 2],
                   ["op_count_min", 16],
                   ["parts_min", 8]],
    },
    {
        "id": "H05", "name": "白天鹅", "subject": "白天鹅",
        "desc": "一只浮在水面上的白天鹅：白色身体呈船形，长颈向上弯成 S 形，头小、喙为橙色，"
                "两翼半张开向上抬起，翼尖用斜面砖收出羽毛轮廓，尾部短而上翘，"
                "下方是蓝色水面平板，水面比身体略大，目标约 260 块积木",
        "complexity": "S 形长颈 + 半张双翼斜面羽毛 + 橙色喙 + 上翘尾 + 蓝色水面底座",
        "min_parts": 7, "min_solid_parts": 5, "min_voxels": 900, "min_ops": 14,
        "require_parts": [
            ("身体", ("身体", "body")),
            ("长颈", ("长颈", "颈", "neck")),
            ("头部", ("头", "head")),
            ("喙", ("喙", "beak")),
            ("翅膀", ("翅膀", "翼", "wing")),
            ("尾巴", ("尾巴", "尾", "tail")),
            ("水面", ("水面", "水", "water")),
        ],
        # 长颈：结果几何检查 S 形弯曲（竖向长度 + 侧向偏移 + 至少一次方向反转），
        # 代替「长颈跨度」与「圆柱算子」两项实现方式断言。
        "checks": [["layers_min", 5],
                   ["s_curve_min", ("长颈", "颈", "neck"), 4, 1.0, 1],
                   ["colors_distinct_min", 3],
                   ["parts_min", 7]],
    },
    {
        "id": "H06", "name": "大象", "subject": "大象",
        "desc": "一头站立的大象：浅灰色厚重身体，四条粗壮圆腿落地，两只大耳朵向两侧展开，"
                "长鼻向下弯曲、鼻端向上卷起，两根米白色象牙向前伸出，头顶有深灰色眼睛，"
                "背部略隆起，尾部短小下垂，目标约 300 块积木",
        "complexity": "四条粗腿 + 双耳对称展开 + 下弯长鼻与卷起鼻端 + 前伸象牙 + 厚重身体",
        "min_parts": 7, "min_solid_parts": 5, "min_voxels": 1000, "min_ops": 16,
        "require_parts": [
            ("身体", ("身体", "body")),
            ("象鼻", ("象鼻", "鼻", "trunk")),
            ("象牙", ("象牙", "牙", "tusk")),
            ("耳朵", ("耳朵", "耳", "ear")),
            ("腿", ("腿", "leg")),
            ("尾巴", ("尾巴", "尾", "tail")),
        ],
        "checks": [["part_box_count_min", ("腿", "leg"), 4],
                   ["both_sides", ("耳朵", "耳", "ear")],
                   ["layers_min", 6],
                   ["cylinder_ops_min", 2],
                   ["parts_min", 7]],
    },
    {
        "id": "H07", "name": "常规动力潜水艇", "subject": "潜水艇",
        "desc": "一艘常规动力潜水艇：深灰色长圆柱形艇体，前部圆钝、尾部收细，艇体上方有流线型指挥塔，"
                "指挥塔顶伸出潜望镜与天线，艇体后部两侧有水平舵，尾部有十字形舵面与螺旋桨，"
                "艇体底部有压载龙骨，艇体两侧有一排圆形舷窗（舷窗为表面涂装），目标约 320 块积木",
        "complexity": "长圆柱艇体 + 流线型指挥塔与潜望镜 + 尾部十字舵与螺旋桨 + 底部龙骨 + 舷窗表面涂装",
        "min_parts": 7, "min_solid_parts": 5, "min_voxels": 1000, "min_ops": 16,
        "require_parts": [
            ("艇体", ("艇体", "hull", "body")),
            ("指挥塔", ("指挥塔", "塔", "conning")),
            ("潜望镜", ("潜望镜", "潜望", "periscope")),
            ("螺旋桨", ("螺旋桨", "桨", "propeller")),
            ("舵面", ("舵", "rudder")),
            ("舷窗", ("舷窗", "窗", "porthole")),
            ("龙骨", ("龙骨", "keel")),
        ],
        # 艇体横卧：单一长条部位用水平轴 "xz" 的最大跨度（即艇体长度；不是组合体，
        # 不存在拿机翼横向宽度冒充纵向长度的问题）；圆截面由 layers 结果几何另查。
        "checks": [["part_span_min", ("艇体", "hull"), 12, "xz"],
                   ["cylinder_ops_min", 2],
                   ["surface_parts_min", 1],
                   ["layers_min", 6],
                   ["op_count_min", 16]],
    },
    {
        "id": "H08", "name": "游乐摩天轮", "subject": "摩天轮",
        "desc": "一座游乐摩天轮：深灰色长方体基座，基座上立两根 A 字形支架，支架顶部架起水平轮轴，"
                "轮轴外侧是大圆环轮辐，圆环上均匀挂着六个彩色吊舱，轮辐与圆环之间用交叉细梁连接，"
                "吊舱是深棕色舱体配白色顶盖，基座旁有电机房与小台阶，目标约 380 块积木",
        "complexity": "A 字支架 + 水平轮轴 + 大圆环轮辐与交叉细梁 + 六个彩色吊舱 + 电机房与台阶",
        "min_parts": 8, "min_solid_parts": 6, "min_voxels": 1400, "min_ops": 20,
        "require_parts": [
            ("A 字形支架", ("支架", "架", "支撑", "support")),
            ("轮轴", ("轮轴", "轴", "axle")),
            ("轮辐", ("轮辐", "辐", "spoke")),
            ("吊舱", ("吊舱", "舱", "gondola")),
            ("基座", ("基座", "底座", "base")),
            ("电机房", ("电机房", "机房", "motor")),
            ("台阶", ("台阶", "step")),
        ],
        # 大圆环轮辐：结果几何检查环向全周覆盖 + 近似同一半径 + 中心不填实
        # （替代「必须有 2 个 cylinder 算子」的实现方式断言）。
        "checks": [["circular_ring_min", ("圆环", "轮辐", "outer_wheel"), 8, 0.35],
                   ["part_box_count_min", ("吊舱", "舱", "gondola"), 6],
                   ["layers_min", 10],
                   ["colors_distinct_min", 3],
                   ["parts_min", 8]],
    },
    {
        "id": "H09", "name": "复古双反照相机", "subject": "双反照相机",
        "desc": "一台复古双反照相机：黑色方正机身，正面上下两个圆形镜头，上层是取景镜头、下层是成像镜头，"
                "镜筒用圆柱凸出机身、镜头周围有浅灰色环圈，机身顶部是深棕色翻盖取景器，打开呈竖直状，"
                "机身侧面有调焦旋钮，底部有三脚架接口与黑色皮饰，机身正面有品牌铭牌（铭牌为表面涂装），"
                "目标约 280 块积木",
        "complexity": "双镜头圆柱凸出 + 浅灰环圈 + 翻盖取景器 + 调焦旋钮 + 皮饰与铭牌表面涂装",
        "min_parts": 7, "min_solid_parts": 5, "min_voxels": 900, "min_ops": 14,
        "require_parts": [
            ("机身", ("机身", "body")),
            ("镜头", ("镜头", "镜", "lens")),
            ("取景器", ("取景器", "取景", "viewfinder")),
            ("旋钮", ("旋钮", "knob", "dial")),
            ("铭牌", ("铭牌", "plaque")),
        ],
        "checks": [["cylinder_ops_min", 2],
                   ["surface_parts_min", 1],
                   ["layers_min", 7],
                   ["colors_distinct_min", 3],
                   ["parts_min", 7]],
    },
    {
        "id": "H10", "name": "航天飞机组合体", "subject": "航天飞机",
        "desc": "一架航天飞机组合体：中央是米白色圆柱形外储箱，两侧各挂一枚白色固体助推器，"
                "前方是白色轨道器，轨道器有圆钝机头、后掠三角机翼、垂直尾翼和尾部三台发动机，"
                "机翼边缘有黑色隔热瓦，腹部为黑色隔热分区（为表面涂装），"
                "组合体立在深灰色发射台底座上，目标约 400 块积木",
        "complexity": "外储箱+双助推器成对 + 轨道器后掠机翼与尾翼 + 三台发动机 + 隔热瓦表面涂装 + 发射台",
        "min_parts": 9, "min_solid_parts": 7, "min_voxels": 1600, "min_ops": 22,
        "require_parts": [
            ("外储箱", ("外储箱", "储箱", "tank")),
            ("固体助推器", ("助推器", "booster")),
            ("轨道器", ("轨道器", "轨道", "orbiter")),
            ("机翼", ("机翼", "翼", "wing")),
            ("尾翼", ("尾翼", "尾", "tail")),
            ("发动机", ("发动机", "engine")),
            ("发射台", ("发射台", "台", "pad")),
        ],
        # 轨道器是组合体：纵向轴 = y（组合体竖直立在发射台上，机头 y=9..10 在最高处、
        # 发动机/尾部 y=2..5 在底部；x 是机翼横向、z 是前后厚度）。旧断言 max(x,z) 只有 4，
        # 是把「机身转向后的横向宽度」当成长度，属于误报。
        #   1) orbiter ∪ 机头 ∪ 机翼 的并集在 y 轴纵向跨度 ≥8，且显式减去外储箱/助推器；
        #   2) orbiter 本体最小体量：≥40 体素（目标 400 块的 1/10，四个主结构之一）且本体
        #      体量 ≥ 本体∪机头∪机翼 的 50%（细节不能比本体还大 → 拒绝「小球挂大翼」）；
        #   3) 机头、机翼与本体体素 6-邻接（真实搭接，不是贴图/悬空）。
        "checks": [["both_sides", ("助推器", "booster")],
                   ["part_union_span_min",
                    ("轨道器", "orbiter", "机头", "nose", "机翼", "wing"),
                    ("外储箱", "储箱", "tank", "助推器", "booster"), "y", 8],
                   ["part_min_volume", ("轨道器", "orbiter"), 40,
                    ("机头", "nose", "机翼", "wing"), 0.5],
                   ["parts_adjacent_min", ("机头", "nose"), ("轨道器", "orbiter"), 2],
                   ["parts_adjacent_min", ("机翼", "wing"), ("轨道器", "orbiter"), 2],
                   ["surface_parts_min", 1],
                   ["layers_min", 10],
                   ["op_count_min", 22]],
    },
]


def hist_failed_cases():
    """历史失败重跑案例：引用 20 例注册表里的原定义，不复制描述。"""
    from tools.e2e_cases_20 import find_case
    out = []
    for cid in HIST_FAILED_IDS:
        case = find_case(cid)
        if case is None:
            raise SystemExit(f"历史失败案例 {cid} 不在 tools/e2e_cases_20.CASES 里")
        out.append(case)
    return out


def batch_cases():
    """本批 20 例：先 10 个全新主题，再 10 个历史失败重跑。"""
    return list(NEW_CASES) + hist_failed_cases()


def audit_history_corpus(corpus=None):
    """开跑前的撞题审计：返回 [(case, [冲突...]), ...]。

    基准语料优先读 artifacts/ 里**已经存在**的历史需求与模型名称/特征（私有数据根）；
    公开仓没有运行产物时回退到 `test/fixtures/public/history-corpus.json`
    （由已发布源码冻结案例生成，排除本批 B 组自己的条目）。两者都没有时返回 None，
    调用方必须报告「未执行完整审计」，不能把空语料当作审计通过。

    corpus 参数仅供测试/审计注入 (descs, names)。
    """
    import glob
    import json
    import os

    if corpus is not None:
        descs, names = list(corpus[0] or []), list(corpus[1] or [])
    else:
        root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        descs, names = [], []
        store = os.path.join(root, "artifacts", "jobs_store.json")
        if os.path.isfile(store):
            try:
                with open(store, encoding="utf-8") as f:
                    for job in json.load(f).values():
                        if isinstance(job, dict) and job.get("desc"):
                            descs.append(str(job["desc"]))
            except (OSError, ValueError):
                pass
        for path in glob.glob(os.path.join(root, "artifacts", "model_*.json")):
            try:
                with open(path, encoding="utf-8") as f:
                    model = json.load(f)
                if isinstance(model, dict):
                    names.extend([str(model.get("name") or ""), str(model.get("slug") or "")]
                                 + [str(x) for x in (model.get("features") or [])])
            except (OSError, ValueError):
                pass
        if not descs and not names:
            from tools.e2e_cases_20 import _load_public_history_corpus
            public = _load_public_history_corpus(exclude_groups=("B",))
            if public is not None:
                descs, names = list(public[0]), list(public[1])
    if not descs and not names:
        return None
    report = []
    for case in NEW_CASES:
        conflicts = []
        subject = case["subject"]
        if case["desc"] in descs:
            conflicts.append("需求原文与历史任务完全相同")
        for d in descs:
            if subject in d:
                conflicts.append(f"主题词「{subject}」出现在历史需求：{d[:40]}…")
                break
        for n in names:
            if subject and subject in n:
                conflicts.append(f"主题词「{subject}」出现在历史模型名称/特征：{n[:40]}")
                break
        report.append((case, conflicts))
    return report


def main(argv=None):
    import json
    import sys

    argv = list(sys.argv[1:] if argv is None else argv)
    if "--audit" in argv:
        report = audit_history_corpus()
        if report is None:
            print("未执行完整撞题审计：缺少历史语料（公开仓应存在 "
                  "test/fixtures/public/history-corpus.json）。")
            return 0 if "--allow-empty" in argv else 2
        bad = 0
        for case, conflicts in report:
            if conflicts:
                bad += 1
                print(f"❌ {case['id']} {case['name']}：")
                for c in conflicts:
                    print("   -", c)
            else:
                print(f"✅ {case['id']} {case['name']}：主题与历史语料无冲突")
        print(f"\n共 {len(report)} 例全新主题，冲突 {bad} 例")
        return 1 if bad else 0
    if "--list" in argv:
        for c in batch_cases():
            print(f"{c['id']} {c['name']:10s} 部位≥{c['min_parts']:2d} 体素≥{c['min_voxels']:4d} "
                  f"算子≥{c['min_ops']:2d}  {c['desc'][:42]}…")
        print(f"\n共 {len(batch_cases())} 例（10 全新 + 10 历史失败重跑）")
        return 0
    print(json.dumps([{k: c[k] for k in ("id", "name", "subject", "desc")}
                      for c in NEW_CASES], ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    import sys
    sys.exit(main())
