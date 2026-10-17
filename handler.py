"""Single-image RunPod worker using Qwen's official Turbo checkpoint."""
import base64
import binascii
import io
import logging
import os
import secrets
import threading
import warnings
from pathlib import Path

import runpod
from PIL import Image, ImageOps, UnidentifiedImageError

MODEL_ID = "Qwen/Qwen-Image-2.1-Turbo"
REVISION = "fc13ba1986fcb905854dc8de2f52eee395f49b5b"
lock = threading.Lock()
Image.MAX_IMAGE_PIXELS = 12_000_000


def reference_image(value):
    if value is None:
        return None
    if not isinstance(value, str) or not value or len(value) > 8_000_000:
        raise ValueError("Reference must be a base64 image of at most 6 MB")
    if value.startswith("data:"):
        header, separator, value = value.partition(",")
        if not separator or header not in ("data:image/png;base64", "data:image/jpeg;base64", "data:image/webp;base64"):
            raise ValueError("Reference must be PNG, JPEG or WebP")
    try:
        raw = base64.b64decode(value, validate=True)
        with warnings.catch_warnings():
            warnings.simplefilter("error", Image.DecompressionBombWarning)
            with Image.open(io.BytesIO(raw)) as source:
                if source.format not in ("PNG", "JPEG", "WEBP") or source.width * source.height > 12_000_000:
                    raise ValueError("Reference must be PNG, JPEG or WebP, at most 12 megapixels")
                image = ImageOps.exif_transpose(source).convert("RGBA")
                image.thumbnail((1024, 1024), Image.Resampling.LANCZOS)
                return image
    except (binascii.Error, OSError, UnidentifiedImageError, Image.DecompressionBombError, Image.DecompressionBombWarning) as error:
        raise ValueError("Invalid reference image") from error


def validate(data):
    if not isinstance(data, dict):
        raise ValueError("input must be an object")
    prompt = data.get("prompt")
    if not isinstance(prompt, str) or not prompt.strip() or len(prompt) > 20000:
        raise ValueError("prompt must contain 1 to 20000 characters")
    if data.get("images"):
        raise ValueError("Use faceReference or initImage for a single reference")
    face = data.get("faceReference")
    reference = reference_image(face if face is not None else data.get("initImage"))
    if face is not None:
        prompt = (
            "Use the person in the reference image as the same character in the new photograph. "
            "Preserve their facial identity, facial proportions, eye shape, nose, lips, skin tone "
            "and distinctive facial features. Do not replace their face with a different person. "
            "Change the pose, clothing and background as requested in this scene: " + prompt
        )
    width, height = data.get("width", 1024), data.get("height", 1024)
    if any(type(v) is not int or v < 256 or v > 1536 or v % 32 for v in (width, height)):
        raise ValueError("dimensions must be multiples of 32 from 256 to 1536")
    if width * height > 1572864:
        raise ValueError("maximum output is 1.5 megapixels")
    seed = data.get("seed", secrets.randbelow(2**31))
    if type(seed) is not int or not 0 <= seed < 2**31:
        raise ValueError("invalid seed")
    return prompt, width, height, seed, reference


def main():
    import torch
    from diffusers import QwenImage21Pipeline

    if not torch.cuda.is_available():
        raise RuntimeError("A CUDA GPU is required")
    model_path = Path(os.environ.get("MODEL_PATH", "/opt/qwen-image-21-turbo"))
    if not (model_path / "model_index.json").exists():
        from huggingface_hub import snapshot_download
        snapshot_download(
            repo_id=MODEL_ID, revision=REVISION, local_dir=str(model_path),
            ignore_patterns=["assets/*", ".gitattributes"], max_workers=4,
        )
    pipe = QwenImage21Pipeline.from_pretrained(
        str(model_path),
        dtype=torch.bfloat16, local_files_only=True,
    ).to("cuda")
    pipe.set_progress_bar_config(disable=True)
    # Qwen Image 2.1 tiled decoding introduces magenta seams in RGB and alpha.
    # Decode the complete frame; never hide this defect with color correction.
    pipe.vae.disable_tiling()
    pipe.vae.disable_slicing()

    def handler(job):
        try:
            prompt, width, height, seed, reference = validate(job.get("input"))
        except ValueError as error:
            return {"error": str(error)}
        with lock, torch.inference_mode():
            try:
                # The checkpoint supplies its own official eight-step sigmas.
                image = pipe(
                    prompt=prompt, width=width, height=height,
                    image=reference,
                    use_kv_cache=True,
                    generator=torch.Generator("cpu").manual_seed(seed),
                ).images[0]
                buffer = io.BytesIO()
                image.save(buffer, format="PNG")
                if buffer.tell() > 5_500_000:
                    return {"error": "Result exceeds the inline image size limit"}
                return {
                    "model": MODEL_ID, "revision": REVISION, "seed": seed,
                    "reference_used": reference is not None,
                    "vae_tiling": False,
                    "images": [{"data": base64.b64encode(buffer.getvalue()).decode("ascii")}],
                }
            except torch.cuda.OutOfMemoryError:
                return {"error": "GPU memory exhausted; reduce image dimensions", "refresh_worker": True}
            except Exception:
                logging.exception("Qwen generation failed")
                return {"error": "Image generation failed; check the worker logs", "refresh_worker": True}

    runpod.serverless.start({"handler": handler})


if __name__ == "__main__":
    main()
