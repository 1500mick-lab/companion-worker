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
# Ubuntu 24.04 hernoemde libglib2.0-0 naar libglib2.0-0t64 (de 64-bits
# time_t-overgang), en libgl1-mesa-glx heet daar alleen nog libgl1. Welke naam
# bestaat hangt af van de release van het basis-image, dus beide worden
# geprobeerd; pas als geen van beide er is valt de build om. De ctypes-regel
# controleert daarna dat libGL echt laadbaar is, want dat is wat cv2 nodig
# heeft - en een cv2 die niet importeert neemt stilzwijgend de hele node mee.
#
# GEEN commentaarregels binnen deze RUN: een regel die op \ eindigt plakt aan
# de volgende, en een # daarin zou de rest van het commando wegcommentarieren.
RUN set -eux; \
    apt-get update; \
    apt-get install -y --no-install-recommends \
      build-essential cmake git unzip curl ca-certificates; \
    apt-get install -y --no-install-recommends libgl1 || \
      apt-get install -y --no-install-recommends libgl1-mesa-glx; \
    apt-get install -y --no-install-recommends libglib2.0-0t64 || \
      apt-get install -y --no-install-recommends libglib2.0-0; \
    python -c "import ctypes; ctypes.CDLL('libGL.so.1'); print('libGL ok')"; \
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

# GPEN-BFR-512 als alternatieve restauratie. De ontwikkelaar die ReActors
# HyperSwap-ondersteuning schreef meldt dat inswapper met GPEN-BFR-512 op
# zichtbaarheid 0.7 de beste gelijkenis geeft die hij kent - beter dan
# CodeFormer, en juist sterker in gezichtsdetail zoals de mond.
RUN comfy model download \
      --url https://huggingface.co/datasets/Gourieff/ReActor/resolve/main/models/facerestore_models/GPEN-BFR-512.onnx \
      --relative-path models/facerestore_models \
      --filename GPEN-BFR-512.onnx

# GPEN-BFR-1024 voor meer detail in het gezicht. ReActor leest de werkgrootte
# UIT DE BESTANDSNAAM - r_faceboost/restorer.py doet letterlijk
# `if "1024" in face_restore_model.lower(): face_size = 1024`. Dit bestand mag
# dus nooit hernoemd worden, anders draait hij alsnog op 512.
RUN comfy model download \
      --url https://huggingface.co/datasets/Gourieff/ReActor/resolve/main/models/facerestore_models/GPEN-BFR-1024.onnx \
      --relative-path models/facerestore_models \
      --filename GPEN-BFR-1024.onnx

# HyperSwap werkt op 256x256 in plaats van de 128x128 van inswapper. Dat is
# vier keer zoveel gezichtsinformatie, en het verschil dat ertoe doet zodra
# het gezicht in beeld groter is dan 128 pixels - wat bij een portret van
# 832x1216 altijd zo is. FaceFusion, dat het model maakte, heeft het in 3.3.2
# tot standaard gemaakt in plaats van inswapper.
#
# ReActor kiest het model op de BESTANDSNAAM: bevat die "hyperswap", dan
# gebruikt hij de HyperSwapper-klasse en zoekt hij in models/hyperswap. Deze
# bestanden dus niet hernoemen.
#
# Alle drie de varianten, want 1a/1b/1c zijn geen snelheidsniveaus maar
# afzonderlijk getrainde modellen - even groot, zelfde graaf. Welke op een
# bepaald gezicht het beste werkt is niet te voorspellen.
RUN set -eux; \
    for v in 1a 1b 1c; do \
      comfy model download \
        --url "https://huggingface.co/datasets/Gourieff/ReActor/resolve/main/models/hyperswap_${v}_256.onnx" \
        --relative-path models/hyperswap \
        --filename "hyperswap_${v}_256.onnx"; \
    done; \
    ls -la /comfyui/models/hyperswap

# Zie de toelichting in het script: ReActor voert HyperSwap een uitsnede die
# 22,4% te ver is ingezoomd. Dit zet de uitlijning gelijk aan wat FaceFusion
# gebruikt, en faalt als de code upstream is veranderd.
COPY patch_hyperswap.py /tmp/patch_hyperswap.py
RUN python /tmp/patch_hyperswap.py && rm -f /tmp/patch_hyperswap.py

# ---- wat ReActor anders TIJDENS HET DRAAIEN ophaalt ----
#
# Dit was de echte oorzaak van een eerste gezichtswissel die 357 seconden
# duurde terwijl de tweede er 9 nodig had. Een serverless container begint
# elke koude start met een lege schijf, dus die download gebeurde telkens
# opnieuw.
#
# r_facelib/utils/misc.py rekent het doelpad uit als ROOT_DIR/../../models/
# facedetection, oftewel /comfyui/models/facedetection, en de bestandsnaam is
# simpelweg de laatste component van de URL. De enige cachecontrole is
# os.path.exists(), dus het bestand hier neerzetten schakelt de download
# volledig uit.
#
# parsing_parsenet.pth is niet optioneel: init_parsing_model staat NIET achter
# de use_parse-vlag, dus die wordt opgehaald zodra er uberhaupt gerestaureerd
# wordt, ongeacht welke instellingen je kiest.
#
# De laatste twee zijn de alternatieve detectoren. Klein genoeg om mee te
# nemen, en anders betaal je alsnog een download op het moment dat je ooit
# van detector wisselt.
RUN set -eux; \
    mkdir -p /comfyui/models/facedetection; \
    cd /comfyui/models/facedetection; \
    curl -fSL --retry 3 -O https://github.com/xinntao/facexlib/releases/download/v0.1.0/detection_Resnet50_Final.pth; \
    curl -fSL --retry 3 -O https://github.com/sczhou/CodeFormer/releases/download/v0.1.0/parsing_parsenet.pth; \
    curl -fSL --retry 3 -O https://github.com/xinntao/facexlib/releases/download/v0.1.0/detection_mobilenet0.25_Final.pth; \
    curl -fSL --retry 3 -O https://github.com/sczhou/CodeFormer/releases/download/v0.1.0/yolov5n-face.pth; \
    ls -la

# Upscalers, voor scherpere uitvoer: renderen op 832x1216 en daarna 4x
# opschalen met RealESRGAN, terug naar 2x. Deze stonden op het oude volume en
# waren nooit in het image beland - de eerste opschaalpoging faalde daarom op
# "model_name not in []".
RUN comfy model download       --url https://huggingface.co/ai-forever/Real-ESRGAN/resolve/main/RealESRGAN_x4.pth       --relative-path models/upscale_models       --filename RealESRGAN_x4.pth

# VideoHelperSuite, zodat de worker een clip als EEN mp4 teruggeeft in plaats
# van als losse frames. Dat is niet cosmetisch: RunPod begrenst hoe groot een
# job-antwoord mag zijn, en 25 frames als base64-PNG ging daaroverheen - de
# job meldde COMPLETED en gaf niets terug.
RUN git clone --depth 1 https://github.com/Kosinkadink/ComfyUI-VideoHelperSuite.git \
      /comfyui/custom_nodes/ComfyUI-VideoHelperSuite && \
    python -m pip install --no-cache-dir \
      -r /comfyui/custom_nodes/ComfyUI-VideoHelperSuite/requirements.txt

# VideoHelperSuite roept ffmpeg aan voor alles wat geen gif is.
RUN apt-get update && \
    apt-get install -y --no-install-recommends ffmpeg && \
    rm -rf /var/lib/apt/lists/* && \
    ffmpeg -version | head -1

# Zonder deze patch levert VideoHelperSuite niets op: de worker leest alleen
# de sleutel "images" en VHS schrijft onder "gifs". Zie het script.
COPY patch_handler.py /tmp/patch_handler.py
RUN python /tmp/patch_handler.py && rm -f /tmp/patch_handler.py

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
