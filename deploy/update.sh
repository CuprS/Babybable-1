#!/usr/bin/env bash
# Deploy the latest code from GitHub (or apply changed settings in deploy/.env):
#   /opt/babybabel/deploy/update.sh
set -euo pipefail
cd "$(dirname "$0")"

echo "==> Pulling the latest code"
git -C .. pull --ff-only

echo "==> Backing up the database before updating"
./backup.sh

echo "==> Rebuilding and restarting (only changed parts restart)"
docker compose up -d --build

echo "==> Cleaning up old images"
docker image prune -f >/dev/null

docker compose ps
