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


def auto_post_once():
    """
    Syncs latest queue/history from GitHub Cloud first so local and Cloud runners
    never double-publish, refills queue if empty, then publishes the next Reel.
    """
    from config import pull_state_from_github

    pull_state_from_github()

    pending_count = get_queue_status()
    if pending_count == 0:
        print("[*] Pending queue is empty. Running autonomous discovery refill (count=3)...")
        discover_and_refill(count=3)
        pending_count = get_queue_status()

    if pending_count == 0:
        print("[!] Unable to discover any new pending videos right now.")
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
