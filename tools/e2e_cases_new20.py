# -*- coding: utf-8 -*-
"""新 20 例复杂案例 N01–N20 的案例单源（真实浏览器 E2E 加压集）。

背景与口径（与 G01–G10 独立确认集同一套验收语义）：
  1. 主题由 Lead 用本地历史语料（历史需求 + 模型名称/特征 + C/H/G 案例池）扫描后冻结：
     20 个主题词在历史语料与案例池中 0 命中；audit 仍必须 0 冲突，不允许把旧题改名冒充新颖。
  2. 每例以「目标约 N 块积木」为规模目标，验收 bricks_ratio = 实际零件数/目标块数，
     统一容差 >= 0.5 才算达标（N_TARGET_TOLERANCE，「中位 ≥50%」的逐例口径）。
  3. 复杂度两层：需求达标档（部位/特征/目标块数，硬失败）+ 当前能力回归档
     （体素/层数/颜色等，只记录不判失败，见 tools/e2e_assert_new20.py）。
  4. 体素下限按 G 组口径：min_voxels = (target_blocks / 2) * 4 = 2 * target_blocks（回归档参考）；
     min_ops 只作回归档参考（不设强制算子数量），取 target//20 的保守值。
  5. 每例在 stress 里标 1–3 个压力类别（harness 加压维度），并在 historical_failure_hint
     写明针对的历史失败现象，避免「没有针对性」的泛化案例。

字段约定（与 tools/e2e_cases_g.py 完全相同）：
  id/name/subject/desc、complexity、stress、historical_failure_hint、
  target_blocks/min_parts/min_solid_parts/min_voxels/min_ops、
  require_parts（[(部位名, (关键词...)), ...]）、checks（[[检查名, 参数...], ...]）。

需求原文（desc）纪律：必须是可直接提交 Web 工坊的真实用户输入（中文一段话，8–12 个
可辨识部位/特征 + 至少两类结构特征），结尾逐字包含「目标约 N 块积木」；不使用透明件、
文字/水印、超过网格容量（24×24×14、5800 体素）的规模或不可实现的细节。

新颖性审计：
  python -m tools.e2e_cases_new20 --audit
  基准语料复用 tools.e2e_cases_20._load_history_corpus（历史需求 + 模型名称/特征），
  并额外对 C/H/G 案例池做主题/原文核对；本组自己跑过的需求与产物按 _n_campaign_scope
  口径排除，防止跑完后自我撞题。
"""
from __future__ import annotations

from legogod.plan_scale import parse_target_blocks as _parse_target_blocks

# 统一规模容差：bricks_ratio >= 0.5 才算「目标块数达标」（中位 ≥50% 的逐例口径）
N_TARGET_TOLERANCE = 0.5

# harness 允许的压力类别（stress 字段只能从这里取，便于工具按压力维度分组统计）
STRESS_CATEGORIES = (
    "suspension", "thin_parts", "support", "disconnected", "coverage", "scale",
    "gate", "visual", "arch_negative_space", "paired_symmetry", "curved",
)


def parse_target_blocks(desc):
    """从需求原文解析目标块数 N（单源：legogod.plan_scale.parse_target_blocks）。

    与生产口径完全一致：同时接受「目标 N 块」与「目标约 N 块」；
    没有该句返回 None（N 组全部有目标块数）。
    """
    return _parse_target_blocks(desc)


N_CASES = [
    {
        # 400 = 2×200 体素回归参考；10 个需求特征 → 部位下限 10；算子参考 20。
        "id": "N01", "name": "孔雀开屏", "subject": "孔雀",
        "desc": "拼一只开屏的孔雀：小巧的头部上方立着一排冠羽，短喙和两侧眼睛清晰，"
                "蓝绿色的身体前低后高，身体两侧收着成对翅膀，身后立起一片半圆形展开的尾屏，"
                "尾屏由多层羽片和异色羽眼组成，双腿分立落地，脚爪抓地，目标约 400 块积木",
        "complexity": "半圆扇形尾屏（多层羽片径向展开）+ 异色羽眼外露 + 成对翅膀 + 双腿分立落地",
        "stress": ["support", "thin_parts", "gate"],
        "historical_failure_hint": "悬挑/细长类：历史 C02/C13/C14 硬失败，大面积薄尾屏最易在支撑预检与"
                                   "部位突显门禁被拒（2026-11-03 G 组内容断言 0/10）",
        "target_blocks": 400,
        "min_parts": 10, "min_solid_parts": 9, "min_voxels": 800, "min_ops": 20,
        "require_parts": [
            ("头部", ("头部", "头", "head")),
            ("冠羽", ("冠羽", "冠", "crest")),
            ("喙", ("喙", "嘴", "beak")),
            ("眼睛", ("眼睛", "眼", "eye")),
            ("身体", ("身体", "躯干", "body")),
            ("翅膀", ("翅膀", "翼", "wing")),
            ("尾屏", ("尾屏", "尾羽", "尾", "tail", "fan")),
            ("羽眼", ("羽眼", "眼斑", "羽片", "feather")),
            ("双腿", ("腿", "脚爪", "爪", "leg")),
        ],
        "checks": [
            ["g_fan_tail", ("尾屏", "尾羽", "尾", "tail", "fan"), 90, 5],
            ["both_sides", ("翅膀", "翼", "wing")],
            ["g_part_clusters_min", ("腿", "脚爪", "爪", "leg"), 2],
            ["g_grounded_min", ("腿", "脚爪", "爪", "leg")],
            ["g_exposed_contrast_color", ("羽眼", "眼斑", "羽片", "feather"), 2,
             ("身体", "躯干", "body"), True],
            ["g_not_solid_block", (), 0.75],
            ["colors_distinct_min", 4],
            ["layers_min", 5],
        ],
    },
    {
        "id": "N02", "name": "蝴蝶", "subject": "蝴蝶",
        "desc": "拼一只展翅的蝴蝶：细长的身体分成头、胸、腹三节，头顶两根细触角向外弯曲，"
                "复眼用异色小点，左右各有一片上翅和一片下翅，四片翅膀成对地平展着向两侧伸出，"
                "翅膀上有异色斑纹，六条细腿收在身体下方，目标约 260 块积木",
        "complexity": "四片真实翅膀左右成对（上翅/下翅分列）+ 细长三段身体比例 + 触角成对 + 异色复眼/斑纹",
        "stress": ["paired_symmetry", "thin_parts", "gate"],
        "historical_failure_hint": "成对/薄片类：历史 H04 成对前肢被合并、双翼类贴花被门禁拒；"
                                   "G 组内容断言 0/10",
        "target_blocks": 260,
        "min_parts": 8, "min_solid_parts": 7, "min_voxels": 520, "min_ops": 13,
        "require_parts": [
            ("身体", ("身体", "躯干", "body")),
            ("头部", ("头部", "头", "head")),
            ("胸部", ("胸部", "胸", "thorax")),
            ("腹部", ("腹部", "腹", "abdomen")),
            ("触角", ("触角", "触须", "antenna")),
            ("复眼", ("复眼", "眼", "eye")),
            ("上翅", ("上翅", "前翅", "forewing", "upper")),
            ("下翅", ("下翅", "后翅", "hindwing", "lower")),
            ("翅膀", ("翅膀", "翼", "wing")),
            ("腿", ("腿", "足", "leg")),
        ],
        "checks": [
            ["g_wings_four_paired", ("翅膀", "翼", "wing"), 2, 3],
            ["both_sides", ("触角", "触须", "antenna")],
            ["g_part_clusters_min", ("腿", "足", "leg"), 6],
            ["g_exposed_contrast_color", ("复眼", "眼", "eye"), 2],
            ["g_part_ratio_diff", ("腹部", "腹", "abdomen"), ("胸部", "胸", "thorax"), 1.2],
            ["g_not_solid_block", (), 0.75],
            ["colors_distinct_min", 3],
            ["layers_min", 4],
        ],
    },
    {
        "id": "N03", "name": "章鱼", "subject": "章鱼",
        "desc": "拼一只张开触手的章鱼：圆鼓鼓的外套膜身体呈曲面，头顶有喷水孔，正前方一对突出的"
                "眼睛和一张小嘴，身体下方伸出八条向不同方向弯垂的触手，触手根部粗、末端收细，"
                "每条触手内侧有两排异色吸盘，目标约 340 块积木",
        "complexity": "八条触手向多方位弯垂（根部粗末端收细）+ 圆鼓外套膜多截面轮廓 + 异色吸盘外露",
        "stress": ["curved", "thin_parts", "disconnected"],
        "historical_failure_hint": "分体断连/细长类：历史 C02/C06/C16 断连硬失败，八条触手常被合并成"
                                   "一块或互相断开（G 组内容断言 0/10）",
        "target_blocks": 340,
        "min_parts": 8, "min_solid_parts": 7, "min_voxels": 680, "min_ops": 17,
        "require_parts": [
            ("外套膜", ("外套膜", "头部", "mantle")),
            ("喷水孔", ("喷水孔", "喷水", "siphon")),
            ("眼睛", ("眼睛", "眼", "eye")),
            ("嘴", ("嘴", "喙", "口", "beak", "mouth")),
            ("触手", ("触手", "腕", "tentacle")),
            ("触手末端", ("末端", "尖端", "tentacle_tip", "tip")),
            ("吸盘", ("吸盘", "sucker")),
        ],
        "checks": [
            ["g_tentacle_directions", ("触手", "腕", "tentacle"), 4, 2],
            ["g_part_clusters_min", ("触手", "腕", "tentacle"), 4],
            ["g_exposed_contrast_color", ("吸盘", "sucker"), 4,
             ("外套膜", "头部", "mantle"), False],
            ["g_sphere_profile", ("外套膜", "头部", "mantle")],
            ["g_not_solid_block", (), 0.8],
            ["colors_distinct_min", 3],
        ],
    },
    {
        "id": "N04", "name": "螃蟹", "subject": "螃蟹",
        "desc": "拼一只横着走的螃蟹：宽扁的深红色头胸甲两端各伸出一只大螯，螯上带一排锯齿，"
                "头胸甲前端两根眼柄顶着外凸的眼睛，下方左右各四条步足共八条，"
                "步足分节并向两侧斜撑，腹部收在下方，目标约 300 块积木",
        "complexity": "左右成对大螯 + 八条分节步足向两侧斜撑落地 + 宽扁甲壳横向展开 + 眼柄外凸",
        "stress": ["paired_symmetry", "support", "gate"],
        "historical_failure_hint": "成对/支撑类：历史 H04/C03 成对前肢与斜撑支撑失败，八足与大螯在"
                                   "部位绑定时易合并（G 组内容断言 0/10）",
        "target_blocks": 300,
        "min_parts": 8, "min_solid_parts": 7, "min_voxels": 600, "min_ops": 15,
        "require_parts": [
            ("头胸甲", ("头胸甲", "甲壳", "壳", "carapace", "shell")),
            ("大螯", ("大螯", "螯", "钳", "claw")),
            ("眼睛", ("眼睛", "眼", "eye")),
            ("眼柄", ("眼柄", "柄", "stalk")),
            ("步足", ("步足", "腿", "足", "leg")),
            ("腹部", ("腹部", "腹", "abdomen")),
        ],
        "checks": [
            ["g_paired_across_axis", ("大螯", "螯", "钳", "claw"), "x"],
            ["g_legs_separate_min", ("步足", "腿", "足", "leg"), 6],
            ["both_sides", ("大螯", "螯", "钳", "claw")],
            ["g_exposed_contrast_color", ("眼睛", "眼", "eye"), 2],
            ["part_span_min", ("头胸甲", "甲壳", "壳", "carapace", "shell"), 8, "x"],
            ["g_not_solid_block", (), 0.8],
            ["layers_min", 3],
        ],
    },
    {
        "id": "N05", "name": "鹦鹉", "subject": "鹦鹉",
        "desc": "拼一只站在横枝上的彩色鹦鹉：圆头、向下弯曲的钩状喙、两侧外凸的眼睛，"
                "头顶一撮竖起的冠羽，身体两侧收着成对翅膀，身后垂下渐长的尾羽，"
                "两只爪子抓在横枝上，横枝由一根立柱托起，目标约 280 块积木",
        "complexity": "垂长尾羽真实长度 + 成对翅膀收拢 + 钩状喙异色外露 + 双爪抓枝/横枝悬挑在立柱上",
        "stress": ["thin_parts", "support", "gate"],
        "historical_failure_hint": "细长/悬挑类：历史 C02/C13/C14 硬失败，垂长尾羽与横枝在支撑预检中"
                                   "最易断连（G 组内容断言 0/10）",
        "target_blocks": 280,
        "min_parts": 9, "min_solid_parts": 8, "min_voxels": 560, "min_ops": 14,
        "require_parts": [
            ("头部", ("头部", "头", "head")),
            ("喙", ("喙", "嘴", "beak")),
            ("眼睛", ("眼睛", "眼", "eye")),
            ("冠羽", ("冠羽", "冠", "crest")),
            ("身体", ("身体", "躯干", "body")),
            ("翅膀", ("翅膀", "翼", "wing")),
            ("尾羽", ("尾羽", "尾", "tail")),
            ("爪子", ("爪子", "爪", "脚", "claw")),
            ("横枝", ("横枝", "树枝", "枝", "branch", "perch")),
            ("立柱", ("立柱", "柱", "支架", "pole", "post")),
        ],
        "checks": [
            ["part_span_min", ("尾羽", "尾", "tail"), 5, "y"],
            ["both_sides", ("翅膀", "翼", "wing")],
            ["g_exposed_contrast_color", ("喙", "嘴", "beak"), 2,
             ("身体", "躯干", "body")],
            ["g_parts_contact", ("爪子", "爪", "脚", "claw"), ("横枝", "树枝", "枝", "branch", "perch")],
            ["g_parts_contact", ("横枝", "树枝", "枝", "branch", "perch"),
             ("立柱", "柱", "支架", "pole", "post")],
            ["g_part_clusters_min", ("爪子", "爪", "脚", "claw"), 2],
            ["g_grounded_min", ("立柱", "柱", "支架", "pole", "post")],
            ["g_not_solid_block", (), 0.75],
            ["colors_distinct_min", 4],
        ],
    },
    {
        "id": "N06", "name": "海马", "subject": "海马",
        "desc": "拼一只海马：头顶有冠状突起，管状长吻向前伸出，两侧眼睛外凸，"
                "背部有一排扇形背鳍，身体前侧有胸鳍，腹部下方鼓起育袋，"
                "长尾向后卷成螺旋，尾巴末端逐渐收细，目标约 250 块积木",
        "complexity": "长尾卷成螺旋（S 形/回卷结果几何）+ 扇形背鳍 + 管状长吻收细 + 育袋鼓出",
        "stress": ["curved", "thin_parts", "disconnected"],
        "historical_failure_hint": "弧面/细长类：历史 H05 天鹅长颈的 S 形内容断言未过；卷尾最易被"
                                   "简化成直块（2026-11-03 G 组内容断言 0/10）",
        "target_blocks": 250,
        "min_parts": 8, "min_solid_parts": 7, "min_voxels": 500, "min_ops": 12,
        "require_parts": [
            ("冠", ("冠", "头顶", "突起", "crest")),
            ("长吻", ("长吻", "吻", "嘴", "snout")),
            ("眼睛", ("眼睛", "眼", "eye")),
            ("背鳍", ("背鳍", "鳍", "fin")),
            ("胸鳍", ("胸鳍", "胸", "pectoral")),
            ("身体", ("身体", "躯干", "body")),
            ("育袋", ("育袋", "袋", "pouch")),
            ("卷尾", ("卷尾", "尾", "tail")),
        ],
        "checks": [
            ["s_curve_min", ("卷尾", "尾", "tail"), 4, 1.5, 1],
            ["part_span_min", ("身体", "躯干", "body"), 5, "y"],
            ["g_parts_contact", ("卷尾", "尾", "tail"), ("身体", "躯干", "body")],
            ["g_exposed_contrast_color", ("眼睛", "眼", "eye"), 2],
            ["part_span_min", ("长吻", "吻", "嘴", "snout"), 4, "xz"],
            ["g_not_solid_block", (), 0.75],
            ["colors_distinct_min", 3],
        ],
    },
    {
        "id": "N07", "name": "蝎子", "subject": "蝎子",
        "desc": "拼一只举着尾刺的蝎子：扁平的头胸甲前端一对大螯成对张开，螯上带齿，"
                "头胸甲上方两只小眼睛，身体两侧各伸出四条步足共八条，"
                "后方五节分节的腹部向后延伸，腹部末端的细尾向上高高翘起，尾尖有一根毒刺，"
                "目标约 320 块积木",
        "complexity": "高翘尾节/毒刺真实悬空（高出头胸甲）+ 左右成对大螯 + 八条分立步足 + 五节腹部",
        "stress": ["paired_symmetry", "support", "gate"],
        "historical_failure_hint": "成对/悬空类：历史 H04/C03 成对前肢与悬空尾部失败；高翘尾刺需要"
                                   "真实悬空支撑（G 组内容断言 0/10）",
        "target_blocks": 320,
        "min_parts": 9, "min_solid_parts": 8, "min_voxels": 640, "min_ops": 16,
        "require_parts": [
            ("头胸甲", ("头胸甲", "甲壳", "壳", "carapace", "shell")),
            ("大螯", ("大螯", "螯", "钳", "claw")),
            ("眼睛", ("眼睛", "眼", "eye")),
            ("步足", ("步足", "腿", "足", "leg")),
            ("腹部", ("腹部", "腹", "abdomen")),
            ("尾巴", ("尾巴", "尾", "tail")),
            ("毒刺", ("毒刺", "尾刺", "刺", "stinger")),
        ],
        "checks": [
            ["g_paired_across_axis", ("大螯", "螯", "钳", "claw"), "x"],
            ["g_legs_separate_min", ("步足", "腿", "足", "leg"), 6],
            ["part_raised_above", ("毒刺", "尾刺", "刺", "stinger"),
             ("头胸甲", "甲壳", "壳", "body"), 1],            ["g_parts_contact", ("大螯", "螯", "钳", "claw"),
             ("头胸甲", "甲壳", "壳", "carapace", "shell")],
            ["g_exposed_contrast_color", ("眼睛", "眼", "eye"), 2],
            ["g_not_solid_block", (), 0.8],
            ["layers_min", 4],
        ],
    },
    {
        "id": "N08", "name": "飞马", "subject": "飞马",
        "desc": "拼一只展翅的飞马：马头高昂，颈背有一排鬃毛，前胸宽厚，"
                "背上一对宽大的白色翅膀向左右两侧上方展开，翅膀上有多层羽片，"
                "四条腿前后分开站立，前腿直立、后腿略弯，蹄子落地，尾巴向后飘起，"
                "目标约 380 块积木",
        "complexity": "成对宽翼向斜上方大跨度悬挑 + 多层羽片 + 四条腿前后分立落地 + 长颈抬头",
        "stress": ["support", "thin_parts", "paired_symmetry"],
        "historical_failure_hint": "悬空悬挑/成对类：历史 H01/C06/C16 硬失败，展开双翼属大跨度悬挑，"
                                   "支撑与门禁两处最易拒（G 组内容断言 0/10）",
        "target_blocks": 380,
        "min_parts": 10, "min_solid_parts": 9, "min_voxels": 760, "min_ops": 19,
        "require_parts": [
            ("马头", ("马头", "头部", "头", "head")),
            ("鬃毛", ("鬃毛", "鬃", "mane")),
            ("前胸", ("前胸", "胸", "chest")),
            ("身体", ("身体", "躯干", "body")),
            ("翅膀", ("翅膀", "翼", "wing")),
            ("羽片", ("羽片", "羽毛", "feather")),
            ("腿", ("腿", "leg")),
            ("马蹄", ("马蹄", "蹄", "hoof")),
            ("尾巴", ("尾巴", "尾", "tail")),
        ],
        "checks": [
            ["both_sides", ("翅膀", "翼", "wing")],
            ["g_part_clusters_min", ("翅膀", "翼", "wing"), 2],
            ["part_span_min", ("翅膀", "翼", "wing"), 8, "x"],
            ["g_legs_separate_min", ("腿", "leg"), 4],
            ["g_neck_raise", ("马头", "头部", "头", "颈", "head", "neck"),
             ("身体", "躯干", "body"), 4, 2],
            ["g_parts_contact", ("翅膀", "翼", "wing"), ("身体", "躯干", "body")],
            ["part_span_min", ("身体", "躯干", "body"), 6, "x"],
            ["g_not_solid_block", (), 0.75],
            ["colors_distinct_min", 2],
        ],
    },
    {
        "id": "N09", "name": "帕特农神庙", "subject": "帕特农神庙",
        "desc": "拼一座帕特农神庙：三层递收的石台基，正面一排八根带凹槽的立柱，柱顶托着额枋，"
                "上方是三角形山花和双坡屋顶，屋顶两端留有三角形空隙，中间是内殿和正门，"
                "正门是两侧立柱之间的贯通门洞，左右两侧也有柱廊，目标约 440 块积木",
        "complexity": "八柱柱廊真实分立 + 门洞贯通负空间 + 双坡屋顶斜面与山花 + 三层递收台基",
        "stress": ["arch_negative_space", "coverage", "gate"],
        "historical_failure_hint": "拱洞负空间/铺砖覆盖类：历史 C07 门洞通过但整例仍失败；覆盖失败 5 例"
                                   "（support_column 预算耗尽，2026-11-03 报告）",
        "target_blocks": 440,
        "min_parts": 10, "min_solid_parts": 9, "min_voxels": 880, "min_ops": 22,
        "require_parts": [
            ("台基", ("台基", "台阶", "基座", "base", "step")),
            ("立柱", ("立柱", "柱", "column")),
            ("额枋", ("额枋", "横梁", "architrave", "beam")),
            ("山花", ("山花", "pediment")),
            ("屋顶", ("屋顶", "屋面", "roof")),
            ("内殿", ("内殿", "内室", "cella")),
            ("正门", ("正门", "门洞", "门", "door", "gate")),
            ("侧柱廊", ("柱廊", "侧廊", "colonnade")),
        ],
        "checks": [
            ["negative_space_passage", ("正门", "门洞", "门", "door", "gate"), "z", 3, 1],
            ["layer_components_min", 6],
            ["eave_slope_overhang", ("屋顶", "山花", "roof", "pediment"),
             ("立柱", "柱", "column"), 1, 4, 1],
            ["tiered_min", 3],
            ["g_grounded_min", ("台基", "台阶", "基座", "base", "step")],
            ["g_parts_contact", ("立柱", "柱", "column"),
             ("台基", "台阶", "基座", "base", "step")],
            ["g_parts_contact", ("额枋", "横梁", "architrave", "beam"), ("立柱", "柱", "column")],
            ["colors_distinct_min", 2],
            ["g_not_solid_block", (), 0.85],
        ],
    },
    {
        "id": "N10", "name": "泰姬陵", "subject": "泰姬陵",
        "desc": "拼一座泰姬陵：白色大理石主体中央是巨大的洋葱形穹顶，穹顶呈曲面向上收分，"
                "穹顶下方是鼓座，四角各立一座圆柱形宣礼塔，正面中央是一个高大的拱门，"
                "两侧各有两个小拱龛，主体两侧展开成对的侧翼，前方有一条长水池，"
                "底部有方形台基，目标约 430 块积木",
        "complexity": "洋葱穹顶弧面收分 + 中央拱门负空间 + 四角宣礼塔分立 + 成对侧翼 + 长水池",
        "stress": ["curved", "arch_negative_space", "coverage"],
        "historical_failure_hint": "弧面/拱洞负空间类：历史 H02 穹顶与 C07 门洞内容断言通过但整例失败于"
                                   "覆盖与规模（G 组内容断言 0/10）",
        "target_blocks": 430,
        "min_parts": 10, "min_solid_parts": 9, "min_voxels": 860, "min_ops": 21,
        "require_parts": [
            ("穹顶", ("穹顶", "洋葱", "圆顶", "dome")),
            ("鼓座", ("鼓座", "鼓形", "鼓", "drum")),
            ("宣礼塔", ("宣礼塔", "尖塔", "塔", "minaret", "tower")),
            ("拱门", ("拱门", "门洞", "拱", "arch", "gate")),
            ("拱龛", ("拱龛", "壁龛", "龛", "niche")),
            ("侧翼", ("侧翼", "翼", "wing")),
            ("水池", ("水池", "池", "pool")),
            ("台基", ("台基", "基座", "base")),
        ],
        "checks": [
            ["g_curved_taper_body", ("穹顶", "洋葱", "圆顶", "dome")],
            ["negative_space_passage", ("拱门", "门洞", "拱", "arch", "gate"), "z", 3, 1],
            ["g_part_clusters_min", ("宣礼塔", "尖塔", "塔", "minaret", "tower"), 4],
            ["both_sides", ("宣礼塔", "尖塔", "塔", "minaret", "tower")],
            ["g_parts_contact", ("穹顶", "洋葱", "圆顶", "dome"), ("鼓座", "鼓形", "鼓", "drum")],
            ["g_parts_contact", ("鼓座", "鼓形", "鼓", "drum"), ("主体", "body", "建筑")],
            ["g_grounded_min", ("台基", "基座", "base")],
            ["tiered_min", 3],
            ["colors_distinct_min", 2],
            ["g_not_solid_block", (), 0.85],
        ],
    },
    {
        "id": "N11", "name": "圣瓦西里大教堂", "subject": "圣瓦西里大教堂",
        "desc": "拼一座圣瓦西里大教堂：中央一座高高的帐篷形尖顶，周围环绕多座不同颜色的曲面"
                "洋葱形穹顶，穹顶向上收分，每座穹顶下都有圆柱形鼓座和方形塔身，"
                "塔身之间用拱廊连接，底部是宽大的基座，外墙有红白相间的条纹，"
                "顶部的十字架指向天空，目标约 420 块积木",
        "complexity": "多个不同颜色洋葱穹顶（弧面收分）+ 帐篷尖顶 + 鼓座/塔身分层 + 拱廊连接 + 多色分区",
        "stress": ["curved", "scale", "gate"],
        "historical_failure_hint": "弧面/规模类：历史 H02 曲面屋顶内容断言通过但整例未达；多塔规模使"
                                   "实际/目标零件数中位仅 27% < 50%",
        "target_blocks": 420,
        "min_parts": 10, "min_solid_parts": 9, "min_voxels": 840, "min_ops": 21,
        "require_parts": [
            ("帐篷顶", ("帐篷顶", "帐篷", "尖顶", "tent", "spire")),
            ("洋葱穹顶", ("洋葱", "穹顶", "圆顶", "dome")),
            ("鼓座", ("鼓座", "鼓形", "鼓", "drum")),
            ("塔身", ("塔身", "塔楼", "塔", "tower")),
            ("拱廊", ("拱廊", "拱", "廊", "arcade")),
            ("基座", ("基座", "底座", "base")),
            ("十字架", ("十字架", "十字", "cross")),
        ],
        "checks": [
            ["g_curved_taper_body", ("洋葱", "穹顶", "圆顶", "dome")],
            ["colors_distinct_min", 5],
            ["g_parts_contact", ("洋葱", "穹顶", "圆顶", "dome"), ("鼓座", "鼓形", "鼓", "drum")],
            ["g_parts_contact", ("鼓座", "鼓形", "鼓", "drum"), ("塔身", "塔楼", "塔", "tower")],
            ["g_grounded_min", ("基座", "底座", "base")],
            ["tiered_min", 3],
            ["g_part_clusters_min", ("洋葱", "穹顶", "圆顶", "dome"), 3],
            ["g_not_solid_block", (), 0.8],
        ],
    },
    {
        "id": "N12", "name": "悬索桥", "subject": "悬索桥",
        "desc": "拼一座跨江悬索桥：左右两岸各有一座高桥塔，两座桥塔之间横跨两条主缆，"
                "主缆在跨中明显下垂成弧线，主缆上用一排竖直吊索吊住下方平直的桥面，"
                "桥面两端各有锚碇，桥面上有成对栏杆，桥塔顶部有横梁，目标约 410 块积木",
        "complexity": "主缆跨中真实下垂弧线 + 一排吊索吊住桥面（悬吊关系）+ 双塔成对 + 桥面长跨",
        "stress": ["suspension", "thin_parts", "support"],
        "historical_failure_hint": "悬吊/悬空类：历史 H01/C06/C16 硬失败（悬吊快照多数不可评估），"
                                   "主缆垂度与吊索最易退化成直线或贴死桥面",
        "target_blocks": 410,
        "min_parts": 9, "min_solid_parts": 8, "min_voxels": 820, "min_ops": 20,
        "require_parts": [
            ("桥塔", ("桥塔", "塔", "tower", "pylon")),
            ("主缆", ("主缆", "悬索", "缆", "cable")),
            ("吊索", ("吊索", "吊杆", "竖索", "hanger", "suspender")),
            ("桥面", ("桥面", "桥板", "面", "deck")),
            ("锚碇", ("锚碇", "锚", "anchor")),
            ("栏杆", ("栏杆", "扶手", "rail")),
            ("横梁", ("横梁", "横撑", "crossbeam")),
        ],
        "checks": [
            ["g_suspension_sag", ("主缆", "悬索", "缆", "cable"), 2,
             ("吊索", "吊杆", "竖索", "hanger", "suspender"), 2],
            ["part_span_min", ("桥面", "桥板", "deck"), 12, "x"],
            ["g_legs_separate_min", ("桥塔", "塔", "tower", "pylon"), 2],
            ["g_parts_contact", ("主缆", "悬索", "缆", "cable"), ("桥塔", "塔", "tower", "pylon")],
            ["g_parts_contact", ("吊索", "吊杆", "竖索", "hanger", "suspender"),
             ("桥面", "桥板", "deck")],
            ["both_sides", ("桥塔", "塔", "tower", "pylon")],
            ["g_parts_contact", ("栏杆", "扶手", "rail"), ("桥面", "桥板", "deck")],
            ["g_not_solid_block", (), 0.8],
        ],
    },
    {
        "id": "N13", "name": "比萨斜塔", "subject": "比萨斜塔",
        "desc": "拼一座比萨斜塔：底部是圆形基座，上方一圈圈带立柱的环形柱廊逐层收分，"
                "塔身整体明显向一侧倾斜，顶部是直径较小的钟亭，钟亭里有成对铜钟，"
                "底层开门洞，柱廊之间是真实镂空的环形走廊，目标约 390 块积木",
        "complexity": "塔轴逐层同向偏移（倾斜结果几何）+ 环形柱廊真实镂空 + 逐层收分 + 底层门洞",
        "stress": ["curved", "coverage", "arch_negative_space"],
        "historical_failure_hint": "弧面/铺砖覆盖类：历史 H08/C11 圆环内容断言通过但整例失败；"
                                   "倾斜塔身逐层错位最易在覆盖与支撑预检失败",
        "target_blocks": 390,
        "min_parts": 9, "min_solid_parts": 8, "min_voxels": 780, "min_ops": 19,
        "require_parts": [
            ("基座", ("基座", "底座", "base")),
            ("柱廊", ("柱廊", "廊", "colonnade")),
            ("立柱", ("立柱", "柱", "column")),
            ("钟亭", ("钟亭", "钟楼", "belfry")),
            ("铜钟", ("铜钟", "钟", "bell")),
            ("门洞", ("门洞", "门", "door")),
            ("塔身", ("塔身", "塔体", "塔", "tower")),
        ],
        "checks": [
            ["g_leaning_tower", ("塔身", "塔体", "塔", "tower"), 3, 5, 0.12],
            ["tiered_min", 3],
            ["g_grounded_min", ("基座", "底座", "base")],
            ["negative_space_passage", ("门洞", "门", "door"), "z", 2, 1],
            ["g_parts_contact", ("柱廊", "廊", "colonnade"), ("塔身", "塔体", "塔", "tower")],
            ["g_parts_contact", ("钟亭", "钟楼", "belfry"), ("塔身", "塔体", "塔", "tower")],
            ["enclosed_interior_min", 2],
            ["colors_distinct_min", 2],
            ["g_not_solid_block", (), 0.8],
        ],
    },
    {
        "id": "N14", "name": "旋转木马", "subject": "旋转木马",
        "desc": "拼一座旋转木马：圆形转盘底座，中央一根高立柱撑起圆锥形顶棚，"
                "顶棚边缘垂下成排彩色灯泡，转盘上分布四匹木马，木马前后错落并上下起伏，"
                "木马两侧有金色立柱穿过，底座四周有台阶，顶棚下悬挂一圈成对的吊灯，"
                "目标约 360 块积木",
        "complexity": "圆锥顶棚悬挑在中心立柱上 + 四匹木马环绕分布 + 悬挂吊灯成对 + 圆柱底座",
        "stress": ["curved", "suspension", "coverage"],
        "historical_failure_hint": "悬吊/弧面类：历史 H01/C06 悬吊与 H08 圆环均曾交付但内容断言未过；"
                                   "顶棚悬挑与吊灯吊挂最易被打回",
        "target_blocks": 360,
        "min_parts": 9, "min_solid_parts": 8, "min_voxels": 720, "min_ops": 18,
        "require_parts": [
            ("转盘", ("转盘", "底盘", "圆盘", "platform")),
            ("中心立柱", ("中心立柱", "立柱", "中心柱", "柱", "pole")),
            ("顶棚", ("顶棚", "顶盖", "棚", "canopy")),
            ("木马", ("木马", "马", "horse")),
            ("台阶", ("台阶", "梯", "step")),
            ("灯泡", ("灯泡", "灯", "light")),
            ("吊灯", ("吊灯", "灯笼", "lantern")),
        ],
        "checks": [
            ["part_span_min", ("中心立柱", "中心柱", "柱", "pole"), 6, "y"],
            ["g_parts_contact", ("顶棚", "顶盖", "棚", "canopy"), ("中心立柱", "中心柱", "柱", "pole")],
            ["g_part_clusters_min", ("木马", "马", "horse"), 4],
            ["both_sides", ("木马", "马", "horse")],
            ["g_grounded_min", ("转盘", "底盘", "圆盘", "platform")],
            ["colors_distinct_min", 5],
            ["g_parts_contact", ("中心立柱", "中心柱", "柱", "pole"),
             ("转盘", "底盘", "圆盘", "platform")],
            ["g_not_solid_block", (), 0.8],
        ],
    },
    {
        "id": "N15", "name": "双翼飞机", "subject": "双翼飞机",
        "desc": "拼一架老式双翼飞机：细长机身前端是旋转的螺旋桨，机头有圆形发动机罩，"
                "机身上下两层机翼平行展开，上下机翼之间用成对支柱连接，机翼两侧有张线，"
                "尾部有垂直尾翼和水平尾翼，机腹下方起落架带两个圆形轮子，机身中部有敞开的驾驶舱，"
                "目标约 350 块积木",
        "complexity": "上下双翼分层悬挑 + 成对支柱/张线连接 + 圆形轮子起落架 + 垂直/水平尾翼",
        "stress": ["paired_symmetry", "thin_parts", "support"],
        "historical_failure_hint": "成对/细长类：历史 C02/C14 硬失败，双层机翼与成对支柱易被合并、"
                                   "支撑不足（G 组内容断言 0/10）",
        "target_blocks": 350,
        "min_parts": 10, "min_solid_parts": 9, "min_voxels": 700, "min_ops": 17,
        "require_parts": [
            ("机身", ("机身", "机体", "fuselage", "body")),
            ("螺旋桨", ("螺旋桨", "桨", "propeller", "prop")),
            ("发动机罩", ("发动机罩", "机头", "罩", "engine", "cowling")),
            ("上翼", ("上翼", "上层机翼", "upper")),
            ("下翼", ("下翼", "下层机翼", "lower")),
            ("机翼", ("机翼", "翼", "wing")),
            ("支柱", ("支柱", "撑杆", "strut")),
            ("垂直尾翼", ("垂尾", "垂直尾翼", "vertical")),
            ("水平尾翼", ("平尾", "水平尾翼", "horizontal")),
            ("起落架", ("起落架", "起落", "gear", "landing")),
            ("轮子", ("轮子", "轮", "wheel")),
        ],
        "checks": [
            ["part_span_min", ("机翼", "翼", "wing"), 8, "x"],
            ["part_raised_above", ("上翼", "上层机翼", "upper"), ("下翼", "下层机翼", "lower"), 1],
            ["g_parts_contact", ("支柱", "撑杆", "strut"), ("机翼", "翼", "wing")],
            ["g_round_wheels", ("轮子", "轮", "wheel"), 2, 3],
            ["g_part_clusters_min", ("支柱", "撑杆", "strut"), 2],
            ["g_parts_contact", ("机翼", "翼", "wing"), ("机身", "机体", "fuselage", "body")],
            ["g_parts_contact", ("起落架", "起落", "gear", "landing"),
             ("机身", "机体", "fuselage", "body")],
            ["g_not_solid_block", (), 0.8],
            ["layers_min", 4],
        ],
    },
    {
        "id": "N16", "name": "农场拖拉机", "subject": "农场拖拉机",
        "desc": "拼一辆农场拖拉机：车头有发动机罩和格栅，罩子后面是敞开的驾驶座和方向盘，"
                "两侧伸出一对成对的后视镜，排气管从发动机罩上方竖起，车尾有牵引挂钩，"
                "后轮是两个巨大的花纹轮，前轮是两个小转向轮，挡泥板悬挑着盖住后轮上半圈，"
                "目标约 330 块积木",
        "complexity": "后轮大/前轮小的轮径比 + 成对后视镜 + 排气管竖出 + 挡泥板悬挑盖住后轮",
        "stress": ["scale", "paired_symmetry", "gate"],
        "historical_failure_hint": "成对/规模类：历史 H07/C03 车辆轮组失败；后大前小的轮径关系最易被"
                                   "做成一样大（G 组内容断言 0/10、目标比中位 27%）",
        "target_blocks": 330,
        "min_parts": 9, "min_solid_parts": 8, "min_voxels": 660, "min_ops": 16,
        "require_parts": [
            ("发动机罩", ("发动机罩", "机罩", "罩", "hood")),
            ("驾驶座", ("驾驶座", "座椅", "座位", "seat")),
            ("方向盘", ("方向盘", "方向", "steering")),
            ("排气管", ("排气管", "排气", "管", "exhaust")),
            ("牵引挂钩", ("牵引挂钩", "挂钩", "牵引", "hitch")),
            ("后轮", ("后轮", "大轮", "rear")),
            ("前轮", ("前轮", "小轮", "front")),
            ("挡泥板", ("挡泥板", "挡泥", "fender")),
            ("后视镜", ("后视镜", "镜子", "mirror")),
        ],
        "checks": [
            ["g_wheel_size_ratio", ("后轮", "大轮", "rear"), ("前轮", "小轮", "front"), 1.4],
            ["g_round_wheels", ("车轮", "轮", "wheel"), 4],
            ["both_sides", ("后视镜", "镜子", "mirror")],
            ["g_parts_contact", ("挡泥板", "挡泥", "fender"), ("后轮", "大轮", "rear")],
            ["part_span_min", ("排气管", "排气", "管", "exhaust"), 3, "y"],
            ["g_parts_contact", ("排气管", "排气", "管", "exhaust"),
             ("发动机罩", "机罩", "罩", "hood")],
            ["g_grounded_min", ("后轮", "大轮", "rear")],
            ["g_grounded_min", ("前轮", "小轮", "front")],
            ["g_not_solid_block", (), 0.8],
        ],
    },
    {
        "id": "N17", "name": "塔式起重机", "subject": "塔式起重机",
        "desc": "拼一座塔式起重机：方形格构塔身从底座向上立起，塔顶有回转平台和司机室，"
                "回转平台上伸出长长的水平起重臂向外悬挑，另一侧伸出平衡臂，"
                "平衡臂末端挂着配重块，起重臂上用吊索悬挂吊钩，塔身侧面有一架爬梯，"
                "底部是混凝土底座，目标约 310 块积木",
        "complexity": "长起重臂大悬挑 + 反向平衡臂/配重 + 吊索吊钩合法悬吊 + 格构塔身 + 爬梯梯级",
        "stress": ["suspension", "support", "thin_parts"],
        "historical_failure_hint": "悬吊/悬挑类：历史 H01/C06/C16 硬失败；长悬臂加吊钩悬吊是历史失败"
                                   "重灾区（悬吊快照多不可评估、锁扣不足）",
        "target_blocks": 310,
        "min_parts": 10, "min_solid_parts": 9, "min_voxels": 620, "min_ops": 15,
        "require_parts": [
            ("塔身", ("塔身", "塔体", "格构", "mast")),
            ("底座", ("底座", "基座", "base")),
            ("回转平台", ("回转平台", "回转", "平台", "platform")),
            ("司机室", ("司机室", "驾驶室", "cab")),
            ("起重臂", ("起重臂", "主臂", "jib", "boom")),
            ("平衡臂", ("平衡臂", "平衡", "counter")),
            ("配重", ("配重", "counterweight")),
            ("吊索", ("吊索", "吊绳", "缆", "sling", "cable")),
            ("吊钩", ("吊钩", "钩", "hook")),
            ("爬梯", ("爬梯", "梯", "ladder")),
        ],
        "checks": [
            ["part_span_min", ("起重臂", "主臂", "jib", "boom"), 8, "x"],
            ["g_opposite_side", ("配重", "counterweight"), ("起重臂", "主臂", "jib", "boom"), 2],
            ["g_suspension_hanging", ("吊钩", "钩", "hook"),
             ("吊索", "吊绳", "缆", "sling", "cable"), 2],
            ["g_ladder_rungs", ("爬梯", "梯", "ladder"), 2],
            ["g_parts_contact", ("吊索", "吊绳", "缆", "sling", "cable"),
             ("起重臂", "主臂", "jib", "boom")],
            ["g_parts_contact", ("起重臂", "主臂", "jib", "boom"),
             ("回转平台", "回转", "平台", "platform")],
            ["g_grounded_min", ("底座", "基座", "base")],
            ["g_parts_contact", ("塔身", "塔体", "格构", "mast"), ("底座", "基座", "base")],
            ["g_not_solid_block", (), 0.8],
        ],
    },
    {
        "id": "N18", "name": "月球车", "subject": "月球车",
        "desc": "拼一辆月球车：舱体是带斜面的金属车身，顶部铺着一块倾斜的太阳能板，"
                "车身四周伸出成对的六只圆形车轮，车轮带花纹，车头有桅杆上的相机，"
                "桅杆顶端还有一根细天线，车身前方有可折叠的机械臂，车尾有散热板，"
                "目标约 290 块积木",
        "complexity": "六只成对圆形车轮 + 斜面车身/倾斜太阳能板 + 桅杆天线竖出 + 机械臂悬挑",
        "stress": ["coverage", "paired_symmetry", "support"],
        "historical_failure_hint": "覆盖/支撑类：历史 C03/C13 覆盖与悬挑失败；六轮成对与机械臂易被简化，"
                                   "斜面太阳能板易被判贴花（G 组内容断言 0/10）",
        "target_blocks": 290,
        "min_parts": 9, "min_solid_parts": 8, "min_voxels": 580, "min_ops": 14,
        "require_parts": [
            ("舱体", ("舱体", "车身", "body")),
            ("太阳能板", ("太阳能板", "太阳翼", "板", "panel")),
            ("车轮", ("车轮", "轮", "wheel")),
            ("相机", ("相机", "摄像", "camera")),
            ("桅杆", ("桅杆", "杆", "mast")),
            ("天线", ("天线", "antenna")),
            ("机械臂", ("机械臂", "机械", "臂", "arm")),
            ("散热板", ("散热板", "散热", "radiator")),
        ],
        "checks": [
            ["g_round_wheels", ("车轮", "轮", "wheel"), 6, 6],
            ["part_span_min", ("太阳能板", "太阳翼", "板", "panel"), 6, "xz"],
            ["g_parts_contact", ("太阳能板", "太阳翼", "板", "panel"), ("舱体", "车身", "body")],
            ["g_parts_contact", ("机械臂", "机械", "臂", "arm"), ("舱体", "车身", "body")],
            ["part_span_min", ("桅杆", "杆", "mast"), 3, "y"],
            ["g_exposed_contrast_color", ("相机", "摄像", "camera"), 1],
            ["both_sides", ("车轮", "轮", "wheel")],
            ["g_not_solid_block", (), 0.8],
        ],
    },
    {
        "id": "N19", "name": "管风琴", "subject": "管风琴",
        "desc": "拼一台管风琴：木制琴体立在地面上，正面排列多根高低不同的银色音管，"
                "音管中间高两侧低形成多层收分，音管下方是键盘和黑白琴键，"
                "琴体两侧有成对的装饰立柱，底部有踏板，琴体背面有气箱，顶部有雕花冠饰，"
                "目标约 270 块积木",
        "complexity": "多根竖立音管（每根竖向连续细长）+ 高低叠落多层收分 + 黑白琴键异色 + 两侧成对装饰柱",
        "stress": ["thin_parts", "coverage", "visual"],
        "historical_failure_hint": "细长/视觉类：历史 C02/C13 细长部件硬失败，高保真成功 0/30；"
                                   "整排细管在铺砖与渲染评审中易塌成墙板",
        "target_blocks": 270,
        "min_parts": 8, "min_solid_parts": 7, "min_voxels": 540, "min_ops": 13,
        "require_parts": [
            ("琴体", ("琴体", "琴箱", "箱体", "case")),
            ("音管", ("音管", "管", "pipe")),
            ("键盘", ("键盘", "琴键", "键", "key", "keyboard")),
            ("踏板", ("踏板", "pedal")),
            ("气箱", ("气箱", "风箱", "箱", "bellows")),
            ("装饰立柱", ("装饰立柱", "装饰柱", "立柱", "柱", "column")),
            ("冠饰", ("冠饰", "雕花", "顶饰", "crest")),
        ],
        "checks": [
            ["g_strings_vertical_min", ("音管", "管", "pipe"), 8],
            ["tiered_min", 3],
            ["g_grounded_min", ("琴体", "琴箱", "箱体", "case")],
            ["g_parts_contact", ("键盘", "琴键", "键", "key", "keyboard"),
             ("琴体", "琴箱", "箱体", "case")],
            ["colors_distinct_min", 3],
            ["g_exposed_contrast_color", ("琴键", "键盘", "key", "keyboard"), 2,
             ("琴体", "琴箱", "箱体", "case")],
            ["g_not_solid_block", (), 0.8],
            ["layers_min", 6],
        ],
    },
    {
        "id": "N20", "name": "热气球", "subject": "热气球",
        "desc": "拼一只热气球：上方是鼓鼓的彩色气囊，气囊表面有纵向彩色条纹，"
                "气囊底部收口处有燃烧器，燃烧器下方用四根吊绳悬挂住方形吊篮，"
                "吊篮侧面有花纹，吊篮四角包边，气囊底部与吊篮之间留出空隙，吊篮落在地面，"
                "目标约 240 块积木",
        "complexity": "气囊多截面弧面轮廓 + 气囊在吊篮上方真实空隙 + 四根吊绳连接吊篮 + 纵向条纹分色",
        "stress": ["curved", "suspension", "visual"],
        "historical_failure_hint": "悬吊/弧面类：历史 H01/C06/C16 硬失败加 H02 曲面；气囊-吊篮上下"
                                   "关系与吊绳连接最易失效（G 组内容断言 0/10）",
        "target_blocks": 240,
        "min_parts": 8, "min_solid_parts": 7, "min_voxels": 480, "min_ops": 12,
        "require_parts": [
            ("气囊", ("气囊", "球囊", "气球", "envelope", "balloon")),
            ("条纹", ("条纹", "彩条", "stripe")),
            ("燃烧器", ("燃烧器", "喷嘴", "火焰", "burner")),
            ("吊绳", ("吊绳", "绳索", "绳", "rope")),
            ("吊篮", ("吊篮", "篮子", "篮", "basket")),
            ("包边", ("包边", "护角", "边", "corner")),
        ],
        "checks": [
            ["g_balloon_basket", ("气囊", "球囊", "气球", "envelope", "balloon"),
             ("吊篮", "篮子", "篮", "basket"), ("吊绳", "绳索", "绳", "rope"), 1],
            ["g_sphere_profile", ("气囊", "球囊", "气球", "envelope", "balloon")],
            ["g_grounded_min", ("吊篮", "篮子", "篮", "basket")],
            ["g_parts_contact", ("吊绳", "绳索", "绳", "rope"), ("吊篮", "篮子", "篮", "basket")],
            ["g_parts_contact", ("吊绳", "绳索", "绳", "rope"),
             ("气囊", "球囊", "气球", "envelope", "balloon")],
            ["colors_distinct_min", 4],
            ["g_not_solid_block", (), 0.8],
        ],
    },
]


def all_n_cases():
    """N01–N20 全部案例（新 20 例加压集单源，不与 C/H/G 组混放）。"""
    return list(N_CASES)


def find_n_case(case_id=None, desc=None):
    """按案例编号或需求原文查找 N 组案例；语义与 tools.e2e_cases_g.find_g_case 一致。

    编号大小写不敏感（先 strip 再 upper）；原文必须逐字相等；同一原文命中多个案例时
    要求显式给编号（返回 None），避免区间/初始化解析误配。
    """
    if case_id:
        cid = str(case_id).strip().upper()
        for c in N_CASES:
            if c["id"] == cid:
                return c
        return None
    if desc is not None:
        hits = [c for c in N_CASES if c["desc"] == desc]
        if len(hits) == 1:
            return hits[0]
    return None


def summary_target_from_desc(desc):
    """供审计/测试核对：从原文解析的块数目标必须与 target_blocks 冻结值一致。"""
    return parse_target_blocks(desc)


# ---------------------------------------------------------------- 主题新颖性审计
def _n_campaign_scope(root):
    """本组自己的运行产物范围：({需求原文集合}, {run_id 集合})。

    与 tools.e2e_cases_g._g_campaign_scope 同口径：N 组跑过之后 artifacts/ 与
    jobs_store 里会出现自己的需求与模型，审计必须把它们排除，否则自己跑过的案例
    会被自己判成「已存在」。排除只针对本组原文/run，历史基线其余部分照常审计。
    """
    import glob
    import json
    import os

    descs = {c["desc"] for c in N_CASES}
    runs = set()
    for path in glob.glob(os.path.join(root, "artifacts", "e2e-20", "**", "*.json"), recursive=True):
        try:
            with open(path, encoding="utf-8") as f:
                data = json.load(f)
        except (OSError, ValueError):
            continue
        if not isinstance(data, dict):
            continue
        # 只有明确属于 N 组原文的产物才纳入本组排除范围；E2E 目录里其他批次
        # 的 run 一律不动，否则会把历史基线的模型名误删。
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
    # 方案已经落盘（孤儿运行）。只按本组需求原文精确匹配 run 记录，把它们也纳入排除范围。
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


def _load_n_history_corpus():
    """基准语料：e2e_cases_20._load_history_corpus 同源（历史需求 + 模型名称/特征），
    再剔除本组自己的历史产物（需求原文与模型名/特征），避免跑完后自我撞题。"""
    import collections
    import glob
    import json
    import os

    from tools.e2e_cases_20 import _load_history_corpus

    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    n_descs, n_runs = _n_campaign_scope(root)
    # 公开仓没有运行产物时 _load_history_corpus 回退到 public/history-corpus.json；
    # 传入本组 N 以排除自己的案例，避免自我撞题。
    descs, names = _load_history_corpus(exclude_groups=("N",))
    descs = [d for d in descs if d not in n_descs]

    own_vals = collections.Counter()
    if n_runs:
        for path in glob.glob(os.path.join(root, "artifacts", "model_*.json")):
            try:
                with open(path, encoding="utf-8") as f:
                    model = json.load(f)
            except (OSError, ValueError):
                continue
            if not isinstance(model, dict) or str(model.get("runId")) not in n_runs:
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


def _case_pool_entries():
    """C/H/G 既有案例池（主题词/原文）——历史语料之外的第二道新颖性基线。"""
    from tools.e2e_cases_20 import all_cases as all_ch_cases
    from tools.e2e_cases_g import G_CASES

    entries = []
    for case in all_ch_cases():
        entries.append({"source": "C/H案例池", "id": case.get("id"),
                        "subject": case.get("subject") or "", "desc": case.get("desc") or ""})
    for case in G_CASES:
        entries.append({"source": "G案例池", "id": case.get("id"),
                        "subject": case.get("subject") or "", "desc": case.get("desc") or ""})
    return entries


def _audit_one(case, descs, names):
    """对单个案例做主题/原文撞题判定，返回冲突原因列表（与 G 组审计同口径）。"""
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


def _audit_pool(case, pools):
    """与 C/H/G 既有案例池比对：原文完全相同或主题词出现在池内需求/主题都算撞题。"""
    conflicts = []
    subject = case["subject"]
    for entry in pools:
        if case["desc"] == entry["desc"]:
            conflicts.append(f"需求原文与{entry['source']}案例 {entry['id']} 完全相同")
            continue
        if subject and subject in (entry["desc"] or ""):
            conflicts.append(f"主题词「{subject}」出现在{entry['source']}案例 {entry['id']} 的需求")
        elif subject and subject == (entry["subject"] or ""):
            conflicts.append(f"主题与{entry['source']}案例 {entry['id']} 完全相同")
    return conflicts


def audit_n_cases(cases=None, corpus=None, check_case_pools=True, pools=None):
    """N 组主题新颖性审计，返回结构化报告 dict：
    {"cases": [{id,name,subject,conflicts}], "conflicts": [{id,name,reasons}], "ok": bool,
     "corpus": {"descs":N,"names":N}, "pools": {"count":N}, "used_clean_baseline": bool}

    corpus 参数仅供测试注入 (descs, names)；默认取 _load_n_history_corpus()。
    历史语料为空（干净检出）时 used_clean_baseline=True 并在 cases 里照常逐例审计。
    check_case_pools=True 时额外核对 C/H/G 既有案例池（任务要求「案例池亦不得冲突」）。
    撞题必须 ok=False 且逐条列出原因，不得改名/放宽冒充新颖。
    """
    pool = list(cases if cases is not None else N_CASES)
    descs, names = corpus if corpus is not None else _load_n_history_corpus()
    descs, names = list(descs or []), list(names or [])
    case_pools = list(pools if pools is not None else _case_pool_entries()) if check_case_pools else []
    rows, conflicts = [], []
    for case in pool:
        reasons = _audit_one(case, descs, names)
        reasons.extend(_audit_pool(case, case_pools))
        rows.append({"id": case["id"], "name": case["name"], "subject": case["subject"],
                     "conflicts": reasons})
        if reasons:
            conflicts.append({"id": case["id"], "name": case["name"], "reasons": reasons})
    return {
        "cases": rows,
        "conflicts": conflicts,
        "ok": not conflicts,
        "corpus": {"descs": len(descs), "names": len(names)},
        "pools": {"count": len(case_pools)},
        "used_clean_baseline": not descs and not names,
    }


def main(argv=None):
    import json
    import sys

    # Windows GBK 控制台兼容：--audit/--list 的打印不能因编码崩溃（验收命令必须可直接跑）。
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except (AttributeError, ValueError):  # 老 Python / 非文本 stdout
        pass
    argv = list(sys.argv[1:] if argv is None else argv)
    if "--audit" in argv:
        report = audit_n_cases()
        if report["used_clean_baseline"]:
            print("未执行完整新颖性审计：缺少历史语料（公开仓应存在 "
                  "test/fixtures/public/history-corpus.json）。")
            return 0 if "--allow-empty" in argv else 2
        print(f"基准语料：历史需求 {report['corpus']['descs']} 条、"
              f"模型名称/特征 {report['corpus']['names']} 条、"
              f"既有案例池 {report['pools']['count']} 例\n")
        for row in report["cases"]:
            if row["conflicts"]:
                print(f"[冲突] {row['id']} {row['name']}：")
                for c in row["conflicts"]:
                    print("   -", c)
            else:
                print(f"[OK] {row['id']} {row['name']}：主题与历史语料/案例池无冲突")
        print(f"\n共 {len(report['cases'])} 例，冲突 {len(report['conflicts'])} 例")
        return 0 if report["ok"] else 1
    if "--list" in argv:
        for c in N_CASES:
            print(f"{c['id']} {c['name']:8s} 目标≈{c['target_blocks']:3d}块 "
                  f"部位≥{c['min_parts']:2d} 体素回归参考≥{c['min_voxels']:4d} "
                  f"压力={'/'.join(c['stress'])}  {c['desc'][:38]}…")
        print(f"\n共 {len(N_CASES)} 例")
        return 0
    print(json.dumps([{k: c[k] for k in ("id", "name", "subject", "desc", "target_blocks")}
                      for c in N_CASES], ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    import sys
    sys.exit(main())
