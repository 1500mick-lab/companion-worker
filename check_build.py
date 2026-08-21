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
    # InstantID: identiteit tijdens het samplen in plaats van een swap erna.
    "models/instantid/ip-adapter.bin",
    "models/controlnet/instantid_diffusion_pytorch_model.safetensors",
    "models/insightface/models/antelopev2",
    # Maskeren, zodat de swap kan blijven staan waar iets voor haar gezicht
    # langsloopt.
    "models/ultralytics/bbox/face_yolov8m.pt",
    "models/sams/sam_vit_b_01ec64.pth",
]

# buffalo_l bevat vijf modellen. De bestaanscontrole van ReActor kijkt maar
# naar drie ervan; ontbreken de andere twee, dan worden die stilzwijgend
# overgeslagen - geen fout, alleen slechtere landmarkdetectie.
BUFFALO = ["det_10g.onnx", "w600k_r50.onnx", "genderage.onnx",
           "2d106det.onnx", "1k3d68.onnx"]

# antelopev2 is de encoder van InstantID - een andere inbeddingsruimte dan
# buffalo_l, dus geen vervanging maar een tweede set. De zip pakt uit met een
# map antelopev2 erin; slaat de build die niet plat, dan staan deze bestanden
# een niveau te diep en ziet insightface een lege modellijst.
ANTELOPE = ["scrfd_10g_bnkps.onnx", "glintr100.onnx", "genderage.onnx",
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
REQUIRED_NODES = ["ReActorFaceSwap", "ReActorRestoreFace", "ReActorMaskHelper"]

# InstantID registreert zijn nodes in een eigen bestand, niet in dat van
# ReActor. ApplyInstantID is degene die de app aanroept; de andere twee laden
# het model en analyseren het bronggezicht.
INSTANTID_NODES = ["InstantIDModelLoader", "InstantIDFaceAnalysis", "ApplyInstantID"]

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

print("== antelopev2 compleet ==")
av = os.path.join(COMFY, "models/insightface/models/antelopev2")
if os.path.isdir(av):
    have = set(os.listdir(av))
    if "antelopev2" in have:
        problems.append(
            "antelopev2 is niet platgeslagen: de modellen staan in "
            "models/antelopev2/antelopev2/, waar insightface niet kijkt")
    for f in ANTELOPE:
        if f in have:
            print("  ok   %s" % f)
        else:
            print("  MIST %s" % f)
            problems.append("antelopev2 mist " + f)
else:
    problems.append("antelopev2 map ontbreekt")

print("== python-pakketten ==")
for name, why in IMPORTS:
    try:
        module = importlib.import_module(name)
        version = getattr(module, "__version__", "")
        print("  ok   %-18s %s" % (name, version))
    except Exception as e:
        print("  MIST %-18s %s" % (name, str(e)[:90]))
        problems.append("kan %s niet importeren%s" % (name, (" - " + why) if why else ""))

def read_python(directory):
    """Alle python in een node-map aan elkaar geplakt.

    Niet alleen nodes.py: welke node in welk bestand staat is aan upstream,
    en ReActorMaskHelper bleek elders geregistreerd. Een controle die maar in
    een bestand kijkt keurt dan een prima image af."""
    out = ""
    for root, _dirs, files in os.walk(directory):
        for name in files:
            if name.endswith(".py"):
                try:
                    out += open(os.path.join(root, name), encoding="utf-8").read()
                except Exception:
                    traceback.print_exc()
    return out


print("== node geregistreerd ==")
if not os.path.isdir(NODE_DIR):
    problems.append("ComfyUI-ReActor staat er niet")
else:
    source = read_python(NODE_DIR)
    for want in REQUIRED_NODES:
        # De registratie is een sleutel in NODE_CLASS_MAPPINGS; een losse
        # klassenaam zegt niets, want die kan gedefinieerd zijn zonder ooit
        # geregistreerd te worden.
        if re.search(r'["\']%s["\']\s*:' % re.escape(want), source):
            print("  ok   %s staat in NODE_CLASS_MAPPINGS" % want)
        else:
            print("  MIST %s" % want)
            problems.append("node niet geregistreerd in nodes.py: " + want)

print("== instantid geregistreerd ==")
iid_dir = os.path.join(COMFY, "custom_nodes", "ComfyUI_InstantID")
iid_src = read_python(iid_dir) if os.path.isdir(iid_dir) else ""
if not iid_src:
    problems.append("ComfyUI_InstantID ontbreekt of bevat geen python")
else:
    for want in INSTANTID_NODES:
        if re.search(r'["\']%s["\']\s*:' % re.escape(want), iid_src):
            print("  ok   %s staat in NODE_CLASS_MAPPINGS" % want)
        else:
            print("  MIST %s" % want)
            problems.append("node niet geregistreerd: " + want)

print("== onnxruntime draait op de GPU ==")
# De requirements van InstantID bevatten een kale `onnxruntime`. Die naast
# onnxruntime-gpu installeren geeft twee pakketten die dezelfde module
# claimen, en dan valt de swap stilletjes terug op de CPU.
try:
    import onnxruntime
    providers = onnxruntime.get_available_providers()
    if "CUDAExecutionProvider" in providers:
        print("  ok   %s" % ", ".join(providers))
    else:
        problems.append("onnxruntime heeft geen CUDAExecutionProvider: %s" % providers)
except Exception as e:
    problems.append("onnxruntime niet importeerbaar: %s" % str(e)[:90])

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
