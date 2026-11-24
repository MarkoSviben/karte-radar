#!/usr/bin/env bash
# Jedan krug radara: scan -> spremi stanje (grana 'state') -> objavi stranicu (karte-pregled).
# Poziva ga petlja u .github/workflows/radar.yml. Argumenti se prosljedjuju `radar scan` (npr. --digest-now).
set -euo pipefail

python -m radar scan "$@"

# stanje: uvijek jedan commit (force push), da grana ne raste
(
  cd state
  rm -rf .git
  git init -q -b state
  git add seen.json PREGLED.md
  git -c user.name="radar-bot" -c user.email="radar-bot@users.noreply.github.com" commit -qm "state $(date -u +%FT%TZ)"
  git push -qf "https://x-access-token:${GH_TOKEN}@github.com/${GITHUB_REPOSITORY}.git" state
)

# stranica
if [ -z "${PAGES_DEPLOY_KEY:-}" ] || [ ! -f state/site/data.json ]; then
  echo "preskacem objavu stranice"
  exit 0
fi
mkdir -p ~/.ssh
if [ ! -f ~/.ssh/pages ]; then
  echo "$PAGES_DEPLOY_KEY" > ~/.ssh/pages && chmod 600 ~/.ssh/pages
  ssh-keyscan -t ed25519 github.com >> ~/.ssh/known_hosts 2>/dev/null
fi
rm -rf pub && mkdir -p pub && cp state/site/index.html state/site/data.json pub/ && touch pub/.nojekyll
(
  cd pub
  git init -q -b main
  git add -A
  git -c user.name="radar-bot" -c user.email="radar-bot@users.noreply.github.com" commit -qm "pregled $(date -u +%FT%TZ)"
  GIT_SSH_COMMAND="ssh -i ~/.ssh/pages -o IdentitiesOnly=yes" git push -qf "git@github.com:${PAGES_REPO}.git" main
)
