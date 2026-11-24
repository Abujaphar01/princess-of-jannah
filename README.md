# Princess of Jannah - 24/7 WhatsApp & Islamic Scholars Video Automation Engine

Autonomous short-video discovery, WhatsApp group ingestion (**Princess of Jannah Posts**), concise captioning, 3x-daily WAT scheduling, and direct Meta Graph API publishing for **Princess of Jannah**, featuring Northern Nigeria's prominent Sunnah scholars:

1. **Sheikh Ja'afar Mahmud Adam (Rahimahullah)**
2. **Sheikh Muhammad Auwal Adam Albani Zaria (Rahimahullah)**
3. **Prof. Muhammad Sani Umar Rijiyar Lemo**
4. **Sheikh Aminu Ibrahim Daurawa**
5. **Sheikh Ahmad Tijjani Guruntum**
6. **Sheikh Prof. Isa Ali Ibrahim Pantami**
7. **Prof. Mansur Isa Yelwa**
8. **Sheikh Dr. Abdallah Gadon Kaya**
9. **Sheikh Abu Haitham**
10. **Sheikh Muhammad Sadis**

---

## Key Features

- **24/7 WhatsApp Admin Group Bot (`whatsapp_bot.js` + `whatsapp_pipeline.py`):**
  - Strictly locked to the **`Princess of Jannah Posts`** WhatsApp group.
  - Send any shared link (Facebook Reels/share links, YouTube Shorts, Instagram, TikTok) or upload a video directly into **`Princess of Jannah Posts`** — the bot downloads it, extracts the shared caption, auto-queues it for the next WAT slot (`06:30`, `13:30`, `20:30` WAT), and replies with a confirmation card.
  - Supports in-group commands:
    - `STATUS` / `QUEUE` / `PING`: Shows live queue count and next scheduled WAT time.
    - `DISCOVER`: Autonomously discovers & queues a fresh short video from the next scholar in rotation.
    - `PUBLISH NOW`: Immediately publishes the next queued video to Facebook Reels.
- **FastAPI Web Dashboard & Integrated WAT Auto-Scheduler (`server.py`):**
  - `/qr` — Scan the live WhatsApp QR code from your browser to link your WhatsApp account.
  - `/queue` — View all pending videos and their exact scheduled WAT publishing slots.
  - `/bot-logs` — Live auto-refreshing logs for both the WhatsApp bot and the 3x daily WAT scheduler.
  - `/send-test` — Send a test message directly to **Princess of Jannah Posts**.
  - `/reset-session` — Clear old WhatsApp session credentials and generate a fresh QR code.
  - **Integrated 3x Daily WAT Auto-Scheduler:** Runs continuously inside `server.py` at **06:30 AM**, **01:30 PM**, and **08:30 PM WAT** (`UTC+1`), auto-refilling the queue if empty and publishing to Facebook Reels.

---

## Option A: Run 24/7 in the Cloud (Render / Docker)

1. Push this repository to GitHub and connect it to **Render.com** (using [render.yaml](file:///c:/Users/jafar/Desktop/Antigravity/Princess%20of%20Jannah/render.yaml)) or run via Docker:
   ```bash
   docker compose up -d --build
   ```
2. Set environment variables (`PAGE_ID` and `PAGE_ACCESS_TOKEN`).
3. Open `https://<your-server-url>/qr` in your browser, and scan the QR code once using **WhatsApp > Linked Devices > Link a Device**.
4. Share links or videos anytime in the **`Princess of Jannah Posts`** WhatsApp group!

---

## Option B: Run Locally on Windows

1. Copy [.env.example](file:///c:/Users/jafar/Desktop/Antigravity/Princess%20of%20Jannah/.env.example) to `.env` and fill in `PAGE_ID` and `PAGE_ACCESS_TOKEN`.
2. Double-click or run [start_whatsapp.bat](file:///c:/Users/jafar/Desktop/Antigravity/Princess%20of%20Jannah/start_whatsapp.bat):
   ```powershell
   .\start_whatsapp.bat
   ```
3. Scan the QR code in the terminal or at `http://localhost:7860/qr`.

---

## CLI Usage (`engine.py`)

```bash
python engine.py scholars              # View the 10 scholars registry
python engine.py discover --count 3    # Autonomously discover & queue 3 short videos
python engine.py add "<shared_url>"    # Add a shared link via CLI
python engine.py queue                 # View upcoming publication queue
python engine.py publish               # Publish next pending video immediately
python engine.py auto-post             # Auto-refill if empty + publish next video
```
