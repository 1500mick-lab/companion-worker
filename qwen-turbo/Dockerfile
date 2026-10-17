FROM pytorch/pytorch:2.8.0-cuda12.8-cudnn9-runtime
ENV PYTHONUNBUFFERED=1 HF_HUB_DISABLE_TELEMETRY=1 TOKENIZERS_PARALLELISM=false HF_XET_CHUNK_CACHE_SIZE_BYTES=0
WORKDIR /app
RUN apt-get update && apt-get install -y --no-install-recommends git ca-certificates build-essential python3-dev && rm -rf /var/lib/apt/lists/*
RUN pip install --no-cache-dir runpod==1.12.0 numpy==1.26.4 diffusers==0.29.2 transformers==4.44.2 accelerate==0.34.2 huggingface_hub==0.25.2 pillow safetensors insightface==0.7.3 onnxruntime==1.20.1 onnx==1.17.0 opencv-python-headless==4.10.0.84 && pip check
RUN git clone https://github.com/tencent-ailab/IP-Adapter.git /opt/IP-Adapter && cd /opt/IP-Adapter && git checkout 62e4af9d0c1ac7d5f8dd386a0ccf2211346af1a2
ENV PYTHONPATH=/opt/IP-Adapter
COPY handler.py /app/handler.py
CMD ["python", "-u", "/app/handler.py"]
