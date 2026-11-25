"""
Princess of Jannah — 24/7 Cloud Comment Auto-Responder & Follow Inviter
Runs 100% in GitHub Actions Cloud (zero laptop/browser required).
Checks all published Reels/Posts via official Meta Graph API for new user comments,
likes each user's comment, and replies warmly in Hausa inviting them to click
'Follow' on Princess Of Jannah!
"""

import json
import requests
from config import DATA_DIR, PAGE_ID, PAGE_ACCESS_TOKEN, now_wat

REPLIED_COMMENTS_FILE = DATA_DIR / "replied_comments.json"
GRAPH_API_VERSION = "v21.0"
BASE_GRAPH_URL = f"https://graph.facebook.com/{GRAPH_API_VERSION}"

HAUSA_FOLLOW_REPLIES = [
    "Allah ya saka da alkhairi! Mungode da ziyartar shafin Princess Of Jannah. Ku danna 'Follow' domin samun gajerun karatuttukan Maluman Sunnah a kullum.",
    "Ameen ya Rabbi! Allah ya amfane mu baki daya. Kada ku manta ku danna 'Follow' a shafin Princess Of Jannah domin karin fadakarwa a kowace rana.",
    "Masha'Allah, mungode sosai! Ku biyo shafin Princess Of Jannah (Follow) domin samun ingantattun wa'azuzzukan Maluman Sunnah a kullum.",
]


def load_replied_ids() -> set[str]:
    if REPLIED_COMMENTS_FILE.exists():
        try:
            with open(REPLIED_COMMENTS_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)
            if isinstance(data, list):
                return set(str(x) for x in data)
        except Exception:
            pass
    return set()


def save_replied_ids(replied: set[str]) -> None:
    with open(REPLIED_COMMENTS_FILE, "w", encoding="utf-8") as f:
        json.dump(sorted(replied), f, indent=2)


def process_new_comments_in_cloud() -> int:
    if not PAGE_ID or not PAGE_ACCESS_TOKEN:
        print("[!] PAGE_ID or PAGE_ACCESS_TOKEN not configured.")
        return 0

    replied_ids = load_replied_ids()
    r = requests.get(
        f"{BASE_GRAPH_URL}/{PAGE_ID}/published_posts",
        params={
            "fields": "id,permalink_url",
            "limit": 20,
            "access_token": PAGE_ACCESS_TOKEN,
        },
        timeout=15,
    )
    if r.status_code != 200:
        print(f"[!] Could not fetch published_posts: {r.text[:200]}")
        return 0

    posts = r.json().get("data", [])
    newly_invited = 0

    for idx, p in enumerate(posts):
        post_id = p.get("id")
        if not post_id:
            continue

        rc = requests.get(
            f"{BASE_GRAPH_URL}/{post_id}/comments",
            params={
                "fields": "id,message,from,created_time",
                "limit": 50,
                "access_token": PAGE_ACCESS_TOKEN,
            },
            timeout=15,
        )
        if rc.status_code != 200:
            continue

        comments = rc.json().get("data", [])
        for c in comments:
            cid = str(c.get("id", ""))
            if not cid or cid in replied_ids:
                continue

            sender_id = str(c.get("from", {}).get("id", ""))
            if sender_id == str(PAGE_ID):
                replied_ids.add(cid)
                continue

            # 1. Like the user's comment
            try:
                requests.post(
                    f"{BASE_GRAPH_URL}/{cid}/likes",
                    data={"access_token": PAGE_ACCESS_TOKEN},
                    timeout=12,
                )
            except Exception:
                pass

            # 2. Reply politely inviting them to Follow Princess Of Jannah
            reply_text = HAUSA_FOLLOW_REPLIES[(idx + newly_invited) % len(HAUSA_FOLLOW_REPLIES)]
            try:
                resp = requests.post(
                    f"{BASE_GRAPH_URL}/{cid}/comments",
                    data={"message": reply_text, "access_token": PAGE_ACCESS_TOKEN},
                    timeout=15,
                ).json()
                if "id" in resp:
                    print(f"[+] Replied & invited commenter on {cid} ({now_wat().isoformat()})")
                    replied_ids.add(cid)
                    newly_invited += 1
                else:
                    print(f"[!] Comment reply response on {cid}: {resp}")
            except Exception as e:
                print(f"[!] Error replying to comment {cid}: {e}")

    save_replied_ids(replied_ids)
    print(f"[OK] Cloud comment sweep complete. Newly invited commenters: {newly_invited}")
    return newly_invited


if __name__ == "__main__":
    process_new_comments_in_cloud()
