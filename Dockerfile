# ComfyUI worker met face swap en alle modellen ingebakken.
#
# Twee dingen zitten hier in die het standaard-image niet heeft.
#
# 1. ReActor, voor gezichtsconsistentie. RunPods documentatie is stellig dat
#    een network volume wel modellen maar geen custom nodes kan leveren:
#    "not suitable for installing custom nodes; use the Custom Dockerfile
#    method for that".
#
# 2. De modellen zelf. Dat is een bewuste ommezwaai. Ze stonden op een network
#    volume, maar zo'n volume bestaat in precies een datacenter (EU-RO-1), dus
#    elke worker die het gebruikt moet daar draaien. Zat dat vol, dan namen de
#    endpoints jobs aan en gebeurde er nooit iets - soms gemeld als
#    "throttled", soms als een worker die "klaar" heette en niets deed. Het
#    chat-endpoint, dat geen volume gebruikt, had dat probleem nooit.
#
#    De prijs: een image van tegen de 30 GB en een tragere allereerste start
#    per nieuwe worker. Daar staat tegenover dat de worker terecht kan waar
#    dan ook een kaart vrij is, in plaats van te wachten op een datacenter.

FROM runpod/worker-comfyui:5.8.6-base

# insightface compileert vanaf broncode (er is geen wheel voor deze
# combinatie) en heeft daarvoor een C++-toolchain plus cmake nodig. Ontbreken
# die, dan faalt de pip-install met een weinig zeggende melding over een
# missende compiler.
RUN apt-get update && \
    apt-get install -y --no-install-recommends build-essential cmake git unzip && \
    rm -rf /var/lib/apt/lists/*

# Rechtstreeks van GitHub, niet via `comfy-node-install <naam>`: ReActor staat
# niet in het Comfy-register, dus een naam lost daar niet op.
RUN git clone --depth 1 https://github.com/Gourieff/ComfyUI-ReActor.git \
      /comfyui/custom_nodes/ComfyUI-ReActor && \
    python -m pip install --no-cache-dir \
      -r /comfyui/custom_nodes/ComfyUI-ReActor/requirements.txt

# De node bevat een nuditeitsclassifier - de README noemt het project
# "SFW-Friendly" met "a nudity detector to avoid using this software with 18+
# content" - en er is geen gedocumenteerde schakelaar om dat uit te zetten.
# Hij geeft een zwart beeld terug bij wat hij afkeurt, en erger: nsfw_image()
# geeft ook True terug als het model niet laadt, dus een mislukte download zou
# elke generatie blanco maken.
#
# Deze installatie genereert bewust volwassen materiaal, op een prive-instantie
# met een gebruiker. De controle wordt daarom hier uitgeschakeld in plaats van
# tijdens runtime omzeild. Een herdefinitie erachter plakken houdt de patch
# werkend als upstream de binnenkant herschrijft.
RUN set -eux; \
    f="$(find /comfyui/custom_nodes -name reactor_sfw.py | head -1)"; \
    test -n "$f"; \
    printf '\n\n# Uitgeschakeld tijdens de build - zie de Dockerfile.\ndef nsfw_image(img_data, model_path: str):\n    return False\n' >> "$f"; \
    tail -4 "$f"

# buffalo_l is de set waarmee insightface een gezicht vindt en codeert. Komt
# als zip die in een specifieke maplayout uitgepakt moet worden.
RUN set -eux; \
    mkdir -p /comfyui/models/insightface/models/buffalo_l; \
    cd /comfyui/models/insightface/models/buffalo_l; \
    curl -fsSL -o /tmp/buffalo_l.zip \
      https://github.com/deepinsight/insightface/releases/download/v0.7/buffalo_l.zip; \
    unzip -o /tmp/buffalo_l.zip; \
    rm -f /tmp/buffalo_l.zip; \
    ls -la

# ---- modellen ----
# Elk in een eigen RUN. RunPod hanteert 30 minuten per build-stap, dus een
# groot bestand telt zo niet op bij de rest; en bij een wijziging hoeft alleen
# de betreffende laag opnieuw.

# Stable Video Diffusion, voor de videoknop.
RUN comfy model download \
      --url https://huggingface.co/stabilityai/stable-video-diffusion-img2vid-xt/resolve/main/svd_xt.safetensors \
      --relative-path models/checkpoints \
      --filename svd_xt.safetensors

# Het gezichtsmodel voor ReActor. InsightFace heeft inswapper uit publieke
# distributie gehaald, dus dit is een mirror; verdwijnt die, dan valt de app
# terug op genereren zonder swap.
RUN comfy model download \
      --url https://huggingface.co/ezioruan/inswapper_128.onnx/resolve/main/inswapper_128.onnx \
      --relative-path models/insightface \
      --filename inswapper_128.onnx

# CodeFormer, voor de restauratiestap na de swap. Upstream heet het bestand
# codeformer.pth; ReActor verwacht codeformer-v0.1.0.pth.
RUN comfy model download \
      --url https://github.com/sczhou/CodeFormer/releases/download/v0.1.0/codeformer.pth \
      --relative-path models/facerestore_models \
      --filename codeformer-v0.1.0.pth

# Liever de build laten falen dan een generatie: een node of model dat er niet
# is komt tijdens een request naar boven als een nietszeggende foutmelding.
RUN python -c "import os, sys; \
missing = [p for p in ['/comfyui/models/checkpoints/svd_xt.safetensors', \
                       '/comfyui/models/insightface/inswapper_128.onnx', \
                       '/comfyui/models/facerestore_models/codeformer-v0.1.0.pth'] \
           if not os.path.exists(p)]; \
nodes = [r for r, _, _ in os.walk('/comfyui/custom_nodes') if 'eactor' in r.lower()]; \
print('ReActor:', nodes[:1]); \
sys.exit(('ontbreekt: ' + str(missing)) if missing else (0 if nodes else 'ReActor is niet geinstalleerd'))"

# RunPods GitHub-build controleert of de Dockerfile een handler aanroept en
# weigert de repo anders met "runpod.serverless.start() handler not found".
# Het basis-image regelt dat zelf via CMD ["/start.sh"], maar dat is van
# buitenaf niet zichtbaar. Vandaar dit expliciete startpunt.
#
# NIET naar /handler.py kopieren: dat bestaat al in het basis-image en zou
# daarmee overschreven worden. rp_handler.py draagt direct over aan /start.sh.
COPY rp_handler.py /rp_handler.py
CMD ["python3", "-u", "/rp_handler.py"]
