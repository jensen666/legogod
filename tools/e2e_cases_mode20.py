# -*- coding: utf-8 -*-
"""M01–M20 双模式恢复 E2E 的冻结案例单源（fast × 1 + fidelity × 1，共 40 个浏览器任务）。

口径来源：
  - 冻结 M01–M20，每个案例分别跑 fast × 1 与 fidelity × 1；同一案例两臂使用完全
    相同的案例原文、目标块数、断言、模型、代码与并发；需求原文与断言在运行前冻结并保存哈希。
  - 表格「冻结需求原文」列本文件逐字复制（含标点与「目标约 N 块积木」写法），不得改题；
    表格「该例核心结果断言」列的每个分句都必须在本文件的 checks 里有对应结果断言
    （实现见 tools/e2e_assert_mode20.py；通用可信底线与目标块数比由断言器统一执行）。
  - 逐例记录 bricks / targetBlocks 并按冻结容差 >= 0.5 判目标规模达标。

字段约定（与 tools/e2e_cases_new20.py / tools/e2e_cases_r.py 一致的风格）：
  id/name/tier/desc/target_blocks、require_parts（[(部位名, (关键词...)), ...]）、
  checks（[[检查名, 参数...], ...]）、notes（核心断言分句 -> 检查映射，便于复核）。
  tier 只允许「简单」「复杂」，各 10 例（需求表格冻结档位）。

需求原文纪律：desc 是可直接提交 Web 工坊的真实用户输入，逐字等于需求表格原文；
不改写、不补充、不删标点。desc 与 target_blocks 都由 FROZEN_DESC_SHA256 冻结：
哈希一旦与常量不一致，--audit 必须报「冻结原文被改动」，不许改名/放宽冒充一致。

用法：
    python -m tools.e2e_cases_mode20 --list     # 案例表（ID/档位/名称/目标块数/原文）
    python -m tools.e2e_cases_mode20 --hash     # 逐例冻结原文 SHA-256
    python -m tools.e2e_cases_mode20 --audit    # 结构自检（数量/ID 连续/tier 计数/desc 非空/哈希稳定）
    python -m tools.e2e_cases_mode20            # JSON 摘要
"""
from __future__ import annotations

import hashlib
import json
import os
import sys

from legogod.plan_scale import parse_target_blocks as _parse_target_blocks

# 目标规模统一容差：bricks / targetBlocks >= 0.5 才算目标块数达标。
# 与 tools/e2e_assert_20.TARGET_RATIO_MIN 同一冻结口径，
# 本文件不重复定义断言阈值，只冻结案例侧期望值；断言器运行时仍 import TARGET_RATIO_MIN。
M_TARGET_TOLERANCE = 0.5

# 冻结档位：简单 10 例、复杂 10 例。
M_TIERS = ("简单", "复杂")
M_TIER_COUNTS = {"简单": 10, "复杂": 10}

# 需求原文冻结哈希（sha256(utf-8(desc))）。开跑前冻结；任何改动都会让 --audit 失败。
FROZEN_DESC_SHA256 = {
    "M01": "fa237916d0d231bab8f8162a6cf7401dd8ddeb64a0ed1c0b5c5db226afb12202",
    "M02": "a637d76226cb8f3f4b4e3e908f78857b46e68ae7f124a19c6c1904094e78e032",
    "M03": "1a32f2cc28bf804c94b6e688915ed1b29fc315f42c56fe9a6955cf3e75a1fb76",
    "M04": "afc80df1ff1eb99259665a6ad1cb88fa42f12edc99e6403609c1af1dd3e09df1",
    "M05": "dd9b057a7c79f83d766e949076a3ddbfcdb8b2ce1bebb08a9214116514f9c103",
    "M06": "11d209b55fb0ae6c7f4a1197742f423bc9301a1bd20c721e637b1858d1065cf8",
    "M07": "5c173c4e1f9e3fe0bf458d906478239e1a86e0d4d51a5601829429eb7b1261f8",
    "M08": "0f4ab24c84e3571496c4c04e9efabe1b27b8f4976ff1e3414c1248f706046877",
    "M09": "3b050dd2956cf361f32354882b3dc4f5cc73a5ff80fe709a27710b1ba2c2a07c",
    "M10": "3a3259e6b5bdb5fd003d26d8c0926f905cce162396016703dbce63f9fcbabbbe",
    "M11": "3e22d04e5fad8ddc1f2fcc9968d4887376ab4bd0b6c06f980ac1766b6d69c41a",
    "M12": "2183a4d5e9f730a0c8fe07beb2b264ae88e4ad93758d5f5221ec1c58b4b32c2f",
    "M13": "eb34e027c28ad93083a96d7d9b513814735686e8e188400db3b51576220c3f81",
    "M14": "06573f47ce6d85c2175bff096c78dbef0ae7a7807e0435a4359433c2c5a8a104",
    "M15": "b3bf41c6a93028df759543bb942010bdb706b7b9bf480169752ac83862e86267",
    "M16": "fae7552bb53d0e5169887071aecb9e629df13458011d7719642d19785fdf681e",
    "M17": "d3537b814055e7ac5ec0b5d9fada2d8996ad163e6acc99047d79d0c474732206",
    "M18": "b3ca3106ff3154ce3de1c7ab3a462449b2dd7bb9658af9b93ce0134e6942b6ae",
    "M19": "4e01be1c8ed57d0ae03e06e26366511a24a051f4dcb7843086c591c05a776c21",
    "M20": "92bcef023cfb07f3ca04bdc1eb6d97d0811b612be23542d672b12a369bbffd9d",
}

# 期望 ID 顺序与冻结目标块数（与冻结原文「目标约 N 块积木」一致）。
M_EXPECTED_IDS = [f"M{i:02d}" for i in range(1, 21)]


def parse_target_blocks(desc):
    """从需求原文解析目标块数 N（单源：legogod.plan_scale.parse_target_blocks）。

    生产单源同时接受「目标 N 块」与「目标约 N 块」，E2E 断言不得自写正则解析。
    """
    return _parse_target_blocks(desc)


def desc_sha256(desc):
    """冻结需求原文哈希：sha256(utf-8(desc)) 的十六进制串。"""
    return hashlib.sha256((desc or "").encode("utf-8")).hexdigest()


M_CASES = [
    {
        "id": "M01", "name": "两层小房", "tier": "简单",
        "desc": "一座小型两层房：两层四壁，底层一扇门、两扇窗，红色坡屋顶，目标约 100 块积木",
        "target_blocks": 100,
        "notes": "两层体量=storeys_min；门洞贯通=wall_opening_min(墙体)；"
                 "两扇窗开洞或异色=windows_evidenced；红色坡屋顶=part_color_ratio_min+sloped_part_min；"
                 "整体连通=parts_union_components（墙/屋顶；楼板并入墙体的实现也合法，"
                 "不作为独立必需部位）",
        "require_parts": [
            ("墙体", ("墙", "墙体", "wall")),
            ("屋顶", ("屋顶", "房顶", "roof")),
            ("门", ("门", "door")),
            ("窗", ("窗", "window")),
        ],
        "checks": [
            ["layers_min", 3],
            ["storeys_min", 2, 4],
            ["wall_opening_min", ("墙", "墙体", "wall"), 2, 1],
            ["windows_evidenced", ("窗", "window"), ("墙", "墙体", "wall"), 2],
            ["part_color_ratio_min", ("屋顶", "房顶", "roof"), "R", 0.35],
            ["sloped_part_min", ("屋顶", "房顶", "roof"), 2],
            ["parts_union_components", [("墙", "墙体", "wall"), ("屋顶", "房顶", "roof")], 1],
        ],
    },
    {
        "id": "M02", "name": "站立小狗", "tier": "简单",
        "desc": "一只站着的小狗：四条腿、两只垂耳、黑鼻子、两只眼睛、短尾巴，目标约 80 块积木",
        "target_blocks": 80,
        "notes": "四肢分立且落地=g_legs_separate_min；双耳下垂=pair_sides_min+part_below_ref；"
                 "黑鼻双眼外露=part_color_ratio_min/exposed_color_min；"
                 "短尾存在且连入主体=part_min_volume+parts_adjacent_min",
        "require_parts": [
            ("身体", ("身体", "body", "躯干")),
            ("头部", ("头部", "头", "head")),
            ("腿", ("腿", "leg")),
            ("耳朵", ("耳", "ear")),
            ("鼻子", ("鼻", "nose")),
            ("眼睛", ("眼", "eye")),
            ("尾巴", ("尾巴", "尾", "tail")),
        ],
        "checks": [
            ["g_legs_separate_min", ("腿", "leg"), 4],
            ["pair_sides_min", ("耳", "耳朵", "ear"), 1],
            ["part_below_ref", ("耳", "耳朵", "ear"), ("头", "头部", "head"), 0.5],
            ["part_color_ratio_min", ("鼻子", "鼻", "nose"), "K", 0.5],
            ["exposed_color_min", ("鼻子", "鼻", "nose"), 1, "K", ("身体", "body")],
            ["exposed_color_min", ("眼睛", "眼", "eye"), 2, None, ("身体", "body")],
            ["part_min_volume", ("尾巴", "尾", "tail"), 1],
            ["parts_adjacent_min", ("尾巴", "尾", "tail"), ("身体", "body"), 1],
        ],
    },
    {
        "id": "M03", "name": "单孔小桥", "tier": "简单",
        "desc": "一座单孔小桥：两端桥墩、贯通桥洞、平直桥面，目标约 100 块积木",
        "target_blocks": 100,
        "notes": "两端桥墩落地=g_legs_separate_min；桥洞真实贯通且未被填实=negative_space_passage；"
                 "桥面跨洞连通=part_span_min+parts_adjacent_min",
        "require_parts": [
            ("桥墩", ("桥墩", "桥台", "pier", "abutment")),
            ("桥面", ("桥面", "deck")),
        ],
        "checks": [
            ["g_legs_separate_min", ("桥墩", "桥台", "pier", "abutment"), 2],
            ["negative_space_passage", ("桥墩", "桥台", "拱", "arch", "pier"), "xz", 2, 1, 3],
            ["part_span_min", ("桥面", "deck"), 5, "xz"],
            ["parts_adjacent_min", ("桥面", "deck"), ("桥墩", "桥台", "pier"), 1],
        ],
    },
    {
        "id": "M04", "name": "红色小汽车", "tier": "简单",
        "desc": "一辆红色小汽车：红色车身、四个黑色车轮、两个前灯、前后车窗，目标约 80 块积木",
        "target_blocks": 80,
        "notes": "红色车身=part_color_ratio_min；四轮成对=g_part_clusters_min+pair_sides_min；"
                 "两前灯外露=exposed_color_min；前后车窗外露可辨=windows_evidenced；"
                 "车轮与车身连接=g_parts_contact",
        "require_parts": [
            ("车身", ("车身", "车体", "body")),
            ("车轮", ("车轮", "轮", "wheel")),
            ("前灯", ("前灯", "车灯", "headlight", "lamp")),
            ("车窗", ("车窗", "窗", "window")),
        ],
        "checks": [
            ["part_color_ratio_min", ("车身", "车体", "body"), "R", 0.35],
            ["g_part_clusters_min", ("车轮", "轮", "wheel"), 4],
            ["pair_sides_min", ("车轮", "轮", "wheel"), 1, "auto"],
            ["part_color_ratio_min", ("车轮", "轮", "wheel"), "K", 0.3],
            ["exposed_color_min", ("前灯", "车灯", "headlight", "lamp"), 2, None,
             ("车身", "车体", "body")],
            ["windows_evidenced", ("车窗", "窗", "window"), ("车身", "车体", "body"), 2],
            ["g_parts_contact", ("车轮", "轮", "wheel"), ("车身", "车体", "body")],
        ],
    },
    {
        "id": "M05", "name": "两层小塔楼", "tier": "简单",
        "desc": "一座两层小塔楼：灰色塔身、正面门洞、顶部垛口，目标约 100 块积木",
        "target_blocks": 100,
        "notes": "两层灰色塔身=storeys_min+part_color_ratio_min(灰)；正面门洞贯通=wall_opening_min(塔身)；"
                 "至少两组凹凸垛口=crenellated_top_min；不是实心方盒=g_not_solid_block",
        "require_parts": [
            ("塔身", ("塔身", "塔", "tower")),
            ("门", ("门", "door")),
        ],
        "checks": [
            ["storeys_min", 2, 4],
            ["part_color_ratio_min", ("塔身", "塔", "tower"), "LD", 0.5],
            ["wall_opening_min", ("塔身", "塔", "tower"), 2, 1],
            ["crenellated_top_min", ("塔身", "塔", "tower"), 2],
            ["g_not_solid_block", (), 0.7],
        ],
    },
    {
        "id": "M06", "name": "小树", "tier": "简单",
        "desc": "一棵小树：棕色树干、绿色树冠、树根落地，目标约 60 块积木",
        "target_blocks": 60,
        "notes": "棕干绿冠=part_color_ratio_min(树干/树冠)；树干落地=g_grounded_min(树干/树根)；"
                 "树冠在树干上方且连接=part_above_ref+parts_adjacent_min；整体非单一方块=g_not_solid_block",
        "require_parts": [
            ("树干", ("树干", "trunk")),
            ("树冠", ("树冠", "冠", "canopy", "crown", "leaf")),
            ("树根", ("树根", "根", "root")),
        ],
        "checks": [
            ["part_color_ratio_min", ("树干", "trunk"), "TU", 0.45],
            ["part_color_ratio_min", ("树冠", "冠", "canopy", "crown", "leaf"), "GAEN", 0.45],
            ["g_grounded_min", ("树干", "树根", "trunk", "root")],
            ["part_above_ref", ("树冠", "冠", "canopy", "crown", "leaf"), ("树干", "trunk"), 1],
            ["parts_adjacent_min", ("树冠", "冠", "canopy", "crown", "leaf"),
             ("树干", "trunk"), 1],
            ["g_not_solid_block", (), 0.58],
        ],
    },
    {
        "id": "M07", "name": "小帆船", "tier": "简单",
        "desc": "一艘小帆船：棕色船身、一根桅杆、一面白色船帆，目标约 80 块积木",
        "target_blocks": 80,
        "notes": "船身航行轮廓=cigar_taper_min(细长+两端收)；一根独立桅杆=part_span_min(y)+"
                 "part_extends_beyond(高于船身)；白色薄帆可辨且连接桅杆=thin_plate_min+"
                 "part_color_ratio_min+parts_adjacent_min",
        "require_parts": [
            ("船身", ("船身", "船体", "hull")),
            ("桅杆", ("桅杆", "桅", "mast")),
            ("船帆", ("船帆", "帆", "sail")),
        ],
        "checks": [
            ["cigar_taper_min", ("船身", "船体", "hull"), 6, 1.5, 0.85],
            ["part_color_ratio_min", ("船身", "船体", "hull"), "TU", 0.35],
            ["part_span_min", ("桅杆", "桅", "mast"), 3, "y"],
            ["part_extends_beyond", ("桅杆", "桅", "mast"), ("船身", "船体", "hull"), "y", 1],
            ["thin_plate_min", ("船帆", "帆", "sail"), 2, 2],
            ["part_color_ratio_min", ("船帆", "帆", "sail"), "WM", 0.5],
            ["parts_adjacent_min", ("船帆", "帆", "sail"), ("桅杆", "桅", "mast"), 1],
        ],
    },
    {
        "id": "M08", "name": "坐姿小猫", "tier": "简单",
        "desc": "一只坐着的小猫：身体、头部、两只尖耳、四只爪子、上翘尾巴，目标约 80 块积木",
        "target_blocks": 80,
        "notes": "头身分体可辨=part_above_ref+part_min_volume；双尖耳成对=both_sides+tapered_parts_min；"
                 "四爪存在=g_part_clusters_min；尾巴上翘并连入身体=part_span_min(y)+parts_adjacent_min",
        "require_parts": [
            ("身体", ("身体", "body")),
            ("头部", ("头部", "头", "head")),
            ("耳朵", ("耳", "ear")),
            ("爪子", ("爪", "脚", "paw")),
            ("尾巴", ("尾巴", "尾", "tail")),
        ],
        "checks": [
            ["part_above_ref", ("头部", "头", "head"), ("身体", "body"), 1],
            ["part_min_volume", ("头部", "头", "head"), 2],
            ["both_sides", ("耳", "耳朵", "ear")],
            ["tapered_parts_min", ("耳", "耳朵", "ear"), 2, 0.7],
            ["g_part_clusters_min", ("爪", "脚", "paw"), 4],
            ["part_span_min", ("尾巴", "尾", "tail"), 2, "y"],
            ["parts_adjacent_min", ("尾巴", "尾", "tail"), ("身体", "body"), 1],
        ],
    },
    {
        "id": "M09", "name": "小飞机", "tier": "简单",
        "desc": "一架小飞机：机身、左右主翼、尾翼、两个引擎，目标约 100 块积木",
        "target_blocks": 100,
        "notes": "左右主翼成对展开=both_sides+part_span_min(xz)；尾翼存在=part_span_min(y)；"
                 "两个引擎成对且与主机翼/机身连接=g_part_clusters_min+parts_adjacent_any",
        "require_parts": [
            ("机身", ("机身", "fuselage", "body")),
            ("主翼", ("主翼", "机翼", "翼", "wing")),
            ("尾翼", ("尾翼", "垂尾", "tail", "fin")),
            ("引擎", ("引擎", "发动机", "engine")),
        ],
        "checks": [
            ["both_sides", ("主翼", "机翼", "翼", "wing")],
            ["part_span_min", ("主翼", "机翼", "翼", "wing"), 4, "xz"],
            ["part_span_min", ("尾翼", "垂尾", "tail", "fin"), 2, "y"],
            ["g_part_clusters_min", ("引擎", "发动机", "engine"), 2],
            ["parts_adjacent_any", ("引擎", "发动机", "engine"),
             [("主翼", "机翼", "翼", "wing"), ("机身", "fuselage", "body")], 1],
            ["part_min_volume", ("机身", "fuselage", "body"), 4],
        ],
    },
    {
        "id": "M10", "name": "站姿机器人", "tier": "简单",
        "desc": "一个站姿机器人：头部、躯干、左右手臂、左右腿，胸口蓝色徽章，目标约 100 块积木",
        "target_blocks": 100,
        "notes": "四肢左右分立并连接=pair_sides_min+parts_contact；头与躯干可辨=part_above_ref；"
                 "蓝色胸口徽章外露且不得内埋=part_color_ratio_min(蓝)+exposed_color_min",
        "require_parts": [
            ("头部", ("头部", "头", "head")),
            ("躯干", ("躯干", "身体", "torso", "body")),
            ("手臂", ("手臂", "臂", "arm")),
            ("腿", ("腿", "leg")),
            ("徽章", ("徽章", "胸章", "badge")),
        ],
        "checks": [
            ["pair_sides_min", ("手臂", "臂", "arm"), 1, "x"],
            ["pair_sides_min", ("腿", "leg"), 1, "x"],
            ["g_grounded_min", ("腿", "leg")],
            ["g_parts_contact", ("手臂", "臂", "arm"), ("躯干", "身体", "torso", "body")],
            ["g_parts_contact", ("腿", "leg"), ("躯干", "身体", "torso", "body")],
            ["part_above_ref", ("头部", "头", "head"), ("躯干", "身体", "torso", "body"), 1],
            ["part_color_ratio_min", ("徽章", "胸章", "badge"), "BI", 0.5],
            ["exposed_color_min", ("徽章", "胸章", "badge"), 2, "BI",
             ("躯干", "身体", "torso", "body")],
        ],
    },
    {
        "id": "M11", "name": "中世纪城堡", "tier": "复杂",
        "desc": "一座中世纪城堡：四座角楼、城墙带垛口、正面大门、围合内院，目标约 300 块积木",
        "target_blocks": 300,
        "notes": "四角楼可辨=corner_towers_min+part_span_min(y)；城墙与角楼连通=parts_union_components；"
                 "垛口重复出现=crenellated_top_min；大门贯通=wall_opening_min(城墙)；"
                 "内院不得填实=enclosed_interior_min",
        "require_parts": [
            ("角楼", ("角楼", "塔楼", "corner", "tower")),
            ("城墙", ("城墙", "墙", "wall")),
            ("大门", ("大门", "城门", "gate")),
        ],
        "checks": [
            ["corner_towers_min", ("角楼", "塔楼", "corner", "tower"), ("城墙", "墙", "wall"), 4],
            ["part_span_min", ("角楼", "塔楼", "corner", "tower"), 3, "y"],
            ["parts_union_components", [("角楼", "塔楼", "corner", "tower"),
                                        ("城墙", "墙", "wall"),
                                        ("大门", "城门", "gate")], 1],
            ["crenellated_top_min", ("城墙", "墙", "wall"), 2],
            ["wall_opening_min", ("城墙", "墙", "wall"), 2, 1],
            ["enclosed_interior_min", 2],
        ],
    },
    {
        "id": "M12", "name": "三桅大帆船", "tier": "复杂",
        "desc": "一艘三桅大帆船：尖艏尖艉、三根桅杆挂白帆、舷墙、艏楼和艉楼，目标约 260 块积木",
        "target_blocks": 260,
        "notes": "船艏艉收尖=cigar_taper_min(两端收分)；三桅独立=g_part_clusters_min+part_span_min(y)；"
                 "白帆真实薄面=thin_plate_min+part_color_ratio_min(白)；舷墙/艏楼/艉楼存在=part_min_volume；"
                 "整体连通=parts_union_components",
        "require_parts": [
            ("船身", ("船身", "船体", "hull")),
            ("桅杆", ("桅杆", "桅", "mast")),
            ("船帆", ("船帆", "帆", "sail")),
            ("舷墙", ("舷墙", "船帮", "bulwark")),
            ("艏楼", ("艏楼", "forecastle")),
            ("艉楼", ("艉楼", "后楼", "poop")),
        ],
        "checks": [
            ["cigar_taper_min", ("船身", "船体", "hull"), 8, 1.8, 0.75],
            ["g_part_clusters_min", ("桅杆", "桅", "mast"), 3],
            ["part_span_min", ("桅杆", "桅", "mast"), 5, "y"],
            ["thin_plate_min", ("船帆", "帆", "sail"), 3, 2],
            ["part_color_ratio_min", ("船帆", "帆", "sail"), "WM", 0.45],
            ["part_min_volume", ("舷墙", "船帮", "bulwark"), 2],
            ["part_min_volume", ("艏楼", "forecastle"), 2],
            ["part_min_volume", ("艉楼", "后楼", "poop"), 2],
            ["parts_union_components", [("船身", "船体", "hull"), ("桅杆", "桅", "mast"),
                                        ("船帆", "帆", "sail"),
                                        ("舷墙", "船帮", "bulwark")], 1],
        ],
    },
    {
        "id": "M13", "name": "三孔石拱桥", "tier": "复杂",
        "desc": "一座三孔石拱桥：三个贯通拱洞、四组桥墩、桥面护栏、两端引桥，目标约 260 块积木",
        "target_blocks": 260,
        "notes": "三个独立贯通桥洞=negative_space_passages_min；四组桥墩落地=g_legs_separate_min；"
                 "桥面连续=part_span_min+parts_adjacent_min；护栏与两端引桥存在=pair_sides_min+"
                 "part_min_volume",
        "require_parts": [
            ("桥墩", ("桥墩", "桥台", "pier", "abutment")),
            ("桥面", ("桥面", "deck")),
            ("护栏", ("护栏", "栏杆", "rail")),
            ("引桥", ("引桥", "坡道", "approach", "ramp")),
        ],
        "checks": [
            ["negative_space_passages_min", ("桥墩", "桥台", "pier", "abutment"), "auto", 3, 2, 1],
            ["g_legs_separate_min", ("桥墩", "桥台", "pier", "abutment"), 4],
            ["part_span_min", ("桥面", "deck"), 5, "xz"],
            ["pair_sides_min", ("护栏", "栏杆", "rail"), 1, "auto"],
            ["pair_sides_min", ("引桥", "坡道", "approach", "ramp"), 1, "auto",
             ("桥面", "deck")],
            ["part_min_volume", ("引桥", "坡道", "approach", "ramp"), 2],
            ["parts_adjacent_min", ("桥面", "deck"), ("桥墩", "桥台", "pier"), 1],
        ],
    },
    {
        "id": "M14", "name": "云梯消防车", "tier": "复杂",
        "desc": "一辆云梯消防车：红色车身、驾驶室、六个车轮、顶部伸缩云梯、两侧支撑脚，目标约 240 块积木",
        "target_blocks": 240,
        "notes": "六轮成对=g_part_clusters_min+pair_sides_min；驾驶室可辨=part_min_volume；"
                 "云梯独立且外伸=part_span_min+part_extends_beyond+part_min_volume；"
                 "两侧支撑脚=pair_sides_min+g_grounded_min；红白色分区=part_color_ratio_min+"
                 "color_ratio_min+colors_distinct_min",
        "require_parts": [
            ("车身", ("车身", "车体", "body")),
            ("驾驶室", ("驾驶室", "驾驶舱", "cab")),
            ("车轮", ("车轮", "轮", "wheel")),
            ("云梯", ("云梯", "梯", "ladder")),
            ("支撑脚", ("支撑脚", "支腿", "支撑", "outrigger")),
        ],
        "checks": [
            ["g_part_clusters_min", ("车轮", "轮", "wheel"), 6],
            ["pair_sides_min", ("车轮", "轮", "wheel"), 1, "auto"],
            ["part_min_volume", ("驾驶室", "驾驶舱", "cab"), 4],
            ["part_span_min", ("云梯", "梯", "ladder"), 4, "xz"],
            ["part_extends_beyond", ("云梯", "梯", "ladder"), ("车身", "车体", "body"), "xz", 1],
            ["part_min_volume", ("云梯", "梯", "ladder"), 3],
            ["pair_sides_min", ("支撑脚", "支腿", "支撑", "outrigger"), 1, "auto"],
            ["g_grounded_min", ("支撑脚", "支腿", "支撑", "outrigger")],
            ["part_color_ratio_min", ("车身", "车体", "body"), "R", 0.35],
            ["color_ratio_min", "WM", 0.05],
            ["colors_distinct_min", 3],
        ],
    },
    {
        "id": "M15", "name": "大象", "tier": "复杂",
        "desc": "一头大象：长鼻子向下垂、两只大耳朵、四条粗腿、两根象牙、短尾巴，目标约 220 块积木",
        "target_blocks": 220,
        "notes": "长鼻下垂且连接=part_span_min(y)+part_below_ref+parts_adjacent_min；"
                 "双耳成对外凸=both_sides+part_extends_beyond；四腿落地=g_legs_separate_min；"
                 "两根象牙成对=both_sides+part_extends_beyond；短尾存在=part_min_volume+parts_adjacent_min",
        "require_parts": [
            ("身体", ("身体", "躯干", "body")),
            ("头部", ("头部", "头", "head")),
            ("长鼻", ("长鼻", "鼻", "trunk", "nose")),
            ("耳朵", ("耳朵", "耳", "ear")),
            ("象牙", ("象牙", "牙", "tusk")),
            ("腿", ("腿", "leg")),
            ("尾巴", ("尾巴", "尾", "tail")),
        ],
        "checks": [
            ["part_span_min", ("长鼻", "鼻", "trunk", "nose"), 3, "y"],
            ["part_below_ref", ("长鼻", "鼻", "trunk", "nose"), ("头", "头部", "head"), 1],
            ["parts_adjacent_min", ("长鼻", "鼻", "trunk", "nose"), ("头", "头部", "head"), 1],
            ["both_sides", ("耳", "耳朵", "ear")],
            ["part_extends_beyond", ("耳", "耳朵", "ear"), ("头", "头部", "head"), "x", 1],
            ["g_legs_separate_min", ("腿", "leg"), 4],
            ["both_sides", ("象牙", "牙", "tusk")],
            ["part_min_volume", ("象牙", "牙", "tusk"), 1],
            ["part_min_volume", ("尾巴", "尾", "tail"), 1],
            ["parts_adjacent_min", ("尾巴", "尾", "tail"), ("身体", "body"), 1],
        ],
    },
    {
        "id": "M16", "name": "埃菲尔铁塔", "tier": "复杂",
        "desc": "一座埃菲尔铁塔：四条向外张开的塔腿、三层观景平台、逐层收尖的塔身、顶部天线，目标约 320 块积木",
        "target_blocks": 320,
        "notes": "四塔腿外张并落地=g_part_clusters_min+legs_splay_min；三层平台沿高度分布=part_levels_min；"
                 "塔身收分=tiered_min；天线独立=part_span_min(y)+part_raised_above；"
                 "中央负空间不得填实=center_void_min",
        "require_parts": [
            ("塔腿", ("塔腿", "腿", "leg")),
            ("平台", ("平台", "观景台", "platform")),
            ("塔身", ("塔身", "塔体", "tower")),
            ("天线", ("天线", "antenna")),
        ],
        "checks": [
            ["g_part_clusters_min", ("塔腿", "腿", "leg"), 4],
            ["legs_splay_min", ("塔腿", "腿", "leg"), 0.5, 1],
            ["part_levels_min", ("平台", "观景台", "platform"), 3, 2],
            ["tiered_min", 3],
            ["part_span_min", ("天线", "antenna"), 2, "y"],
            ["part_raised_above", ("天线", "antenna"), ("平台", "观景台", "platform"), 1],
            ["center_void_min", ("塔腿", "腿", "leg", "塔身", "塔体", "tower",
                                 "平台", "观景台", "platform", "桁架", "truss"), 4],
        ],
    },
    {
        "id": "M17", "name": "悉尼歌剧院", "tier": "复杂",
        "desc": "一座悉尼歌剧院：多片层叠贝壳形屋顶、长方形基座、正立面玻璃幕墙，目标约 260 块积木",
        "target_blocks": 260,
        "notes": "多片壳体而非单块方顶+高低曲率变化=shell_roof_min；基座存在=part_min_volume+"
                 "part_span_min；幕墙存在且配色可辨=part_span_min+part_color_ratio_min+colors_distinct_min",
        "require_parts": [
            ("屋顶", ("屋顶", "壳体", "贝壳", "shell", "roof")),
            ("基座", ("基座", "底座", "base", "podium")),
            ("幕墙", ("幕墙", "玻璃", "curtain", "glass", "facade")),
        ],
        "checks": [
            ["shell_roof_min", ("屋顶", "壳体", "贝壳", "shell", "roof"), 2, 6, 2],
            ["part_color_ratio_min", ("屋顶", "壳体", "贝壳", "shell", "roof"), "WM", 0.4],
            ["part_min_volume", ("基座", "底座", "base", "podium"), 4],
            ["part_span_min", ("基座", "底座", "base", "podium"), 4, "xz"],
            ["part_span_min", ("幕墙", "玻璃", "curtain", "glass", "facade"), 3, "xz"],
            ["part_color_ratio_min", ("幕墙", "玻璃", "curtain", "glass", "facade"),
             "BIKD", 0.35],
            ["colors_distinct_min", 3],
        ],
    },
    {
        "id": "M18", "name": "游乐摩天轮", "tier": "复杂",
        "desc": "一座游乐摩天轮：圆形轮缘、中心轮轴和辐条、八个吊舱、两侧 A 形支架、底座，目标约 280 块积木",
        "target_blocks": 280,
        "notes": "轮缘成环且中心留空=circular_ring_min；轮轴与辐条存在=part_min_volume+radial_spokes_min+"
                 "parts_adjacent_min；八舱沿轮周分布=perimeter_objects_min；"
                 "双侧支架落地并连接轮轴=pair_sides_min+parts_adjacent_min(底座/轮轴)+g_grounded_min(底座)",
        "require_parts": [
            ("轮缘", ("轮缘", "轮圈", "圆环", "环", "rim", "ring")),
            ("轮轴", ("轮轴", "轴", "axle")),
            ("辐条", ("辐条", "轮辐", "spoke")),
            ("吊舱", ("吊舱", "舱", "gondola", "cabin")),
            ("支架", ("支架", "支撑", "support", "frame")),
            ("底座", ("底座", "基座", "base")),
        ],
        "checks": [
            ["circular_ring_min", ("轮缘", "轮圈", "圆环", "环", "rim", "ring"), 8, 0.35, 0.2],
            ["part_min_volume", ("轮轴", "轴", "axle"), 1],
            ["radial_spokes_min", ("辐条", "轮辐", "spoke"),
             ("轮缘", "轮圈", "圆环", "环", "rim", "ring"), 4, 0.5],
            ["parts_adjacent_min", ("辐条", "轮辐", "spoke"), ("轮轴", "轴", "axle"), 1],
            ["perimeter_objects_min", ("吊舱", "舱", "gondola", "cabin"),
             ("轮缘", "轮圈", "圆环", "环", "rim", "ring"), 8, 8, 0.5],
            ["pair_sides_min", ("支架", "支撑", "support", "frame"), 1, "auto"],
            ["parts_adjacent_min", ("支架", "支撑", "support", "frame"),
             ("底座", "基座", "base"), 1],
            ["parts_adjacent_min", ("支架", "支撑", "support", "frame"),
             ("轮轴", "轴", "axle"), 1],
            ["g_grounded_min", ("底座", "基座", "base")],
        ],
    },
    {
        "id": "M19", "name": "潜水艇", "tier": "复杂",
        "desc": "一艘常规动力潜水艇：细长艇身、指挥围壳、潜望镜、首尾水平舵、尾部螺旋桨，目标约 220 块积木",
        "target_blocks": 220,
        "notes": "艇身细长=cigar_taper_min；围壳外凸=part_extends_beyond(y)+parts_adjacent_min；"
                 "潜望镜独立=part_span_min(y)+part_raised_above；首尾舵成对=pair_sides_min(按艇身纵轴)；"
                 "尾桨位于艇尾且连接=part_extends_beyond(xz)+parts_adjacent_min",
        "require_parts": [
            ("艇身", ("艇身", "艇体", "船身", "hull")),
            ("围壳", ("围壳", "指挥塔", "conning")),
            ("潜望镜", ("潜望镜", "periscope")),
            ("舵", ("舵", "rudder")),
            ("螺旋桨", ("螺旋桨", "桨", "propeller", "prop")),
        ],
        "checks": [
            ["cigar_taper_min", ("艇身", "艇体", "船身", "hull"), 8, 2.2, 0.85],
            ["part_extends_beyond", ("围壳", "指挥塔", "conning"),
             ("艇身", "艇体", "hull"), "y", 1],
            ["parts_adjacent_min", ("围壳", "指挥塔", "conning"),
             ("艇身", "艇体", "hull"), 1],
            ["part_span_min", ("潜望镜", "periscope"), 2, "y"],
            ["part_raised_above", ("潜望镜", "periscope"), ("围壳", "指挥塔", "conning"), 1],
            ["pair_sides_min", ("舵", "rudder"), 1, "auto", ("艇身", "艇体", "hull")],
            ["part_extends_beyond", ("舵", "rudder"), ("艇身", "艇体", "hull"), "xz", 1],
            ["part_extends_beyond", ("螺旋桨", "桨", "propeller", "prop"),
             ("艇身", "艇体", "hull"), "xz", 1],
            ["parts_adjacent_any", ("螺旋桨", "桨", "propeller", "prop"),
             [("艇身", "艇体", "hull"), ("舵", "rudder")], 1],
        ],
    },
    {
        "id": "M20", "name": "航天飞机组合体", "tier": "复杂",
        "desc": "一架航天飞机组合体：带主翼和垂尾的轨道器、中央外储箱、两枚固体助推器，目标约 320 块积木",
        "target_blocks": 320,
        "notes": "轨道器主翼/垂尾可辨=part_span_min+both_sides；中央储箱独立=part_min_volume；"
                 "两助推器成对=g_part_clusters_min+both_sides；三者连接为整体且非单一方柱="
                 "parts_union_components+g_not_solid_block",
        "require_parts": [
            ("轨道器", ("轨道器", "orbiter")),
            ("主翼", ("主翼", "机翼", "翼", "wing")),
            ("垂尾", ("垂尾", "垂直尾翼", "尾翼", "fin", "tail")),
            ("储箱", ("储箱", "外储箱", "燃料箱", "tank")),
            ("助推器", ("助推器", "固体助推", "booster")),
        ],
        "checks": [
            ["both_sides", ("主翼", "机翼", "翼", "wing")],
            ["part_span_min", ("主翼", "机翼", "翼", "wing"), 3, "xz"],
            ["part_span_min", ("垂尾", "垂直尾翼", "尾翼", "fin", "tail"), 2, "y"],
            ["part_min_volume", ("储箱", "外储箱", "燃料箱", "tank"), 4],
            ["g_part_clusters_min", ("助推器", "固体助推", "booster"), 2],
            ["both_sides", ("助推器", "固体助推", "booster")],
            ["parts_union_components", [("轨道器", "orbiter"), ("储箱", "外储箱", "燃料箱", "tank"),
                                        ("助推器", "固体助推", "booster")], 1],
            ["g_not_solid_block", (), 0.6],
        ],
    },
]


def all_m_cases():
    """M01–M20 全部案例（返回副本列表，单个 dict 为冻结单源的浅拷贝，防外部改动）。"""
    return [dict(case) for case in M_CASES]


def find_m_case(case_id=None, desc=None):
    """按案例编号或需求原文查找 M 案例；语义与 tools/e2e_cases_new20.find_n_case 一致。

    编号大小写不敏感（strip 后 upper）；原文必须逐字相等；同一原文命中多个案例时
    要求显式给编号（返回 None），避免区间解析误配。
    """
    if case_id:
        cid = str(case_id).strip().upper()
        for case in M_CASES:
            if case["id"] == cid:
                return case
        return None
    if desc is not None:
        hits = [case for case in M_CASES if case["desc"] == desc]
        if len(hits) == 1:
            return hits[0]
    return None


def case_hash(case):
    """单个案例的冻结需求原文 SHA-256（sha256(utf-8(desc))）。"""
    return desc_sha256((case or {}).get("desc"))


def frozen_hashes():
    """M01–M20 冻结需求原文 SHA-256：{case_id: hexdigest}（按 ID 顺序）。"""
    return {case["id"]: case_hash(case) for case in M_CASES}


def _parse_requirement_table():
    """读取冻结需求表格的 M01–M20 原文（用于审计「逐字复制」）。

    需求原文属于项目内部资料，不随公开仓库发布；只有显式设置环境变量
    LEGO_REQUIREMENT_DOC 指向该文档时才做逐字核对，否则返回 None，
    --audit 报告 doc_ok=None（未执行完整审计），不能据此宣称逐字一致。
    """
    path = os.environ.get("LEGO_REQUIREMENT_DOC")
    if not path or not os.path.isfile(path):
        return None
    rows = {}
    with open(path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line.startswith("| M"):
                continue
            cells = [cell.strip() for cell in line.strip("|").split("|")]
            if len(cells) >= 4 and cells[0].startswith("M"):
                rows[cells[0]] = {"tier": cells[1], "desc": cells[2], "core": cells[3]}
    return rows


def audit_m_cases(cases=None, check_doc=True):
    """案例单源结构自检，返回结构化报告 dict（不抛异常）。

    检查项：数量 20、ID 顺序 M01–M20、tier 只有简单/复杂且各 10 例、desc 非空且以
    「块积木」结尾、冻结哈希与 FROZEN_DESC_SHA256 一致、target_blocks 与原文解析一致、
    require_parts/checks 非空、名称/原文唯一；check_doc=True 时再核对需求文档表格原文逐字一致。
    """
    pool = list(cases if cases is not None else M_CASES)
    problems = []

    if len(pool) != 20:
        problems.append(f"案例数量 {len(pool)} != 20")
    ids = [case.get("id") for case in pool]
    if ids != M_EXPECTED_IDS:
        problems.append(f"ID 不是连续的 M01–M20：{ids}")
    tier_counts = {}
    for case in pool:
        tier = case.get("tier")
        tier_counts[tier] = tier_counts.get(tier, 0) + 1
        cid = case.get("id")
        desc = case.get("desc") or ""
        if not desc.strip():
            problems.append(f"{cid} desc 为空")
        elif not desc.endswith("块积木"):
            problems.append(f"{cid} desc 未以「块积木」结尾（不是冻结需求原文）")
        digest = case_hash(case)
        if FROZEN_DESC_SHA256.get(cid) != digest:
            problems.append(f"{cid} 冻结哈希不一致（需求原文被改动）")
        parsed = parse_target_blocks(desc)
        if parsed != case.get("target_blocks"):
            problems.append(f"{cid} 原文解析目标块数 {parsed} != 冻结 target_blocks "
                            f"{case.get('target_blocks')}")
        if not case.get("require_parts"):
            problems.append(f"{cid} require_parts 为空")
        if not case.get("checks"):
            problems.append(f"{cid} checks 为空")
    extra_tiers = sorted(set(tier_counts) - set(M_TIERS))
    if extra_tiers:
        problems.append(f"出现非法档位：{extra_tiers}（只允许 {M_TIERS}）")
    for tier, want in M_TIER_COUNTS.items():
        if tier_counts.get(tier, 0) != want:
            problems.append(f"档位「{tier}」数量 {tier_counts.get(tier, 0)} != {want}")
    if len({case.get("name") for case in pool}) != len(pool):
        problems.append("案例名称不唯一")
    if len({case.get("desc") for case in pool}) != len(pool):
        problems.append("需求原文不唯一")

    doc_ok = None
    if check_doc:
        table = _parse_requirement_table()
        if table is None:
            doc_ok = None
        else:
            doc_ok = True
            for case in pool:
                row = table.get(case.get("id"))
                if row is None:
                    problems.append(f"{case.get('id')} 不在需求 §6.5 表格中")
                    doc_ok = False
                    continue
                if row["desc"] != case.get("desc"):
                    problems.append(f"{case.get('id')} 与需求 §6.5 表格原文不一致（未逐字复制）")
                    doc_ok = False
                if row["tier"] != case.get("tier"):
                    problems.append(f"{case.get('id')} 档位与需求表格不一致："
                                    f"{case.get('tier')} != {row['tier']}")
                    doc_ok = False

    return {
        "ok": not problems,
        "problems": problems,
        "count": len(pool),
        "ids": ids,
        "tier_counts": tier_counts,
        "frozen_hashes": frozen_hashes(),
        "doc_matches": doc_ok,
    }


def main(argv=None):
    try:  # Windows GBK 控制台兼容：--list/--hash/--audit 打印不能因编码崩溃
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except (AttributeError, ValueError):
        pass
    argv = list(sys.argv[1:] if argv is None else argv)
    if "--audit" in argv:
        report = audit_m_cases()
        doc = report["doc_matches"]
        doc_text = ("需求文档表格逐字一致" if doc
                    else "未核对需求文档（文档不可用）" if doc is None
                    else "需求文档表格核对失败")
        print(f"案例 {report['count']} 例；档位 {report['tier_counts']}；{doc_text}")
        if report["problems"]:
            print("审计失败：")
            for problem in report["problems"]:
                print(" -", problem)
            return 1
        print("ID 连续、desc 非空、冻结哈希稳定、目标块数与原文一致；审计通过")
        return 0
    if "--hash" in argv:
        for case in M_CASES:
            print(f"{case['id']} {case_hash(case)}")
        return 0
    if "--list" in argv:
        for case in M_CASES:
            print(f"{case['id']} {case['tier']} {case['name']:8s} "
                  f"目标≈{case['target_blocks']:3d}块 "
                  f"要求部位{len(case['require_parts']):2d}项 检查{len(case['checks']):2d}项  "
                  f"{case['desc']}")
        print(f"\n共 {len(M_CASES)} 例（简单 10 / 复杂 10）")
        return 0
    summary = [{key: case[key] for key in ("id", "name", "tier", "desc", "target_blocks")}
               for case in M_CASES]
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
