#!/bin/bash
echo "=============================================================="
echo " Starting Princess of Jannah 24/7 Cloud Engine (WhatsApp+WAT) "
echo "=============================================================="

# Configure git identity & authenticated remote if GITHUB_TOKEN is provided in Cloud
git config --global user.name "PrincessOfJannah Cloud Bot"
git config --global user.email "bot@princessofjannah.local"
if [ -n "$GITHUB_TOKEN" ]; then
  git remote set-url origin "https://x-access-token:${GITHUB_TOKEN}@github.com/Abujaphar01/princess-of-jannah.git" 2>/dev/null || true
fi

# Start FastAPI Web Dashboard (/qr, /queue, /bot-logs)
PORT=${PORT:-10000}
echo "[+] Starting FastAPI Dashboard on port ${PORT}..."
uvicorn server:app --host 0.0.0.0 --port ${PORT} &

# Start the WhatsApp Multi-Device Bot Daemon in a self-healing supervisor loop
echo "[+] Starting WhatsApp Bot Daemon for group: Princess of Jannah Posts..."
while true; do
  node whatsapp_bot.js
  echo "[!] whatsapp_bot.js exited; restarting in 3s..."
  sleep 3
done
