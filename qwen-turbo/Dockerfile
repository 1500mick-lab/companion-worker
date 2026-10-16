FROM pytorch/pytorch:2.8.0-cuda12.8-cudnn9-runtime
ENV PYTHONUNBUFFERED=1 HF_HUB_DISABLE_TELEMETRY=1 TOKENIZERS_PARALLELISM=false
WORKDIR /app
RUN apt-get update && apt-get install -y --no-install-recommends git ca-certificates && rm -rf /var/lib/apt/lists/*
RUN pip install --no-cache-dir runpod==1.12.0 transformers==5.20.1 accelerate pillow safetensors huggingface_hub \
    'diffusers @ git+https://github.com/huggingface/diffusers.git@d42ebf9c6e0b46103b74283f5324357a67acaa04' && pip check
ENV HF_HUB_OFFLINE=1 MODEL_PATH=/runpod-volume/huggingface-cache/hub/models--Qwen--Qwen-Image-2.1-Turbo/snapshots/fc13ba1986fcb905854dc8de2f52eee395f49b5b
COPY handler.py /app/handler.py
CMD ["python", "-u", "/app/handler.py"]
