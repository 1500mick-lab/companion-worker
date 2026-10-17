"""Validate reference handling without downloading models or using a GPU."""
import base64
import importlib.util
import io
import sys
import types
import unittest
from pathlib import Path

from PIL import Image

sys.modules.setdefault("runpod", types.ModuleType("runpod"))
spec = importlib.util.spec_from_file_location("worker", Path(__file__).parents[1] / "handler.py")
worker = importlib.util.module_from_spec(spec)
spec.loader.exec_module(worker)


class ReferenceTests(unittest.TestCase):
    def image(self, size=(64, 80)):
        output = io.BytesIO()
        Image.new("RGB", size, "blue").save(output, "PNG")
        return base64.b64encode(output.getvalue()).decode()

    def test_face_is_decoded_without_rewriting_scene(self):
        prompt, _, _, _, ref = worker.validate({"prompt": "in a garden", "faceReference": self.image()})
        self.assertEqual(ref.size, (64, 80))
        self.assertEqual(ref.mode, "RGBA")
        self.assertEqual(prompt, "in a garden")

    def test_large_input_is_downscaled_and_face_takes_precedence(self):
        *_, ref = worker.validate({"prompt": "portrait", "faceReference": self.image((1600, 1200)), "initImage": "invalid"})
        self.assertEqual(ref.size, (1024, 768))

    def test_editing_and_text_only_remain_available(self):
        prompt, *_, ref = worker.validate({"prompt": "blue background", "initImage": "data:image/png;base64," + self.image()})
        self.assertEqual(prompt, "blue background")
        self.assertIsNotNone(ref)
        self.assertIsNone(worker.validate({"prompt": "portrait"})[-1])

    def test_bad_references_fail_instead_of_being_ignored(self):
        for value in ("https://example.com/portrait.png", "bad", "", 123, "data:image/svg+xml;base64,AAAA", "A" * 8_000_001):
            with self.subTest(value=str(value)[:40]), self.assertRaises(ValueError):
                worker.validate({"prompt": "portrait", "faceReference": value})


class QualityTests(unittest.TestCase):
    def test_small_legacy_sizes_render_native_detail_with_bounded_work(self):
        for width, height in [(512, 640), (768, 1024), (832, 1216), (1024, 1024), (1536, 1024)]:
            out_w, out_h = worker.quality_dimensions(width, height)
            self.assertGreaterEqual(out_w * out_h, 1_400_000)
            self.assertLessEqual(out_w * out_h, 1_572_864)
            self.assertLessEqual(max(out_w, out_h), 1536)
            self.assertEqual(out_w % 32, 0)
            self.assertEqual(out_h % 32, 0)
            self.assertLess(abs(out_w / out_h - width / height), 0.04)

    def test_extreme_ratios_remain_within_existing_memory_limit(self):
        for width, height in [(256, 1536), (1536, 256), (256, 256)]:
            w, h = worker.quality_dimensions(width, height)
            self.assertLessEqual(w * h, 1_572_864)
            self.assertLessEqual(max(w, h), 1536)
            self.assertGreaterEqual(min(w, h), 256)


if __name__ == "__main__":
    unittest.main()
