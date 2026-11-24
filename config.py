import os
import sys
import json
from pathlib import Path
from datetime import datetime, timezone, timedelta

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
if hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")

BASE_DIR = Path(__file__).resolve().parent
DATA_DIR = BASE_DIR / "data"
MEDIA_DIR = BASE_DIR / "media_vault"

DATA_DIR.mkdir(parents=True, exist_ok=True)
MEDIA_DIR.mkdir(parents=True, exist_ok=True)

ENV_FILE = BASE_DIR / ".env"

def load_env():
    env_vars = {}
    if ENV_FILE.exists():
        with open(ENV_FILE, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if line and not line.startswith("#") and "=" in line:
                    key, val = line.split("=", 1)
                    env_vars[key.strip()] = val.strip()
    return env_vars

ENV = load_env()

def _get_config(keys, default=""):
    for key in keys:
        val = os.getenv(key) or ENV.get(key)
        if val:
            return val
    return default

PAGE_ID = _get_config(["PAGE_ID", "FB_PAGE_ID"], "")
PAGE_ACCESS_TOKEN = _get_config(["PAGE_ACCESS_TOKEN", "FB_PAGE_ACCESS_TOKEN"], "")

# West Africa Time (Northern Nigeria - UTC+1)
WAT_TZ = timezone(timedelta(hours=1))

def now_wat() -> datetime:
    return datetime.now(WAT_TZ)

# Adaptive Page-Stage Velocity Profiles (WAT / UTC+1)
STAGE_1_SLOTS = ["06:30", "13:30", "17:30", "20:30"]  # 0-499 followers: 4 prime slots/day (Incubation & Trust)
STAGE_2_SLOTS = ["05:30", "09:30", "13:30", "17:30", "21:00"]  # 500-4,999 followers: 5 slots/day (Momentum)
STAGE_3_SLOTS = ["01:15", "05:30", "08:30", "11:45", "14:45", "18:00", "21:15"]  # 5,000+ followers: 7 slots/day (Authority)

TIMEZONE = os.getenv("TIMEZONE", ENV.get("TIMEZONE", "Africa/Lagos"))
POST_TIMES = [
    t.strip()
    for t in os.getenv("POST_TIMES", ENV.get("POST_TIMES", ",".join(STAGE_1_SLOTS))).split(",")
    if t.strip()
]
MIN_REEL_DURATION_SEC = int(os.getenv("MIN_REEL_DURATION_SEC", ENV.get("MIN_REEL_DURATION_SEC", "15")))
MAX_REEL_DURATION_SEC = int(os.getenv("MAX_REEL_DURATION_SEC", ENV.get("MAX_REEL_DURATION_SEC", "120")))

QUEUE_FILE = DATA_DIR / "queue.json"
HISTORY_FILE = DATA_DIR / "history.json"
SCHOLARS_FILE = DATA_DIR / "scholars.json"
ANALYTICS_CACHE_FILE = DATA_DIR / "analytics_cache.json"

if not QUEUE_FILE.exists():
    with open(QUEUE_FILE, "w", encoding="utf-8") as f:
        json.dump([], f, indent=2)

if not HISTORY_FILE.exists():
    with open(HISTORY_FILE, "w", encoding="utf-8") as f:
        json.dump([], f, indent=2)


def sync_state_to_github(commit_msg: str = "Auto: Sync queue and history state [skip ci]") -> bool:
    """
    Automatically commits and pushes data/queue.json and data/history.json to GitHub
    so the 24/7 GitHub Actions / Render Cloud runner always has the latest queued videos
    even if the laptop is subsequently turned off.
    """
    import subprocess

    try:
        git_dir = BASE_DIR / ".git"
        if not git_dir.exists():
            return False
        subprocess.run(["git", "add", "data/queue.json", "data/history.json", "media_vault"], cwd=str(BASE_DIR), capture_output=True, timeout=20)
        res = subprocess.run(["git", "commit", "-m", commit_msg], cwd=str(BASE_DIR), capture_output=True, text=True, timeout=15)
        if res.returncode == 0:
            subprocess.run(["git", "push", "origin", "main"], cwd=str(BASE_DIR), capture_output=True, timeout=30)
            print("[CLOUD SYNC] Synced queue & history to GitHub Cloud (Abujaphar01/princess-of-jannah).")
            return True
    except Exception as e:
        print(f"[!] Cloud sync warning: {e}")
    return False
