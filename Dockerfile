# ComfyUI worker met face swap.
#
# Het standaard-image runpod/worker-comfyui heeft geen custom nodes, en
# RunPods eigen documentatie is daar stellig over: een network volume kan
# modellen leveren maar geen nodes — "not suitable for installing custom
# nodes; use the Custom Dockerfile method for that". Gezichtsconsistentie
# werkt met ReActor, en dat is een custom node. Vandaar dit image.
#
# Modellen zitten hier bewust NIET in. Die staan op het network volume, wat
# dit image klein houdt en betekent dat een ander model geen herbouw kost.
# De enige uitzondering is buffalo_l: insightface wil die uit een zip in een
# eigen maplayout hebben, wat op een volume onhandiger is dan hier.

FROM runpod/worker-comfyui:5.8.6-base

# insightface compileert vanaf broncode (geen wheel voor deze combinatie), en
# heeft daarvoor een C++-toolchain plus cmake nodig. Ontbreken die, dan faalt
# de pip-install met een weinig zeggende foutmelding over een missende
# compiler.
RUN apt-get update && \
    apt-get install -y --no-install-recommends build-essential cmake git unzip && \
    rm -rf /var/lib/apt/lists/*

# Rechtstreeks van GitHub, niet via `comfy-node-install <naam>`: ReActor staat
# niet in het Comfy-register, dus een naam zou hier niet oplossen. Een
# vastgezette clone is bovendien reproduceerbaar.
RUN git clone --depth 1 https://github.com/Gourieff/ComfyUI-ReActor.git \
      /comfyui/custom_nodes/ComfyUI-ReActor && \
    python -m pip install --no-cache-dir \
      -r /comfyui/custom_nodes/ComfyUI-ReActor/requirements.txt

# De node bevat een nuditeitsclassifier — de README noemt het project
# "SFW-Friendly" met "a nudity detector to avoid using this software with 18+
# content" — en er is geen gedocumenteerde schakelaar om dat uit te zetten.
# Hij geeft een zwart beeld terug bij wat hij afkeurt, en erger: nsfw_image()
# geeft óók True terug als het model niet laadt, dus één mislukte download zou
# élke generatie blanco maken.
#
# Deze installatie genereert bewust volwassen materiaal, op een privé-instantie
# met één gebruiker. De controle wordt daarom hier uitgeschakeld in plaats van
# tijdens runtime omzeild. Een herdefinitie erachter plakken (in plaats van de
# oorspronkelijke functie bewerken) houdt de patch werkend als upstream de
# binnenkant herschrijft.
RUN set -eux; \
    f="$(find /comfyui/custom_nodes -name reactor_sfw.py | head -1)"; \
    test -n "$f"; \
    printf '\n\n# Uitgeschakeld tijdens de build — zie de Dockerfile.\ndef nsfw_image(img_data, model_path: str):\n    return False\n' >> "$f"; \
    tail -4 "$f"

# buffalo_l is de detectie- en herkenningsset waarmee insightface een gezicht
# vindt en codeert. Hij komt als zip die in een specifieke map uitgepakt moet
# worden, dus die halen we hier binnen in plaats van los op het volume.
RUN set -eux; \
    mkdir -p /comfyui/models/insightface/models/buffalo_l; \
    cd /comfyui/models/insightface/models/buffalo_l; \
    curl -fsSL -o /tmp/buffalo_l.zip \
      https://github.com/deepinsight/insightface/releases/download/v0.7/buffalo_l.zip; \
    unzip -o /tmp/buffalo_l.zip; \
    rm -f /tmp/buffalo_l.zip; \
    ls -la

# Liever de build laten falen dan een generatie: een node die er niet is komt
# er tijdens een request uit als een nietszeggende "node type not found".
RUN python -c "import os, sys; \
hits = [r for r, _, _ in os.walk('/comfyui/custom_nodes') if 'eactor' in r.lower()]; \
print('ReActor gevonden in:', hits[:1]); \
sys.exit(0 if hits else 'ReActor is niet geinstalleerd')"

# RunPods GitHub-build controleert of de Dockerfile een handler aanroept en
# weigert de repo anders met "runpod.serverless.start() handler not found".
# Het basis-image regelt dit zelf via CMD ["/start.sh"], maar dat is van
# buitenaf niet zichtbaar. Vandaar dit expliciete startpunt.
#
# NIET naar /handler.py kopiëren: dat bestand bestaat al in het basis-image en
# zou daarmee overschreven worden. rp_handler.py draagt direct over aan
# /start.sh, zodat de container zich verder gedraagt als voorheen.
COPY rp_handler.py /rp_handler.py
CMD ["python3", "-u", "/rp_handler.py"]
