@echo off
title Princess of Jannah — WhatsApp Bot & 3x Daily WAT Scheduler
echo ================================================================
echo   Princess of Jannah - Starting Dashboard, Scheduler & WhatsApp
echo   Target Group: Princess of Jannah Posts
echo   Dashboard / QR Pairing URL: http://localhost:7860/qr
echo ================================================================

if not exist "node_modules" (
    echo [*] Installing Node.js WhatsApp dependencies...
    call npm install
)

echo [*] Starting FastAPI Dashboard ^& 3x Daily WAT Scheduler on port 7860...
start "PrincessOfJannah-Server" cmd /c "python server.py"

echo [*] Starting WhatsApp Bot Daemon...
node whatsapp_bot.js
pause
