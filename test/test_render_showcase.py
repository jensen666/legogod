# -*- coding: utf-8 -*-
"""九宫格展示的案例集合与合成约束。"""
import json
import os
import tempfile
import unittest

from PIL import Image

from tools import render_showcase


class ShowcaseTest(unittest.TestCase):
    def test_nine_unique_examples_are_in_public_manifest(self):
        """九宫格恰好九例，且每例都有可公开追溯的模型夹具。"""
        slugs = [slug for slug, _title in render_showcase.SHOWCASE]
        self.assertEqual(len(slugs), 9)
        self.assertEqual(len(set(slugs)), 9)
        manifest_path = os.path.join(render_showcase.ROOT, "test", "fixtures", "public-fixtures.json")
        with open(manifest_path, encoding="utf-8") as f:
            manifest = json.load(f)
        available = {entry.get("path", "").removeprefix("test/fixtures/public/models/model_").removesuffix(".json")
                     for entry in manifest.get("entries") or [] if entry.get("type") == "model"}
        self.assertTrue(set(slugs).issubset(available))

    def test_stale_cards_are_removed(self):
        """换例后删除旧卡片，当前九例不会被误删。"""
        with tempfile.TemporaryDirectory() as out_dir:
            card_dir = os.path.join(out_dir, "showcase")
            os.makedirs(card_dir)
            stale = os.path.join(card_dir, "little-turtle.png")
            current = os.path.join(card_dir, f"{render_showcase.SHOWCASE[0][0]}.png")
            Image.new("RGB", (1, 1), "white").save(stale)
            Image.new("RGB", (1, 1), "white").save(current)
            render_showcase._remove_stale_cards(out_dir)
            self.assertFalse(os.path.exists(stale))
            self.assertTrue(os.path.exists(current))

    def test_grid_is_three_by_three(self):
        """合成图尺寸对应三列三行；案例数不对时明确拒绝。"""
        records = []
        with tempfile.TemporaryDirectory() as out_dir:
            os.makedirs(os.path.join(out_dir, "showcase"))
            for slug, _title in render_showcase.SHOWCASE:
                Image.new("RGB", (440, 340), "white").save(os.path.join(out_dir, "showcase", f"{slug}.png"))
                records.append({"slug": slug})
            path = render_showcase.compose_grid(records, out_dir)
            with Image.open(path) as image:
                self.assertEqual(image.size, (1404, 1104))
            with self.assertRaises(ValueError):
                render_showcase.compose_grid(records[:8], out_dir)


if __name__ == "__main__":
    unittest.main()
