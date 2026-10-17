"""SDXL FaceID Plus V2 worker: condition generation on identity, never swap pixels."""
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

MODEL_ID = "SG161222/RealVisXL_V4.0"
REVISION = "26dfe44930964cd70d0a817b6d1cc945c130e38d"
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
    print("Loading SDXL FaceID Plus V2 worker", flush=True)
    import cv2
    import numpy as np
    import torch
    from diffusers import AutoencoderKL, DDIMScheduler, StableDiffusionXLPipeline
    from huggingface_hub import hf_hub_download, snapshot_download
    from insightface.app import FaceAnalysis
    from insightface.utils import face_align
    from ip_adapter.ip_adapter_faceid import IPAdapterFaceIDPlusXL

    if not torch.cuda.is_available():
        raise RuntimeError("A CUDA GPU is required")
    cache = Path("/opt/faceid-models")
    cache.mkdir(exist_ok=True)
    model = snapshot_download(MODEL_ID, revision=REVISION, local_dir=str(cache / "sdxl"),
        allow_patterns=["model_index.json", "scheduler/*", "tokenizer/*", "tokenizer_2/*",
                        "text_encoder/config.json", "text_encoder/model.fp16.safetensors",
                        "text_encoder_2/config.json", "text_encoder_2/model.fp16.safetensors",
                        "unet/config.json", "unet/diffusion_pytorch_model.fp16.safetensors"])
    vae_path = snapshot_download("madebyollin/sdxl-vae-fp16-fix", revision="207b116dae70ace3637169f1ddd2434b91b3a8cd",
        local_dir=str(cache / "vae"), allow_patterns=["config.json", "diffusion_pytorch_model.safetensors"])
    encoder = snapshot_download("h94/IP-Adapter", revision="018e402774aeeddd60609b4ecdb7e298259dc729",
        local_dir=str(cache / "clip"), allow_patterns=["models/image_encoder/config.json", "models/image_encoder/model.safetensors"])
    adapter_path = hf_hub_download("h94/IP-Adapter-FaceID", "ip-adapter-faceid-plusv2_sdxl.bin",
        revision="43907e6f44d079bf1a9102d9a6e56aef7a219bae")
    vae = AutoencoderKL.from_pretrained(vae_path, torch_dtype=torch.float16)
    pipe = StableDiffusionXLPipeline.from_pretrained(model, vae=vae,
        torch_dtype=torch.float16, variant="fp16", local_files_only=True, add_watermarker=False).to("cuda")
    pipe.scheduler = DDIMScheduler(num_train_timesteps=1000, beta_start=0.00085, beta_end=0.012,
        beta_schedule="scaled_linear", clip_sample=False, set_alpha_to_one=False, steps_offset=1)
    pipe.set_progress_bar_config(disable=True)
    pipe.vae.disable_tiling()
    adapter = IPAdapterFaceIDPlusXL(pipe, str(Path(encoder) / "models/image_encoder"), adapter_path, "cuda")
    faces = FaceAnalysis(name="buffalo_l", root=str(cache / "insightface"),
        allowed_modules=["detection", "recognition"], providers=["CPUExecutionProvider"])
    faces.prepare(ctx_id=-1, det_size=(640, 640))

    def handler(job):
        try:
            data = job.get("input")
            prompt, width, height, seed, reference = validate(data)
            negative = data.get("negativePrompt", "")
            if not isinstance(negative, str) or len(negative) > 4000:
                raise ValueError("Invalid negative prompt")
            # Bound compute independently of legacy client step preferences.
            steps = 30
        except ValueError as error:
            return {"error": str(error)}
        with lock, torch.inference_mode():
            try:
                if reference is not None:
                    rgb = np.array(reference.convert("RGB"))
                    detected = faces.get(cv2.cvtColor(rgb, cv2.COLOR_RGB2BGR))
                    if len(detected) != 1:
                        return {"error": "FaceID vereist precies één duidelijk zichtbaar gezicht in de profielfoto."}
                    face = detected[0]
                    embedding = torch.from_numpy(face.normed_embedding).unsqueeze(0)
                    crop = face_align.norm_crop(rgb, landmark=face.kps, image_size=224)
                else:
                    # Keep adapter token layout valid while disabling all identity influence.
                    embedding = torch.zeros((1, 512))
                    crop = Image.new("RGB", (224, 224), "black")
                images = adapter.generate(face_image=crop, faceid_embeds=embedding,
                    prompt=prompt, negative_prompt=negative or "blurry, low quality, distorted face, watermark, text",
                    scale=0.8 if reference is not None else 0.0, s_scale=1.0, shortcut=True,
                    num_samples=1, num_inference_steps=steps, guidance_scale=6.0,
                    width=width, height=height, seed=seed)
                buffer = io.BytesIO()
                images[0].convert("RGB").save(buffer, format="PNG")
                if buffer.tell() > 5_500_000:
                    return {"error": "Result exceeds the inline image size limit"}
                return {"model": MODEL_ID, "revision": REVISION, "seed": seed,
                    "identity_engine": "ip-adapter-faceid-plusv2-sdxl",
                    "reference_used": reference is not None, "face_swap_applied": False,
                    "images": [{"data": base64.b64encode(buffer.getvalue()).decode("ascii")} ]}
            except torch.cuda.OutOfMemoryError:
                return {"error": "GPU memory exhausted; reduce image dimensions", "refresh_worker": True}
            except Exception:
                logging.exception("SDXL FaceID generation failed")
                return {"error": "FaceID generation failed; check the worker logs", "refresh_worker": True}

    runpod.serverless.start({"handler": handler})


if __name__ == "__main__":
    try:
        main()
    except Exception:
        import sys, traceback
        traceback.print_exc(file=sys.stdout)
        raise
