# -*- coding: utf-8 -*-
"""明亮积木工坊 Web 静态契约。"""
import os
import re
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
WEB = os.path.join(ROOT, "web")


def read_web(name):
    """读取 Web 源文件。"""
    with open(os.path.join(WEB, name), encoding="utf-8") as handle:
        return handle.read()


def luminance(hex_color):
    """计算 sRGB 相对亮度。"""
    channels = [int(hex_color[index:index + 2], 16) / 255 for index in (0, 2, 4)]
    linear = [value / 12.92 if value <= 0.04045 else ((value + 0.055) / 1.055) ** 2.4
              for value in channels]
    return sum(value * weight for value, weight in zip(linear, (0.2126, 0.7152, 0.0722)))


def contrast(foreground, background):
    """计算两个六位十六进制颜色的 WCAG 对比度。"""
    high, low = sorted((luminance(foreground), luminance(background)), reverse=True)
    return (high + 0.05) / (low + 0.05)


class WebThemeTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.css = read_web("app.css")
        cls.variables = dict(re.findall(r"--([\w-]+):\s*(#[0-9a-fA-F]{6})\s*;", cls.css))

    def test_light_palette_and_real_preview_surfaces(self):
        """全局、组件与两个 3D 入口均使用浅色表面。"""
        expected = {
            "bg": "#f5f6f8",
            "panel": "#ffffff",
            "panel-2": "#eef1f5",
            "stage": "#e9eef3",
            "text": "#20242b",
            "text-2": "#4b5563",
            "muted": "#667085",
            "brand": "#ffb02e",
            "brand-ink": "#201404",
            "brand-text": "#8a5500",
        }
        for name, value in expected.items():
            self.assertEqual(self.variables.get(name), value, name)
        self.assertIn("color-scheme: light;", self.css)
        self.assertNotIn("color-scheme: dark;", self.css)
        self.assertIn("scene.background = new THREE.Color(0xe9eef3);", read_web("preview.js"))
        self.assertIn("background: #e9eef3;", read_web("viewer.js"))
        shell = read_web("shell.html")
        self.assertIn("background:#f5f6f8;color:#20242b", shell)

    def test_text_and_status_contrast(self):
        """正文、黄色按钮和各语义文字在浅底上达到普通文字 4.5:1。"""
        pairs = (
            ("text", "bg"),
            ("text-2", "panel"),
            ("muted", "bg"),
            ("muted", "panel"),
            ("brand-text", "brand-bg"),
            ("brand-ink", "brand"),
            ("ok", "ok-bg"),
            ("warn", "warn-bg"),
            ("bad", "bad-bg"),
            ("info", "info-bg"),
            ("fb", "fb-bg"),
        )
        for foreground, background in pairs:
            ratio = contrast(self.variables[foreground][1:], self.variables[background][1:])
            self.assertGreaterEqual(ratio, 4.5, f"{foreground} / {background}: {ratio:.2f}")
        self.assertGreaterEqual(contrast("ffffff", self.variables["danger"][1:]), 4.5)

    def test_legacy_dark_surfaces_are_removed(self):
        """旧整页与局部深色不再残留在主题入口。"""
        old_colors = ("#0f1216", "#151a21", "#1b222b", "#12171d", "#0e1216",
                      "#101418", "#e8e6e1", "0x12171d")
        for name in ("app.css", "stage.css", "preview.js", "shell.html"):
            source = read_web(name).lower()
            for color in old_colors:
                self.assertNotIn(color, source, f"{name} 仍包含 {color}")


if __name__ == "__main__":
    unittest.main()
