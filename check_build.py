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
    "models/hyperswap/hyperswap_1a_256.onnx",
    "models/hyperswap/hyperswap_1b_256.onnx",
    "models/hyperswap/hyperswap_1c_256.onnx",
    "models/facerestore_models/GPEN-BFR-512.onnx",
    # Deze twee haalde ReActor tijdens het draaien op - 186 MB per koude
    # start, want de container begint elke keer leeg. parsing_parsenet is
    # niet optioneel: init_parsing_model staat niet achter de use_parse-vlag.
    "models/facedetection/detection_Resnet50_Final.pth",
    "models/facedetection/parsing_parsenet.pth",
    "models/facerestore_models/GPEN-BFR-1024.onnx",
    "models/upscale_models/RealESRGAN_x4.pth",
]

# buffalo_l bevat vijf modellen. De bestaanscontrole van ReActor kijkt maar
# naar drie ervan; ontbreken de andere twee, dan worden die stilzwijgend
# overgeslagen - geen fout, alleen slechtere landmarkdetectie.
BUFFALO = ["det_10g.onnx", "w600k_r50.onnx", "genderage.onnx",
           "2d106det.onnx", "1k3d68.onnx"]

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
REQUIRED_NODES = ["ReActorFaceSwap", "ReActorRestoreFace"]

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

print("== buffalo_l compleet ==")
bl = os.path.join(COMFY, "models/insightface/models/buffalo_l")
if os.path.isdir(bl):
    have = set(os.listdir(bl))
    for f in BUFFALO:
        if f in have:
            print("  ok   %s" % f)
        else:
            print("  MIST %s" % f)
            problems.append("buffalo_l mist " + f)
else:
    problems.append("buffalo_l map ontbreekt")

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

print("== videohelpersuite ==")
vhs = os.path.join(COMFY, "custom_nodes", "ComfyUI-VideoHelperSuite")
if os.path.isdir(vhs):
    print("  ok   node aanwezig")
else:
    problems.append("ComfyUI-VideoHelperSuite ontbreekt")

print("== handler leest video-uitvoer ==")
# Zonder deze patch geeft VHS niets terug: de worker kijkt alleen naar
# "images" en VHS schrijft onder "gifs". Dat faalt stil, dus het hoort een
# build-fout te zijn en geen verrassing bij de eerste clip.
handler = "/handler.py"
if os.path.isfile(handler):
    if 'node_output.pop("gifs")' in open(handler, encoding="utf-8").read():
        print("  ok   gifs worden als images opgehaald")
    else:
        problems.append("de handler-patch voor video-uitvoer ontbreekt")
else:
    problems.append("/handler.py ontbreekt")

print("== hyperswap-uitlijning ==")
hs = os.path.join(NODE_DIR, "reactor_core", "hyperswap.py")
if os.path.isfile(hs):
    text = open(hs, encoding="utf-8").read()
    if "92.589" in text and "84.87" not in text:
        print("  ok   gecorrigeerd naar FaceFusions arcface_128@256")
    else:
        problems.append("de hyperswap-uitlijning is niet gepatcht")
else:
    problems.append("reactor_core/hyperswap.py ontbreekt")

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
