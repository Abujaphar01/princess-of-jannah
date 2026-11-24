import os
import re
import sys
import json
import time
import shutil
import subprocess
import requests
from pathlib import Path
from config import (
    PAGE_ID,
    PAGE_ACCESS_TOKEN,
    QUEUE_FILE,
    HISTORY_FILE,
    SCHOLARS_FILE,
    ANALYTICS_CACHE_FILE,
    STAGE_1_SLOTS,
    STAGE_2_SLOTS,
    STAGE_3_SLOTS,
    MIN_REEL_DURATION_SEC,
    MAX_REEL_DURATION_SEC,
    now_wat,
)

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
if hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")

GRAPH_API_VERSION = "v21.0"
BASE_GRAPH_URL = f"https://graph.facebook.com/{GRAPH_API_VERSION}"

# =====================================================================
# 1. CATEGORIZED HAUSA & SUNNAH VIRAL HOOK LIBRARY
# =====================================================================

HOOK_BANK = {
    0: [  # Archetype 0: Urgent Fiqh & Sunnah Curiosity
        "Shin ka san hukuncin wannan mas'alar a koyarwar Sunnah?",
        "Amsa mai gamsarwa kan tambayar da take damun mutane da yawa.",
        "Wannan bayanin zai warware maka shakka cikin dakika kadan.",
        "Abu mai muhimmanci da kowane Musulmi ya kamata ya sani.",
    ],
    1: [  # Archetype 1: Heart-Softening Reminder & Solace
        "Nasiha mai ratsa zuciya wadda za ta kara maka natsuwa.",
        "Tsaya na dakika daya ka saurari wannan tunatarwar mai girma.",
        "Magana mai taba zuciya daga bakin babban malami.",
        "Idan zuciyarka tana neman natsuwa, saurari wannan bayanin.",
    ],
    2: [  # Archetype 2: Common Mistake Correction & Ibadah
        "Kuskuren da mutane da yawa suke tafkawa ba tare da sun sani ba.",
        "Hukunci mai muhimmanci wanda bai kamata Musulmi ya jahilta ba.",
        "Gyara ibadarka: Saurari yadda Annabi (SAW) ya koyar da wannan.",
        "Kashedi mai karfi tare da hujja daga Al-Qur'ani da Sunnah.",
    ],
    3: [  # Archetype 3: Timeless Scholarly Legacy & Sadaqatul Jariyah
        "Ilimi mai amfani: Sadaqatul Jariyah ga duk wanda ya saurara kuma ya yada.",
        "Gundarin ilimi da hikima daga maluman Sunnah na Arewa.",
        "Darasi mai tsada cikin gajeren lokaci—saurara har karshe.",
        "Taskar maluman Sunnah: Karatu mai cike da hujjoji.",
    ],
}

AREWA_TAG_CLUSTERS = [
    "#PrincessOfJannah #Sunnah #Arewa #Hausa #Kano #Kaduna #Abuja #Tafsiri",
    "#PrincessOfJannah #Waazi #HausaIslam #Arewa #Zaria #Maiduguri #Katsina #Sokoto",
    "#PrincessOfJannah #Fiqhu #Aqidah #Sunnah #Arewa #Bauchi #NigeriaMuslims",
    "#PrincessOfJannah #MalumanSunnah #Karatu #Hadisi #Arewa #Kano #Kaduna",
]


def _find_ffmpeg_exe() -> str | None:
    sys_ffmpeg = shutil.which("ffmpeg")
    if sys_ffmpeg:
        return sys_ffmpeg
    try:
        import imageio_ffmpeg
        return imageio_ffmpeg.get_ffmpeg_exe()
    except Exception:
        return None


def clean_raw_title(raw_title: str, scholar: dict | None = None) -> str:
    """
    Cleans raw YouTube/social media titles by stripping noise (#shorts, file codes, URLs)
    and upgrading overly generic titles into clear Hausa topic descriptions.
    """
    if not raw_title:
        raw_title = ""

    # Take first non-empty line before hashtags block
    first_line = raw_title.strip().split("\n")[0].strip()

    # Strip inline hashtags, URLs, and common noise tags
    cleaned = re.sub(r"https?://\S+", "", first_line)
    cleaned = re.sub(r"#\S+", "", cleaned)
    cleaned = re.sub(r"\b(shorts|short|tiktok|reels|reel|video|mp4|IMG_\d+|VID_\d+)\b", "", cleaned, flags=re.IGNORECASE)
    cleaned = re.sub(r"\s+", " ", cleaned).strip(" -_|:,.")

    # Check if the remaining title is just the scholar's bare name or too short
    scholar_name = (scholar or {}).get("name", "")
    generic_names = [
        "sheikh jaafar kano",
        "sheikh jaafar",
        "jaafar mahmud adam",
        "albani zaria",
        "sheikh albani",
        "aminu daurawa",
        "pantami",
        "guruntum",
        "rijiyar lemo",
        "mansur isa yelwa",
        "gadon kaya",
        "abu haitham",
        "muhammad sadis",
    ]

    low = cleaned.lower()
    if len(cleaned) < 12 or low in generic_names or (scholar_name and low == scholar_name.lower()):
        specialty = (scholar or {}).get("specialty", "Tafsiri da Koyarwar Sunnah")
        return f"Muhimmin Bayani Kan {specialty}"

    return cleaned


def build_viral_caption(
    raw_title: str,
    scholar: dict | None = None,
    is_shared_link: bool = False,
    archetype_index: int | None = None,
) -> str:
    """
    Builds a high-retention, algorithm-optimized Hausa/Sunnah caption.
    - If is_shared_link=True and raw_title has content, strictly preserves the shared caption.
    - If autonomously discovered, packages it into one of 4 Rotating Hausa Viral Archetypes.
    """
    scholar = scholar or {
        "id": "general_sunnah",
        "name": "Maluman Sunnah",
        "specialty": "Koyarwar Al-Qur'ani da Sunnah",
        "hashtags": ["#PrincessOfJannah", "#Sunnah", "#Arewa"],
    }

    unique_scholar_tags = [
        t for t in scholar.get("hashtags", []) if t.lower() != "#princessofjannah"
    ][:2]
    scholar_tags = " ".join(unique_scholar_tags) if unique_scholar_tags else "#MalumanSunnah"

    # 1. Preserve original caption on user-shared links
    if is_shared_link and raw_title and len(raw_title.strip()) > 5:
        clean_shared = raw_title.strip()
        if "#" not in clean_shared:
            return f"{clean_shared}\n\n{scholar_tags} #PrincessOfJannah #Sunnah #Arewa"
        return clean_shared

    # 2. Determine rotating archetype index (0..3)
    if archetype_index is None:
        try:
            with open(QUEUE_FILE, "r", encoding="utf-8") as f:
                q_len = len(json.load(f))
            with open(HISTORY_FILE, "r", encoding="utf-8") as f:
                h_len = len(json.load(f))
            archetype_index = (q_len + h_len) % 4
        except Exception:
            archetype_index = int(time.time()) % 4
    else:
        archetype_index = archetype_index % 4

    topic = clean_raw_title(raw_title, scholar)
    scholar_name = scholar.get("name", "Maluman Sunnah")
    is_deceased = "rahimahullah" in scholar_name.lower()
    scholar_dua = (
        "Allah ya ji kan Malam da rahama, ya saka masa da Aljannah."
        if is_deceased
        else "Allah ya saka wa Malam da alkhairi, ya kara masa lafiya."
    )

    hooks = HOOK_BANK[archetype_index]
    hook = hooks[len(topic) % len(hooks)]
    cluster_tags = AREWA_TAG_CLUSTERS[archetype_index]

    if archetype_index == 0:
        caption = (
            f"{hook}\n\n"
            f"Malam: {scholar_name}\n"
            f"Maudu'i: {topic}\n\n"
            f"Saurari cikakken bayani cikin dakika kadan. @followers ku tura wa 'yan uwa domin amfanarwa.\n\n"
            f"{scholar_tags} {cluster_tags}"
        )
    elif archetype_index == 1:
        caption = (
            f"{hook}\n\n"
            f"Daga bakin: {scholar_name}\n"
            f"Darasi: {topic}\n\n"
            f"{scholar_dua} @followers kada ku manta ku yada wannan alkhairin.\n\n"
            f"{scholar_tags} {cluster_tags}"
        )
    elif archetype_index == 2:
        caption = (
            f"{hook}\n\n"
            f"Bayani daga: {scholar_name}\n"
            f"Kan Maudu'in: {topic}\n\n"
            f"Ku saurara har karshe domin gyara ibadah. @followers ku yada domin samun ladan sadaqatul jariyah.\n\n"
            f"{scholar_tags} {cluster_tags}"
        )
    else:
        caption = (
            f"{hook}\n\n"
            f"Tare da: {scholar_name}\n"
            f"Bayani: {topic}\n\n"
            f"{scholar_dua} @followers ku tura wa 'yan uwa Musulmi.\n\n"
            f"{scholar_tags} {cluster_tags}"
        )

    return caption


# =====================================================================
# 2. FFMPEG 0.0s HOOK & VOICE CLARITY MASTERING
# =====================================================================

def master_video_for_retention(video_path: str | Path) -> bool:
    """
    Runs an automated FFmpeg mastering pass on a video clip:
    1. Trims dead opening silence so the scholar's voice starts at 0.0s.
    2. Applies 85Hz high-pass filter to cut mic rumble.
    3. Boosts 3kHz vocal clarity band (+2dB) and applies dynamic loudness normalization.
    Safely falls back to the original file if anything fails.
    """
    target = Path(video_path)
    if not target.exists() or not target.is_file():
        return False

    ffmpeg_exe = _find_ffmpeg_exe()
    if not ffmpeg_exe:
        print("[!] FFmpeg binary not found; skipping audio/retention mastering.")
        return False

    temp_out = target.with_suffix(".mastered.mp4")
    audio_filter = (
        "silenceremove=start_periods=1:start_duration=0.05:start_threshold=-42dB,"
        "highpass=f=85,"
        "equalizer=f=3000:width_type=h:width=1000:g=2,"
        "dynaudnorm=f=150:g=15"
    )

    cmd = [
        ffmpeg_exe,
        "-y",
        "-i",
        str(target),
        "-af",
        audio_filter,
        "-c:v",
        "libx264",
        "-preset",
        "veryfast",
        "-crf",
        "23",
        "-c:a",
        "aac",
        "-b:a",
        "192k",
        "-movflags",
        "+faststart",
        str(temp_out),
    ]

    try:
        print(f"[*] Mastering audio & 0.0s retention hook for: {target.name} ...")
        res = subprocess.run(cmd, capture_output=True, text=True, timeout=180)
        if res.returncode == 0 and temp_out.exists() and temp_out.stat().st_size > 50_000:
            temp_out.replace(target)
            print(f"[+] Mastering complete: {target.name} ({target.stat().st_size / (1024*1024):.2f} MB)")
            return True
        else:
            if temp_out.exists():
                temp_out.unlink(missing_ok=True)
            print(f"[!] FFmpeg mastering returned non-zero ({res.returncode}), keeping original video.")
            return False
    except Exception as e:
        if temp_out.exists():
            temp_out.unlink(missing_ok=True)
        print(f"[!] FFmpeg mastering exception ({e}), keeping original video.")
        return False


# =====================================================================
# 3. ADAPTIVE PAGE-STAGE VELOCITY ENGINE
# =====================================================================

def _slot_24h_to_12h(slot_24h: str) -> str:
    try:
        h, m = map(int, slot_24h.split(":"))
        suffix = "AM" if h < 12 else "PM"
        h12 = h % 12
        if h12 == 0:
            h12 = 12
        return f"{h12:02d}:{m:02d} {suffix}"
    except Exception:
        return slot_24h


def get_adaptive_wat_schedule(force_refresh: bool = False) -> dict:
    """
    Determines the page's current growth stage based on live Facebook Page follower count
    and returns the optimal daily WAT posting schedule:
    - Stage 1 (0 - 499 followers): 4 prime WAT slots/day (Incubation & Trust Building)
    - Stage 2 (500 - 4,999 followers): 5 WAT slots/day (Momentum & Expansion)
    - Stage 3 (5,000+ followers): 7 WAT slots/day (24-Hour Viral Authority)
    """
    now_ts = time.time()
    cached = {}

    if ANALYTICS_CACHE_FILE.exists() and not force_refresh:
        try:
            with open(ANALYTICS_CACHE_FILE, "r", encoding="utf-8") as f:
                cached = json.load(f)
            if now_ts - cached.get("timestamp", 0) < 1200 and "schedule_info" in cached:
                return cached["schedule_info"]
        except Exception:
            pass

    followers = cached.get("followers_count", 0)
    page_name = cached.get("page_name", "Princess Of Jannah")

    if PAGE_ID and PAGE_ACCESS_TOKEN and PAGE_ID != "your_page_id_here":
        try:
            r = requests.get(
                f"{BASE_GRAPH_URL}/{PAGE_ID}",
                params={"fields": "id,name,followers_count,fan_count", "access_token": PAGE_ACCESS_TOKEN},
                timeout=12,
            )
            if r.status_code == 200:
                data = r.json()
                followers = int(data.get("followers_count") or data.get("fan_count") or 0)
                page_name = data.get("name", page_name).strip()
        except Exception:
            pass

    if followers < 500:
        stage_num = 1
        stage_name = "Stage 1: Incubation & Trust Building (0–499 Followers)"
        slots = STAGE_1_SLOTS
        rationale = "4 prime WAT slots/day spaced 4–6h apart to maximize completion rate & avoid new-page spam filters."
    elif followers < 5000:
        stage_num = 2
        stage_name = "Stage 2: Momentum & Expansion (500–4,999 Followers)"
        slots = STAGE_2_SLOTS
        rationale = "5 high-velocity WAT slots/day capturing Fajr, morning commute, post-Dhuhr, Asr, and night peak."
    else:
        stage_num = 3
        stage_name = "Stage 3: Viral Authority (5,000+ Followers)"
        slots = STAGE_3_SLOTS
        rationale = "7 daily WAT slots across the full 24-hour cycle including Tahajjud & global diaspora windows."

    schedule_info = {
        "page_name": page_name,
        "page_id": PAGE_ID,
        "followers_count": followers,
        "stage_num": stage_num,
        "stage_name": stage_name,
        "slots": slots,
        "slots_12h": [_slot_24h_to_12h(s) for s in slots],
        "posts_per_day": len(slots),
        "rationale": rationale,
        "updated_at_wat": now_wat().strftime("%Y-%m-%d %I:%M:%S %p WAT"),
    }

    try:
        cached["timestamp"] = now_ts
        cached["followers_count"] = followers
        cached["page_name"] = page_name
        cached["schedule_info"] = schedule_info
        with open(ANALYTICS_CACHE_FILE, "w", encoding="utf-8") as f:
            json.dump(cached, f, indent=2)
    except Exception:
        pass

    return schedule_info


# =====================================================================
# 4. LIVE META GRAPH API ANALYTICS & QUEUE OPTIMIZER
# =====================================================================

def fetch_page_analytics() -> dict:
    """
    Queries live Facebook Graph API for Page metrics and published Reel engagement
    (plays/views, likes, comments, shares, status).
    """
    sched = get_adaptive_wat_schedule(force_refresh=True)

    try:
        with open(HISTORY_FILE, "r", encoding="utf-8") as f:
            history = json.load(f)
    except Exception:
        history = []

    try:
        with open(QUEUE_FILE, "r", encoding="utf-8") as f:
            queue = json.load(f)
        pending_count = len([q for q in queue if q.get("status") == "pending"])
    except Exception:
        pending_count = 0

    reel_metrics = []
    total_likes = 0
    total_comments = 0
    total_shares = 0
    total_views = 0

    # Check up to last 10 published reels in history
    for item in reversed(history[-10:]):
        vid_id = item.get("fb_video_id") or item.get("facebook_result", {}).get("video_id")
        if not vid_id:
            continue

        views = 0
        likes = 0
        comments = 0
        shares = 0
        v_status = "published"
        permalink = f"https://www.facebook.com/reel/{vid_id}/"

        if PAGE_ID and PAGE_ACCESS_TOKEN:
            try:
                r = requests.get(
                    f"{BASE_GRAPH_URL}/{vid_id}",
                    params={
                        "fields": "id,views,permalink_url,status,likes.summary(true),comments.summary(true)",
                        "access_token": PAGE_ACCESS_TOKEN,
                    },
                    timeout=12,
                )
                if r.status_code == 200:
                    vdata = r.json()
                    views = int(vdata.get("views") or 0)
                    likes = int(vdata.get("likes", {}).get("summary", {}).get("total_count", 0))
                    comments = int(vdata.get("comments", {}).get("summary", {}).get("total_count", 0))
                    v_status = vdata.get("status", {}).get("video_status", "ready")
                    if vdata.get("permalink_url"):
                        permalink = f"https://www.facebook.com{vdata['permalink_url']}"
            except Exception:
                pass

        total_views += views
        total_likes += likes
        total_comments += comments
        total_shares += shares

        reel_metrics.append({
            "video_id": vid_id,
            "scholar": item.get("scholar", "Maluman Sunnah"),
            "duration": item.get("duration", 0),
            "published_at": item.get("published_at", ""),
            "views": views,
            "likes": likes,
            "comments": comments,
            "shares": shares,
            "status": v_status,
            "permalink": permalink,
        })

    return {
        "schedule": sched,
        "total_published": len(history),
        "pending_in_queue": pending_count,
        "totals": {
            "views": total_views,
            "likes": total_likes,
            "comments": total_comments,
            "shares": total_shares,
        },
        "reels": reel_metrics,
    }


def format_whatsapp_analytics_card() -> str:
    """
    Formats a clean Hausa/English Social Media Growth Report card for WhatsApp and CLI.
    """
    data = fetch_page_analytics()
    sched = data["schedule"]
    totals = data["totals"]
    slots_str = ", ".join(sched["slots_12h"])

    lines = [
        "*PRINCESS OF JANNAH — SOCIAL MEDIA GROWTH REPORT*",
        "",
        f"• *Shafi (Page):* {sched['page_name']} (`{sched['page_id']}`)",
        f"• *Mabiya (Followers):* {sched['followers_count']}",
        f"• *Matakin Girma (Growth Stage):* {sched['stage_name']}",
        f"• *Tsarin Wallafawa (Daily Velocity):* Posts {sched['posts_per_day']} a rana ({slots_str} WAT)",
        f"• *Bidiyoyin da aka wallafa:* {data['total_published']} | *A Queue:* {data['pending_in_queue']}",
        f"• *Jimillar Kallo (Views):* {totals['views']} | *Likes:* {totals['likes']} | *Comments:* {totals['comments']}",
        "",
        "*REELS NA KARSHE A FACEBOOK:*",
    ]

    if not data["reels"]:
        lines.append("• Babu bidiyon da aka wallafa tukuna.")
    else:
        for idx, r in enumerate(data["reels"][:5], 1):
            lines.append(
                f"{idx}. *{r['scholar']}* ({r['duration']}s)\n"
                f"   Status: `{r['status'].upper()}` | Views: {r['views']} | Likes: {r['likes']} | Comments: {r['comments']}\n"
                f"   🔗 {r['permalink']}"
            )

    return "\n".join(lines)


def optimize_existing_queue() -> int:
    """
    Upgrades all pending items in data/queue.json with:
    1. Rotating Hausa Viral Caption Archetypes (preserving user-shared captions).
    2. FFmpeg 0.0s hook & voice clarity audio mastering.
    """
    if not QUEUE_FILE.exists():
        return 0

    with open(QUEUE_FILE, "r", encoding="utf-8") as f:
        queue = json.load(f)

    with open(SCHOLARS_FILE, "r", encoding="utf-8") as f:
        raw_scholars = json.load(f)
    scholar_list = raw_scholars if isinstance(raw_scholars, list) else raw_scholars.get("scholars", [])
    scholars = {s["id"]: s for s in scholar_list if isinstance(s, dict) and "id" in s}

    upgraded = 0
    for idx, item in enumerate(queue):
        if item.get("status") != "pending":
            continue

        scholar_id = item.get("scholar_id", "")
        scholar = scholars.get(scholar_id, {"name": item.get("scholar", "Maluman Sunnah"), "hashtags": []})
        is_shared = bool(item.get("is_shared_link", False))

        # 1. Upgrade caption if not already using our rotating archetype format
        old_caption = item.get("caption", "")
        if not is_shared and "@followers" not in old_caption:
            raw_topic = old_caption.split("\n")[0].strip()
            item["caption"] = build_viral_caption(
                raw_title=raw_topic,
                scholar=scholar,
                is_shared_link=False,
                archetype_index=idx % 4,
            )
            item["viral_archetype"] = idx % 4
            print(f"[+] Upgraded caption for [{item['id']}] ({scholar.get('name')}) -> Archetype #{idx % 4}")

        # 2. Run FFmpeg 0.0s hook & voice clarity mastering if not yet mastered
        vpath = item.get("video_path", "")
        if vpath and Path(vpath).exists() and not item.get("audio_mastered"):
            if master_video_for_retention(vpath):
                item["audio_mastered"] = True

        upgraded += 1

    with open(QUEUE_FILE, "w", encoding="utf-8") as f:
        json.dump(queue, f, indent=2, ensure_ascii=False)

    return upgraded


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="Princess of Jannah — Viral Social Media Growth Engine")
    parser.add_argument("--report", action="store_true", help="Print live Facebook Page growth & analytics report")
    parser.add_argument("--optimize-queue", action="store_true", help="Upgrade queued videos with viral captions & FFmpeg mastering")
    args = parser.parse_args()

    if args.optimize_queue:
        count = optimize_existing_queue()
        print(f"[OK] Optimized {count} queued video(s).")
    else:
        print(format_whatsapp_analytics_card())
