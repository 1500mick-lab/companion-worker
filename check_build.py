"""
Controleert tijdens de build of het image compleet is.

Bestaat omdat de eerste geslaagde build een kapot image opleverde. ComfyUI
slaat een custom node die niet importeert stilzwijgend over, dus het image
werd netjes gepubliceerd, de worker startte, foto's werkten - en pas bij de
eerste gezichtswissel kwam er "Node 'ReActorFaceSwap' not found" uit. De
oorzaak lag drie stappen eerder: insightface staat niet in de requirements.txt
van de node en werd dus nooit geinstalleerd.

Wat hier NIET gebeurt is de node volledig laden. Dat werd geprobeerd en het
faalt altijd: ReActor importeert comfy.model_management, en ComfyUI roept
tijdens dat importeren torch.cuda.current_device() aan. RunPods bouwmachines
hebben geen GPU, dus dat eindigt gegarandeerd in "Found no NVIDIA driver" -
een fout over de bouwomgeving, niet over het image.

In plaats daarvan wordt getest wat wel te testen valt zonder GPU: staan de
modellen er, zijn de python-pakketten die de node importeert aanwezig, en
registreert de broncode de node die de app aanroept. Precies die eerste
storing - insightface ontbreekt - wordt hiermee gevangen.
"""

import importlib
import os
import re
import sys
import traceback

COMFY = "/comfyui"
NODE_DIR = os.path.join(COMFY, "custom_nodes", "ComfyUI-ReActor")

MODELS = [
    "models/checkpoints/pornworksRealPornPhoto_ponyV04.safetensors",
    "models/checkpoints/svd_xt.safetensors",
    "models/insightface/inswapper_128.onnx",
    "models/facerestore_models/codeformer-v0.1.0.pth",
    "models/insightface/models/buffalo_l",
]

# Wat de node importeert en wat zonder GPU te controleren is. insightface en
# cv2 staan bovenaan: die twee waren de daadwerkelijke storing.
IMPORTS = [
    ("insightface", "ontbreekt in de requirements.txt van de node"),
    ("cv2", "opencv; heeft libGL nodig, dat in een kaal image ontbreekt"),
    ("onnxruntime", "draait het swap-model"),
    ("onnx", ""),
    ("albumentations", ""),
    ("ultralytics", ""),
    ("segment_anything", ""),
]

# De nodes waar de app op leunt.
REQUIRED_NODES = ["ReActorFaceSwap"]

problems = []

print("== modellen ==")
for rel in MODELS:
    path = os.path.join(COMFY, rel)
    if os.path.isdir(path):
        n = len(os.listdir(path))
        print("  ok   %s (%d bestanden)" % (rel, n))
        if n == 0:
            problems.append("map is leeg: " + rel)
    elif os.path.isfile(path):
        print("  ok   %s (%.1f MB)" % (rel, os.path.getsize(path) / 1048576))
    else:
        print("  MIST %s" % rel)
        problems.append("ontbreekt: " + rel)

print("== python-pakketten ==")
for name, why in IMPORTS:
    try:
        module = importlib.import_module(name)
        version = getattr(module, "__version__", "")
        print("  ok   %-18s %s" % (name, version))
    except Exception as e:
        print("  MIST %-18s %s" % (name, str(e)[:90]))
        problems.append("kan %s niet importeren%s" % (name, (" - " + why) if why else ""))

print("== node geregistreerd ==")
nodes_py = os.path.join(NODE_DIR, "nodes.py")
if not os.path.isfile(nodes_py):
    problems.append("ComfyUI-ReActor/nodes.py staat er niet")
else:
    try:
        source = open(nodes_py, encoding="utf-8").read()
    except Exception:
        traceback.print_exc()
        source = ""
    for want in REQUIRED_NODES:
        # De registratie is een sleutel in NODE_CLASS_MAPPINGS; een losse
        # klassenaam zegt niets, want die kan gedefinieerd zijn zonder ooit
        # geregistreerd te worden.
        if re.search(r'["\']%s["\']\s*:' % re.escape(want), source):
            print("  ok   %s staat in NODE_CLASS_MAPPINGS" % want)
        else:
            print("  MIST %s" % want)
            problems.append("node niet geregistreerd in nodes.py: " + want)

print("== nsfw-controle uitgeschakeld ==")
sfw = os.path.join(NODE_DIR, "scripts", "reactor_sfw.py")
if os.path.isfile(sfw):
    tail = open(sfw, encoding="utf-8").read()[-400:]
    if "return False" in tail:
        print("  ok   patch staat achter reactor_sfw.py")
    else:
        problems.append("de nsfw-patch staat niet in reactor_sfw.py")
else:
    print("  (geen reactor_sfw.py gevonden - upstream kan het hernoemd hebben)")

if problems:
    print("\n== BUILD AFGEKEURD ==")
    for p in problems:
        print("  - " + p)
    sys.exit(1)

print("\nAlles aanwezig.")
