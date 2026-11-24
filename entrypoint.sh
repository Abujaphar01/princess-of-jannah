#!/bin/bash
echo "=============================================================="
echo " Starting Princess of Jannah 24/7 Cloud Engine (WhatsApp+WAT) "
echo "=============================================================="

# Start FastAPI Web Dashboard (/qr, /queue, /bot-logs) + 3x Daily WAT Auto-Scheduler
PORT=${PORT:-10000}
echo "[+] Starting FastAPI Dashboard & 3x Daily WAT Auto-Scheduler on port ${PORT}..."
uvicorn server:app --host 0.0.0.0 --port ${PORT} &

# Start the WhatsApp Multi-Device Bot Daemon in foreground
echo "[+] Starting WhatsApp Bot Daemon for group: Princess of Jannah Posts..."
exec node whatsapp_bot.js
