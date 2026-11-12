#!/usr/bin/env bash
set -euo pipefail

# Bootstrap and start ClayChat with Docker Compose on a Debian/Ubuntu GCE VM.
APP_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

if [[ ! -f "$APP_DIR/Dockerfile" || ! -f "$APP_DIR/docker-compose.yml" ]]; then
  echo "Run this script from the extracted ClayChat deployment directory." >&2
  exit 1
fi

if ! command -v docker >/dev/null 2>&1; then
  sudo apt-get update
  sudo apt-get install -y curl ca-certificates
  curl -fsSL https://get.docker.com | sudo sh
fi

if ! sudo docker compose version >/dev/null 2>&1; then
  sudo apt-get update
  sudo apt-get install -y docker-compose-plugin
fi

sudo systemctl enable --now docker

# Add 2 GiB swap when running on small VMs (e.g. e2-micro 1 GiB RAM) so Vite builds do not OOM.
if [[ "$(swapon --show --noheadings | wc -l)" -eq 0 && ! -f /swapfile ]]; then
  sudo fallocate -l 2G /swapfile || sudo dd if=/dev/zero of=/swapfile bs=1M count=2048 status=none
  sudo chmod 600 /swapfile
  sudo mkswap /swapfile >/dev/null
  sudo swapon /swapfile
  if ! grep -q '^/swapfile ' /etc/fstab; then
    echo '/swapfile none swap sw 0 0' | sudo tee -a /etc/fstab >/dev/null
  fi
fi

if [[ ! -f /etc/claychat.env ]]; then
  sudo install -m 600 -o root -g root /dev/null /etc/claychat.env
  sudo tee /etc/claychat.env >/dev/null <<'ENV'
CHAT_DOMAIN=localhost
META_MODEL=muse-spark-1.3
CHAT_INVITE_CODE=
MODEL_API_KEY=
ENV
fi

cd "$APP_DIR"
sudo docker compose --env-file /etc/claychat.env up -d --build

for _ in $(seq 1 30); do
  if curl -fsS http://127.0.0.1:8080/readyz >/dev/null 2>&1; then
    echo "ClayChat is ready on port 8080 (web/WebSocket) and port 8765 (raw TCP)."
    exit 0
  fi
  sleep 2
done

echo "Timed out waiting for http://127.0.0.1:8080/readyz; inspect container logs with: sudo docker compose logs --tail=100" >&2
exit 1

