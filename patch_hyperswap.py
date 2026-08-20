"""
Corrigeert de uitlijning waarmee ReActor gezichten aan HyperSwap aanbiedt.

HyperSwap is gemaakt door FaceFusion en verwacht een uitsnede volgens hun
`arcface_128`-sjabloon, opgeschaald naar 256 pixels. Dat geeft deze
bestemmingspunten, met een oogafstand van 70,47 pixels:

    [[ 92.589, 103.393],
     [163.064, 103.003],
     [128.050, 143.473],
     [ 99.099, 184.731],
     [157.460, 184.408]]

ReActor hardcodeert in reactor_core/hyperswap.py een andere set, met een
oogafstand van 86,26. Het model krijgt daardoor een uitsnede die 22,4% te ver
is ingezoomd ten opzichte van waarop het getraind is - het gezicht valt
letterlijk buiten het kader dat het model verwacht, en de gelijkenis lijdt
daaronder.

Dat dit een fout is en niet een bewuste keuze blijkt uit ReActor zelf: het
inswapper-pad in reactor_core/inswap.py rekent dezelfde transformatie wel
correct uit (ARCFACE_STD_POINTS * size/128, met een verschuiving van 8*ratio
in x) en komt tot op vier decimalen uit op de waarden hierboven. Alleen het
hyperswap-pad wijkt af.

De patch faalt luidruchtig als het bestand of de variabele er niet is, want
stilzwijgend overslaan zou betekenen dat je een image krijgt dat er goed
uitziet en slechter presteert dan het kan.
"""

import os
import re
import sys

TARGET = "/comfyui/custom_nodes/ComfyUI-ReActor/reactor_core/hyperswap.py"

CORRECT = """std_landmarks_256 = np.array([
    [ 92.589, 103.393],
    [163.064, 103.003],
    [128.050, 143.473],
    [ 99.099, 184.731],
    [157.460, 184.408]
], dtype=np.float32)"""


def main():
    if not os.path.isfile(TARGET):
        sys.exit("hyperswap.py niet gevonden op " + TARGET)

    source = open(TARGET, encoding="utf-8").read()

    pattern = re.compile(
        r"std_landmarks_256\s*=\s*np\.array\(\[.*?\]\s*,\s*dtype\s*=\s*np\.float32\s*\)",
        re.S,
    )
    match = pattern.search(source)
    if not match:
        sys.exit("std_landmarks_256 niet gevonden - upstream heeft dit hernoemd of herschreven")

    before = match.group(0)
    if "92.589" in before:
        print("uitlijning was al correct, niets te doen")
        return

    patched = source[: match.start()] + CORRECT + source[match.end():]
    with open(TARGET, "w", encoding="utf-8") as fh:
        fh.write(patched)

    # Terugcontroleren in plaats van aannemen dat het schrijven klopte.
    again = open(TARGET, encoding="utf-8").read()
    if "92.589" not in again or "84.87" in again:
        sys.exit("patch is niet aangekomen")

    print("uitlijning gecorrigeerd:")
    print("  was:", " ".join(before.split())[:90])
    print("  nu :", " ".join(CORRECT.split())[:90])


if __name__ == "__main__":
    main()
