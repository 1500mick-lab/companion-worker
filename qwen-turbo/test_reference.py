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


if __name__ == "__main__":
    unittest.main()
