#!/usr/bin/env bash
set -euo pipefail

# Run as the Ubuntu VM's regular sudo-capable SSH user after uploading the app.
APP_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
APP_USER="$(id -un)"

if [[ ! -f "$APP_DIR/chat_server.py" || ! -f "$APP_DIR/web_app.py" || ! -f "$APP_DIR/frontend/dist/index.html" ]]; then
  echo "Upload chat_server.py, web_app.py, and frontend/dist before running this script." >&2
  exit 1
fi

sudo apt-get update
sudo apt-get install -y python3 python3-aiohttp curl
PYTHON_BIN="$(command -v python3)"

sudo tee /etc/systemd/system/tcp-chat.service >/dev/null <<UNIT
[Unit]
Description=Chunky TCP chat and React web gateway
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
User=$APP_USER
WorkingDirectory=$APP_DIR
EnvironmentFile=-/etc/tcp-chat.env
ExecStart=$PYTHON_BIN $APP_DIR/web_app.py --tcp-host 0.0.0.0 --tcp-port 8765 --web-host 0.0.0.0 --web-port 8080
Restart=always
RestartSec=3
NoNewPrivileges=true

[Install]
WantedBy=multi-user.target
UNIT

sudo systemctl daemon-reload
sudo systemctl enable --now tcp-chat
sudo systemctl --no-pager --full status tcp-chat
