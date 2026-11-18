# -*- coding: utf-8 -*-
"""从公开模型夹具生成九宫格展示：真实求解、统一校验、等轴渲染与卡片合成。"""
import argparse
import json
import os
import sys
import tempfile
import time

from PIL import Image, ImageChops, ImageDraw, ImageFont, ImageOps

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from legogod import tiler  # noqa: E402
from legogod.render import render_views  # noqa: E402
from legogod.validate import validate_solution  # noqa: E402

SHOWCASE = (
    ("mid-castle", "中世纪城堡"),
    ("yellow-floppy-dog", "垂耳小狗"),
    ("red-apple-stem", "红苹果"),
    ("streamline-galleon", "流线帆船"),
    ("three-mast-galleon-v3", "三桅帆船"),
    ("red-retro-car", "红色复古车"),
    ("medieval-corner-towers-castle", "四角楼城堡"),
    ("arch-bridge", "石拱桥"),
    ("small-bridge", "小桥"),
)
ACCENTS = ("#E5A100", "#C96C4B", "#4D87A8", "#4D87A8", "#6875A9", "#4E5262", "#4D9A72", "#D55445", "#E5A100")


def _load_json(path):
    """读取 UTF-8 JSON，缺失或非法时给出明确错误。"""
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def _font(size, bold=False):
    """优先使用常见中文字体，找不到时回退 Pillow 默认可用字体。"""
    candidates = [
        os.environ.get("LEGOGOD_SHOWCASE_FONT_BOLD" if bold else "LEGOGOD_SHOWCASE_FONT"),
        "/usr/share/fonts/opentype/noto/NotoSansCJK-Bold.ttc" if bold else
        "/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc",
        "/System/Library/Fonts/PingFang.ttc",
        "C:/Windows/Fonts/msyhbd.ttc" if bold else "C:/Windows/Fonts/msyh.ttc",
        "DejaVuSans-Bold.ttf" if bold else "DejaVuSans.ttf",
    ]
    for candidate in candidates:
        if not candidate:
            continue
        try:
            return ImageFont.truetype(candidate, size)
        except OSError:
            continue
    return ImageFont.load_default()


def solve_model(path):
    """用完整预算求解公开模型；统一校验失败时禁止生成展示图。"""
    model = _load_json(path)
    layers = sorted(model.get("layers") or [], key=lambda layer: layer.get("y", 0))
    solution, failure = tiler.solve_with_budget(
        model, layers, deadline=time.monotonic() + 20.0,
        validate_fn=validate_solution, log=lambda _message: None,
    )
    if solution is None:
        raise RuntimeError(f"求解失败：{path}: {(failure or {}).get('message')}")
    report = solution.get("validation") or validate_solution(model, solution)
    if not report.get("ok"):
        raise RuntimeError(f"统一校验失败：{path}: {report.get('errors')}")
    return model, solution, report


def _content_image(path, size):
    """裁掉渲染图的纯色背景，再按比例放进卡片展示区。"""
    with Image.open(path) as source:
        image = source.convert("RGB")
    background = Image.new("RGB", image.size, image.getpixel((0, 0)))
    bbox = ImageChops.difference(image, background).getbbox()
    if bbox:
        image = image.crop(bbox)
    return ImageOps.contain(image, size, Image.Resampling.LANCZOS)


def render_card(slug, title, accent, model, solution, temp_dir, out_dir):
    """渲染单个真实案例卡片，返回公开来源、零件数和校验摘要。"""
    prefix = f"showcase_{slug}"
    views = render_views(model, solution, out_dir=temp_dir, scale=12, name_prefix=prefix)
    content = _content_image(views["iso"], (392, 238))
    card = Image.new("RGB", (440, 340), "#FFFFFF")
    draw = ImageDraw.Draw(card)
    draw.rounded_rectangle((0, 0, 439, 339), radius=18, fill="#FFFFFF", outline="#DDE2E8", width=2)
    draw.rounded_rectangle((0, 0, 439, 10), radius=5, fill=accent)
    draw.text((24, 26), title, font=_font(26, bold=True), fill="#20242A")
    pieces = len(solution.get("steps") or [])
    grid = model.get("grid") or {}
    subtitle = f"{pieces} 块零件 · {grid.get('w', '?')}×{grid.get('d', '?')} studs"
    draw.text((24, 66), subtitle, font=_font(18), fill="#68717D")
    x = (440 - content.width) // 2
    y = 100 + (238 - content.height) // 2
    card.paste(content, (x, y))
    rel = f"showcase/{slug}.png"
    card.save(os.path.join(out_dir, rel))
    return {
        "slug": slug,
        "title": title,
        "image": f"assets/{rel}",
        "model": f"test/fixtures/public/models/model_{slug}.json",
        "pieces": pieces,
        "grid": {"w": grid.get("w"), "d": grid.get("d")},
        "validation": "passed",
    }


def compose_grid(cards, out_dir):
    """把九张真实案例卡片合成统一 3×3 展示图。"""
    if len(cards) != 9:
        raise ValueError("九宫格必须恰好包含 9 个案例")
    margin, gap, cell_w, cell_h = 24, 18, 440, 340
    width = margin * 2 + cell_w * 3 + gap * 2
    height = margin * 2 + cell_h * 3 + gap * 2
    sheet = Image.new("RGB", (width, height), "#F3F5F7")
    for index, card in enumerate(cards):
        x = margin + (index % 3) * (cell_w + gap)
        y = margin + (index // 3) * (cell_h + gap)
        with Image.open(os.path.join(out_dir, "showcase", f"{card['slug']}.png")) as image:
            sheet.paste(image.convert("RGB"), (x, y))
    path = os.path.join(out_dir, "showcase-grid.png")
    sheet.save(path)
    return path


def _remove_stale_cards(out_dir):
    """清理已被换下的旧案例，避免九宫格更新后仍公开过期卡片。"""
    expected = {slug for slug, _title in SHOWCASE}
    card_dir = os.path.join(out_dir, "showcase")
    os.makedirs(card_dir, exist_ok=True)
    for name in os.listdir(card_dir):
        if name.endswith(".png") and name[:-4] not in expected:
            os.remove(os.path.join(card_dir, name))


def generate(manifest_path, out_dir):
    """按固定九例生成卡片、九宫格和来源清单，任一例失败则整体失败。"""
    manifest = _load_json(manifest_path)
    models = {entry.get("path", "").removeprefix("test/fixtures/public/models/model_").removesuffix(".json"): entry
              for entry in manifest.get("entries") or [] if entry.get("type") == "model"}
    _remove_stale_cards(out_dir)
    records = []
    with tempfile.TemporaryDirectory(prefix="legogod-showcase-") as temp_dir:
        for (slug, title), accent in zip(SHOWCASE, ACCENTS):
            if slug not in models:
                raise RuntimeError(f"公开夹具清单缺少九宫格案例：{slug}")
            source = os.path.join(ROOT, models[slug]["path"])
            model, solution, _report = solve_model(source)
            record = render_card(slug, title, accent, model, solution, temp_dir, out_dir)
            record["modelSha256"] = models[slug]["sha256"]
            records.append(record)
            print(f"[showcase] {title}: {record['pieces']} 块，统一校验通过", flush=True)
    compose_grid(records, out_dir)
    data = {"schemaVersion": 1, "count": len(records), "examples": records}
    with open(os.path.join(out_dir, "showcase.json"), "w", encoding="utf-8", newline="\n") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
        f.write("\n")
    print(f"[showcase] 已生成 {len(records)} 个案例与九宫格：{out_dir}", flush=True)
    return records


def main(argv=None):
    """命令行入口：默认读取公开清单并写入 assets/。"""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", default=os.path.join(ROOT, "test", "fixtures", "public-fixtures.json"))
    parser.add_argument("--out", default=os.path.join(ROOT, "assets"))
    args = parser.parse_args(argv)
    generate(os.path.abspath(args.manifest), os.path.abspath(args.out))
    return 0


if __name__ == "__main__":
    sys.exit(main())
