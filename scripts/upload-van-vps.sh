#!/usr/bin/env bash
# Zet de ridesims-code van deze machine op de werkbranch van companion-worker.
# Gebruik: bash upload-van-vps.sh /pad/naar/ridesims
set -euo pipefail

BRON="${1:-}"
REPO="https://github.com/1500mick-lab/companion-worker.git"
BRANCH="claude/exciting-dirac-k4p2g6"
WERK="$(mktemp -d)"

if [ -z "$BRON" ]; then
  echo "Mogelijke ridesims-mappen op deze machine:"
  find / -maxdepth 4 -type d -iname '*ridesim*' -not -path '/proc/*' 2>/dev/null || true
  echo
  echo "Draai opnieuw met het pad erbij, bijvoorbeeld:"
  echo "  bash upload-van-vps.sh /home/jij/ridesims"
  exit 1
fi
[ -d "$BRON" ] || { echo "Map $BRON bestaat niet."; exit 1; }

git clone -q -b "$BRANCH" "$REPO" "$WERK/repo"
cd "$WERK/repo"

# Kopieer alles behalve git-data, geheimen, dependencies en rommel.
tar -C "$BRON" \
  --exclude=.git --exclude=.env --exclude='.env.*' --exclude='*.env' \
  --exclude='*.pem' --exclude='*.key' --exclude=id_rsa --exclude=id_ed25519 \
  --exclude=node_modules --exclude=venv --exclude=.venv --exclude=__pycache__ \
  --exclude='*.log' --exclude='*.sqlite' --exclude='*.db' --exclude=dist --exclude=build \
  --exclude=backoffice --exclude='accounts*.json' --exclude='*.bak*' --exclude='*.tar.gz' \
  --exclude='*.swf' --exclude='*.original_unpat*' \
  -cf - . | tar -xf -

# Bestanden groter dan 50 MB horen niet in git.
GROOT="$(find . -path ./.git -prune -o -type f -size +50M -print)"
if [ -n "$GROOT" ]; then
  echo "Deze bestanden zijn groter dan 50 MB en worden overgeslagen:"
  echo "$GROOT"
  echo "$GROOT" | xargs -d '\n' rm -f
fi

# De repo is publiek: stop als er iets in staat dat op een sleutel lijkt.
VERDACHT="$(grep -rIliE \
  '(api[_-]?key|secret|password|passwd|token)[\"'\'' ]*[:=][\"'\'' ]*[A-Za-z0-9_\-]{12,}|sk-[A-Za-z0-9]{20,}|ghp_[A-Za-z0-9]{30,}|AKIA[0-9A-Z]{16}|BEGIN [A-Z ]*PRIVATE KEY' \
  --exclude-dir=.git . || true)"
if [ -n "$VERDACHT" ]; then
  echo "STOP: in deze bestanden staat mogelijk een wachtwoord of sleutel:"
  echo "$VERDACHT"
  echo "Er is niets gepusht. Haal de sleutels eruit (bijv. naar .env) en draai opnieuw."
  exit 1
fi

git add -A
if git diff --cached --quiet; then
  echo "Geen nieuwe bestanden om te pushen."
  exit 0
fi
git -c user.name="ridesims upload" -c user.email="upload@localhost" \
  commit -q -m "ridesims-code van de VPS"
echo "Pushen naar GitHub. Gebruikersnaam = je GitHub-naam, wachtwoord = een personal access token."
git push -q origin "$BRANCH"
echo "Klaar: $(git ls-files | wc -l) bestanden staan op GitHub."
rm -rf "$WERK"
