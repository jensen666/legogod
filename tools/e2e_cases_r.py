# -*- coding: utf-8 -*-
"""R 组（R01–R10）冻结新例案例单源：与 P 组配对做 OFF/ON 两臂真实 E2E。

用途与口径：
  1. R 组是**未参与本轮开发的新例**：10 个主题在历史语料与 C/H/G/N 案例池中 0 命中，
     开跑前冻结需求原文、目标块数与结果断言（desc_sha256 冻结原文哈希，运行记录必须
     与冻结哈希一致，防止跑中改题）。
  2. 与 P 组配对：P 组沿用 H01,C02,C03,C14,N04,N07,N12,N14,N15,N16；OFF/ON 两臂各跑
     同一批 20 例（P 组 10 + R 组 10），R 组不得退化是方案通过标准之一。
  3. **至少 2 例不使用「约」**：R09/R10 的需求原文逐字写作「目标 N 块积木」，其余 8 例
     写作「目标约 N 块积木」；两种写法都必须由生产单源
     `legogod.plan_scale.parse_target_blocks` 解析出与 target_blocks 一致的数字。
  4. 断言两层结构（实现见 tools/e2e_assert_r.py）：
        generic_tier    可信底线（任务成功/最终门禁 replay/统一校验/最终版本产物/
                        无版本覆盖/评审不过期）
        requirement_tier 需求正确性（目标块数比、require_parts 部位、feature checks、
                        min_parts/min_solid_parts）
     errors = generic_tier + requirement_tier；任何一项失败即断言失败。
  5. 规模与复杂度在网格能力内（网格上限 24×24×14、MAX_VOX 5800）：target_blocks 180–440，
     min_voxels = 2×target_blocks（G 组口径回归参考下限），min_parts 与需求部位数一致，
     min_ops 只作回归档参考。

需求原文纪律：必须是可直接提交 Web 工坊的真实中文用户需求（8–12 个可辨识部位/特征 +
至少两类结构特征，规模句结尾），不使用透明件、文字/水印、超网格容量的规模或不可实现的
细节；不以旧题改名冒充新增。

字段约定（与 tools/e2e_cases_new20.py 完全一致）：
  id/name/subject/desc、complexity、stress、historical_failure_hint、
  target_blocks/min_parts/min_solid_parts/min_voxels/min_ops、
  require_parts（[(部位名, (关键词...)), ...]）、checks（[[检查名, 参数...], ...]）；
  另加 desc_sha256（冻结需求原文的 sha256，见 _desc_sha256）。

新颖性审计：
  python -m tools.e2e_cases_r --audit
  基准语料复用 tools.e2e_cases_20._load_history_corpus（历史需求 + 模型名称/特征），
  并额外对 C/H/G/N 既有案例池做主题/原文核对；本组自己跑过的需求与产物按
  _r_campaign_scope 口径排除，防止跑完后自我撞题。
"""
from __future__ import annotations

import hashlib
import re

# 直接复用生产单源：同时接受「目标 N 块」与「目标约 N 块」（要求：禁止自写正则解析）
from legogod.plan_scale import parse_target_blocks as _plan_parse_target_blocks
from tools.e2e_cases_new20 import STRESS_CATEGORIES  # noqa: F401  harness 压力类别单源

# 统一规模容差：bricks_ratio >= 0.5 才算「目标块数达标」（中位 ≥50% 的逐例口径）
R_TARGET_TOLERANCE = 0.5


def parse_target_blocks(desc):
    """从需求原文解析目标块数 N（转调 legogod.plan_scale 唯一入口）。

    生产单源同时接受「目标 N 块」与「目标约 N 块」（「约」可省略、块后可无「积木」）；
    解析不到返回 None。E2E 断言与生产口径不得分叉。
    """
    return _plan_parse_target_blocks(desc)


def _desc_sha256(desc):
    """冻结需求原文哈希：sha256(utf-8(desc)) 的十六进制串。"""
    return hashlib.sha256((desc or "").encode("utf-8")).hexdigest()


R_CASES = [
    {
        # 320 块 ≈ 640 体素回归参考；10 个部位 → 部位下限 10；算子参考 16。
        "id": "R01", "name": "螺旋壳蜗牛", "subject": "蜗牛",
        "desc": "拼一只背着螺旋壳的蜗牛：螺旋壳的壳顶向上收尖，壳面有几圈逐层收分的螺旋纹，"
                "壳口朝向下方张开，壳下面是柔软的身体，身体前端伸出头部，头顶两根细眼柄成对向上竖起，"
                "眼柄末端各有一个异色眼睛，头部下方伸出两根短触角，腹足平贴地面，"
                "身体后端收成一条尖尾，目标约 320 块积木",
        "complexity": "螺旋壳逐层收分（多层壳圈真实成型）+ 壳口向下张开 + 成对眼柄与触角 + 腹足落地",
        "stress": ["curved", "thin_parts", "gate"],
        "historical_failure_hint": "弧面/细长类：历史 C02/C13 细长部件硬失败、H02 曲面内容断言通过但整例"
                                   "未达；螺旋壳逐层收分最易被简化成实心圆块（2026-11-03 报告）",
        "target_blocks": 320,
        "min_parts": 10, "min_solid_parts": 9, "min_voxels": 640, "min_ops": 16,
        "require_parts": [
            ("螺旋壳", ("螺旋壳", "壳", "shell")),
            ("壳顶", ("壳顶", "顶")),
            ("壳口", ("壳口", "口")),
            ("身体", ("身体", "body")),
            ("头部", ("头部", "头", "head")),
            ("眼柄", ("眼柄", "柄", "stalk")),
            ("眼睛", ("眼睛", "眼", "eye")),
            ("触角", ("触角", "触须", "antenna")),
            ("腹足", ("腹足", "足", "foot")),
            ("尖尾", ("尖尾", "尾", "tail")),
        ],
        "checks": [
            ["g_curved_taper_body", ("螺旋壳", "壳", "shell")],
            ["both_sides", ("眼柄", "柄", "stalk")],
            ["g_exposed_contrast_color", ("眼睛", "眼", "eye"), 2, ("身体", "body")],
            ["g_parts_contact", ("螺旋壳", "壳", "shell"), ("身体", "body")],
            ["part_raised_above", ("螺旋壳", "壳", "shell"), ("腹足", "足", "foot"), 1],
            ["g_grounded_min", ("腹足", "足", "foot")],
            ["colors_distinct_min", 3],
            ["g_not_solid_block", (), 0.78],
            ["layers_min", 4],
        ],
        "desc_sha256": "8c703489ff01e686df5ce0ec341b4cfbec3819de3156586ed1e3104b72287826",
    },
    {
        # 280 块 ≈ 560 体素回归参考；8 个部位 → 部位下限 8；算子参考 14。
        "id": "R02", "name": "伞盖水母", "subject": "水母",
        "desc": "拼一只漂在水里的水母：上方是圆鼓的伞盖，伞盖边缘一圈缘膜向下收口，"
                "伞盖内部有中空的内腔，伞盖下方中央垂下四条口腕，口腕周围垂下成排细长触手，"
                "触手末端向不同方向弯垂，触手上有一排异色吸盘，伞盖表面有一圈异色生殖腺，"
                "目标约 280 块积木",
        "complexity": "圆鼓伞盖收分 + 内腔中空 + 成排触手向多方位弯垂 + 口腕/吸盘/生殖腺异色外露",
        "stress": ["curved", "thin_parts", "disconnected"],
        "historical_failure_hint": "分体断连/细长类：历史 C02/C06/C16 断连硬失败，成排触手常被合并成"
                                   "一块或互不连接（N03 章鱼同源风险）",
        "target_blocks": 280,
        "min_parts": 8, "min_solid_parts": 7, "min_voxels": 560, "min_ops": 14,
        "require_parts": [
            ("伞盖", ("伞盖", "伞", "bell", "dome")),
            ("缘膜", ("缘膜", "膜", "velum")),
            ("内腔", ("内腔", "腔", "cavity")),
            ("口腕", ("口腕", "腕", "oral")),
            ("触手", ("触手", "tentacle")),
            ("触手末端", ("末端", "尖端", "tip")),
            ("吸盘", ("吸盘", "sucker")),
            ("生殖腺", ("生殖腺", "腺", "gonad")),
        ],
        "checks": [
            ["g_tentacle_directions", ("触手", "tentacle"), 4, 2],
            ["g_part_clusters_min", ("触手", "tentacle"), 4],
            ["g_curved_taper_body", ("伞盖", "伞", "bell", "dome")],
            ["g_exposed_contrast_color", ("生殖腺", "腺", "gonad"), 2,
             ("伞盖", "伞", "bell", "dome")],
            ["g_exposed_contrast_color", ("吸盘", "sucker"), 3, ("触手", "tentacle")],
            ["g_parts_contact", ("口腕", "腕", "oral"), ("伞盖", "伞", "bell", "dome")],
            ["part_raised_above", ("伞盖", "伞", "bell", "dome"), ("触手", "tentacle"), 1],
            ["colors_distinct_min", 3],
            ["g_not_solid_block", (), 0.8],
            ["layers_min", 4],
        ],
        "desc_sha256": "6385fb4361b1aad2cfcfac583d25c3484b9772a1d24eab59fa39724cd1526f7f",
    },
    {
        # 260 块 ≈ 520 体素回归参考；9 个部位 → 部位下限 9；算子参考 13。
        "id": "R03", "name": "独角仙", "subject": "独角仙",
        "desc": "拼一只独角仙甲虫：头部前端伸出一根向上弯曲的犄角，犄角尖端分成两个小叉，"
                "头两侧是一对异色复眼，前胸背板宽厚，背上有左右分开的两片硬质鞘翅，"
                "鞘翅表面有纵向条纹，身体两侧各伸出三条分节步足共六条，步足向外斜撑，"
                "头部下方有短触角，腹部收在鞘翅下面，目标约 260 块积木",
        "complexity": "高举分叉犄角 + 左右两片鞘翅 + 六条分节斜撑步足 + 前胸背板/头部体量比例差异",
        "stress": ["paired_symmetry", "support", "gate"],
        "historical_failure_hint": "成对/支撑类：历史 H04 成对前肢被合并、C03 斜撑支撑失败；六足与鞘翅"
                                   "在部位绑定时最易合并（2026-11-03 G 组内容断言 0/10）",
        "target_blocks": 260,
        "min_parts": 9, "min_solid_parts": 8, "min_voxels": 520, "min_ops": 13,
        "require_parts": [
            ("头部", ("头部", "头", "head")),
            ("犄角", ("犄角", "角", "horn")),
            ("犄角分叉", ("分叉", "叉", "fork")),
            ("复眼", ("复眼", "眼", "eye")),
            ("前胸背板", ("前胸背板", "前胸", "胸", "thorax")),
            ("鞘翅", ("鞘翅", "翅", "elytra")),
            ("步足", ("步足", "腿", "足", "leg")),
            ("触角", ("触角", "触须", "antenna")),
            ("腹部", ("腹部", "腹", "abdomen")),
        ],
        "checks": [
            ["g_legs_separate_min", ("步足", "腿", "足", "leg"), 6],
            ["both_sides", ("鞘翅", "翅", "elytra")],
            ["part_raised_above", ("犄角", "角", "horn"), ("头部", "头", "head"), 1],
            ["g_parts_contact", ("犄角", "角", "horn"), ("头部", "头", "head")],
            ["g_exposed_contrast_color", ("复眼", "眼", "eye"), 2,
             ("前胸背板", "前胸", "胸", "thorax")],
            ["g_part_ratio_diff", ("前胸背板", "前胸", "胸", "thorax"), ("犄角", "角", "horn"), 1.5],
            ["colors_distinct_min", 3],
            ["g_not_solid_block", (), 0.8],
            ["layers_min", 4],
        ],
        "desc_sha256": "ef3985279ec88749835d691cd1c2607afa3526329341522fd1138a7533765375",
    },
    {
        # 240 块 ≈ 480 体素回归参考；8 个部位 → 部位下限 8；算子参考 12。
        "id": "R04", "name": "书房台灯", "subject": "台灯",
        "desc": "拼一盏书房台灯：底座是圆形厚盘，底座上立着一根细长灯杆，灯杆顶部有一段可弯折的灯臂"
                "向斜前方伸出，灯臂末端接着圆锥形灯罩，灯罩是外扩后向下收分的斜面罩体，"
                "灯罩口朝向下方张开，灯罩里有异色灯泡，灯杆侧面有一个旋钮，灯臂与灯杆之间的关节外露，"
                "底座旁边伸出一根弯折的电线，目标约 240 块积木",
        "complexity": "斜前方悬挑灯臂 + 圆锥灯罩收分斜面 + 灯泡外露异色 + 电线弯折伸展",
        "stress": ["support", "thin_parts", "gate"],
        "historical_failure_hint": "悬挑/细长类：历史 C02/C13 细长件与 H01/C06 悬挑硬失败；斜伸灯臂与"
                                   "灯罩悬挑最易在支撑预检被拒（2026-11-03 报告）",
        "target_blocks": 240,
        "min_parts": 8, "min_solid_parts": 7, "min_voxels": 480, "min_ops": 12,
        "require_parts": [
            ("底座", ("底座", "base")),
            ("灯杆", ("灯杆", "灯柱", "stem", "pole")),
            ("灯臂", ("灯臂", "臂", "arm")),
            ("灯罩", ("灯罩", "罩", "shade")),
            ("灯泡", ("灯泡", "bulb")),
            ("旋钮", ("旋钮", "开关", "knob")),
            ("关节", ("关节", "joint")),
            ("电线", ("电线", "线", "wire", "cable")),
        ],
        "checks": [
            ["g_grounded_min", ("底座", "base")],
            ["g_parts_contact", ("灯杆", "灯柱", "stem", "pole"), ("底座", "base")],
            ["g_parts_contact", ("灯罩", "罩", "shade"), ("灯臂", "臂", "arm")],
            ["part_raised_above", ("灯罩", "罩", "shade"), ("底座", "base"), 3],
            ["part_overhang_min", ("灯臂", "臂", "arm"), 2],
            ["g_parts_contact", ("电线", "线", "wire", "cable"),
             ("底座", "base", "灯杆", "灯柱", "stem", "pole")],
            ["g_exposed_contrast_color", ("灯泡", "bulb"), 1, ("灯罩", "罩", "shade")],
            ["colors_distinct_min", 3],
            ["g_not_solid_block", (), 0.72],
            ["layers_min", 5],
        ],
        "desc_sha256": "feaadd799a59c602c2253a78e4785db3b74cb9ff890e0ff49abce6ba60b9021c",
    },
    {
        # 360 块 ≈ 720 体素回归参考；10 个部位 → 部位下限 10；算子参考 18。
        "id": "R05", "name": "手摇纺车", "subject": "纺车",
        "desc": "拼一架老式手摇纺车：木架上立着一个大车轮，车轮由圆圈轮辋和几根放射状轮辐组成，"
                "轮辐从轮轴向外展开，车轮中心是轮轴，轮轴另一侧连着纱锭，纱锭上绕着一团纱线，"
                "车轮底部连着脚踏板，架子上伸出一根摇柄，轮轴与摇柄之间有一根拉杆斜撑，"
                "木架下端有两条分立的支腿落地，目标约 360 块积木",
        "complexity": "大车轮圆环 + 放射状轮辐 + 轮轴/纱锭/摇柄传动链 + 两根分立支腿落地",
        "stress": ["curved", "paired_symmetry", "gate"],
        "historical_failure_hint": "弧形/覆盖类：历史 H08/C11 圆环内容断言通过但整例失败；大车轮圆环与"
                                   "放射轮辐最易在覆盖预检被简化（2026-11-03 报告）",
        "target_blocks": 360,
        "min_parts": 10, "min_solid_parts": 9, "min_voxels": 720, "min_ops": 18,
        "require_parts": [
            ("车轮", ("车轮", "wheel")),
            ("轮辋", ("轮辋", "辋", "rim")),
            ("轮辐", ("轮辐", "辐", "spoke")),
            ("轮轴", ("轮轴", "轴", "axle")),
            ("纱锭", ("纱锭", "锭", "spindle")),
            ("纱线", ("纱线", "线", "yarn")),
            ("踏板", ("踏板", "脚踏", "pedal")),
            ("摇柄", ("摇柄", "柄", "crank")),
            ("拉杆", ("拉杆", "杆", "rod")),
            ("支腿", ("支腿", "腿", "leg")),
        ],
        "checks": [
            ["g_round_wheels", ("车轮", "wheel"), 1, 1],
            ["g_parts_contact", ("车轮", "wheel"), ("轮轴", "轴", "axle")],
            ["g_parts_contact", ("轮轴", "轴", "axle"), ("支腿", "腿", "leg")],
            ["g_parts_contact", ("拉杆", "杆", "rod"), ("摇柄", "柄", "crank")],
            ["g_parts_contact", ("纱锭", "锭", "spindle"), ("轮轴", "轴", "axle")],
            ["g_legs_separate_min", ("支腿", "腿", "leg"), 2],
            ["part_span_min", ("车轮", "wheel"), 6, "xz"],
            ["part_span_min", ("支腿", "腿", "leg"), 3, "y"],
            ["colors_distinct_min", 2],
            ["g_not_solid_block", (), 0.75],
            ["layers_min", 5],
        ],
        "desc_sha256": "ef7136ec40ecd06497c624d3dcb6dfe1c2d7a6d971905036f3e85c974bf90c84",
    },
    {
        # 220 块 ≈ 440 体素回归参考；8 个部位 → 部位下限 8；算子参考 11。
        "id": "R06", "name": "实验室天平", "subject": "天平",
        "desc": "拼一台实验室天平：底部是方形底座，底座中央立着一根竖直立柱，立柱顶端架着一根水平横梁，"
                "横梁两端左右对称各悬挂一个圆盘，圆盘用三根细吊绳挂在横梁上，"
                "横梁中央有一根竖直指针，指针下方是扇形刻度盘，底座四角各有一个矮脚，"
                "目标约 220 块积木",
        "complexity": "左右对称悬挂双盘 + 三根细吊绳悬吊 + 长横梁 + 扇形刻度盘与指针",
        "stress": ["paired_symmetry", "suspension", "thin_parts"],
        "historical_failure_hint": "悬吊/细长类：历史 H01/C06/C16 悬吊硬失败、C02 细长件失败；吊盘吊绳"
                                   "与长横梁最易退化成贴条（悬吊快照多不可评估）",
        "target_blocks": 220,
        "min_parts": 8, "min_solid_parts": 7, "min_voxels": 440, "min_ops": 11,
        "require_parts": [
            ("底座", ("底座", "base")),
            ("立柱", ("立柱", "柱", "column")),
            ("横梁", ("横梁", "梁", "beam")),
            ("吊盘", ("吊盘", "秤盘", "托盘", "pan")),
            ("吊绳", ("吊绳", "绳", "rope")),
            ("指针", ("指针", "针", "pointer")),
            ("刻度盘", ("刻度盘", "刻度", "dial")),
            ("矮脚", ("矮脚", "脚", "foot")),
        ],
        "checks": [
            ["both_sides", ("吊盘", "秤盘", "托盘", "pan")],
            ["g_parts_contact", ("立柱", "柱", "column"), ("底座", "base")],
            ["g_parts_contact", ("横梁", "梁", "beam"), ("立柱", "柱", "column")],
            ["g_parts_contact", ("吊盘", "秤盘", "托盘", "pan"), ("吊绳", "绳", "rope")],
            ["g_parts_contact", ("吊绳", "绳", "rope"), ("横梁", "梁", "beam")],
            ["part_span_min", ("横梁", "梁", "beam"), 8, "x"],
            ["g_grounded_min", ("底座", "base")],
            ["g_exposed_contrast_color", ("指针", "针", "pointer"), 1,
             ("刻度盘", "刻度", "dial")],
            ["colors_distinct_min", 2],
            ["g_not_solid_block", (), 0.7],
        ],
        "desc_sha256": "1d894dec55bd1daa524aab48f2a0dbaa7dc8c01536bea150395bffb432b54a0e",
    },
    {
        # 400 块 ≈ 800 体素回归参考；9 个部位 → 部位下限 9；算子参考 20。
        "id": "R07", "name": "小型喷泉", "subject": "喷泉",
        "desc": "拼一座小型喷泉：最下面是圆形水池，池壁围出中空的池腔，池沿高出地面，"
                "水池中央立着两级递收的台座，台座顶上是浅盘状的水盘，水盘中央有一根喷口，"
                "喷口喷出向上散开的水柱，水柱两侧垂下成串水珠，水池外沿有一圈台阶，"
                "池壁上贴着异色瓷砖，目标约 400 块积木",
        "complexity": "池壁围合中空池腔 + 两级递收台座 + 浅盘水盘与喷口水柱 + 外沿台阶",
        "stress": ["curved", "coverage", "arch_negative_space"],
        "historical_failure_hint": "中空/覆盖类：历史 C07 门洞负空间内容断言通过但整例失败，覆盖失败 5 例"
                                   "（support_column 预算耗尽，2026-11-03 报告）",
        "target_blocks": 400,
        "min_parts": 9, "min_solid_parts": 8, "min_voxels": 800, "min_ops": 20,
        "require_parts": [
            ("水池", ("水池", "池", "basin")),
            ("池壁", ("池壁", "壁", "wall")),
            ("台座", ("台座", "座", "pedestal")),
            ("水盘", ("水盘", "盘")),
            ("喷口", ("喷口", "喷嘴", "nozzle")),
            ("水柱", ("水柱", "jet")),
            ("水珠", ("水珠", "珠", "droplet")),
            ("台阶", ("台阶", "梯", "step")),
            ("瓷砖", ("瓷砖", "砖", "tile")),
        ],
        "checks": [
            ["g_cup_bottom_closed", ("水池", "池", "basin")],
            ["g_cup_cavity_min", ("水池", "池", "basin"), 10],
            ["g_parts_contact", ("台座", "座", "pedestal"), ("水池", "池", "basin")],
            ["g_parts_contact", ("喷口", "喷嘴", "nozzle"), ("水盘", "盘")],
            ["part_raised_above", ("水盘", "盘"), ("台阶", "梯", "step"), 2],
            ["part_span_min", ("水柱", "jet"), 4, "y"],
            ["tiered_min", 3],
            ["g_grounded_min", ("水池", "池", "basin")],
            ["colors_distinct_min", 3],
            ["g_not_solid_block", (), 0.8],
        ],
        "desc_sha256": "e4798ce28dcb49fac431b81cd23fedf4a636f3ae47cbe0d3a98779da42495a59",
    },
    {
        # 200 块 ≈ 400 体素回归参考；9 个部位 → 部位下限 9；算子参考 10。
        "id": "R08", "name": "老式座钟", "subject": "座钟",
        "desc": "拼一台老式座钟：木制钟壳是方盒形，正面有圆形表盘，表盘边缘一圈刻度，"
                "表盘中央装着异色指针，表盘下方钟壳内挂着一根摆杆，摆杆末端吊着摆锤，"
                "摆杆吊在钟壳内的横梁上，钟壳顶部是逐层收分又向外挑出的弧形顶饰，"
                "底部有四只矮脚，钟壳正面下半部有一扇格栅小门，目标约 200 块积木",
        "complexity": "圆形表盘 + 摆杆吊摆锤 + 钟壳内横梁 + 弧形顶饰 + 四只矮脚落地",
        "stress": ["paired_symmetry", "thin_parts", "visual"],
        "historical_failure_hint": "弧面/视觉类：历史 H02 曲面与 C02/C13 细长件失败；圆表盘与细指针最易"
                                   "被打成实心方板（高保真成功 0/30）",
        "target_blocks": 200,
        "min_parts": 9, "min_solid_parts": 8, "min_voxels": 400, "min_ops": 10,
        "require_parts": [
            ("钟壳", ("钟壳", "壳", "case")),
            ("表盘", ("表盘", "盘", "dial")),
            ("刻度", ("刻度", "格", "tick")),
            ("指针", ("指针", "针", "hand")),
            ("摆锤", ("摆锤", "锤", "bob")),
            ("摆杆", ("摆杆", "杆", "pendulum")),
            ("横梁", ("横梁", "梁", "beam")),
            ("顶饰", ("顶饰", "饰", "finial")),
            ("矮脚", ("矮脚", "脚", "foot")),
        ],
        "checks": [
            ["g_round_wheels", ("表盘", "dial"), 1, 1],
            ["g_parts_contact", ("表盘", "dial"), ("钟壳", "壳", "case")],
            ["g_exposed_contrast_color", ("指针", "针", "hand"), 2, ("表盘", "dial")],
            ["g_parts_contact", ("摆杆", "杆", "pendulum"), ("横梁", "梁", "beam")],
            ["g_parts_contact", ("摆锤", "锤", "bob"), ("摆杆", "杆", "pendulum")],
            ["part_span_min", ("摆杆", "杆", "pendulum"), 4, "y"],
            ["g_grounded_min", ("矮脚", "脚", "foot")],
            ["colors_distinct_min", 3],
            ["g_not_solid_block", (), 0.75],
            ["layers_min", 5],
        ],
        "desc_sha256": "486aab47f7f1eb1b532c68d57d58952a507360ef62b63d371baa8841de927aa5",
    },
    {
        # 【无「约」写法 1/2】180 块 ≈ 360 体素回归参考；11 个部位 → 部位下限 11；算子参考 9。
        "id": "R09", "name": "桌面风铃", "subject": "风铃",
        "desc": "拼一个桌面风铃摆件：方形底座上立着两根分立的支柱，两根支柱顶端架着一根横梁，"
                "横梁中央挂着一个悬挂环，悬挂环下面接圆形顶盖，顶盖边缘有一圈镂空花边，"
                "顶盖下垂着一圈细吊绳，吊绳下端吊着高低不同的金属音管，音管之间留出一格缝隙，"
                "中间几根音管最长、两侧逐渐变短，最中间垂着一根中心吊线，吊线末端是挡风板，"
                "挡风板下面垂着一条流苏，目标 180 块积木",
        "complexity": "镂空花边顶盖 + 成排竖向音管高低收分 + 吊绳/中心吊线悬吊 + 挡风板与流苏",
        "stress": ["curved", "thin_parts", "suspension"],
        "historical_failure_hint": "细长/悬吊类：历史 C02/C13 细长硬失败、H01/C06 悬吊失败；成排音管最易"
                                   "塌成墙板或全部合并（G 组内容断言 0/10）",
        "target_blocks": 180,
        "min_parts": 11, "min_solid_parts": 10, "min_voxels": 360, "min_ops": 9,
        "require_parts": [
            ("底座", ("底座", "base")),
            ("支柱", ("支柱", "柱", "post")),
            ("横梁", ("横梁", "梁", "beam")),
            ("悬挂环", ("悬挂环", "挂环", "ring")),
            ("顶盖", ("顶盖", "盖", "cap")),
            ("花边", ("花边", "镂空", "lace")),
            ("吊绳", ("吊绳", "绳", "rope")),
            ("音管", ("音管", "管", "pipe")),
            ("中心吊线", ("中心吊线", "吊线", "center")),
            ("挡风板", ("挡风板", "挡风", "plate")),
            ("流苏", ("流苏", "穗", "tassel")),
        ],
        "checks": [
            ["both_sides", ("支柱", "柱", "post")],
            ["g_parts_contact", ("支柱", "柱", "post"), ("底座", "base")],
            ["g_parts_contact", ("横梁", "梁", "beam"), ("支柱", "柱", "post")],
            ["g_strings_vertical_min", ("音管", "管", "pipe"), 6],
            ["g_part_clusters_min", ("音管", "管", "pipe"), 5],
            ["g_parts_contact", ("吊绳", "绳", "rope"), ("顶盖", "盖", "cap")],
            ["g_parts_contact", ("吊绳", "绳", "rope"), ("音管", "管", "pipe")],
            ["g_parts_contact", ("挡风板", "挡风", "plate"), ("中心吊线", "吊线", "center")],
            ["g_grounded_min", ("底座", "base")],
            ["g_not_solid_block", (), 0.7],
            ["colors_distinct_min", 2],
            ["layers_min", 5],
        ],
        "desc_sha256": "7cf791f024d75b57533973cbc4bf50c084423c19e9865f5ee56ce2cf208bf166",
    },
    {
        # 【无「约」写法 2/2】300 块 ≈ 600 体素回归参考；10 个部位 → 部位下限 10；算子参考 15。
        "id": "R10", "name": "倒挂树懒", "subject": "树懒",
        "desc": "拼一只倒挂在树枝上的树懒：粗壮的树干立在地面，树干上伸出一根横向树枝，"
                "树枝上悬挂着树懒的四条长肢，前肢和后肢都成对分开，每条肢末端有三根弯曲的长爪"
                "勾住树枝，树懒圆圆的身体倒挂在前肢下方，身体前端是圆头，脸上有一圈异色眼罩，"
                "头两侧有小圆耳，身体后端连着一条短尾，目标 300 块积木",
        "complexity": "四条长肢成对悬挂在树枝上 + 长爪勾枝 + 倒挂身体姿态 + 眼罩异色外露",
        "stress": ["suspension", "paired_symmetry", "support"],
        "historical_failure_hint": "悬空/成对类：历史 H04 成对前肢合并、H01/C06/C16 悬吊硬失败；四条悬挂"
                                   "长肢最易互相断开或贴死树枝（2026-11-03 G 组内容断言 0/10）",
        "target_blocks": 300,
        "min_parts": 10, "min_solid_parts": 9, "min_voxels": 600, "min_ops": 15,
        "require_parts": [
            ("树干", ("树干", "树", "trunk")),
            ("树枝", ("树枝", "枝", "branch")),
            ("前肢", ("前肢", "前腿", "foreleg")),
            ("后肢", ("后肢", "后腿", "hindleg")),
            ("长爪", ("长爪", "爪", "claw")),
            ("身体", ("身体", "body")),
            ("圆头", ("圆头", "头部", "头", "head")),
            ("眼罩", ("眼罩", "面罩", "mask")),
            ("圆耳", ("圆耳", "耳", "ear")),
            ("短尾", ("短尾", "尾", "tail")),
        ],
        "checks": [
            ["both_sides", ("前肢", "前腿", "foreleg")],
            ["both_sides", ("后肢", "后腿", "hindleg")],
            ["g_parts_contact", ("前肢", "前腿", "foreleg"), ("树枝", "枝", "branch")],
            ["g_parts_contact", ("后肢", "后腿", "hindleg"), ("树枝", "枝", "branch")],
            ["g_parts_contact", ("树干", "树", "trunk"), ("树枝", "枝", "branch")],
            ["g_grounded_min", ("树干", "树", "trunk")],
            ["part_span_min", ("树枝", "枝", "branch"), 6, "x"],
            ["g_exposed_contrast_color", ("眼罩", "面罩", "mask"), 2, ("圆头", "头", "head")],
            ["colors_distinct_min", 3],
            ["g_not_solid_block", (), 0.72],
            ["layers_min", 4],
        ],
        "desc_sha256": "475e69ee5ed339e246d8b36fcde9a2a432850b50cbee591e418206043a5a62b4",
    },
]

# 冻结后自检：desc_sha256 必须是原文哈希、target_blocks 必须与原文解析一致。
# （模块导入即校验，防止手工改 desc 忘记更新哈希；测试另有逐例断言。）
for _case in R_CASES:
    if _case["desc_sha256"] == _desc_sha256(_case["desc"]):
        continue
    if _case["desc_sha256"].startswith("__SHA256_") or not _case["desc_sha256"]:
        continue  # 生成期占位符；运行期由下方 _verify_frozen_cases 兜底
    raise RuntimeError(f"{_case['id']} desc_sha256 与需求原文不一致（冻结原文被改动）")
del _case


def all_r_cases():
    """R01–R10 全部案例（冻结新例单源，不与 P/C/H/G/N 组混放）。"""
    return list(R_CASES)


def find_r_case(case_id=None, desc=None):
    """按案例编号或需求原文查找 R 组案例；语义与 tools.e2e_cases_g.find_g_case 一致。

    编号大小写不敏感（先 strip 再 upper）；原文必须逐字相等；同一原文命中多个案例时
    要求显式给编号（返回 None），避免区间/初始化解析误配。
    """
    if case_id:
        cid = str(case_id).strip().upper()
        for c in R_CASES:
            if c["id"] == cid:
                return c
        return None
    if desc is not None:
        hits = [c for c in R_CASES if c["desc"] == desc]
        if len(hits) == 1:
            return hits[0]
    return None


def summary_target_from_desc(desc):
    """供审计/测试核对：从原文解析的块数目标必须与 target_blocks 冻结值一致。"""
    return parse_target_blocks(desc)


def _is_no_yue_case(case):
    """该例是否使用不带「约」的「目标 N 块」写法（方案要求至少 2 例）。"""
    return "约" not in (case.get("desc") or "")


# ---------------------------------------------------------------- 主题新颖性审计
def _r_campaign_scope(root):
    """本组自己的运行产物范围：({需求原文集合}, {run_id 集合})。

    与 tools.e2e_cases_g._g_campaign_scope 同口径：R 组跑过之后 artifacts/ 与
    jobs_store 里会出现自己的需求与模型，审计必须把它们排除，否则自己跑过的案例
    会被自己判成「已存在」。排除只针对本组原文/run，历史基线其余部分照常审计。
    """
    import glob
    import json
    import os

    descs = {c["desc"] for c in R_CASES}
    runs = set()
    for path in glob.glob(os.path.join(root, "artifacts", "e2e-20", "**", "*.json"), recursive=True):
        try:
            with open(path, encoding="utf-8") as f:
                data = json.load(f)
        except (OSError, ValueError):
            continue
        if not isinstance(data, dict):
            continue
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
    # 运行记录兜底：E2E 轮次被中断时单例 JSON 可能没写出来，但 run_<id>.json 已落盘（孤儿运行）。
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


def _load_r_history_corpus():
    """基准语料：e2e_cases_20._load_history_corpus 同源（历史需求 + 模型名称/特征），
    再剔除本组自己的历史产物（需求原文与模型名/特征），避免跑完后自我撞题。"""
    import collections
    import glob
    import json
    import os

    from tools.e2e_cases_20 import _load_history_corpus

    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    r_descs, r_runs = _r_campaign_scope(root)
    # 公开仓没有运行产物时 _load_history_corpus 回退到 public/history-corpus.json；
    # 传入本组 R 以排除自己的案例，避免自我撞题。
    descs, names = _load_history_corpus(exclude_groups=("R",))
    descs = [d for d in descs if d not in r_descs]

    own_vals = collections.Counter()
    if r_runs:
        for path in glob.glob(os.path.join(root, "artifacts", "model_*.json")):
            try:
                with open(path, encoding="utf-8") as f:
                    model = json.load(f)
            except (OSError, ValueError):
                continue
            if not isinstance(model, dict) or str(model.get("runId")) not in r_runs:
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
    """C/H/G/N 既有案例池（主题词/原文）——历史语料之外的第二道新颖性基线。"""
    from tools.e2e_cases_20 import all_cases as all_ch_cases
    from tools.e2e_cases_g import G_CASES
    from tools.e2e_cases_new20 import N_CASES

    entries = []
    for source, cases in (("C/H案例池", all_ch_cases()), ("G案例池", G_CASES),
                          ("N案例池", N_CASES)):
        for case in cases:
            entries.append({"source": source, "id": case.get("id"),
                            "subject": case.get("subject") or "",
                            "desc": case.get("desc") or ""})
    return entries


def _audit_one(case, descs, names):
    """对单个案例做主题/原文撞题判定，返回冲突原因列表（与 N 组审计同口径）。"""
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
    """与 C/H/G/N 既有案例池比对：原文完全相同或主题词出现在池内需求/主题都算撞题。"""
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


def audit_r_cases(cases=None, corpus=None, check_case_pools=True, pools=None):
    """R 组主题新颖性审计，返回结构化报告 dict：
    {"cases": [{id,name,subject,no_yue,conflicts}], "conflicts": [...], "ok": bool,
     "corpus": {"descs":N,"names":N}, "pools": {"count":N}, "used_clean_baseline": bool}

    corpus 参数仅供测试注入 (descs, names)；默认取 _load_r_history_corpus()。
    历史语料为空（干净检出）时 used_clean_baseline=True 并在 cases 里照常逐例审计。
    check_case_pools=True 时额外核对 C/H/G/N 既有案例池（任务要求「案例池亦不得冲突」）。
    撞题必须 ok=False 且逐条列出原因，不得改名/放宽冒充新颖。
    """
    pool = list(cases if cases is not None else R_CASES)
    descs, names = corpus if corpus is not None else _load_r_history_corpus()
    descs, names = list(descs or []), list(names or [])
    case_pools = list(pools if pools is not None else _case_pool_entries()) if check_case_pools else []
    rows, conflicts = [], []
    for case in pool:
        reasons = _audit_one(case, descs, names)
        reasons.extend(_audit_pool(case, case_pools))
        rows.append({"id": case.get("id"), "name": case.get("name"),
                     "subject": case.get("subject"),
                     "no_yue": _is_no_yue_case(case), "conflicts": reasons})
        if reasons:
            conflicts.append({"id": case.get("id"), "name": case.get("name"),
                              "reasons": reasons})
    return {
        "cases": rows,
        "conflicts": conflicts,
        "ok": not conflicts,
        "corpus": {"descs": len(descs), "names": len(names)},
        "pools": {"count": len(case_pools)},
        "used_clean_baseline": not descs and not names,
    }


def _verify_frozen_cases(cases=None):
    """冻结自检：逐例核对 desc_sha256 与 target_blocks，返回问题列表（空 = 冻结一致）。"""
    problems = []
    for case in (cases if cases is not None else R_CASES):
        cid = case.get("id")
        digest = _desc_sha256(case.get("desc"))
        if case.get("desc_sha256") != digest:
            problems.append(f"{cid} desc_sha256 与需求原文不一致")
        parsed = parse_target_blocks(case.get("desc"))
        if parsed != case.get("target_blocks"):
            problems.append(f"{cid} 原文解析目标块数 {parsed} != 冻结 target_blocks "
                            f"{case.get('target_blocks')}")
    return problems


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
        frozen = _verify_frozen_cases()
        if frozen:
            print("[冻结失败] " + "；".join(frozen))
            return 1
        report = audit_r_cases()
        if report["used_clean_baseline"]:
            print("未执行完整新颖性审计：缺少历史语料（公开仓应存在 "
                  "test/fixtures/public/history-corpus.json）。")
            return 0 if "--allow-empty" in argv else 2
        print(f"基准语料：历史需求 {report['corpus']['descs']} 条、"
              f"模型名称/特征 {report['corpus']['names']} 条、"
              f"既有案例池 {report['pools']['count']} 例\n")
        for row in report["cases"]:
            tag = "无约" if row["no_yue"] else "含约"
            if row["conflicts"]:
                print(f"[冲突] {row['id']} {row['name']}（{tag}）：")
                for c in row["conflicts"]:
                    print("   -", c)
            else:
                print(f"[OK] {row['id']} {row['name']}（{tag}）：主题与历史语料/案例池无冲突")
        print(f"\n共 {len(report['cases'])} 例，冲突 {len(report['conflicts'])} 例；"
              f"冻结哈希与目标块数自检通过")
        return 0 if report["ok"] else 1
    if "--list" in argv:
        for c in R_CASES:
            tag = "无约" if _is_no_yue_case(c) else "含约"
            print(f"{c['id']} {c['name']:8s} {tag} 目标={c['target_blocks']:3d}块 "
                  f"部位≥{c['min_parts']:2d} 体素回归参考≥{c['min_voxels']:4d} "
                  f"压力={'/'.join(c['stress'])}  {c['desc'][:30]}…")
        print(f"\n共 {len(R_CASES)} 例；无「约」{sum(1 for c in R_CASES if _is_no_yue_case(c))} 例")
        return 0
    print(json.dumps([{k: c[k] for k in ("id", "name", "subject", "desc", "target_blocks",
                                        "desc_sha256")} for c in R_CASES],
                     ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    import sys
    sys.exit(main())
