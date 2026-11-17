# -*- coding: utf-8 -*-
"""20 个全新复杂造型案例定义（浏览器真实 LLM 端到端验收的设计单源）。

设计约束：
  1. 主题必须是此前从未生成过的对象 —— 与 artifacts/ 历史模型、历史任务需求、
     历史运行记录逐条比对（`python -m tools.e2e_cases_20 --novelty`）；
  2. 尽量复杂：每例显式要求 10~15 个可辨识部位、中空/斜面/悬挑/成对/多层收分等
     至少两类结构特征，目标 260~440 块积木（对照存量复杂模型部位数 12~16、
     体素 2000~3300、算子 30~100 的包络）；
  3. 案例描述是最终提交给 Web 工坊的真实用户输入，必须能通过固定主链的硬约束：
     颜色来自零件库 16 色、无透明材质、无文字、无超长无支撑悬臂、模型 6-连通；
  4. 每例都给出一组「结果正确性」断言（require_parts + checks + 复杂度下限），
     由 tools/e2e_assert_20.py 执行，拒绝“跑通即通过”。
     收分不使用 slope_min：斜面体素不足不算断言失败。描述里的「正斜坡砖」保持原句。

案例字段约定：
  id/name/subject/desc      案例编号、中文名、主题关键词（novelty 审计用）、用户需求原文
  complexity                复杂度设计说明（写进验收表）
  min_parts/min_solid_parts/min_voxels/min_ops   复杂度下限（对照实际产物）
  require_parts             [(检查名, (id/名称关键词...)), ...] 部位存在性断言
  checks                    [["check_name", args...], ...] 几何/配色/结构断言
"""
from __future__ import annotations

CASES = [
    {
        "id": "C01", "name": "大本钟钟楼", "subject": "大本钟",
        "desc": "一座大本钟钟楼：米白色石砌方形塔身高耸，塔身四面有狭长拱窗，上部四面各嵌一面白色圆形钟盘（钟盘与指针为表面涂装细节）"
                "与黑色指针，钟盘上方有装饰檐口与金色饰带，四角有壁柱，塔顶为深灰色四坡尖顶并用正斜坡砖收尖、立金色塔尖，"
                "底部正面有拱形大门与三级台阶，钟盘四周有石雕栏杆，目标约 380 块积木",
        "complexity": "方形高塔多层收分 + 四面钟盘表面涂装 + 拱窗/拱门中空 + 四坡尖顶斜面 + 壁柱/栏杆细节",
        "min_parts": 11, "min_solid_parts": 8, "min_voxels": 900, "min_ops": 18,
        "require_parts": [
            ("塔身", ("塔身", "塔楼", "tower", "body")),
            ("钟盘", ("钟盘", "钟面", "表盘", "clock")),
            ("指针", ("指针", "hand")),
            ("尖顶", ("尖顶", "屋顶", "spire", "roof")),
            ("塔尖", ("塔尖", "尖塔", "finial")),
            ("拱窗", ("拱窗", "窗", "window")),
            ("大门", ("大门", "门", "door")),
            ("台阶", ("台阶", "step")),
            ("壁柱", ("壁柱", "柱", "column", "pillar")),
            ("檐口", ("檐口", "檐", "cornice")),
            ("栏杆", ("栏杆", "rail")),
        ],
        "checks": [["layers_min", 10], ["surface_parts_min", 1],
                   ["colors_distinct_min", 3]],
    },
    {
        "id": "C02", "name": "应县木塔", "subject": "应县木塔",
        "desc": "一座五层六檐木塔：方形浅灰色石台基上立五层深棕色塔身，逐层向上收窄，每层屋檐向四面挑出、"
                "屋面用正斜坡砖收尖，层间设斗拱与木栏杆，四面开拱门与直棂窗，塔顶立金属塔刹、相轮与宝珠，"
                "内部各层中空，目标约 420 块积木",
        "complexity": "五层收分塔身 + 六重挑檐斜面 + 斗拱/栏杆 + 四面中空门窗 + 塔刹相轮宝珠",
        "min_parts": 11, "min_solid_parts": 8, "min_voxels": 1800, "min_ops": 25,
        "require_parts": [
            ("台基", ("台基", "基座", "base")),
            ("塔身", ("塔身", "塔", "body")),
            ("屋檐", ("檐", "roof")),
            ("斗拱", ("斗拱", "bracket")),
            ("栏杆", ("栏杆", "rail")),
            ("拱门", ("拱门", "门", "door")),
            ("直棂窗", ("直棂窗", "窗", "window")),
            ("塔刹", ("塔刹", "刹", "finial")),
            ("相轮", ("相轮", "ring")),
            ("宝珠", ("宝珠", "珠", "bead")),
        ],
        "checks": [["layers_min", 10], ["tiered_min", 3],
                   ["enclosed_interior_min", 1], ["op_count_min", 25]],
    },
    {
        "id": "C03", "name": "天坛祈年殿", "subject": "祈年殿",
        "desc": "一座三重檐圆形大殿：三层米白色圆形台基逐层收小，台基上立圆形红墙大殿，正面开三座拱门，"
                "四周环绕红色柱廊与汉白玉栏杆，殿顶为三重蓝色琉璃瓦圆顶逐层收分，顶部立金色宝顶，"
                "屋面用斜面砖收出弧形轮廓，目标约 360 块积木",
        "complexity": "圆形台基/墙/三重圆顶多用圆柱与收分 + 三拱门 + 柱廊栏杆 + 蓝/红/白三色分区",
        "min_parts": 10, "min_solid_parts": 7, "min_voxels": 1500, "min_ops": 20,
        "require_parts": [
            ("台基", ("台基", "基座", "base")),
            ("红墙", ("红墙", "墙", "wall")),
            ("拱门", ("拱门", "门", "door")),
            ("柱廊", ("柱廊", "柱", "column")),
            ("栏杆", ("栏杆", "rail")),
            ("圆顶", ("圆顶", "屋顶", "roof", "dome")),
            ("宝顶", ("宝顶", "顶", "finial")),
        ],
        "checks": [["cylinder_ops_min", 2], ["layers_min", 8],
                   ["colors_distinct_min", 3], ["op_count_min", 20]],
    },
    {
        "id": "C04", "name": "巴黎凯旋门", "subject": "凯旋门",
        "desc": "一座大型石砌凯旋门：正面中央为贯通的大型拱门、可容纳通行，两侧是厚重墩柱，墩柱表面有浮雕带"
                "与柱式线脚，顶部有檐口与顶楼，顶楼两端各立一组雕塑，中央拱门两侧各开一座小拱门，"
                "基座前有五级台阶，整体米白色石材，目标约 320 块积木",
        "complexity": "贯通大拱门（y=0 双墩分离）+ 小拱门 + 墩柱/浮雕带/檐口/顶楼 + 台阶",
        "min_parts": 10, "min_solid_parts": 7, "min_voxels": 1300, "min_ops": 18,
        "require_parts": [
            ("主拱门", ("主拱门", "拱门", "central_arch", "arch")),
            ("墩柱", ("墩柱", "柱", "pier")),
            ("浮雕带", ("浮雕", "relief")),
            ("装饰线脚", ("线脚", "molding", "trim")),
            ("檐口", ("檐口", "檐", "cornice")),
            ("顶楼", ("顶楼", "顶", "attic")),
            ("雕塑", ("雕塑", "雕像", "statue")),
            ("小拱门", ("小拱门", "侧拱", "side_arch")),
            ("台阶", ("台阶", "step")),
        ],
        "checks": [["ground_components_min", 2], ["layers_min", 6],
                   ["color_ratio_min", "MW", 0.35], ["op_count_min", 18]],
    },
    {
        "id": "C05", "name": "海边灯塔", "subject": "灯塔",
        "desc": "一座海边白色灯塔：圆形塔身自下而上略微收分，塔身交替刷红色环带，塔顶为黑色灯室与环绕玻璃窗（玻璃窗为深色表面涂装），"
                "灯室外有环形观景平台与金属栏杆，塔身沿高度开小窗，底部有木门，底座是灰色礁石堆，"
                "塔顶立风向天线，旁边连着低矮的看守小屋，目标约 300 块积木",
        "complexity": "圆柱塔身收分 + 红白环带配色 + 灯室/观景平台/栏杆 + 礁石基座 + 看守小屋",
        # 部位下限（按需求原文重算）：
        #   需求点名 11 项，其中「红色环带」是塔身配色特征（不占独立部位，由
        #   red_band_alternating 检查）；「玻璃窗」是表面涂装（surface 计 1 个部位）；
        #   「环形观景平台」与「金属栏杆」允许合并为 1 个部位。
        #   总部位 = 塔身/灯室/玻璃窗(surface)/平台/栏杆/小窗/木门/礁石/天线/小屋 = 10，
        #   合并平台+栏杆后 = 9；立体部位 = 总部位 - 玻璃窗 = 8。不得靠红环带凑数量。
        "min_parts": 9, "min_solid_parts": 8, "min_voxels": 1300, "min_ops": 18,
        "require_parts": [
            ("塔身", ("塔身", "塔", "body")),
            ("灯室", ("灯室", "灯", "lantern")),
            ("观景平台", ("平台", "platform")),
            ("栏杆", ("栏杆", "rail")),
            ("小窗", ("小窗", "窗", "window")),
            ("木门", ("木门", "门", "door")),
            ("礁石", ("礁石", "岩石", "rock")),
            ("天线", ("天线", "antenna")),
            ("看守小屋", ("小屋", "hut", "house")),
        ],
        "checks": [["cylinder_ops_min", 1], ["layers_min", 9],
                   ["color_ratio_min", "WR", 0.5], ["colors_distinct_min", 3],
                   ["red_band_alternating", ("塔身", "圆形塔身", "tower"), "R", "W", 2, 0.8]],
    },
    {
        "id": "C06", "name": "荷兰风车磨坊", "subject": "风车磨坊",
        "desc": "一座荷兰风车磨坊：石砌圆形磨坊塔身，深灰色锥形屋顶，屋顶正面伸出十字形四片木制风叶，"
                "每片风叶带横向木条与斜撑，磨坊一侧有环形工作平台与木栏杆，塔身底部开小门与两扇窗，"
                "石砌基座旁连着一间低矮的磨坊主小屋，目标约 320 块积木",
        "complexity": "圆形塔身 + 锥形屋顶 + 十字四叶真实悬挑 + 环形平台栏杆 + 附属小屋",
        "min_parts": 10, "min_solid_parts": 7, "min_voxels": 1300, "min_ops": 18,
        "require_parts": [
            ("塔身", ("塔身", "磨坊", "mill", "body")),
            ("锥形屋顶", ("锥", "屋顶", "roof")),
            ("风叶", ("风叶", "blade", "sail")),
            ("风叶横条", ("木条", "横板", "横撑", "crossbar", "frame")),
            ("工作平台", ("平台", "platform")),
            ("栏杆", ("栏杆", "rail")),
            ("小门", ("门", "door")),
            ("窗", ("窗", "window")),
            ("基座", ("基座", "base")),
            ("小屋", ("小屋", "house")),
        ],
        "checks": [["cylinder_ops_min", 1], ["part_spans_two_axes", ("风叶", "blade"), 4],
                   ["layers_min", 8], ["op_count_min", 18]],
    },
    {
        "id": "C07", "name": "三间四柱牌坊", "subject": "牌坊",
        "desc": "一座三间四柱中式牌坊：四根石柱立在石基座上，柱脚前后有抱鼓石，明间高、两次间低，"
                "柱顶横架额枋与花板，明间额枋上嵌匾额（匾额为表面涂装），上方是三重歇山顶，屋顶用斜面砖做出飞檐翘角，"
                "明间下方留可通行的门洞，目标约 300 块积木",
        "complexity": "四柱三间开间 + 抱鼓石/额枋/花板/匾额 + 三重歇山飞檐斜面 + 明间通行门洞",
        # 部位下限（按需求原文重算）：
        #   需求点名 7 组部位：四根石柱、石基座、抱鼓石、额枋、花板、匾额(surface)、三重歇山顶。
        #   「门洞」是负空间贯通特征、「飞檐」是屋顶斜面/出挑方向特征，二者都不是独立部位，
        #   分别由 negative_space_passage / eave_slope_overhang 检查，不得拿来凑部位数量；
        #   额枋与花板允许合并为 1 个部位。故总部位 = 6（5 立体 + 匾额 surface），立体 ≥5。
        "min_parts": 6, "min_solid_parts": 5, "min_voxels": 1200, "min_ops": 18,
        "require_parts": [
            ("石柱", ("柱", "column", "pillar")),
            ("石基座", ("基座", "base", "台基")),
            ("抱鼓石", ("抱鼓", "drum")),
            ("额枋", ("额枋", "beam", "lintel")),
            ("花板", ("花板", "panel")),
            ("匾额", ("匾额", "plaque")),
            ("歇山顶", ("歇山", "屋顶", "roof")),
        ],
        "checks": [["layer_components_min", 3], ["layers_min", 7],
                   ["op_count_min", 18],
                   ["negative_space_passage", ("柱", "基座", "column", "base"), "xz", 3, 1, 3],
                   ["eave_slope_overhang", ("歇山", "屋顶", "roof"), ("柱", "column", "pillar"),
                    1, 8, 2]],
    },
    {
        "id": "C08", "name": "老式蒸汽火车头", "subject": "蒸汽火车头",
        "desc": "一台老式蒸汽火车头：横卧的深绿色圆柱形锅炉，前端有圆形烟箱门与黑色斜面板排障器，锅炉上方立烟囱"
                "与汽包，中部驾驶室带侧窗与顶棚，底部前后各有大动轮、小导轮与连接杆，车头前有前照灯与汽笛，"
                "后部挂煤水车，车轮与车架黑色，整体停在铁轨上，目标约 400 块积木",
        "complexity": "圆柱锅炉 + 烟囱/汽包/烟箱门 + 驾驶室 + 动轮导轮连杆 + 排障器斜面 + 煤水车 + 铁轨",
        "min_parts": 12, "min_solid_parts": 9, "min_voxels": 1600, "min_ops": 22,
        "require_parts": [
            ("锅炉", ("锅炉", "boiler")),
            ("烟箱门", ("烟箱", "smokebox")),
            ("排障器", ("排障", "cowcatcher", "pilot")),
            ("烟囱", ("烟囱", "chimney", "stack")),
            ("汽包", ("汽包", "dome")),
            ("驾驶室", ("驾驶室", "cab")),
            ("大动轮", ("动轮", "driver", "wheel")),
            ("小导轮", ("导轮", "pilot_wheel", "leading")),
            ("连接杆", ("连接杆", "连杆", "rod")),
            ("前照灯", ("前照灯", "headlight", "lamp")),
            ("汽笛", ("汽笛", "whistle")),
            ("煤水车", ("煤水车", "tender")),
            ("铁轨", ("铁轨", "rail", "track")),
        ],
        "checks": [["cylinder_ops_min", 2],
                   ["part_box_count_min", ("大动轮", "动轮", "导轮", "driver", "wheel"), 4],
                   ["parts_min", 12]],
    },
    {
        "id": "C09", "name": "伦敦红色双层巴士", "subject": "双层巴士",
        "desc": "一辆伦敦红色双层巴士：方正上下两层车厢，上层有连续车窗与车顶通风口，下层有前门、中门与侧窗，"
                "车身两侧各两个黑色车轮，车头有挡风玻璃、车灯与目的地牌（车灯与目的地牌为表面涂装细节），车尾有后梯窗，"
                "车顶前沿有弧形遮阳板，车身有白色分隔线与深色窗框，目标约 300 块积木",
        "complexity": "双层体量 + 连续车窗 + 前后车门 + 四轮 + 车头标识牌 + 白色分隔线配色",
        "min_parts": 10, "min_solid_parts": 7, "min_voxels": 1300, "min_ops": 18,
        "require_parts": [
            ("车身", ("车身", "body", "bus")),
            ("上层车窗", ("上层窗", "窗", "window")),
            ("前门", ("前门", "door")),
            ("中门", ("中门", "door")),
            ("侧窗", ("侧窗", "窗", "window")),
            ("车轮", ("车轮", "轮", "wheel")),
            ("挡风玻璃", ("挡风", "windshield")),
            ("车灯", ("车灯", "灯", "light")),
            ("目的地牌", ("目的地", "destination", "sign")),
            ("后梯窗", ("后梯", "楼梯", "stair")),
            ("遮阳板", ("遮阳", "visor", "awning")),
        ],
        "checks": [["layers_min", 7], ["part_box_count_min", ("车轮", "轮", "wheel"), 4],
                   ["colors_distinct_min", 3], ["op_count_min", 18]],
    },
    {
        "id": "C10", "name": "矿用自卸卡车", "subject": "矿用自卸卡车",
        "desc": "一辆大型矿用自卸卡车：低矮前部驾驶室带斜挡风玻璃与顶部护栏，后方巨大 V 形橙色车斗，"
                "车斗前端有加高挡板，两侧有登车楼梯与走台，车架装两个前轮与四个后轮，黑色巨型轮胎配深灰色轮毂，"
                "车头有散热格栅、前灯与保险杠，目标约 380 块积木",
        "complexity": "驾驶室 + V 形车斗斜面 + 六轮 + 楼梯走台 + 格栅灯组 + 橙/黑/深灰配色",
        "min_parts": 12, "min_solid_parts": 9, "min_voxels": 1600, "min_ops": 22,
        "require_parts": [
            ("驾驶室", ("驾驶室", "cab")),
            ("挡风玻璃", ("挡风", "windshield")),
            ("护栏", ("护栏", "rail")),
            ("V形车斗", ("车斗", "bed", "dump")),
            ("挡板", ("挡板", "front_board", "board")),
            ("楼梯", ("楼梯", "stair", "ladder")),
            ("走台", ("走台", "walkway")),
            ("前轮", ("前轮", "front")),
            ("后轮", ("后轮", "rear")),
            ("散热格栅", ("格栅", "grille")),
            ("前灯", ("前灯", "灯", "light")),
            ("保险杠", ("保险杠", "bumper")),
        ],
        # 轮毂不是独立部位而是轮组的异色可见细节：改为「与轮胎异色 + 外露 + 与轮胎体素相邻」
        # 的结果几何检查，不再要求部位清单里恰好有「轮毂」。
        "checks": [["part_box_count_min", ("前轮", "后轮", "轮", "wheel"), 4], ["parts_min", 12],
                   ["hub_contrast_adjacent", ("前轮", "后轮", "轮", "wheel"), "K", "D", 1],
                   ["colors_distinct_min", 3], ["op_count_min", 22]],
    },
    {
        "id": "C11", "name": "蒸汽朋克飞艇", "subject": "蒸汽朋克飞艇",
        "desc": "一艘停在地面的蒸汽朋克飞艇：巨大的银色雪茄形气囊横卧，气囊尾部装十字形尾翼与方向舵，"
                "气囊下方由四根黄铜支架架在黄铜吊舱上方，吊舱有一排圆形舷窗（舷窗为表面涂装）、前部探照灯与侧面螺旋桨，"
                "吊舱后方有蒸汽烟囱与舵轮，气囊前部有铜制撞角，目标约 360 块积木",
        "complexity": "横卧雪茄气囊（长跨圆柱/放样）+ 十字尾翼 + 四支架 + 吊舱舷窗/螺旋桨/烟囱/舵轮 + 铜银配色",
        "min_parts": 10, "min_solid_parts": 7, "min_voxels": 1500, "min_ops": 20,
        "require_parts": [
            ("气囊", ("气囊", "balloon", "envelope")),
            ("尾翼", ("尾翼", "fin", "tail")),
            ("方向舵", ("方向舵", "rudder")),
            ("支架", ("支架", "strut", "mount")),
            ("吊舱", ("吊舱", "gondola", "cabin")),
            ("舷窗", ("舷窗", "porthole", "window")),
            ("探照灯", ("探照灯", "searchlight", "lamp")),
            ("螺旋桨", ("螺旋桨", "propeller", "prop")),
            ("烟囱", ("烟囱", "chimney", "stack")),
            ("舵轮", ("舵轮", "helm", "wheel")),
            ("撞角", ("撞角", "ram")),
        ],
        # 气囊横卧：长跨用水平轴 "xz"（单一长条部位的最大水平跨度即其长度，
        # 不是组合体，不能被别的部位横向宽度顶替）；圆柱算子改为可复现的雪茄形收分几何检查。
        "checks": [["cigar_taper_min", ("气囊", "balloon", "envelope"), 10, 2.0, 0.6],
                   ["part_span_min", ("气囊", "balloon", "envelope"), 10, "xz"],
                   ["layers_min", 8], ["op_count_min", 20]],
    },
    {
        "id": "C12", "name": "履带式挖掘机", "subject": "挖掘机",
        "desc": "一台黄色履带式挖掘机：底部双履带带负重轮，履带上方旋转平台装深色玻璃驾驶室与后部配重，"
                "前部粗壮动臂向前下方伸出，动臂端部连接斗杆向下折，末端带斗齿的铲斗落在地面附近，"
                "动臂与斗杆间有液压缸，车顶有警示灯与排气管，履带与斗齿黑色，目标约 360 块积木",
        "complexity": "双履带/负重轮 + 旋转平台 + 驾驶室 + 动臂/斗杆/铲斗多段悬挑 + 液压缸 + 警示灯排气管",
        "min_parts": 11, "min_solid_parts": 8, "min_voxels": 1400, "min_ops": 20,
        "require_parts": [
            ("履带", ("履带", "track")),
            ("负重轮", ("负重轮", "roller", "wheel")),
            ("旋转平台", ("旋转平台", "平台", "platform")),
            ("驾驶室", ("驾驶室", "cab")),
            ("配重", ("配重", "counterweight")),
            ("动臂", ("动臂", "boom")),
            ("斗杆", ("斗杆", "stick", "arm")),
            ("铲斗", ("铲斗", "bucket")),
            ("斗齿", ("斗齿", "tooth", "teeth")),
            ("液压缸", ("液压", "cylinder", "hydraulic")),
            ("警示灯", ("警示灯", "灯", "warning")),
            ("排气管", ("排气管", "exhaust")),
        ],
        "checks": [["part_overhang_min", ("动臂", "斗杆", "铲斗", "boom", "arm", "bucket"), 2],
                   ["part_box_count_min", ("履带", "track"), 2], ["parts_min", 11], ["op_count_min", 20]],
    },
    {
        "id": "C13", "name": "云梯消防车", "subject": "云梯消防车",
        "desc": "一辆红色云梯消防车：驾驶室带宽大挡风玻璃与车顶警灯（警灯为表面涂装小色点），车身两侧有卷帘门与工具箱，"
                "车顶转台托着多节云梯，云梯斜向上伸出车体并带两侧梯轨与梯级，车尾有水泵与水带接口，"
                "底部前后各两个黑色车轮，车头有前灯与保险杠，目标约 340 块积木",
        "complexity": "驾驶室 + 卷帘门/工具箱 + 多节斜向云梯（真实悬挑）+ 水泵接口 + 四轮 + 警灯灯组",
        "min_parts": 12, "min_solid_parts": 9, "min_voxels": 1400, "min_ops": 22,
        "require_parts": [
            ("驾驶室", ("驾驶室", "cab")),
            ("挡风玻璃", ("挡风", "windshield")),
            ("警灯", ("警灯", "light", "beacon")),
            ("卷帘门", ("卷帘门", "shutter", "door")),
            ("工具箱", ("工具箱", "toolbox")),
            ("转台", ("转台", "turntable")),
            ("云梯", ("云梯", "ladder")),
            ("梯轨", ("梯轨", "rail")),
            ("梯级", ("梯级", "rung", "step")),
            ("水泵", ("水泵", "pump")),
            ("水带接口", ("水带", "hose")),
            ("车轮", ("车轮", "轮", "wheel")),
            ("前灯", ("前灯", "灯", "light")),
            ("保险杠", ("保险杠", "bumper")),
        ],
        "checks": [["part_overhang_min", ("云梯", "ladder"), 3],
                   ["part_box_count_min", ("车轮", "轮", "wheel"), 4], ["parts_min", 12],
                   ["op_count_min", 22]],
    },
    {
        "id": "C14", "name": "救援直升机", "subject": "救援直升机",
        "desc": "一架红白涂装的救援直升机：流线型机身，前部大玻璃驾驶舱，机顶主旋翼，尾部细长尾梁接尾桨，"
                "机身两侧短翼挂架，底部起落架滑橇，侧面舱门与救援绞车，机头雷达罩与探照灯，"
                "机身白色、侧面橙色条纹，目标约 320 块积木",
        "complexity": "流线机身 + 驾驶舱 + 顶部主旋翼长跨 + 尾梁尾桨 + 短翼挂架 + 滑橇起落架 + 绞车雷达罩",
        "min_parts": 10, "min_solid_parts": 7, "min_voxels": 1300, "min_ops": 20,
        "require_parts": [
            ("机身", ("机身", "body", "fuselage")),
            ("驾驶舱", ("驾驶舱", "cockpit", "canopy")),
            ("主旋翼", ("主旋翼", "rotor", "blade")),
            ("尾梁", ("尾梁", "tail", "boom")),
            ("尾桨", ("尾桨", "tail_rotor", "tail rotor")),
            ("短翼", ("短翼", "stub", "wing")),
            ("起落架滑橇", ("滑橇", "skid", "landing")),
            ("舱门", ("舱门", "door")),
            ("救援绞车", ("绞车", "winch")),
            ("雷达罩", ("雷达", "radar")),
            ("探照灯", ("探照灯", "searchlight", "lamp")),
        ],
        # 主旋翼水平展开（x/z 取最大，旋翼盘水平）；尾梁沿机身纵向 z（机身为 z=13 长轴）。
        "checks": [["part_span_min", ("主旋翼", "rotor"), 6, "xz"],
                   ["part_span_min", ("尾梁", "boom"), 5, "z"],
                   ["part_box_count_min", ("滑橇", "skid", "起落架"), 2],
                   ["colors_distinct_min", 3]],
    },
    {
        "id": "C15", "name": "复古机械打字机", "subject": "打字机",
        "desc": "一台复古机械打字机：深灰色金属机身，前部三排圆形米白色按键，机身中部黑色字锤组，"
                "后方横向黑色滚筒与两侧卷纸旋钮，右侧有回车杆，侧面色带轴与调节旋钮，底部深棕色木质底座，"
                "键盘上方有金属铭牌（铭牌为表面涂装），机身后部抬起呈斜面，目标约 260 块积木",
        "complexity": "三排按键 + 字锤组 + 滚筒卷纸旋钮 + 回车杆 + 色带轴 + 铭牌表面细节 + 后部斜面",
        "min_parts": 9, "min_solid_parts": 6, "min_voxels": 1000, "min_ops": 16,
        "require_parts": [
            ("机身", ("机身", "body")),
            ("按键", ("按键", "键", "key")),
            ("字锤", ("字锤", "typebar", "hammer")),
            ("滚筒", ("滚筒", "roller", "platen")),
            ("卷纸旋钮", ("卷纸", "knob", "旋钮")),
            ("回车杆", ("回车", "return", "lever")),
            ("色带轴", ("色带", "ribbon")),
            ("调节旋钮", ("旋钮", "knob", "dial")),
            ("木质底座", ("底座", "base")),
            ("金属铭牌", ("铭牌", "plaque", "nameplate")),
        ],
        "checks": [["surface_parts_min", 1], ["parts_min", 9],
                   ["colors_distinct_min", 4]],
    },
    {
        "id": "C16", "name": "老式留声机", "subject": "留声机",
        "desc": "一台老式留声机：深棕色木制方形箱体，顶部黑色唱盘与银色唱臂，唱臂末端圆形唱头，"
                "箱体正面有雕花装饰板与黄铜铭牌（铭牌为表面涂装），侧面有摇柄与黄铜旋钮，上方巨大的黄铜喇叭呈锥形向外张开，"
                "喇叭口边缘有波纹，底座四角有铜脚，目标约 280 块积木",
        "complexity": "木箱 + 唱盘/唱臂/唱头 + 锥形大喇叭 + 摇柄/旋钮/铜脚 + 雕花铭牌细节 + 木铜双材质配色",
        "min_parts": 9, "min_solid_parts": 6, "min_voxels": 1000, "min_ops": 18,
        "require_parts": [
            ("木箱", ("木箱", "箱体", "box", "case")),
            ("唱盘", ("唱盘", "turntable", "record")),
            ("唱臂", ("唱臂", "tonearm", "arm")),
            ("唱头", ("唱头", "cartridge", "head")),
            ("雕花装饰板", ("雕花", "装饰", "carving")),
            ("铭牌", ("铭牌", "plaque")),
            ("摇柄", ("摇柄", "crank", "handle")),
            ("旋钮", ("旋钮", "knob")),
            ("喇叭", ("喇叭", "horn")),
            ("铜脚", ("铜脚", "feet", "foot")),
        ],
        "checks": [["cylinder_ops_min", 1], ["parts_min", 9],
                   ["colors_distinct_min", 3], ["op_count_min", 18]],
    },
    {
        "id": "C17", "name": "街机游戏机", "subject": "街机游戏机",
        "desc": "一台街机游戏机：黑色高柜体，上部斜置屏幕发出蓝绿色光（屏幕与按钮为表面涂装细节），屏幕上方红色发光灯箱，"
                "中部控制台有摇杆与六个彩色按钮，下部投币口与出币口，柜体侧面有彩色条纹与扬声器格栅，"
                "底部脚轮，背面有散热孔，目标约 260 块积木",
        "complexity": "高柜体 + 斜置屏幕 + 发光灯箱 + 摇杆六键控制台 + 投币出币口 + 条纹/格栅/脚轮多细节",
        "min_parts": 10, "min_solid_parts": 7, "min_voxels": 1000, "min_ops": 16,
        "require_parts": [
            ("柜体", ("柜体", "cabinet", "body")),
            ("屏幕", ("屏幕", "screen", "display")),
            ("灯箱", ("灯箱", "marquee", "lightbox")),
            ("控制台", ("控制台", "console", "panel")),
            ("摇杆", ("摇杆", "joystick", "stick")),
            ("按钮", ("按钮", "button")),
            ("投币口", ("投币", "coin")),
            ("出币口", ("出币", "coin")),
            ("条纹", ("条纹", "stripe")),
            ("扬声器格栅", ("扬声器", "喇叭", "speaker", "grille")),
            ("脚轮", ("脚轮", "caster", "wheel")),
            ("散热孔", ("散热", "vent")),
        ],
        "checks": [["colors_distinct_min", 4], ["parts_min", 10], ["surface_parts_min", 1]],
    },
    {
        "id": "C18", "name": "海边天文台", "subject": "天文台",
        "desc": "一座海边天文台：圆形石砌基座建筑，顶部是半球形银灰色圆顶，圆顶开一道观测缝与可滑动天窗，"
                "建筑正面有拱门与台阶，圆顶下方有一圈栏杆与望远镜镜筒，侧面有观测窗与排水管，"
                "屋顶立风向标与避雷针，目标约 300 块积木",
        "complexity": "圆形基座 + 半球圆顶（圆柱收分）+ 观测缝/天窗 + 拱门台阶 + 栏杆镜筒 + 风向标避雷针",
        "min_parts": 11, "min_solid_parts": 8, "min_voxels": 1100, "min_ops": 18,
        "require_parts": [
            ("基座建筑", ("基座", "建筑", "base")),
            ("圆顶", ("圆顶", "dome", "roof")),
            ("观测缝", ("观测缝", "缝", "slit")),
            ("天窗", ("天窗", "shutter", "window")),
            ("拱门", ("拱门", "door")),
            ("台阶", ("台阶", "step")),
            ("栏杆", ("栏杆", "rail")),
            ("望远镜镜筒", ("镜筒", "telescope", "tube")),
            ("观测窗", ("观测窗", "窗", "window")),
            ("排水管", ("排水", "drain", "pipe")),
            ("风向标", ("风向标", "vane", "weather")),
            ("避雷针", ("避雷针", "lightning", "rod")),
        ],
        # 半球圆顶用圆柱收分表达（案例原文未要求斜面砖），不设 slope 断言，以圆柱体元验证
        "checks": [["cylinder_ops_min", 2], ["layers_min", 7],
                   ["parts_min", 11]],
    },
    {
        "id": "C19", "name": "座头鲸", "subject": "座头鲸",
        "desc": "一头座头鲸：流线型黑白身体，背部黑色、腹部白色带纵向褶皱，头部有藤壶与喷气孔，"
                "巨大的胸鳍向两侧展开，尾鳍水平分叉并向上翘起，背部有小背鳍，眼睛、藤壶与喷气孔为表面涂装小色点，"
                "嘴部线条清晰，目标约 260 块积木",
        "complexity": "长跨流线躯体 + 黑白分区 + 两侧胸鳍展开 + 分叉尾鳍翘起 + 背鳍/藤壶/喷气孔/眼睛细节",
        "min_parts": 9, "min_solid_parts": 6, "min_voxels": 1000, "min_ops": 16,
        "require_parts": [
            ("身体", ("身体", "body", "torso")),
            ("腹部", ("腹部", "belly")),
            ("头部", ("头部", "head")),
            ("藤壶", ("藤壶", "barnacle")),
            ("喷气孔", ("喷气", "blowhole")),
            ("胸鳍", ("胸鳍", "fin")),
            ("尾鳍", ("尾鳍", "fluke", "tail")),
            ("背鳍", ("背鳍", "dorsal")),
            ("眼睛", ("眼睛", "眼", "eye")),
            ("嘴部", ("嘴", "mouth", "jaw")),
        ],
        # 躯体流线型：纵向沿 x（鲸体长轴，实际产物 x=21、z=10；x/z 都不是"横向宽度"，
        # 单一躯体部位取显式纵向轴 x，不能拿别的部位顶替），胸鳍左右成对。
        "checks": [["part_span_min", ("身体", "body", "torso"), 12, "x"],
                   ["both_sides", ("胸鳍", "fin")],
                   ["color_ratio_min", "K", 0.2], ["parts_min", 9]],
    },
    {
        "id": "C20", "name": "哥特式大教堂", "subject": "哥特式大教堂",
        "desc": "一座哥特式大教堂：正面两座对称钟楼，钟楼顶部尖塔，中央玫瑰窗（玫瑰窗为表面涂装）与尖拱大门，立面有扶壁"
                "与雕像壁龛，中部高耸中殿与两侧侧廊，飞扶壁连接侧廊与中殿，屋面深灰色，交叉处有尖顶，"
                "整体米白色石材，目标约 440 块积木",
        "complexity": "对称双钟楼 + 尖塔/交叉尖顶斜面 + 玫瑰窗表面 + 尖拱大门 + 中殿侧廊 + 飞扶壁薄壁 + 扶壁壁龛",
        "min_parts": 11, "min_solid_parts": 8, "min_voxels": 1800, "min_ops": 25,
        "require_parts": [
            ("钟楼", ("钟楼", "tower", "bell")),
            ("尖塔", ("尖塔", "spire")),
            ("玫瑰窗", ("玫瑰窗", "rose")),
            ("尖拱大门", ("尖拱", "大门", "door", "arch")),
            ("扶壁", ("扶壁", "buttress")),
            ("雕像壁龛", ("壁龛", "niche", "statue")),
            ("中殿", ("中殿", "nave")),
            ("侧廊", ("侧廊", "aisle")),
            ("飞扶壁", ("飞扶壁", "flying")),
            ("屋面", ("屋面", "roof")),
            ("交叉尖顶", ("交叉", "crossing", "flèche", "fleche")),
        ],
        "checks": [["paired_or_span", ("钟楼", "tower")],
                   ["layers_min", 10], ["surface_parts_min", 1], ["parts_min", 11]],
    },
]


def all_cases():
    """20 例 + 另补四例 + 第二批全新主题（H01–H10）。

    新颖性审计与 20 例注册表纪律仍只看 CASES；批次案例只是可被编号/原文找到，
    供 tools/e2e_browser_20.py 按 `--cases H01-H10` 挑选。
    """
    from tools.e2e_cases_batch2 import NEW_CASES
    from tools.e2e_cases_extra import EXTRA_CASES
    return list(CASES) + list(EXTRA_CASES) + list(NEW_CASES)


def find_case(case_id=None, desc=None):
    """按案例编号或需求原文查找案例；同时命中多个原文时要求显式给 --case。

    另补四例（C21–C24）也能按编号或原文命中，但不计入 20 例新颖性集合。
    """
    pool = all_cases()
    if case_id:
        for c in pool:
            if c["id"] == case_id.strip().upper():
                return c
        return None
    if desc is not None:
        hits = [c for c in pool if c["desc"] == desc]
        if len(hits) == 1:
            return hits[0]
    return None


def _campaign_scope(root):
    """本轮 20 例验收自己的运行产物范围：({需求原文集合}, {run_id 集合})。

    「此前没有生成过」必须以**本轮验收开始前**的历史语料为基准；冒烟/批次运行本身会
    写进 artifacts/ 与 jobs_store，因此 novelty 审计要把本轮验收产生的需求与 run
    排除，否则自己跑过的案例会被自己判成“已生成”。
    """
    import glob
    import json
    import os

    descs = {c["desc"] for c in CASES}
    runs = set()
    for path in glob.glob(os.path.join(root, "artifacts", "e2e-20", "**", "*.json"), recursive=True):
        try:
            with open(path, encoding="utf-8") as f:
                data = json.load(f)
        except (OSError, ValueError):
            continue
        if not isinstance(data, dict):
            continue
        if data.get("runId"):
            runs.add(str(data["runId"]))
        result = data.get("result") if isinstance(data.get("result"), dict) else {}
        if result.get("run_id"):
            runs.add(str(result["run_id"]))
        for attempt in result.get("attempts_detail") or []:
            if isinstance(attempt, dict) and attempt.get("run_id"):
                runs.add(str(attempt["run_id"]))
        for item in data.get("cases") or []:
            if isinstance(item, dict) and item.get("runId"):
                runs.add(str(item["runId"]))
    store = os.path.join(root, "artifacts", "jobs_store.json")
    if os.path.isfile(store):
        try:
            with open(store, encoding="utf-8") as f:
                for job in json.load(f).values():
                    if not isinstance(job, dict):
                        continue
                    result = job.get("result") if isinstance(job.get("result"), dict) else {}
                    if job.get("desc") not in descs and result.get("run_id") not in runs:
                        continue
                    if result.get("run_id"):
                        runs.add(str(result["run_id"]))
                    for attempt in result.get("attempts_detail") or []:
                        if isinstance(attempt, dict) and attempt.get("run_id"):
                            runs.add(str(attempt["run_id"]))
        except (OSError, ValueError):
            pass
    return descs, runs


def _history_data_roots(root):
    """历史运行数据的根目录列表。

    默认使用仓库根（artifacts/ 下的运行产物）；需要完整历史语料时，用环境变量
    LEGO_HISTORY_ROOT 指向外部数据根（多个用 os.pathsep 分隔）。缺少完整历史时
    novelty 审计应报告「未执行完整审计」，不能宣称审计通过。
    """
    import os

    env = os.environ.get("LEGO_HISTORY_ROOT")
    if env:
        return [part for part in env.split(os.pathsep) if part]
    return [root]


def _public_corpus_path():
    """公开审计语料路径：test/fixtures/public/history-corpus.json。"""
    import os

    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    return os.path.join(root, "test", "fixtures", "public", "history-corpus.json")


def _load_public_history_corpus(exclude_groups=None):
    """读取公开新颖性审计语料（由已发布源码中的冻结需求原文/主题词生成）。

    返回 (descs, names)；文件缺失/非法/排除后为空时返回 None。exclude_groups 用于
    排除本组自己的案例，避免跑过一次后自我撞题（默认排除 C 组）。
    公开语料不含 artifacts/ 运行记录，也不新增披露。
    """
    import json
    import os

    path = _public_corpus_path()
    if not os.path.isfile(path):
        return None
    try:
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
    except (OSError, ValueError):
        return None
    groups = data.get("groups") if isinstance(data, dict) else None
    if not isinstance(groups, dict) or not groups:
        return None
    excluded = set(exclude_groups) if exclude_groups is not None else {"C"}
    descs, names = [], []
    for group_id, group in groups.items():
        if group_id in excluded or not isinstance(group, dict):
            continue
        descs.extend(str(d) for d in (group.get("descs") or []) if str(d))
        names.extend(str(n) for n in (group.get("subjects") or []) if str(n))
    if not descs and not names:
        return None
    return descs, names


def _load_history_corpus(exclude_groups=None):
    """读取**本轮验收开始前**的历史语料（历史需求 + 模型名称/特征/主题），用于 novelty 审计。

    私有数据根（artifacts/ 与本地证据目录）存在时按其历史运行产物读取；干净检出
    （公开仓）没有运行产物，自动回退到公开审计语料
    `test/fixtures/public/history-corpus.json`（并由 exclude_groups 排除本组条目）。
    两者都缺失时返回空 (descs, names)，调用方必须报告「未执行完整审计」并失败，
    不能宣称审计通过。
    """
    import glob
    import json
    import os

    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    campaign_descs, campaign_runs = _campaign_scope(root)
    descs, names = [], []
    for data_root in _history_data_roots(root):
        store = os.path.join(data_root, "artifacts", "jobs_store.json")
        if os.path.isfile(store):
            try:
                with open(store, encoding="utf-8") as f:
                    for job in json.load(f).values():
                        if isinstance(job, dict) and job.get("desc"):
                            if job["desc"] in campaign_descs:
                                continue
                            if ((job.get("result") or {}).get("run_id")) in campaign_runs:
                                continue
                            descs.append(job["desc"])
            except (OSError, ValueError):
                pass
        for pattern in (os.path.join(data_root, "artifacts", "run_*.json"),
                        os.path.join(data_root, "artifacts", "e2e-history", "**", "run_*.json")):
            for path in glob.glob(pattern, recursive=True):
                try:
                    with open(path, encoding="utf-8") as f:
                        rec = json.load(f)
                    if isinstance(rec, dict) and rec.get("desc"):
                        if rec.get("runId") in campaign_runs or rec["desc"] in campaign_descs:
                            continue
                        descs.append(rec["desc"])
                except (OSError, ValueError):
                    pass
        for path in glob.glob(os.path.join(data_root, "artifacts", "model_*.json")):
            try:
                with open(path, encoding="utf-8") as f:
                    model = json.load(f)
                if isinstance(model, dict):
                    if model.get("runId") in campaign_runs:
                        continue
                    names.extend([str(model.get("name") or ""), str(model.get("slug") or "")]
                                 + [str(x) for x in (model.get("features") or [])])
            except (OSError, ValueError):
                pass
    if not descs and not names:
        public = _load_public_history_corpus(exclude_groups)
        if public is not None:
            return public
    return descs, names


def novelty_report():
    """对 20 个案例做主题/原文唯一性审计，返回 [(case, [冲突...]), ...]。"""
    descs, names = _load_history_corpus()
    if not descs and not names:
        return None
    report = []
    for case in CASES:
        conflicts = []
        if any(case["desc"] == d for d in descs):
            conflicts.append("需求原文与历史任务完全相同")
        subject = case["subject"]
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
    if "--novelty" in argv:
        report = novelty_report()
        if report is None:
            print("未执行完整新颖性审计：缺少历史语料（公开仓应存在 "
                  "test/fixtures/public/history-corpus.json；私有仓可设置 "
                  "LEGO_HISTORY_ROOT）。")
            return 0 if "--allow-empty" in argv else 2
        import os as _os
        root = _os.path.dirname(_os.path.dirname(_os.path.abspath(__file__)))
        descs, names = _load_history_corpus()
        campaign_descs, campaign_runs = _campaign_scope(root)
        print(f"基准语料（已排除本轮 20 例自己的 {len(campaign_descs)} 条需求 / "
              f"{len(campaign_runs)} 份 run）：历史需求 {len(descs)} 条、模型名称/特征 {len(names)} 条\n")
        bad = 0
        for case, conflicts in report:
            if conflicts:
                bad += 1
                print(f"❌ {case['id']} {case['name']}：")
                for c in conflicts:
                    print("   -", c)
            else:
                print(f"✅ {case['id']} {case['name']}：主题与历史语料无冲突")
        print(f"\n共 {len(report)} 例，冲突 {bad} 例")
        return 1 if bad else 0
    if "--list" in argv:
        for c in CASES:
            print(f"{c['id']} {c['name']:12s} 部位≥{c['min_parts']:2d} 体素≥{c['min_voxels']:4d} "
                  f"算子≥{c['min_ops']:2d}  {c['desc'][:46]}…")
        print(f"\n共 {len(CASES)} 例")
        return 0
    print(json.dumps([{k: c[k] for k in ("id", "name", "subject", "desc")} for c in CASES],
                     ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    import sys
    sys.exit(main())
