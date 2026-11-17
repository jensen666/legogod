# -*- coding: utf-8 -*-
"""N01–N20 新 20 例的「结果正确性」专项断言（tools/e2e_cases_new20.py 的检查器实现）。

用法：
    python -m tools.e2e_assert_new20 <run_id>                 # 按运行记录 desc 自动匹配 N 案例
    python -m tools.e2e_assert_new20 <run_id> --case N01
    python -m tools.e2e_assert_new20 <run_id> --json out.json

口径（与 tools/e2e_assert_g.check_objects_g 完全一致）：
  - 通用硬底线：任务成功、最终门禁未降级（以 record["finalGateReplay"] 为准，旧记录兼容
    退回 gateFailed）、统一校验按同一模型重算全绿、最终版本产物齐全；
  - 需求达标档（硬失败）：require_parts 部位存在且未删空、本轮专项几何断言、
    部位数/立体部位数下限、目标块数统一容差 bricks/目标 >= 0.5（N_TARGET_TOLERANCE）；
  - 当前能力回归档（只记录不判失败）：体素/层数/颜色/斜面/算子数与设计参考下限的比较；
  - 检查器一律 fn(ctx, *args) -> list[str]，不抛异常（check_objects_n 兜底），错误给中文可读原因。

检查器复用策略（只读复用，不修改现有文件）：
  - 本模块只新增 6 个检查器（N_CHECKS：扇形尾屏 / 触手方位 / 悬索垂度 / 倾斜塔 /
    轮径比 / 气囊-吊篮关系），导入时并入 tools.e2e_assert_g.G_CHECKS，供 check_objects_g
    在同一注册表里执行；
  - check_objects_n 的检查解析顺序为 N_CHECKS → G_CHECKS → tools.e2e_assert_20._CHECKS，
    因此 G 组 30+ 检查器与 20 例通用检查器都可直接写进 N 案例的 checks，无需复制实现。
"""
import json
import math
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from tools.e2e_assert import (  # noqa: E402
    _colored_cells, assert_generic, draw_request_count, load_run, review_with_source,
)
from tools.e2e_assert_20 import (  # noqa: E402
    _CHECKS as _GENERIC_CHECKS, _part_counts, _require_parts, _slope_count,
)
from tools.e2e_assert_g import (  # noqa: E402
    G_CHECKS, _adjacent, _cells_of_part, _final_gate_replay_errors, _part_cells,
    _solid_cells, _span,
)
from tools.e2e_cases_new20 import (  # noqa: E402
    N_TARGET_TOLERANCE, find_n_case, parse_target_blocks,
)

# 本轮新检查器注册表：名字 -> fn(ctx, *args) -> list[str]；导入完成后再并入 G_CHECKS。
N_CHECKS = {}


def _ncheck(name):
    def deco(fn):
        N_CHECKS[name] = fn
        return fn
    return deco


# ================================================================ N01 扇形尾屏
@_ncheck("g_fan_tail")
def _c_fan_tail(ctx, patterns, min_spread=90.0, min_bins=5):
    """扇形尾屏：尾屏必须从靠近身体的窄根部向上呈扇形张开（径向外扩 + 角向覆盖）。

    判据（只看结果几何，不看涂装）：
      1) 竖向层数 ≥3（尾屏立起来，不是一层贴片）；
      2) 逐层横向宽度：最大宽度 ≥ 根部宽度 + 2 且 ≥ 2 倍根部宽度（真实张开）；
      3) 以根部中心为原点，高出根部各格的相对竖直张角 ≥min_spread 度，
         且覆盖 ≥min_bins 个 20° 角向箱（竖条/直板张角与角向覆盖都不足）。
    """
    model = ctx["model"]
    hits, cells = _part_cells(model, patterns)
    if not hits:
        return [f"未找到尾屏部位 {patterns}（扇形尾屏缺失）"]
    if not cells:
        return [f"尾屏部位 {patterns} 缺少几何体素数据（boxes 为空，涂装不算尾屏）"]
    u_axis = 0 if _span(cells, 0) >= _span(cells, 2) else 2
    ys = sorted({c[1] for c in cells})
    if len(ys) < 3:
        return [f"扇形尾屏竖向层数不足：{len(ys)} < 3（尾屏没有立起来）"]
    widths = {y: len({c[u_axis] for c in cells if c[1] == y}) for y in ys}
    base_w = widths[ys[0]]
    max_w = max(widths.values())
    errors = []
    if max_w < base_w + 2 or max_w < 2 * base_w:
        errors.append(f"尾屏没有向上张开成扇形：根部宽 {base_w} → 最大宽 {max_w}"
                      f"（需要至少 {base_w + 2} 且 ≥2 倍根部宽）")
    bottom = [c for c in cells if c[1] == ys[0]]
    base_u = sum(c[u_axis] for c in bottom) / float(len(bottom))
    spread_lo, spread_hi = 180.0, -180.0
    bins = set()
    considered = 0
    for (x, y, z) in cells:
        if y <= ys[0]:
            continue
        du = float(x if u_axis == 0 else z) - base_u
        dv = float(y - ys[0])
        theta = math.degrees(math.atan2(du, dv))  # 0°=正上方，±180°=正下方
        spread_lo = min(spread_lo, theta)
        spread_hi = max(spread_hi, theta)
        bins.add(int((theta + 180.0) // 20.0) % 18)
        considered += 1
    if considered < 3:
        return errors + [f"尾屏几乎没有高出根部的展开体素：{considered} < 3（尾屏未张开）"]
    spread = spread_hi - spread_lo
    if spread < min_spread:
        errors.append(f"尾屏张角不足：{spread:.0f}° < {min_spread:.0f}°（竖条/直板不是扇形）")
    if len(bins) < min_bins:
        errors.append(f"尾屏角向覆盖不足：{len(bins)} 个角向区段 < {min_bins}（扇形没有均匀展开）")
    return errors


# ================================================================ N03 触手方位
@_ncheck("g_tentacle_directions")
def _c_tentacle_directions(ctx, patterns, min_dirs=4, min_drop=2):
    """触手方位：触手必须向不同水平方向弯垂（章鱼八爪鱼的多方位特征）。

    判据：
      1) 竖向跨度 ≥min_drop（真实垂落/弯曲，不是一层贴片）；
      2) 以触手最高层（靠近身体的根部）质心为原点，下半段落点覆盖 ≥min_dirs 个
         45° 水平方位箱（全部挤在一个方向 = 没有张开）。
    """
    model = ctx["model"]
    hits, cells = _part_cells(model, patterns)
    if not hits:
        return [f"未找到触手部位 {patterns}（触手缺失）"]
    if not cells:
        return [f"触手部位 {patterns} 缺少几何体素数据（boxes 为空）"]
    ys = sorted({c[1] for c in cells})
    drop = ys[-1] - ys[0] + 1
    errors = []
    if drop < min_drop:
        errors.append(f"触手竖向跨度不足：{drop} < {min_drop}（触手没有向下垂落/弯曲）")
    top = [c for c in cells if c[1] == ys[-1]]
    cx = sum(c[0] for c in top) / float(len(top))
    cz = sum(c[2] for c in top) / float(len(top))
    mid_y = ys[0] + (drop - 1) / 2.0
    bins, low_cells = set(), 0
    for (x, y, z) in cells:
        if y > mid_y:
            continue
        low_cells += 1
        ang = math.degrees(math.atan2(z - cz, x - cx)) % 360.0
        bins.add(int(ang // 45.0) % 8)
    if low_cells < min_dirs:
        return errors + [f"触手下半段体素过少：{low_cells} < {min_dirs}（无法形成多方位触手）"]
    if len(bins) < min_dirs:
        errors.append(f"触手方位不足：只覆盖 {len(bins)} 个水平方位 < {min_dirs}"
                      "（触手挤在同一方向，没有向四周张开）")
    return errors


# ================================================================ N12 悬索垂度
@_ncheck("g_suspension_sag")
def _c_suspension_sag(ctx, cable_patterns, min_sag=2, hanger_patterns=None, min_hangers=1):
    """悬索垂度：主缆在跨中真实下垂成弧线，吊索从主缆向下吊住桥面。

    判据（结果几何）：
      1) 主缆水平跨度 ≥6；
      2) 沿跨向逐列取主缆最高点：两端（各 1/6 跨）平均高度 - 跨中 1/3 最低点 ≥min_sag；
      3) 给出 hanger_patterns 时：吊索有效挂点 ≥min_hangers，即吊索顶端与对应列主缆
         相邻、底端向下延伸（不能悬空或贴在桥面上）。
    """
    model = ctx["model"]
    cable_hits, cable = _part_cells(model, cable_patterns)
    if not cable_hits:
        return [f"未找到主缆部位 {cable_patterns}（悬索缺失）"]
    if not cable:
        return [f"主缆部位 {cable_patterns} 缺少几何体素数据（boxes 为空）"]
    u_axis = 0 if _span(cable, 0) >= _span(cable, 2) else 2
    top = {}
    for (x, y, z) in cable:
        u = x if u_axis == 0 else z
        top[u] = max(top.get(u, -1), y)
    us = sorted(top)
    span = us[-1] - us[0] + 1
    if span < 6:
        return [f"主缆水平跨度不足：{span} < 6（没有跨江悬索的跨度）"]
    lo, hi = us[0], us[-1]
    edge_n = max(1, span // 6)
    end_vals = [top[u] for u in us if u <= lo + edge_n - 1 or u >= hi - edge_n + 1]
    mid_lo, mid_hi = lo + span / 3.0, hi - span / 3.0
    mid_vals = [top[u] for u in us if mid_lo <= u <= mid_hi]
    if not end_vals or not mid_vals:
        return ["主缆两端/跨中采样不足，无法判定垂度（主缆不连续）"]
    avg_end = sum(end_vals) / float(len(end_vals))
    sag = avg_end - min(mid_vals)
    errors = []
    if sag < min_sag:
        errors.append(f"主缆没有在跨中下垂成弧线：两端平均 y={avg_end:.1f}、"
                      f"跨中最低 y={min(mid_vals)}，垂度 {sag:.1f} < {min_sag}"
                      "（水平直线不是悬索）")
    if hanger_patterns:
        hanger_hits, hangers = _part_cells(model, hanger_patterns)
        if not hanger_hits:
            errors.append(f"未找到吊索部位 {hanger_patterns}（桥面没有被吊住）")
        elif not hangers:
            errors.append(f"吊索部位 {hanger_patterns} 缺少几何体素数据（boxes 为空）")
        else:
            by_u = {}
            for (x, y, z) in hangers:
                u = x if u_axis == 0 else z
                by_u.setdefault(u, []).append(y)
            valid = 0
            for u, ys in by_u.items():
                cable_y = top.get(u)
                if cable_y is None:
                    continue
                if min(ys) < cable_y <= max(ys) + 1:
                    valid += 1
            if valid < min_hangers:
                errors.append(f"吊索没有从主缆向下吊住：有效挂点 {valid} < {min_hangers}"
                              "（吊索顶端必须紧贴主缆、底端向下延伸）")
    return errors


# ================================================================ N13 倾斜塔
@_ncheck("g_leaning_tower")
def _c_leaning_tower(ctx, patterns, min_drift=3, min_layers=5, min_consistency=0.6):
    """倾斜塔：塔身逐层向同一方向偏移（比萨斜塔式整体倾斜）。

    判据：
      1) 塔身层数 ≥min_layers（不是矮墩）；
      2) 顶层质心相对底层质心的水平偏移 ≥min_drift；
      3) 逐层质心滑移方向与总偏移方向一致的比例 ≥min_consistency
         （左右来回摆/S 形不算「整体向一侧倾斜」）。
    """
    model = ctx["model"]
    hits, cells = _part_cells(model, patterns)
    if not hits:
        return [f"未找到塔身部位 {patterns}（无法验证倾斜）"]
    if not cells:
        return [f"塔身部位 {patterns} 缺少几何体素数据（boxes 为空）"]
    ys = sorted({c[1] for c in cells})
    if len(ys) < min_layers:
        return [f"塔身层数不足：{len(ys)} < {min_layers}（矮墩没有倾斜可辨）"]
    cent = {}
    for y in ys:
        pts = [(c[0], c[2]) for c in cells if c[1] == y]
        cent[y] = (sum(p[0] for p in pts) / float(len(pts)),
                   sum(p[1] for p in pts) / float(len(pts)))
    bx, bz = cent[ys[0]]
    tx, tz = cent[ys[-1]]
    dx, dz = tx - bx, tz - bz
    drift = math.hypot(dx, dz)
    axis = 0 if abs(dx) >= abs(dz) else 1
    total = dx if axis == 0 else dz
    errors = []
    if drift < min_drift:
        errors.append(f"塔身没有明显倾斜：顶层相对底层水平偏移 {drift:.1f} < {min_drift}"
                      "（垂直塔不是斜塔）")
    steps = [cent[ys[i + 1]][axis] - cent[ys[i]][axis] for i in range(len(ys) - 1)]
    sign = 1.0 if total >= 0 else -1.0
    nonzero = [s for s in steps if abs(s) > 1e-9]
    if not nonzero:
        errors.append("塔身逐层质心完全不动（垂直塔不是斜塔）")
    else:
        consistent = sum(1 for s in nonzero if s * sign > 0)
        ratio = consistent / float(len(nonzero))
        if ratio < min_consistency:
            errors.append(f"倾斜方向不连贯：同向滑移占比 {ratio:.0%} < {min_consistency:.0%}"
                          "（左右来回摆/S 形不算整体倾斜）")
    return errors


# ================================================================ N16 轮径比
@_ncheck("g_wheel_size_ratio")
def _c_wheel_size_ratio(ctx, big_patterns, small_patterns, min_ratio=1.4):
    """轮径比：大轮（后轮）必须明显大于小轮（前轮），验证拖拉机式轮径关系。

    判据：两组轮子部位各自取「单个部位内竖直跨度最大值」作为轮径（竖直跨度不受两轮
    横向间距/轮距影响，避免把轮距误算成直径），大轮/小轮直径比 ≥min_ratio；
    任一组缺失或直径为 0 都判失败。
    """
    model = ctx["model"]
    big_hits, big_cells = _part_cells(model, big_patterns)
    small_hits, small_cells = _part_cells(model, small_patterns)
    errors = []
    if not big_hits:
        errors.append(f"未找到大轮部位 {big_patterns}（后轮缺失）")
    if not small_hits:
        errors.append(f"未找到小轮部位 {small_patterns}（前轮缺失）")
    if big_hits and not big_cells:
        errors.append(f"大轮部位 {big_patterns} 缺少几何体素数据（boxes 为空）")
    if small_hits and not small_cells:
        errors.append(f"小轮部位 {small_patterns} 缺少几何体素数据（boxes 为空）")
    if errors:
        return errors

    def diameter(hits):
        vals = [_span(_cells_of_part(p), 1) for p in hits if _cells_of_part(p)]
        return max(vals) if vals else 0

    big_d, small_d = diameter(big_hits), diameter(small_hits)
    if small_d <= 0:
        return [f"小轮部位 {small_patterns} 直径无法判定（没有竖直跨度）"]
    ratio = big_d / float(small_d)
    if ratio < min_ratio:
        errors.append(f"轮径比不足：大轮直径 {big_d} / 小轮直径 {small_d} = {ratio:.2f}"
                      f" < {min_ratio}（前后轮被做成一样大）")
    return errors


# ================================================================ N20 气囊-吊篮关系
@_ncheck("g_balloon_basket")
def _c_balloon_basket(ctx, envelope_patterns, basket_patterns, rope_patterns=None, min_gap=1):
    """气囊-吊篮关系：气囊在吊篮正上方且留有空隙、宽度明显大于吊篮、吊绳连接、吊篮落地。

    判据：
      1) 气囊最低层高出吊篮最高层 ≥min_gap（上下关系正确，不能同层或倒置）；
      2) 气囊水平最大宽度 ≥1.5 倍吊篮宽度（鼓胀气囊与方吊篮的大小关系）；
      3) 吊篮最低层 y=0（落地摆放）；
      4) 给出 rope_patterns 时：吊绳存在、与吊篮相邻、整段位于气囊下方并在气囊底
         ≤2 层内结束（真实吊住吊篮，允许中间有燃烧器，不要求与气囊直接相邻）。
    """
    model = ctx["model"]
    env_hits, env = _part_cells(model, envelope_patterns)
    basket_hits, basket = _part_cells(model, basket_patterns)
    errors = []
    if not env_hits:
        errors.append(f"未找到气囊部位 {envelope_patterns}（气囊缺失）")
    if not basket_hits:
        errors.append(f"未找到吊篮部位 {basket_patterns}（吊篮缺失）")
    if env_hits and not env:
        errors.append(f"气囊部位 {envelope_patterns} 缺少几何体素数据（boxes 为空）")
    if basket_hits and not basket:
        errors.append(f"吊篮部位 {basket_patterns} 缺少几何体素数据（boxes 为空）")
    if errors:
        return errors
    env_low = min(c[1] for c in env)
    basket_top = max(c[1] for c in basket)
    if env_low < basket_top + min_gap:
        errors.append(f"气囊没有位于吊篮上方：气囊底 y={env_low}、吊篮顶 y={basket_top}"
                      f"（需要高出 ≥{min_gap} 层，上下关系/空隙未成型）")
    basket_low = min(c[1] for c in basket)
    if basket_low != 0:
        errors.append(f"吊篮没有落地：最低层 y={basket_low} > 0（吊篮悬空放置）")
    env_w = max(_span(env, 0), _span(env, 2))
    basket_w = max(_span(basket, 0), _span(basket, 2))
    if env_w < 1.5 * basket_w:
        errors.append(f"气囊体量不足：气囊宽 {env_w} < 1.5 × 吊篮宽 {basket_w}（不是鼓胀气囊）")
    if rope_patterns:
        rope_hits, ropes = _part_cells(model, rope_patterns)
        if not rope_hits:
            errors.append(f"未找到吊绳部位 {rope_patterns}（吊篮没有被吊住）")
        elif not ropes:
            errors.append(f"吊绳部位 {rope_patterns} 缺少几何体素数据（boxes 为空）")
        else:
            if not _adjacent(ropes, basket):
                errors.append("吊绳与吊篮未接触（吊篮没有被真实吊住）")
            rope_top = max(c[1] for c in ropes)
            if rope_top >= env_low:
                errors.append(f"吊绳穿过气囊：吊绳顶 y={rope_top} 未低于气囊底 y={env_low}")
            elif env_low - rope_top > 2:
                errors.append(f"吊绳没有连到气囊方向：吊绳顶 y={rope_top} 距气囊底 y={env_low}"
                              " 超过 2 层（中间断开的悬空绳不算）")
    return errors


# 导入时并入 G 组注册表：只读复用（不修改 tools/e2e_assert_g.py 源码），
# 让 check_objects_g 也能在同一注册表里执行 N 组新检查器。
G_CHECKS.update(N_CHECKS)
N_NEW_CHECK_NAMES = tuple(N_CHECKS)


def resolve_check(name):
    """解析检查器：N 新检查器 → G 组注册表 → 20 例通用检查器；找不到返回 None。

    N 案例的 checks 可以同时引用本轮 6 个新检查器、G 组 30+ 检查器与
    20 例通用检查器（如 negative_space_passage / eave_slope_overhang /
    layer_components_min / s_curve_min 等），无需复制实现。
    """
    if name in N_CHECKS:
        return N_CHECKS[name]
    if name in G_CHECKS:
        return G_CHECKS[name]
    return _GENERIC_CHECKS.get(name)


# ================================================================ 断言入口
def check_objects_n(record, model, solution, case, review_fallback=None):
    """对 N 组单个案例执行通用底线 + 需求达标档 + 回归档，返回 (errors, metrics)。

    errors = 通用底线失败 + 需求达标档失败（任何一项即断言失败）；
    metrics["requirement_tier"] 只列需求达标档失败项；metrics["regression_tier"]
    只记录回归指标（体素/层数/颜色/算子等），不参与判定。
    任务失败/无产物（model/solution 为空、record.ok=False）时给出可读失败而不是异常。
    review_fallback：旧 run 记录没有 review 时用任务 result.review 补入。
    """
    record = record if isinstance(record, dict) else {}
    model = model if isinstance(model, dict) else {}
    solution = solution if isinstance(solution, dict) else {}
    solution = solution or {}
    case = case if isinstance(case, dict) else {}

    generic_errors = []
    try:
        assert_generic(record, model, solution, generic_errors)
        # 最终门禁以 record["finalGateReplay"] 对最终模型的真实重放为准，
        # 与 G 组 check_objects_g 同口径补一条独立判据（缺失字段时该函数返回空，不误报）。
        generic_errors.extend(_final_gate_replay_errors(record))
    except SystemExit as exc:  # load_run 数据异常被以 SystemExit 抛出时也转可读失败
        generic_errors.append(f"通用底线断言数据异常：{exc}")
    except Exception as exc:  # noqa: BLE001 - 断言模块必须可读失败、不静默通过
        generic_errors.append(f"通用底线断言执行失败：{exc.__class__.__name__}: {exc}")

    ctx = {"model": model, "solution": solution,
           "counts": _part_counts(model),
           "colored": _colored_cells(model),
           "solid": _solid_cells(model)}
    label = f"{case.get('id', 'N??')} {case.get('name', '')}".strip()
    target = case.get("target_blocks")
    if target is None:
        target = parse_target_blocks(case.get("desc") or record.get("desc"))
    bricks = len(solution.get("steps") or [])

    requirement_errors = []
    feature_checks = []
    if record.get("ok"):
        _require_parts(model, requirement_errors, label, case.get("require_parts") or [])
        for spec in case.get("checks") or []:
            name, args = spec[0], spec[1:]
            fn = resolve_check(name)
            if fn is None:
                check_errors = [f"断言配置错误：未知检查 {name}"]
            else:
                try:
                    check_errors = list(fn(ctx, *args) or [])
                except Exception as exc:  # noqa: BLE001 - 产物异常时必须可读失败
                    check_errors = [f"检查 {name} 执行失败：{exc.__class__.__name__}: {exc}"]
            feature_checks.append({"name": name, "ok": not check_errors,
                                   "errors": check_errors})
            requirement_errors.extend(check_errors)
        total, solid_count, _surface = ctx["counts"]
        min_parts = int(case.get("min_parts") or 0)
        min_solid_parts = int(case.get("min_solid_parts") or 0)
        if total < min_parts:
            requirement_errors.append(f"复杂度未达设计下限：部位数 {total} < {min_parts}")
        if solid_count < min_solid_parts:
            requirement_errors.append(
                f"复杂度未达设计下限：立体部位数 {solid_count} < {min_solid_parts}")
        if target:
            ratio = bricks / float(target)
            if ratio < N_TARGET_TOLERANCE:
                requirement_errors.append(
                    f"目标块数未达标：实际零件 {bricks}/{target} = {ratio:.2%} < "
                    f"{N_TARGET_TOLERANCE:.0%}（方案 12.4 统一容差 ±50%）")
    errors = generic_errors + requirement_errors

    review, review_source = review_with_source(record, review_fallback)
    scores = review.get("scores") if isinstance(review.get("scores"), dict) else {}
    attempts = record.get("drawAttempts") or []
    voxels = int(model.get("totalVoxels") or 0)
    ops = len(model.get("ops") or [])
    min_voxels = int(case.get("min_voxels") or 0)
    min_ops = int(case.get("min_ops") or 0)
    bricks_ratio = round(bricks / float(target), 4) if target else None
    metrics = {
        "suite": "N",
        "case": case.get("id"), "name": case.get("name"), "run_id": record.get("runId"),
        "stress": list(case.get("stress") or []),
        "historical_failure_hint": case.get("historical_failure_hint"),
        "task_ok": bool(record.get("ok")), "error": record.get("error"),
        "mode": record.get("mode"), "track": model.get("track"),
        "target_blocks": target,
        "bricks": bricks,
        "bricks_ratio": bricks_ratio,
        "target_blocks_ok": (bricks_ratio is not None
                             and bricks_ratio >= N_TARGET_TOLERANCE),
        "parts": ctx["counts"][0], "solid_parts": ctx["counts"][1],
        "surface_parts": ctx["counts"][2],
        "voxels": voxels, "ops": ops,
        "slope_voxels": _slope_count(model),
        "layers": len(model.get("layers") or []),
        "grid": model.get("grid"),
        "pieces": bricks,
        "colors": len(set(ctx["colored"].values())),
        "gate_failed": bool(record.get("gateFailed") or record.get("gate_failed")),
        "gate_errors": record.get("gateErrors") or record.get("gate_errors") or [],
        "final_gate_replay": record.get("finalGateReplay") or record.get("final_gate_replay"),
        "validation_ok": solution.get("validation", {}).get("ok")
        if isinstance(solution.get("validation"), dict) else None,
        "review_overall": scores.get("overall"),
        "review_flag": record.get("reviewFlag"),
        "draw_attempts": len(attempts),
        "draw_requests": draw_request_count(attempts),
        "review": review,
        "review_source": review_source,
        "feature_checks": feature_checks,
        "requirement_tier": requirement_errors,
        "generic_tier": generic_errors,
        "regression_tier": {
            "voxels": voxels,
            "voxels_per_target_block": round(voxels / float(target), 2) if target else None,
            "design_min_voxels": min_voxels,
            "voxels_below_design_floor": voxels < min_voxels if min_voxels else None,
            "ops": ops,
            "design_min_ops": min_ops,
            "ops_below_design_floor": ops < min_ops if min_ops else None,
            "layers": len(model.get("layers") or []),
            "colors": len(set(ctx["colored"].values())),
            "slope_voxels": _slope_count(model),
            "parts": ctx["counts"][0],
        },
        "assertion_errors": errors,
        "assertion_ok": not errors,
    }
    return errors, metrics


def check_run_n(run_id, case_id=None, review_fallback=None):
    """读取 run 记录与最终产物执行 N 组断言，返回 metrics dict。

    运行记录缺失/损坏时以可读 SystemExit 结束 CLI，不输出裸 traceback。
    review_fallback：任务结果 result.review（旧 run 记录没有 review 时补入）。
    """
    try:
        record, model, solution = load_run(run_id)
    except (OSError, ValueError) as exc:
        raise SystemExit(f"读取 run {run_id} 失败：{exc}") from exc
    case = find_n_case(case_id, desc=record.get("desc"))
    if case is None:
        raise SystemExit(f"无法匹配 N 组案例：case_id={case_id!r} "
                         f"desc={str(record.get('desc'))[:60]!r}"
                         "（请显式给 --case，或确认需求原文与 tools/e2e_cases_new20.py 一致）")
    _errors, metrics = check_objects_n(record, model, solution, case,
                                       review_fallback=review_fallback)
    metrics["desc"] = record.get("desc")
    return metrics


def main(argv=None):
    # Windows GBK 控制台兼容：CLI 打印不能因编码崩溃。
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except (AttributeError, ValueError):  # 老 Python / 非文本 stdout
        pass
    argv = list(sys.argv[1:] if argv is None else argv)
    json_out, case_id, positional = None, None, []
    i = 0
    while i < len(argv):
        a = argv[i]
        if a == "--case":
            i += 1
            case_id = argv[i] if i < len(argv) else None
        elif a == "--json":
            i += 1
            json_out = argv[i] if i < len(argv) else None
        else:
            positional.append(a)
        i += 1
    if len(positional) != 1:
        print("用法: python -m tools.e2e_assert_new20 <run_id> [--case N01] [--json out.json]")
        return 2
    metrics = check_run_n(positional[0], case_id)
    if json_out:
        with open(json_out, "w", encoding="utf-8") as f:
            json.dump(metrics, f, ensure_ascii=False, indent=2)
    print(f"案例 {metrics['case']} {metrics['name']} · run {metrics['run_id']} · "
          f"{'断言通过' if metrics['assertion_ok'] else '断言未通过'}")
    print(f"  目标块数={metrics['target_blocks']} 实际零件={metrics['bricks']} "
          f"比值={metrics['bricks_ratio']} 达标={metrics['target_blocks_ok']}")
    print(f"  任务成功={metrics['task_ok']} 轨道={metrics['track']} 部位={metrics['parts']}"
          f"(立体{metrics['solid_parts']}/涂装{metrics['surface_parts']}) "
          f"体素={metrics['voxels']} 算子={metrics['ops']} 层={metrics['layers']} "
          f"颜色={metrics['colors']} 压力={'/'.join(metrics['stress'])}")
    if metrics["assertion_errors"]:
        print("断言未通过项：")
        for e in metrics["assertion_errors"]:
            print(" -", e)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
