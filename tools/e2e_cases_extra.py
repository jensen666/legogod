# -*- coding: utf-8 -*-
"""修订版另补四例。

不放进 tools/e2e_cases_20.CASES：那 20 例有「此前从未生成过」的新颖性审计，
这四例是旧失败题，主题本来就在历史语料里。查找走 find_case，编号 C21–C24。
断言只用 e2e_assert_20 已注册的检查。checks 不含 slope_min。
"""

EXTRA_CASES = [
    {
        "id": "C21", "name": "现代主战坦克", "subject": "主战坦克",
        "desc": "一辆现代主战坦克：深灰色低矮车体，车体前部是倾斜正面装甲，两侧各一条黑色履带，"
                "履带外侧各有一块深灰色裙板，侧面装米白色反应装甲块，中央是向前收窄的楔形炮塔，"
                "炮塔正面伸出一根深灰色炮管，炮管根部加粗并与炮塔连成一体，不要做成无支撑的超长悬臂，"
                "炮塔顶部有舱盖，车尾有黑色散热格栅，目标约 360 块积木",
        "complexity": "两侧履带成对 + 楔形炮塔与加粗炮管 + 裙板/反应装甲/尾部格栅；颜色只用零件库深灰、黑、米白",
        "min_parts": 8, "min_solid_parts": 6, "min_voxels": 1200, "min_ops": 16,
        "require_parts": [
            ("车体", ("车体", "hull", "body")),
            ("履带", ("履带", "track")),
            ("裙板", ("裙板", "skirt")),
            ("反应装甲", ("反应装甲", "装甲", "armor")),
            ("炮塔", ("炮塔", "turret")),
            ("炮管", ("炮管", "barrel", "gun")),
            ("舱盖", ("舱盖", "hatch")),
            ("格栅", ("格栅", "grille")),
        ],
        "checks": [["both_sides", ("履带", "track")],
                   ["part_span_min", ("炮管", "barrel", "gun"), 4],
                   ["colors_distinct_min", 3], ["op_count_min", 16]],
    },
    {
        "id": "C22", "name": "多孔石拱桥", "subject": "石拱桥",
        "desc": "一座三孔石拱桥：浅灰色石砌，三个拱洞都从桥下贯通到另一侧，洞底不填砖，"
                "四座分水桥墩彼此分开并各自落到地面，桥墩迎水面是尖形破水，"
                "桥面用深灰色砖铺平并连过三孔，两侧立米白色石栏杆，目标约 320 块积木",
        "complexity": "底层至少四块分立桥墩（拱洞贯通到地面）+ 拱券/桥面/栏杆；不是一整块实心底座",
        "min_parts": 6, "min_solid_parts": 4, "min_voxels": 900, "min_ops": 12,
        "require_parts": [
            ("桥墩", ("桥墩", "墩", "pier")),
            ("拱券", ("拱券", "拱", "arch")),
            ("桥面", ("桥面", "deck")),
            ("栏杆", ("栏杆", "rail")),
            ("破水", ("破水", "cutwater")),
        ],
        "checks": [["ground_components_min", 4],
                   ["part_box_count_min", ("桥墩", "墩", "pier"), 4],
                   ["part_span_min", ("桥面", "deck"), 8],
                   ["layers_min", 4]],
    },
    {
        "id": "C23", "name": "中世纪城堡", "subject": "中世纪城堡",
        "desc": "一座中世纪城堡：浅灰色城墙围出中空内院，四个角各一座角楼，城墙顶上有垛口，"
                "正面一座深棕色大门，门洞穿过城墙进入内院，角楼顶是深灰色锥形屋顶，"
                "不要把内院填成实心方块，目标约 340 块积木",
        "complexity": "四座角楼 + 正面大门 + 内院围合中空；垛口与锥顶用斜面，不收成实心盒子",
        "min_parts": 6, "min_solid_parts": 4, "min_voxels": 900, "min_ops": 12,
        "require_parts": [
            ("城墙", ("城墙", "墙", "wall")),
            ("角楼", ("角楼", "tower")),
            ("垛口", ("垛口", "battlement", "crenel")),
            ("大门", ("大门", "门", "gate", "door")),
            ("屋顶", ("屋顶", "roof")),
        ],
        "checks": [["part_box_count_min", ("角楼", "tower"), 4],
                   ["enclosed_interior_min", 1],
                   ["layers_min", 6]],
    },
    {
        "id": "C24", "name": "蒸汽朋克八音盒", "subject": "八音盒",
        "desc": "一台蒸汽朋克八音盒：深棕色木质底座，黄色铜饰边框（不要透明件），"
                "正面观察窗是镂空开口，窗框用深棕色砖围出，从开口能看到内部深灰色齿轮，"
                "顶部是镂空的穹形罩，侧面有发条钥匙，内部中空，不要收成一块实心盒子，目标约 300 块积木",
        "complexity": "底座、观察窗、穹罩都在 + 内部围合空腔；齿轮与发条钥匙是独立部位，不用透明件",
        "min_parts": 6, "min_solid_parts": 4, "min_voxels": 900, "min_ops": 12,
        "require_parts": [
            ("底座", ("底座", "base")),
            ("观察窗", ("观察窗", "窗框", "window")),
            ("穹罩", ("穹罩", "穹", "dome")),
            ("齿轮", ("齿轮", "gear")),
            ("发条钥匙", ("钥匙", "发条", "key")),
        ],
        "checks": [["enclosed_interior_min", 1], ["layers_min", 5],
                   ["colors_distinct_min", 3]],
    },
]
