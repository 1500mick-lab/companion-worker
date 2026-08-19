"""
Startpunt van de container.

RunPods GitHub-build weigert een repo waarvan de Dockerfile geen handler
aanroept: "runpod.serverless.start() handler not found in your repo". Die
controle gaat ervan uit dat je een worker vanaf nul schrijft. Wij bouwen juist
voort op runpod/worker-comfyui, dat zijn eigen handler meebrengt op
/handler.py en normaal start via CMD ["/start.sh"] — en dat script start eerst
ComfyUI en draait daarna pas die handler.

Dit bestand is dus geen vervanging maar een doorgeefluik: het draagt meteen
over aan /start.sh, zodat de container zich exact gedraagt als het
ongewijzigde basis-image. Zou het de handler wél zelf afhandelen, dan kreeg je
een worker die keurig antwoordt maar nooit iets kan renderen omdat ComfyUI
niet draait — een storing die van buitenaf nauwelijks te herkennen is.

De naam is bewust NIET handler.py: dat bestand bestaat al in het basis-image,
en eroverheen kopiëren zou de echte handler wissen.
"""

import os

BASE_ENTRYPOINT = "/start.sh"

if os.path.exists(BASE_ENTRYPOINT):
    # Vervangt dit proces, zodat start.sh PID 1 wordt zoals het hoort en
    # signalen (bijvoorbeeld het afsluiten van een idle worker) normaal
    # aankomen.
    os.execv("/bin/bash", ["/bin/bash", BASE_ENTRYPOINT])

# Hieronder alleen bereikbaar als dit buiten het bedoelde image draait. Dan is
# er geen ComfyUI om tegen te praten, en is stil falen erger dan het zeggen.
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
