"""
Aanwezig om RunPods GitHub-build tevreden te stellen.

Die build weigert een repo zonder handler met "runpod.serverless.start()
handler not found in your repo". Die controle gaat ervan uit dat je een worker
vanaf nul schrijft. Wij doen iets anders: we bouwen VOORT op
runpod/worker-comfyui, dat zijn eigen handler al meebrengt op /handler.py en
start via CMD ["/start.sh"].

De Dockerfile kopieert dit bestand dus niet naar het image, en normaal wordt
het nooit uitgevoerd. Mocht RunPod het ooit tóch als entrypoint gebruiken, dan
draagt het hieronder over aan /start.sh — dat is wat ComfyUI opstart en daarna
de echte handler draait. Zonder die overdracht zou de worker wél reageren maar
nooit iets kunnen renderen, want ComfyUI zou niet draaien.
"""

import os
import sys

BASE_ENTRYPOINT = "/start.sh"

if os.path.exists(BASE_ENTRYPOINT):
    # Vervangt dit proces, zodat de worker zich exact gedraagt als het
    # ongewijzigde basis-image.
    os.execv("/bin/bash", ["/bin/bash", BASE_ENTRYPOINT])

# Alleen bereikbaar als dit buiten het bedoelde image draait. Dan is er geen
# ComfyUI om naartoe te praten, en is stil falen erger dan het zeggen.
import runpod


def handler(job):
    return {
        "error": (
            "Deze worker hoort te draaien op het image uit de Dockerfile in deze "
            "repo, dat voortbouwt op runpod/worker-comfyui. " + BASE_ENTRYPOINT +
            " ontbreekt, dus ComfyUI draait niet."
        )
    }


runpod.serverless.start({"handler": handler})
