"""
Laat de RunPod-worker ook video's teruggeven, niet alleen losse beelden.

worker-comfyui loopt door de uitvoer van elke node en kijkt uitsluitend naar
de sleutel "images". VideoHelperSuite registreert zijn resultaat onder "gifs"
- ook wanneer het een mp4 is. Het gevolg is een job die COMPLETED meldt en
niets teruggeeft; de handler schrijft er zelfs een waarschuwing bij
("produced unhandled output keys") die nergens terechtkomt.

Dat is precies dezelfde stille storing als bij 25 frames, waar de job slaagde
met lege handen omdat het antwoord te groot was. Zonder deze patch zou
VideoHelperSuite in het image zetten helemaal niets opleveren.

Hernoemen is genoeg: de items onder "gifs" hebben dezelfde vorm als die
onder "images" (filename, subfolder, type), en de handler haalt het bestand
op via ComfyUI's /view, dat elk uitvoerbestand serveert. De extensie wordt
uit de bestandsnaam afgeleid, dus een .mp4 komt er als .mp4 uit.
"""

import os
import sys

TARGET = "/handler.py"

ANKER = "        for node_id, node_output in outputs.items():\n"

PATCH = """            # Gepatcht in de Dockerfile: VideoHelperSuite schrijft zijn
            # resultaat onder "gifs" en deze handler leest alleen "images",
            # waardoor een video stilzwijgend verdween. De items hebben
            # dezelfde vorm, dus hernoemen volstaat.
            if "gifs" in node_output and "images" not in node_output:
                node_output["images"] = node_output.pop("gifs")
"""


def main():
    if not os.path.isfile(TARGET):
        sys.exit("handler.py niet gevonden op " + TARGET)

    source = open(TARGET, encoding="utf-8").read()

    if 'node_output.pop("gifs")' in source:
        print("handler was al gepatcht")
        return

    if source.count(ANKER) != 1:
        sys.exit(
            "verwachtte de uitvoerlus precies een keer, vond hem %d keer - "
            "upstream heeft de handler herschreven" % source.count(ANKER)
        )

    source = source.replace(ANKER, ANKER + PATCH, 1)
    with open(TARGET, "w", encoding="utf-8") as fh:
        fh.write(source)

    # Terugcontroleren, en meteen of het bestand nog geldig python is.
    again = open(TARGET, encoding="utf-8").read()
    if 'node_output.pop("gifs")' not in again:
        sys.exit("patch is niet aangekomen")
    compile(again, TARGET, "exec")
    print("handler gepatcht: video-uitvoer wordt nu opgehaald")


if __name__ == "__main__":
    main()
