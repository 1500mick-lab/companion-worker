# Qwen Image 2.1 Turbo op RunPod

Deze branch bevat een aparte native Diffusers-worker voor `Qwen/Qwen-Image-2.1-Turbo`. De bestaande `main`-branch blijft ongewijzigd.

Gebruik op RunPod de branch `codex/qwen-image-21-turbo`, Dockerfile `/qwen-turbo/Dockerfile` en buildcontext `/`. Laat het veld Model leeg. De worker downloadt bij zijn eerste start het vastgezette officiële model rechtstreeks van de openbare Hugging Face-repository. De modelbestanden blijven op de containerschijf bewaard zolang deze worker behouden blijft. Een nieuwe worker moet opnieuw downloaden. De eerste start telt mee als GPU-tijd; er is geen Hugging Face-sleutel nodig. De gewichten worden niet in de container ingebakken en er is geen apart netwerkvolume nodig.

Voorbereide instellingen: één A40 of RTX A6000 met 48 GB VRAM, min 0/max 1 worker, FlashBoot standaard, idle timeout 30 seconden, uitvoeringstime-out 600 seconden, containerschijf 80 GB. Controleer het actuele tarief in het deploymentformulier.

De worker gebruikt de officiële achtstappenscheduler. Hij accepteert tekst en optioneel een referentiefoto via `faceReference` of een te bewerken afbeelding via `initImage` (base64 PNG/JPEG/WebP, maximaal 6 MB en 12 megapixel). Een gezichtsreferentie krijgt een instructie om dezelfde persoon te behouden. Referenties worden met EXIF-correctie tot maximaal 1024 pixels verkleind. Er komt één PNG per verzoek terug, maximaal 1,5 megapixel. Dit is beeldbewerking met Qwen, geen ReActor-faceswap; exacte gezichtsidentiteit is niet gegarandeerd. Zonder referentie blijft tekst-naar-afbeelding werken. Het model heeft de Qwen Research License; zie de officiële modelpagina voor de voorwaarden.

Candy gebruikt `IMAGE_BACKEND=qwen-runpod`, `RUNPOD_API_KEY` en `MEDIA_SERVERLESS_ENDPOINT_ID` op de server. Er is geen QwenCloud-sleutel nodig voor deze worker. De oude QwenCloud-adapter blijft als aparte mogelijkheid beschikbaar.

Voorbeeld van de native workerinvoer:

```json
{"input":{"prompt":"A ceramic fox on a blue table","width":1024,"height":1024,"seed":42}}
```

De bouw en een echte GPU-generatie moeten na deployment gecontroleerd worden. Lokale syntax-, type- en mockcontroles zijn geen bewijs dat het model al op een GPU draait.