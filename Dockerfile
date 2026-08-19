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
#
# curl staat er expliciet bij. Het basis-image heeft het NIET, wat pas bleek
# toen de build afbrak met "curl: not found" op de eerste download - vier
# stappen ver, na het compileren van insightface. ca-certificates hoort er
# meteen bij, anders faalt elke https-download op een onbekende uitgever.
#
# libgl1 en libglib2.0-0 zijn er voor opencv-python. Dat pakket linkt tegen
# libGL, dat in een kaal container-image ontbreekt; zonder deze twee faalt de
# import van cv2 en daarmee de hele node - stil, want ComfyUI slaat een node
# die niet importeert gewoon over.
RUN apt-get update && \
    apt-get install -y --no-install-recommends \
      build-essential cmake git unzip curl ca-certificates \
      libgl1 libglib2.0-0 && \
    rm -rf /var/lib/apt/lists/*

# Rechtstreeks van GitHub, niet via `comfy-node-install <naam>`: ReActor staat
# niet in het Comfy-register, dus een naam lost daar niet op.
RUN git clone --depth 1 https://github.com/Gourieff/ComfyUI-ReActor.git \
      /comfyui/custom_nodes/ComfyUI-ReActor && \
    python -m pip install --no-cache-dir \
      -r /comfyui/custom_nodes/ComfyUI-ReActor/requirements.txt

# insightface en onnxruntime staan NIET in die requirements.txt - daar staan
# alleen albumentations, onnx, opencv-python, numpy, segment_anything en
# ultralytics in. De node importeert insightface wel bij het laden, dus zonder
# deze regel registreert ReActorFaceSwap zich niet en meldt ComfyUI tijdens een
# generatie alleen "Node 'ReActorFaceSwap' not found". Precies zo ging het de
# eerste keer mis. Normaal regelt ComfyUI-Manager dit via de install.py van de
# node; die draait hier niet.
RUN python -m pip install --no-cache-dir insightface onnxruntime-gpu

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

# De checkpoint waar alle foto's op draaien.
#
# Origineel van Civitai, dat een token eist, dus de bouwmachine kan daar niet
# bij. Deze mirrors leveren byte voor byte hetzelfde bestand: alle zes melden
# 6938041176 bytes en dezelfde inhoudshash
# (f7f7bf9dd05a0da64a58ce442d1ef7d0e38c6953bc7065757ec49a6b803fedfc), en die
# grootte komt exact overeen met het exemplaar dat op het volume stond.
#
# Meerdere bronnen op een rij, want dit zijn kopieen die iemand vrijwillig
# host; verdwijnt er een, dan zou de hele build stuklopen op het enige model
# waar niets zonder werkt. De grootte wordt na afloop gecontroleerd, zodat een
# halve download hier faalt en niet pas bij de eerste generatie.
RUN set -eu; \
    dest=/comfyui/models/checkpoints/pornworksRealPornPhoto_ponyV04.safetensors; \
    expected=6938041176; \
    file=pornworksRealPornPhoto_ponyV04.safetensors; \
    mkdir -p "$(dirname "$dest")"; \
    for repo in \
        AI-Porn/pornworks-real-porn-photo-realistic-nsfw-sdxl-and-pony-chekpoint \
        Manjushri/pornworks-real-porn-photo-realistic-nsfw-sdxl-and-pony-chekpoint \
        useracctu/pornworks-real-porn-photo-realistic-nsfw-sdxl-and-pony-chekpoint \
        berserkronin/pornworks-real-porn-photo-realistic-nsfw-sdxl-and-pony-chekpoint \
        ManuelZnnmc/pornworks-real-porn-photo-realistic-nsfw-sdxl-and-pony-chekpoint \
    ; do \
        echo "proberen: $repo"; \
        if curl -fL --retry 3 --retry-delay 5 -o "$dest" \
             "https://huggingface.co/$repo/resolve/main/$file"; then \
            got=$(wc -c < "$dest"); \
            if [ "$got" = "$expected" ]; then echo "gelukt via $repo ($got bytes)"; break; fi; \
            echo "verkeerde grootte van $repo: $got in plaats van $expected"; \
        fi; \
        rm -f "$dest"; \
    done; \
    test -s "$dest"; \
    test "$(wc -c < "$dest")" = "$expected"

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

# Liever de build laten vallen dan een generatie. Dit controleert niet alleen
# of de bestanden er staan, maar IMPORTEERT de node zoals ComfyUI dat doet -
# want de eerste geslaagde build leverde een image op waarin ReActor wel op
# schijf stond maar niet kon laden, en dat merkte je pas bij de eerste
# gezichtswissel.
COPY check_build.py /tmp/check_build.py
RUN python /tmp/check_build.py && rm -f /tmp/check_build.py

# RunPods GitHub-build controleert of de Dockerfile een handler aanroept en
# weigert de repo anders met "runpod.serverless.start() handler not found".
# Het basis-image regelt dat zelf via CMD ["/start.sh"], maar dat is van
# buitenaf niet zichtbaar. Vandaar dit expliciete startpunt.
#
# NIET naar /handler.py kopieren: dat bestaat al in het basis-image en zou
# daarmee overschreven worden. rp_handler.py draagt direct over aan /start.sh.
COPY rp_handler.py /rp_handler.py
CMD ["python3", "-u", "/rp_handler.py"]
