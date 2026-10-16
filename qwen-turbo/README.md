# Qwen Image 2.1 Turbo op RunPod

Deze branch bevat een aparte native Diffusers-worker voor `Qwen/Qwen-Image-2.1-Turbo`. De bestaande `main`-branch blijft ongewijzigd.

Gebruik op RunPod de branch `codex/qwen-image-21-turbo`, Dockerfile `/qwen-turbo/Dockerfile` en buildcontext `/`. De image bevat het vastgezette officiële model; een apart netwerkvolume is niet nodig.

Voorbereide instellingen: één A40 of RTX A6000 met 48 GB VRAM, min 0/max 1 worker, FlashBoot standaard, idle timeout 30 seconden, uitvoeringstime-out 600 seconden, containerschijf 80 GB. Controleer het actuele tarief in het deploymentformulier.

De worker gebruikt de officiële achtstappenscheduler. Hij accepteert alleen tekst-naar-afbeelding, één PNG per verzoek, maximaal 1,5 megapixel. Beeldbewerking en faceswap zijn geen onderdeel van deze worker. Het model heeft de Qwen Research License; zie de officiële modelpagina voor de voorwaarden.

Candy gebruikt `IMAGE_BACKEND=qwen-runpod`, `RUNPOD_API_KEY` en `MEDIA_SERVERLESS_ENDPOINT_ID` op de server. Er is geen QwenCloud-sleutel nodig voor deze worker. De oude QwenCloud-adapter blijft als aparte mogelijkheid beschikbaar.

Voorbeeld van de native workerinvoer:

```json
{"input":{"prompt":"A ceramic fox on a blue table","width":1024,"height":1024,"seed":42}}
```

De bouw en een echte GPU-generatie moeten na deployment gecontroleerd worden. Lokale syntax-, type- en mockcontroles zijn geen bewijs dat het model al op een GPU draait.