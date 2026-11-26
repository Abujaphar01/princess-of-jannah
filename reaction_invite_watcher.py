"""
Princess of Jannah — Zero-Token WhatsApp Batch Like-Invite Alert Watcher
Polls Meta Graph API (0 AI tokens, 0 browser overhead).
Whenever 10+ new Likes accumulate across published Reels/Posts, automatically sends
a crisp WhatsApp Batch Alert into 'Princess of Jannah Posts' with direct 1-tap Reel links
so admins can tap 'Invite' on their phone in 5 seconds!
"""

import argparse
import json
import os
import requests
from config import BASE_DIR, DATA_DIR, PAGE_ID, PAGE_ACCESS_TOKEN, now_wat

INVITED_STATE_FILE = DATA_DIR / "invited_state.json"
SEND_QUEUE_FILE = BASE_DIR / "send_queue.json"
GROUP_JID_FILE = BASE_DIR / "matched_group_jid.txt"
DEFAULT_GROUP_JID = os.environ.get("WHATSAPP_ADMIN_GROUP_ID", "120363413927212088@g.us").strip()
GRAPH_API_VERSION = "v21.0"
BASE_GRAPH_URL = f"https://graph.facebook.com/{GRAPH_API_VERSION}"


def load_invited_state() -> dict:
    if INVITED_STATE_FILE.exists():
        try:
            with open(INVITED_STATE_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)
            if isinstance(data, dict) and "posts" in data:
                return data
        except Exception:
            pass
    return {"posts": {}}


def save_invited_state(state: dict) -> None:
    with open(INVITED_STATE_FILE, "w", encoding="utf-8") as f:
        json.dump(state, f, indent=2, ensure_ascii=False)


def _get_target_group_jid() -> str:
    if DEFAULT_GROUP_JID:
        return DEFAULT_GROUP_JID
    if GROUP_JID_FILE.exists():
        try:
            return GROUP_JID_FILE.read_text(encoding="utf-8").strip()
        except Exception:
            pass
    return "120363413927212088@g.us"


def fetch_live_post_counts(limit: int = 25) -> list[dict]:
    if not PAGE_ID or not PAGE_ACCESS_TOKEN:
        return []

    try:
        r = requests.get(
            f"{BASE_GRAPH_URL}/{PAGE_ID}/published_posts",
            params={
                "fields": "id,permalink_url,created_time,likes.summary(true),comments.summary(true)",
                "limit": limit,
                "access_token": PAGE_ACCESS_TOKEN,
            },
            timeout=15,
        )
        if r.status_code != 200:
            return []
        raw_posts = r.json().get("data", [])
        results = []
        for p in raw_posts:
            pid = p.get("id", "")
            permalink = p.get("permalink_url", "")
            if permalink and permalink.startswith("/"):
                permalink = f"https://www.facebook.com{permalink}"
            likes = int(p.get("likes", {}).get("summary", {}).get("total_count", 0))
            comments = int(p.get("comments", {}).get("summary", {}).get("total_count", 0))
            results.append(
                {
                    "id": pid,
                    "permalink": permalink,
                    "likes": likes,
                    "comments": comments,
                }
            )
        return results
    except Exception as e:
        print(f"[!] Error polling Graph API post counts: {e}")
        return []


def find_posts_with_uninvited_activity() -> list[dict]:
    state = load_invited_state()
    recorded = state.get("posts", {})
    live_posts = fetch_live_post_counts(limit=25)

    pending = []
    for p in live_posts:
        prev = recorded.get(p["id"], {"likes": 0, "comments": 0})
        prev_likes = int(prev.get("likes", 0))
        if p["likes"] > prev_likes:
            pending.append(
                {
                    "id": p["id"],
                    "permalink": p["permalink"],
                    "prev_likes": prev_likes,
                    "live_likes": p["likes"],
                    "new_likes": p["likes"] - prev_likes,
                }
            )
    return pending


def mark_all_current_as_invited() -> dict:
    state = load_invited_state()
    live_posts = fetch_live_post_counts(limit=25)
    for p in live_posts:
        state["posts"][p["id"]] = {
            "likes": p["likes"],
            "comments": p["comments"],
            "permalink": p["permalink"],
            "updated_at": now_wat().isoformat(),
        }
    save_invited_state(state)
    return state


def check_and_trigger_instant_invite(min_batch_likes: int = 10, **_kwargs) -> dict:
    """
    Zero-Token WhatsApp Batch Alert:
    Checks live Facebook Likes across all Reels. Once 10+ new Likes accumulate,
    queues a 1-tap WhatsApp alert card into 'Princess of Jannah Posts' and updates
    the baseline so the next alert fires after the next 10+ new Likes!
    """
    pending = find_posts_with_uninvited_activity()
    total_new_likes = sum(p["new_likes"] for p in pending)

    if total_new_likes < min_batch_likes:
        return {
            "triggered": False,
            "new_likes_accumulated": total_new_likes,
            "threshold": min_batch_likes,
        }

    lines = [
        f"*PRINCESS OF JANNAH — SABBIN LIKES (+{total_new_likes})*",
        "",
        f"Alhamdulillah! An samu sabbin Likes *{total_new_likes}* a kan Reels dinka.",
        "Danna kowane link a kasa ka taba *Reactions -> Invite* domin gayyatarsu su biyo shafin:",
        "",
    ]
    for idx, p in enumerate(pending, 1):
        lines.append(f"{idx}. *+{p['new_likes']} sabbin Likes* (Jimilla: {p['live_likes']})\n   🔗 {p['permalink']}")

    card_text = "\n".join(lines)
    target_jid = _get_target_group_jid()

    current_q = []
    if SEND_QUEUE_FILE.exists():
        try:
            current_q = json.loads(SEND_QUEUE_FILE.read_text(encoding="utf-8"))
            if not isinstance(current_q, list):
                current_q = []
        except Exception:
            current_q = []

    current_q.append({"to": target_jid, "text": card_text})
    SEND_QUEUE_FILE.write_text(json.dumps(current_q, ensure_ascii=False), encoding="utf-8")

    mark_all_current_as_invited()
    return {
        "triggered": True,
        "new_likes": total_new_likes,
        "pending_count": len(pending),
    }


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Princess of Jannah Zero-Token WhatsApp Batch Like Alert")
    parser.add_argument("--check", action="store_true", help="Check accumulated uninvited likes")
    parser.add_argument("--mark-all-current", action="store_true", help="Mark all current likes as invited")
    parser.add_argument("--threshold", type=int, default=10, help="Minimum new likes to trigger WhatsApp batch alert")
    args = parser.parse_args()

    if args.mark_all_current:
        st = mark_all_current_as_invited()
        print(f"[OK] Recorded current invited counts across {len(st.get('posts', {}))} posts.")
    elif args.check:
        pending_list = find_posts_with_uninvited_activity()
        total = sum(x["new_likes"] for x in pending_list)
        print(json.dumps({"new_likes_accumulated": total, "threshold": args.threshold, "posts": pending_list}, indent=2))
    else:
        res = check_and_trigger_instant_invite(min_batch_likes=args.threshold)
        print(json.dumps(res, indent=2))
