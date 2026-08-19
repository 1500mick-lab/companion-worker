# ComfyUI worker with face swapping.
#
# The stock runpod/worker-comfyui image has no custom nodes, and RunPod's own
# documentation is explicit that a network volume cannot supply them:
# "not suitable for installing custom nodes; use the Custom Dockerfile method
# for that". Face swapping needs ReActor, so the image has to be built.
#
# Models are NOT baked in. They live on the network volume, which keeps this
# image small and means swapping a checkpoint does not mean a rebuild. The
# one exception is the insightface detection pack (buffalo_l), which
# insightface insists on unpacking from a zip into its own directory layout —
# far easier to do once at build time than to reproduce on a volume.

FROM runpod/worker-comfyui:5.8.6-base

# ReActor: ReActorFaceSwap / ReActorFaceSwapOpt for the swap,
# ReActorRestoreFace / ReActorRestoreFaceAdvanced for the restoration pass.
RUN comfy-node-install comfyui-reactor

# The upstream node ships a nudity classifier — the README calls the project
# "SFW-Friendly" with "a nudity detector to avoid using this software with
# 18+ content" — and there is no documented switch to turn it off. It returns
# a black image for anything it flags, and, worse, nsfw_image() returns True
# when the classifier merely FAILS TO LOAD, so a hiccup downloading it would
# blank every generation.
#
# This deployment generates adult content by design, on a private, single-user
# instance. The check is therefore neutralised here rather than worked around
# at runtime. Appending a redefinition rather than editing the original body
# keeps the patch working if upstream rewrites the internals.
RUN set -eux; \
    f="$(find / -name reactor_sfw.py -path '*eactor*' | head -1)"; \
    test -n "$f"; \
    printf '\n\n# Overridden at build time — see the Dockerfile.\ndef nsfw_image(img_data, model_path: str):\n    return False\n' >> "$f"; \
    tail -4 "$f"

# buffalo_l is the face detection/recognition pack insightface uses to find
# and encode a face. It is distributed as a zip that has to be expanded into
# a specific directory, so it is fetched at build time instead of being put
# on the volume as a loose file.
RUN set -eux; \
    mkdir -p /comfyui/models/insightface/models; \
    cd /comfyui/models/insightface/models; \
    curl -fsSL -o buffalo_l.zip \
      https://github.com/deepinsight/insightface/releases/download/v0.7/buffalo_l.zip; \
    mkdir -p buffalo_l; \
    cd buffalo_l; \
    unzip -o ../buffalo_l.zip; \
    rm -f ../buffalo_l.zip; \
    ls -la

# Fail the build rather than a generation: a missing node here shows up at
# request time as an unhelpful "node type not found" from ComfyUI.
RUN python -c "\
import os,sys;\
hits=[r for r,_,f in os.walk('/comfyui/custom_nodes') if 'eactor' in r.lower()];\
print('ReActor at:', hits[:1]);\
sys.exit(0 if hits else 'ReActor node was not installed')"
