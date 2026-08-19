"""
Controleert tijdens de build of het image compleet is.

Bestaat omdat de eerste geslaagde build een kapot image opleverde. ComfyUI
slaat een custom node die niet importeert stilzwijgend over, dus het image
werd netjes gepubliceerd, de worker startte, foto's werkten - en pas bij de
eerste gezichtswissel kwam er "Node 'ReActorFaceSwap' not found" uit. De
oorzaak lag drie stappen eerder: insightface staat niet in de requirements.txt
van de node en werd dus nooit geinstalleerd.

Een importfout hoort de build te laten vallen, niet stilletjes door te gaan.
"""

import importlib.util
import os
import sys
import traceback

COMFY = "/comfyui"

MODELS = [
    "models/checkpoints/pornworksRealPornPhoto_ponyV04.safetensors",
    "models/checkpoints/svd_xt.safetensors",
    "models/insightface/inswapper_128.onnx",
    "models/facerestore_models/codeformer-v0.1.0.pth",
    "models/insightface/models/buffalo_l",
]

# De nodes waar de app op leunt. Ontbreekt er een, dan komt dat er tijdens een
# generatie uit als een nietszeggende foutmelding.
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

print("== ReActor laden ==")
# Zoals ComfyUI het doet: het pad van ComfyUI moet erin, anders vinden de
# nodes hun eigen `folder_paths` en `comfy.*` niet.
sys.path.insert(0, COMFY)
node_dir = os.path.join(COMFY, "custom_nodes", "ComfyUI-ReActor")
init = os.path.join(node_dir, "__init__.py")

if not os.path.isfile(init):
    problems.append("ComfyUI-ReActor staat niet in custom_nodes")
else:
    sys.path.insert(0, os.path.join(COMFY, "custom_nodes"))
    try:
        spec = importlib.util.spec_from_file_location("ComfyUI_ReActor", init)
        module = importlib.util.module_from_spec(spec)
        sys.modules["ComfyUI_ReActor"] = module
        spec.loader.exec_module(module)
        names = list(getattr(module, "NODE_CLASS_MAPPINGS", {}))
        print("  geladen, %d nodes: %s" % (len(names), ", ".join(sorted(names)[:8])))
        for want in REQUIRED_NODES:
            if want not in names:
                problems.append("node ontbreekt na het laden: " + want)
    except Exception:
        # De hele traceback, want dit is precies de informatie die anders
        # verloren gaat.
        traceback.print_exc()
        problems.append("ReActor kon niet geimporteerd worden (zie traceback)")

if problems:
    print("\n== BUILD AFGEKEURD ==")
    for p in problems:
        print("  - " + p)
    sys.exit(1)

print("\nAlles aanwezig.")
