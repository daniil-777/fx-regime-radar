#!/usr/bin/env bash
# Nightly refresh on the server (cron, after the 06:00 UTC pipeline commit lands):
#   pull main; if only artifacts changed -> restart the app (it re-reads data/ models/ reports/);
#   if code changed -> rebuild the image and recreate. Idempotent; safe to run by hand.
set -euo pipefail
cd "$(dirname "$0")/.."
before=$(git rev-parse HEAD)
git fetch -q origin main
after=$(git rev-parse origin/main)
if [ "$before" = "$after" ]; then
  echo "$(date -u +%FT%TZ) up to date at ${before:0:7}"; exit 0
fi
git pull -q --ff-only origin main
changed=$(git diff --name-only "$before" "$after")
cd deploy
if echo "$changed" | grep -vqE '^(data|models|reports)/'; then
  echo "$(date -u +%FT%TZ) code changed (${before:0:7}..${after:0:7}) -> rebuild"
  docker compose up -d --build --remove-orphans
  docker image prune -f >/dev/null
else
  echo "$(date -u +%FT%TZ) artifacts changed (${before:0:7}..${after:0:7}) -> restart app"
  docker compose restart app
fi
