"""Single-image RunPod worker using Qwen's official Turbo checkpoint."""
import base64
import io
import logging
import os
import secrets
import threading

MODEL_ID = "Qwen/Qwen-Image-2.1-Turbo"
REVISION = "fc13ba1986fcb905854dc8de2f52eee395f49b5b"
lock = threading.Lock()


def validate(data):
    if not isinstance(data, dict):
        raise ValueError("input must be an object")
    prompt = data.get("prompt")
    if not isinstance(prompt, str) or not prompt.strip() or len(prompt) > 20000:
        raise ValueError("prompt must contain 1 to 20000 characters")
    if any(data.get(key) for key in ("images", "initImage", "faceReference")):
        raise ValueError("This worker supports text-to-image only")
    width, height = data.get("width", 1024), data.get("height", 1024)
    if any(type(v) is not int or v < 256 or v > 1536 or v % 32 for v in (width, height)):
        raise ValueError("dimensions must be multiples of 32 from 256 to 1536")
    if width * height > 1572864:
        raise ValueError("maximum output is 1.5 megapixels")
    seed = data.get("seed", secrets.randbelow(2**31))
    if type(seed) is not int or not 0 <= seed < 2**31:
        raise ValueError("invalid seed")
    return prompt, width, height, seed


def main():
    import runpod
    import torch
    from diffusers import QwenImage21Pipeline

    if not torch.cuda.is_available():
        raise RuntimeError("A CUDA GPU is required")
    pipe = QwenImage21Pipeline.from_pretrained(
        os.environ.get("MODEL_PATH", "/opt/qwen-image-21-turbo"),
        dtype=torch.bfloat16, local_files_only=True,
    ).to("cuda")
    pipe.set_progress_bar_config(disable=True)
    pipe.vae.enable_tiling()

    def handler(job):
        try:
            prompt, width, height, seed = validate(job.get("input"))
        except ValueError as error:
            return {"error": str(error)}
        with lock, torch.inference_mode():
            try:
                # The checkpoint supplies its own official eight-step sigmas.
                image = pipe(
                    prompt=prompt, width=width, height=height,
                    use_kv_cache=True,
                    generator=torch.Generator("cpu").manual_seed(seed),
                ).images[0]
                buffer = io.BytesIO()
                image.save(buffer, format="PNG")
                if buffer.tell() > 5_500_000:
                    return {"error": "Result exceeds the inline image size limit"}
                return {
                    "model": MODEL_ID, "revision": REVISION, "seed": seed,
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
