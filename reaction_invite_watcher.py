"""
Princess of Jannah — Real-Time Facebook Like & Comment Follower-Invite Watcher
Polls Meta Graph API every 45 seconds (zero browser/token cost when idle).
The instant any Reel/Post receives a new Like or Comment, automatically dispatches
an Antigravity Browser Agent session to click 'Invite' on the new reactor/commenter!
"""

import argparse
import json
import os
import shutil
import subprocess
import time
import requests
from config import BASE_DIR, DATA_DIR, PAGE_ID, PAGE_ACCESS_TOKEN, now_wat

INVITED_STATE_FILE = DATA_DIR / "invited_state.json"
GRAPH_API_VERSION = "v21.0"
BASE_GRAPH_URL = f"https://graph.facebook.com/{GRAPH_API_VERSION}"
AGENTAPI_BIN = shutil.which("agentapi") or r"C:\Users\jafar\.gemini\antigravity\bin\agentapi.BAT"


def load_invited_state() -> dict:
    if INVITED_STATE_FILE.exists():
        try:
            with open(INVITED_STATE_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)
            if isinstance(data, dict) and "posts" in data:
                return data
        except Exception:
            pass
    return {"posts": {}, "last_dispatch_ts": 0.0}


def save_invited_state(state: dict) -> None:
    with open(INVITED_STATE_FILE, "w", encoding="utf-8") as f:
        json.dump(state, f, indent=2, ensure_ascii=False)


def fetch_live_post_counts(limit: int = 20) -> list[dict]:
    """
    Fetches live reaction/like and comment counts for recent published posts/reels
    on Princess Of Jannah via official Meta Graph API.
    """
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
    """
    Compares live Graph API like/comment counts against data/invited_state.json
    and returns only the posts that have newly arrived likes or comments.
    """
    state = load_invited_state()
    recorded = state.get("posts", {})
    live_posts = fetch_live_post_counts(limit=20)

    pending = []
    for p in live_posts:
        prev = recorded.get(p["id"], {"likes": 0, "comments": 0})
        prev_likes = max(int(prev.get("likes", 0)), int(prev.get("dispatched_likes", 0)))
        prev_comments = max(int(prev.get("comments", 0)), int(prev.get("dispatched_comments", 0)))
        if p["likes"] > prev_likes or p["comments"] > prev_comments:
            pending.append(
                {
                    "id": p["id"],
                    "permalink": p["permalink"],
                    "prev_likes": prev_likes,
                    "live_likes": p["likes"],
                    "new_likes": max(0, p["likes"] - prev_likes),
                    "prev_comments": prev_comments,
                    "live_comments": p["comments"],
                    "new_comments": max(0, p["comments"] - prev_comments),
                }
            )
    return pending


def mark_all_current_as_invited() -> dict:
    """
    Records current live Graph API like/comment counts into data/invited_state.json
    after the Browser Agent completes clicking 'Invite' across the page.
    """
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


def build_browser_invite_prompt(pending_posts: list[dict]) -> str:
    watcher_script = str((BASE_DIR / "reaction_invite_watcher.py").resolve())
    post_lines = "\n".join(
        [
            f"- {p['permalink']} (Post ID `{p['id']}`: +{p['new_likes']} new like(s), +{p['new_comments']} new comment(s); total {p['live_likes']} likes, {p['live_comments']} comments)"
            for p in pending_posts
        ]
    )
    return (
        f"New reaction(s)/comment(s) just arrived on the 'Princess Of Jannah' Facebook Page (`https://www.facebook.com/princess.of.jannah.2026/`):\n"
        f"{post_lines}\n\n"
        f"Task:\n"
        f"1. Immediately delegate to the `browser` subagent (Model `flash`) to navigate to `https://www.facebook.com/princess.of.jannah.2026/` "
        f"(click 'Switch Now' if prompted so you act as the Page 'Princess Of Jannah').\n"
        f"2. Locate the post(s)/reel(s) above on the timeline, click the reaction count toolbar (`[role=\"toolbar\"][aria-label*=\"See who reacted\"]`) "
        f"to open the Reactions modal (`[role=\"dialog\"]`), scroll if needed, and click every enabled button whose visible text is `'Invite'` "
        f"(also invite any uninvited commenters if shown). Do NOT post comments or delete anything.\n"
        f"3. Once the `browser` subagent confirms all visible uninvited users have been invited, run:\n"
        f"   `python \"{watcher_script}\" --mark-all-current`\n"
        f"   so the invited state is updated."
    )


def check_and_trigger_instant_invite(cooldown_sec: int = 240) -> dict:
    """
    Checks for new likes/comments and dispatches an instant Antigravity Browser Agent
    session if any uninvited likes/comments exist and cooldown has elapsed.
    """
    pending = find_posts_with_uninvited_activity()
    if not pending:
        return {"triggered": False, "pending_count": 0}

    state = load_invited_state()
    now_ts = time.time()
    last_ts = float(state.get("last_dispatch_ts", 0.0))

    if (now_ts - last_ts) < cooldown_sec:
        return {
            "triggered": False,
            "reason": "cooldown_active",
            "pending_count": len(pending),
        }

    if not os.path.exists(AGENTAPI_BIN):
        return {
            "triggered": False,
            "reason": f"agentapi not found at {AGENTAPI_BIN}",
            "pending_count": len(pending),
        }

    prompt = build_browser_invite_prompt(pending)
    total_new_likes = sum(p["new_likes"] for p in pending)
    total_new_comments = sum(p["new_comments"] for p in pending)
    title = f"Auto-Invite Follower (+{total_new_likes}L / +{total_new_comments}C)"

    try:
        subprocess.Popen(
            [
                AGENTAPI_BIN,
                "new-conversation",
                "--model=flash",
                f"--title={title}",
                prompt,
            ],
            cwd=str(BASE_DIR),
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        state["last_dispatch_ts"] = now_ts
        for p in pending:
            entry = state["posts"].setdefault(p["id"], {"likes": p["prev_likes"], "comments": p["prev_comments"], "permalink": p["permalink"]})
            entry["dispatched_likes"] = p["live_likes"]
            entry["dispatched_comments"] = p["live_comments"]
        save_invited_state(state)
        return {
            "triggered": True,
            "pending_count": len(pending),
            "new_likes": total_new_likes,
            "new_comments": total_new_comments,
            "posts": pending,
        }
    except Exception as e:
        return {"triggered": False, "reason": str(e), "pending_count": len(pending)}


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Princess of Jannah Instant Like/Comment Follower Inviter")
    parser.add_argument("--check", action="store_true", help="Check for new uninvited likes/comments")
    parser.add_argument("--mark-all-current", action="store_true", help="Mark all current likes/comments as invited")
    parser.add_argument("--trigger-now", action="store_true", help="Check and trigger Browser Agent invite sweep if needed")
    args = parser.parse_args()

    if args.mark_all_current:
        st = mark_all_current_as_invited()
        print(f"[OK] Recorded current invited counts across {len(st.get('posts', {}))} posts.")
    elif args.trigger_now:
        res = check_and_trigger_instant_invite(cooldown_sec=60)
        print(json.dumps(res, indent=2))
    else:
        pending_list = find_posts_with_uninvited_activity()
        print(json.dumps({"pending_count": len(pending_list), "pending": pending_list}, indent=2))
