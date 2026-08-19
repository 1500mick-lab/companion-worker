# Worker image met face swap

De GPU draait nu `runpod/worker-comfyui:5.8.6-base`. Dat image heeft **geen
custom nodes**, en RunPod's eigen documentatie is daar stellig over: een
network volume kan modellen leveren maar geen nodes — *"not suitable for
installing custom nodes; use the Custom Dockerfile method for that"*.

Gezicht vasthouden werkt met ReActor, en dat is een custom node. Daarom dit
image.

## Waarom via GitHub en niet lokaal

RunPod kan rechtstreeks vanaf een GitHub-repo bouwen: het haalt de Dockerfile
op, bouwt het image in hun eigen infrastructuur en zet het in hun register.
Het alternatief — bouwen op de VPS — betekent Docker installeren op een
machine met 4 cores en 7 GB RAM, een basis-image van 11 GB binnenhalen, en
het resultaat weer ergens naartoe pushen waarvoor je ook nog een
registeraccount nodig hebt. De GitHub-route slaat dat allemaal over.

Grenzen die RunPod stelt: 30 minuten per build-stap, 160 minuten totaal, en
maximaal 80 GB image. Dit image blijft daar ruim onder.

## Stappen

**1. Repo aanmaken**

Maak op github.com een lege repo, bijvoorbeeld `companion-worker`. Publiek of
privé maakt niet uit; bij privé autoriseer je RunPod straks op die repo.

**2. Alleen deze map pushen**

De rest van het project hoeft er niet in — RunPod bouwt alleen wat in de repo
staat, dus hoe kleiner hoe sneller.

```bash
cd worker && git init && git add . && git commit -m "ComfyUI worker met ReActor" && git branch -M main && git remote add origin https://github.com/<jouw-naam>/companion-worker.git && git push -u origin main
```

**3. RunPod toegang geven**

In de console: **Settings → Connections → GitHub → Connect**. Autoriseer, en
geef toegang tot die ene repo.

**4. Endpoint bouwen**

**Serverless → New Endpoint → Import Git Repository**, kies de repo, branch
`main`, Dockerfile-pad `Dockerfile`.

Neem de instellingen van het huidige media-endpoint over, anders draait het
duurder of zonder modellen:

| Instelling | Waarde |
| --- | --- |
| Network volume | hetzelfde volume, datacenter EU-RO-1 |
| GPU's | RTX 4090, RTX A5000, RTX 3090 |
| Workers | min 0, max 1 |
| Idle timeout | 60s |
| Execution timeout | 600s |
| Flashboot | aan |

**5. In gebruik nemen**

Zet het nieuwe endpoint-id in `.env` en schakel face swap in:

```bash
ssh -t companion "sudo sed -i -e 's|^MEDIA_SERVERLESS_ENDPOINT_ID=.*|MEDIA_SERVERLESS_ENDPOINT_ID=<nieuw-id>|' -e 's|^FACE_SWAP_ENABLED=.*|FACE_SWAP_ENABLED=true|' /opt/companion/.env && sudo systemctl restart companion"
```

Het oude endpoint kan daarna weg.

## Waarom hier een handler.py staat

RunPods GitHub-build weigert een repo zonder handler: *"runpod.serverless.start()
handler not found in your repo"*. Die controle gaat ervan uit dat je een worker
vanaf nul schrijft. Wij bouwen juist voort op `runpod/worker-comfyui`, dat zijn
eigen handler al meebrengt op `/handler.py` en start via `CMD ["/start.sh"]`.

De Dockerfile kopieert `handler.py` niet naar het image, dus in de praktijk
wordt hij nooit uitgevoerd — hij is er om de controle te passeren. Mocht RunPod
hem ooit tóch als entrypoint gebruiken, dan draagt hij over aan `/start.sh`, wat
ComfyUI opstart. Zonder die overdracht zou de worker wel antwoorden maar nooit
iets kunnen renderen.

## Wat er in het image zit

- **ReActor**, rechtstreeks van GitHub gekloond. Niet via
  `comfy-node-install <naam>`: ReActor staat niet in het Comfy-register, dus
  een naam zou daar niet oplossen. `ReActorFaceSwap` doet de swap én de
  CodeFormer-restauratie in één node.
- **Build-tools** (build-essential, cmake). insightface heeft geen kant-en-klaar
  wheel voor deze combinatie en compileert vanaf broncode; zonder compiler
  faalt de installatie met een onduidelijke foutmelding.
- **De NSFW-filter uitgeschakeld.** De node bevat een nuditeitsclassifier die
  een zwart beeld teruggeeft bij wat hij afkeurt, en `nsfw_image()` geeft óók
  `True` terug als dat model niet laadt — één mislukte download zou dus alles
  blanco maken. Er is geen schakelaar voor, dus de Dockerfile hangt een
  herdefinitie achter het bestand.
- **buffalo_l** ingebakken. Dat is de detectie-set die insightface gebruikt om
  een gezicht te vinden; hij komt als zip die in een specifieke maplayout
  uitgepakt moet worden, wat op een volume onhandig is.

Modellen zitten bewust **niet** in het image — die blijven op het volume, zodat
een andere checkpoint geen herbouw betekent:

| Bestand | Plek op het volume |
| --- | --- |
| `inswapper_128.onnx` | `models/insightface/` |
| `codeformer-v0.1.0.pth` | `models/facerestore_models/` |

**Beide staan er al.** inswapper is opgehaald (528 MB) en CodeFormer hoefde
niet eens gedownload — die stond al in de oude A1111-map op het volume en is
intern gekopieerd.

## Daarna: video zonder framelimiet

Nu geeft de worker een clip terug als losse PNG-frames, en RunPod begrenst hoe
groot een antwoord mag zijn. Gemeten: 6 en 14 frames komen aan, 25 levert een
job op die "geslaagd" meldt met helemaal geen output. Vandaar `VIDEO_FRAMES=14`.

Een tweede build met VideoHelperSuite erbij laat de worker één kleine mp4
teruggeven in plaats van een stapel frames, waarmee die limiet vervalt en de
25 frames waar svd_xt voor getraind is wél kunnen. Dat is bewust een aparte
stap: eerst face swap laten werken, dan pas iets toevoegen dat de build kan
laten mislukken.

## Als het misgaat

De app valt zelf terug: mislukt de swap, dan wordt de foto opnieuw gegenereerd
met dezelfde seed en zonder swap, zodat je exact het beeld krijgt dat er
anders ook was geweest. In de serverlog staat dan
`face swap failed, retrying without it: <reden>`, en het antwoord draagt de
header `X-Face-Swap: failed`.
