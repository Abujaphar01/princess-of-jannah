#!/bin/bash
echo "=============================================================="
echo " Starting Princess of Jannah 24/7 Cloud Engine (WhatsApp+WAT) "
echo "=============================================================="

# Persist data/ and media_vault/ inside Railway's mounted volume (/app/auth_info_baileys)
# so future cloud deployments & restarts NEVER wipe queued WhatsApp videos or history!
if [ -d "/app/auth_info_baileys" ]; then
  PERSIST_ROOT="/app/auth_info_baileys/_persistent_state"
  mkdir -p "${PERSIST_ROOT}/data" "${PERSIST_ROOT}/media_vault"

  # Always refresh scholars.json from latest image
  if [ -f "/app/data/scholars.json" ]; then
    cp -f "/app/data/scholars.json" "${PERSIST_ROOT}/data/scholars.json"
  fi

  # Seed initial queue.json & history.json on first volume init, and merge any missing history records
  python - <<'PY'
import json
from pathlib import Path

persist_data = Path("/app/auth_info_baileys/_persistent_state/data")
img_data = Path("/app/data")

for fname in ("queue.json", "history.json"):
    p_file = persist_data / fname
    i_file = img_data / fname
    if not p_file.exists():
        p_file.write_text(i_file.read_text(encoding="utf-8") if i_file.exists() else "[]", encoding="utf-8")
    elif fname == "history.json" and i_file.exists():
        try:
            p_list = json.loads(p_file.read_text(encoding="utf-8"))
            i_list = json.loads(i_file.read_text(encoding="utf-8"))
            seen = {x.get("id") for x in p_list if isinstance(x, dict)}
            merged = list(p_list)
            for item in i_list:
                if isinstance(item, dict) and item.get("id") not in seen:
                    merged.append(item)
            if len(merged) != len(p_list):
                p_file.write_text(json.dumps(merged, indent=2, ensure_ascii=False), encoding="utf-8")
        except Exception:
            pass
PY

  # Copy any pre-bundled fallback MP4s into persistent media_vault if not already there
  if [ -d "/app/media_vault" ] && [ ! -L "/app/media_vault" ]; then
    cp -rn /app/media_vault/* "${PERSIST_ROOT}/media_vault/" 2>/dev/null || true
    rm -rf /app/media_vault
  fi
  if [ -d "/app/data" ] && [ ! -L "/app/data" ]; then
    rm -rf /app/data
  fi

  ln -sfn "${PERSIST_ROOT}/data" /app/data
  ln -sfn "${PERSIST_ROOT}/media_vault" /app/media_vault
  echo "[+] Linked /app/data and /app/media_vault to persistent Railway volume!"
fi

# Configure git identity & authenticated remote if GITHUB_TOKEN is provided in Cloud
git config --global user.name "PrincessOfJannah Cloud Bot"
git config --global user.email "bot@princessofjannah.local"
if [ -n "$GITHUB_TOKEN" ]; then
  git remote set-url origin "https://x-access-token:${GITHUB_TOKEN}@github.com/Abujaphar01/princess-of-jannah.git" 2>/dev/null || true
fi

# Start FastAPI Web Dashboard (/qr, /queue, /bot-logs) + 24/7 WAT Auto-Scheduler
PORT=${PORT:-10000}
echo "[+] Starting FastAPI Dashboard & 24/7 WAT Scheduler on port ${PORT}..."
uvicorn server:app --host 0.0.0.0 --port ${PORT} &

# Start the WhatsApp Multi-Device Bot Daemon in a self-healing supervisor loop
echo "[+] Starting WhatsApp Bot Daemon for group: Princess of Jannah Posts..."
while true; do
  node whatsapp_bot.js
  echo "[!] whatsapp_bot.js exited; restarting in 3s..."
  sleep 3
done
