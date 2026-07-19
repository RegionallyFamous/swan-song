# SPDX-License-Identifier: GPL-3.0-or-later

from __future__ import annotations

from pathlib import Path
import sys
import unittest

from PIL import Image


sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools"))
import png2ws_splash


class SplashTests(unittest.TestCase):
    def test_tile_encoder_layout(self) -> None:
        image = Image.new("P", (64, 64), 0)
        image.putpixel((0, 0), 1)
        image.putpixel((1, 0), 2)
        encoded = png2ws_splash.encode_tiles(image)
        self.assertEqual(len(encoded), 1024)
        self.assertEqual(encoded[:2], bytes((0x80, 0x40)))

    def test_render_uses_logo_palette(self) -> None:
        source = Image.new("RGBA", (80, 24), (0, 0, 0, 0))
        source.paste((34, 102, 204, 255), (0, 0, 28, 24))
        source.paste((34, 51, 68, 255), (40, 5, 80, 19))
        rendered = png2ws_splash.render_logo(source)
        self.assertEqual(rendered.size, (64, 64))
        pixels = rendered.get_flattened_data() if hasattr(rendered, "get_flattened_data") else rendered.getdata()
        self.assertIn(2, set(pixels))
        self.assertIn(3, set(pixels))


if __name__ == "__main__":
    unittest.main()
