import json
import time
from datetime import datetime
from config import POST_TIMES, QUEUE_FILE, HISTORY_FILE, now_wat
from discover import discover_and_refill
from publisher import publish_next_in_queue
from viral_growth import get_adaptive_wat_schedule


def get_due_or_missed_slot_today(active_slots: list[str]) -> str | None:
    """
    Checks if a scheduled WAT slot is currently due OR was missed earlier today
    while the laptop was asleep. Enforces a minimum 45-minute cooldown between
    posts so multiple missed slots are spaced out safely.
    """
    now = now_wat()
    today_str = now.strftime("%Y-%m-%d")
    current_hhmm = now.strftime("%H:%M")

    passed_slots = sorted([s for s in active_slots if s <= current_hhmm])
    if not passed_slots:
        return None

    published_today = []
    if HISTORY_FILE.exists():
        try:
            with open(HISTORY_FILE, "r", encoding="utf-8") as f:
                history = json.load(f)
            for item in history:
                pub_at = item.get("published_at", "")
                if pub_at.startswith(today_str):
                    published_today.append(pub_at)
        except Exception:
            pass

    if len(published_today) >= len(passed_slots):
        return None

    # Check 45-minute cooldown since last post today
    if published_today:
        try:
            last_dt = datetime.fromisoformat(published_today[-1])
            if (now - last_dt).total_seconds() < 2700:
                return None
        except Exception:
            pass

    target_slot = passed_slots[len(published_today)]
    return f"{today_str}_{target_slot}"


def get_queue_status():
    with open(QUEUE_FILE, "r", encoding="utf-8") as f:
        queue = json.load(f)
    pending = [q for q in queue if q.get("status") == "pending"]
    return len(pending)


def _was_posted_recently_on_facebook(min_gap_sec: int = 7200) -> bool:
    """
    Queries live Meta Graph API /{PAGE_ID}/published_posts (plus local HISTORY_FILE)
    to ensure scheduled runs never double-post right after an instant WhatsApp post
    or a delayed GitHub Actions cron run (< 2 hours gap).
    """
    import requests
    from config import PAGE_ID, PAGE_ACCESS_TOKEN

    now_ts = now_wat().timestamp()

    if HISTORY_FILE.exists():
        try:
            with open(HISTORY_FILE, "r", encoding="utf-8") as f:
                hist = json.load(f)
            if hist:
                last_pub = hist[-1].get("published_at", "")
                if last_pub and (now_ts - datetime.fromisoformat(last_pub).timestamp()) < min_gap_sec:
                    return True
        except Exception:
            pass

    if PAGE_ID and PAGE_ACCESS_TOKEN and PAGE_ID != "your_page_id_here":
        try:
            r = requests.get(
                f"https://graph.facebook.com/v21.0/{PAGE_ID}/published_posts",
                params={"fields": "id,created_time", "limit": 3, "access_token": PAGE_ACCESS_TOKEN},
                timeout=12,
            )
            if r.status_code == 200:
                posts = r.json().get("data", [])
                if posts and posts[0].get("created_time"):
                    ct = posts[0]["created_time"].replace("+0000", "+00:00")
                    if (now_ts - datetime.fromisoformat(ct).timestamp()) < min_gap_sec:
                        return True
        except Exception:
            pass

    return False


def auto_post_once():
    """
    WhatsApp-First + Non-WhatsApp Fallback Auto-Publisher:
    1. Syncs latest queue/history from GitHub Cloud.
    2. Skips if a post already went live on Facebook in the last 2 hours (prevents back-to-back/cron duplicates).
    3. Publishes WhatsApp-shared content FIRST whenever present in queue.
    4. Only posts a non-WhatsApp scholar clip if there is NO WhatsApp content in the queue.
    """
    from config import pull_state_from_github

    pull_state_from_github()

    if _was_posted_recently_on_facebook(min_gap_sec=7200):
        print("[DEDUP COOLDOWN] A Reel was already published on Facebook within the last 2 hours. Skipping this slot.")
        return None

    pending_count = get_queue_status()
    if pending_count == 0:
        print("[*] Queue is empty (no WhatsApp items waiting). Discovering 1 fallback scholar Reel...")
        discover_and_refill(count=1)
        pending_count = get_queue_status()

    if pending_count == 0:
        print("[!] Unable to find any pending video right now.")
        return None

    return publish_next_in_queue()


def run_scheduler_loop():
    sched = get_adaptive_wat_schedule()
    active_slots = sched.get("slots", POST_TIMES)
    print("=" * 65)
    print("   Princess of Jannah - Adaptive Viral Reels Scheduler Daemon")
    print("=" * 65)
    print(f"[*] Active Growth Stage: {sched.get('stage_name')} ({sched.get('followers_count', 0)} followers)")
    print(f"[*] Target Post Times (WAT / UTC+1): {', '.join(active_slots)}")
    print(f"[*] Current Time (WAT): {now_wat().strftime('%Y-%m-%d %H:%M:%S')}")
    print(f"[*] Current Pending Queue Count: {get_queue_status()}")
    print("[*] Scheduler is active. Press Ctrl+C to terminate.")
    print("-" * 65)

    last_posted_slot = None

    while True:
        try:
            active_slots = get_adaptive_wat_schedule().get("slots", POST_TIMES)
            due_slot_key = get_due_or_missed_slot_today(active_slots)

            if due_slot_key and last_posted_slot != due_slot_key:
                print(f"\n[!] TRIGGERING DUE / CATCH-UP WAT SLOT: {due_slot_key}")
                res = auto_post_once()
                if res:
                    last_posted_slot = due_slot_key

            # Check every 25 seconds
            time.sleep(25)
        except KeyboardInterrupt:
            print("\n[*] Scheduler stopped by user.")
            break
        except Exception as e:
            print(f"[!] Error in scheduler loop: {e}")
            time.sleep(30)


if __name__ == "__main__":
    run_scheduler_loop()
