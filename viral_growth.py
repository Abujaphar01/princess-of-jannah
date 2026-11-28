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
# 1. NATURAL HUMAN HAUSA CAPTION ENGINE (ZERO ROBOTIC / AI PHRASING)
# =====================================================================

LIVING_SCHOLAR_DUAS = [
    "Allah ya saka da alkhairi, ya kara lafiya.",
    "Allah ya kara wa Malam lafiya da nisan kwana mai albarka.",
    "Allah ya sa mu dace, ya amfane mu da abin da muka saurara.",
    "Allah ya saka wa Malam da alkhairi, ya sa mu amfana.",
    "Allah ya ba mu ikon aiki da abin da muka ji.",
    "Allah ya kara mana ilimi mai amfani da ikhlasi.",
]

DECEASED_SCHOLAR_DUAS = [
    "Allah ya jikan sa da rahama, ya gafarta masa.",
    "Allah ya kai haske kabarinsa, ya saka masa da Aljannah.",
    "Allah ya jikan Malam da rahama, ya sa mu amfana da iliminsa.",
    "Allah ya gafarta masa, ya hada mu a Aljannatul Firdaus.",
]

SCHOLAR_STRIP_PATTERNS = [
    r"\b(?:marigayi|sheikh|shaikh|prof\.?|professor|dr\.?|malam|mal\.?|ustaz|alhaji)\b",
    r"\brahimahullah(?:u)?\b",
    r"\bhafizahullah(?:u)?\b",
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


def topic_fingerprint(text: str) -> str:
    """
    Produces a normalized fingerprint of a video's core Hausa topic (stripping scholar names,
    hashtags, punctuation, and boilerplate words) to detect duplicate clips across channels.
    """
    if not text:
        return ""
    first_chunk = text.strip().split("\n\n")[0]
    lowered = re.sub(r"https?://\S+|#\S+", " ", first_chunk.lower())
    lowered = re.sub(r"\[\[.*?\]\]|\[.*?\]", " ", lowered)
    noise_words = {
        "sheikh", "shaikh", "prof", "professor", "dr", "malam", "mal", "marigayi",
        "rahimahullah", "rahimahullahu", "jaafar", "jafar", "mahmud", "adam", "kano",
        "albani", "albaniy", "zaria", "zariya", "auwal", "muhammad", "sani", "umar",
        "rijiyar", "lemo", "aminu", "ibrahim", "daurawa", "ahmad", "tijjani", "guruntum",
        "isa", "ali", "pantami", "mansur", "yelwa", "abdallah", "abdullahi", "usman",
        "gadon", "kaya", "abu", "haitham", "haisam", "khamis", "sadis", "jamil", "jameel",
        "shorts", "short", "waazi", "nasiha", "karatu", "darasi", "bayani", "maudui",
        "tare", "daga", "bakin", "kan", "tunatarwa", "mai", "amfani", "allah", "dace",
        "amfane", "abin", "abinda", "muka", "saurara", "kara", "mana", "imani", "ikhlasi",
        "saka", "alkhairi", "musaurari", "wannan", "saurara", "kaji", "ratsa", "zuciya",
        "kowane", "musulmi", "matukar", "rayuwarmu", "yau", "kullum", "kalmomi", "masu",
        "duniya", "lahira", "ikon", "aiki", "shiga", "rai", "fadakarwa", "shirye", "bisa",
        "tafarkin", "sunnah", "muhimmanci", "iyali", "alumma", "ilmantarwa", "rayuwar",
        "tsoronsa", "gyaran", "muamala", "rabauta", "daraja", "neman", "tsira", "cika",
    }
    tokens = [t for t in re.findall(r"[a-z0-9']+", lowered) if len(t) > 2 and t not in noise_words]
    return " ".join(tokens[:8])


def _smart_sentence_case(text: str) -> str:
    """
    Converts ALL-CAPS YouTube titles into natural human sentence casing
    while keeping normal mixed-case titles intact.
    """
    letters = [c for c in text if c.isalpha()]
    if not letters:
        return text
    upper_ratio = sum(1 for c in letters if c.isupper()) / len(letters)
    if upper_ratio > 0.65:
        lowered = text.lower()
        return lowered[:1].upper() + lowered[1:]
    return text


def clean_raw_title(raw_title: str, scholar: dict | None = None) -> str:
    """
    Cleans raw YouTube/social titles so they read like a real human wrote them:
    - Removes [[brackets]], || channel suffixes, URLs, #hashtags, em-dashes, and file codes
    - Removes duplicate mentions of the scholar's name so it never repeats twice
    - Fixes ALL-CAPS shouting into natural Hausa casing
    """
    if not raw_title:
        raw_title = ""

    first_line = raw_title.strip().split("\n")[0].strip()

    # Strip URLs, hashtags, @handles, [[...]], [...], and social noise tokens
    cleaned = re.sub(r"https?://\S+", "", first_line)
    cleaned = re.sub(r"#\S+", "", cleaned)
    cleaned = re.sub(r"@\S+(?:\s+azumi)?", "", cleaned, flags=re.IGNORECASE)
    cleaned = re.sub(r"\[\[.*?\]\]", " ", cleaned)
    cleaned = re.sub(r"\[.*?\]", " ", cleaned)
    cleaned = re.sub(r"[—–]+", " - ", cleaned)
    cleaned = re.sub(
        r"\b(shorts|short|tiktok|reels|reel|video|mp4|official|channel|tv|IMG_\d+|VID_\d+)\b",
        "",
        cleaned,
        flags=re.IGNORECASE,
    )

    # Split on pipe or double-slash separators (||, |, //) and keep the segment with the actual topic
    if "|" in cleaned or "//" in cleaned:
        parts = [p.strip(" -_:,.") for p in re.split(r"\|+|//+", cleaned) if p.strip(" -_:,.")]
        if parts:
            scholar_kws = [k.lower() for k in (scholar or {}).get("keywords", [])]
            non_name_parts = [
                p for p in parts
                if not any(kw in p.lower() for kw in scholar_kws) or len(p.split()) > 5
            ]
            cleaned = non_name_parts[0] if non_name_parts else max(parts, key=len)

    # Strip leading or trailing scholar name prefixes/suffixes (e.g. "Sheikh Pantami: ..." or "... tare da Malam X")
    if scholar:
        kws = sorted(scholar.get("keywords", []), key=len, reverse=True)
        for name_variant in [scholar.get("name", ""), scholar.get("short_name", ""), *kws]:
            nv = name_variant.strip()
            if not nv:
                continue
            esc = re.escape(nv)
            cleaned = re.sub(rf"^(?:[\w.\s']*?{esc})\s*[:\-–—]+\s*", "", cleaned, flags=re.IGNORECASE)
            cleaned = re.sub(rf"\s+(?:tare\s+da\s+|daga\s+)?(?:(?:sheikh|shaikh|prof\.?|dr\.?|malam|mal\.?|marigayi)\s+)*{esc}[\s()a-z]*$", "", cleaned, flags=re.IGNORECASE)
            cleaned = re.sub(rf"\s*[:\-–—]+\s*(?:[\w.\s']*?{esc})[\s()a-z]*$", "", cleaned, flags=re.IGNORECASE)

    # Strip any dangling honorifics left at the very end (e.g. "Hukuncin maita Dr.")
    cleaned = re.sub(
        r"\s+(?:tare\s+da|daga|by)?\s*(?:marigayi|sheikh|shaikh|prof\.?|professor|dr\.?|malam|mal\.?|ustaz|hafizahullah|rahimahullah)\.?\s*$",
        "",
        cleaned,
        flags=re.IGNORECASE,
    )

    for pat in SCHOLAR_STRIP_PATTERNS:
        cleaned = re.sub(rf"^\s*{pat}\s*[:\-–—]*\s*$", "", cleaned, flags=re.IGNORECASE)

    cleaned = re.sub(r"\s+", " ", cleaned).strip(" -_|:,.")
    cleaned = _smart_sentence_case(cleaned)

    low = cleaned.lower()
    scholar_name = (scholar or {}).get("name", "").lower()
    short_name = (scholar or {}).get("short_name", "").lower()
    scholar_kws = [k.lower() for k in (scholar or {}).get("keywords", [])]

    if (
        len(cleaned) < 10
        or low in {scholar_name, short_name, *scholar_kws}
    ):
        specialty = (scholar or {}).get("specialty", "Tunatarwa da Nasiha").split(",")[0].strip()
        return f"Tunatarwa mai amfani kan {specialty.lower()}"

    return cleaned


def _dedupe_hashtags(tags: list[str], max_tags: int = 4) -> str:
    seen = set()
    out = []
    for raw in tags:
        for tok in raw.split():
            if not tok.startswith("#"):
                continue
            key = tok.lower()
            if key not in seen:
                seen.add(key)
                out.append(tok)
            if len(out) >= max_tags:
                return " ".join(out)
    return " ".join(out)


def build_viral_caption(
    raw_title: str,
    scholar: dict | None = None,
    is_shared_link: bool = False,
    archetype_index: int | None = None,
) -> str:
    """
    Builds a warm, natural, 100% human-sounding Hausa caption:
    - Preserves original captions on user-shared links/videos verbatim.
    - No robotic labels ('Maudu'i:', 'Kan Maudu'in:', 'Daga bakin:'), no em-dashes,
      no translated clickbait, no duplicate scholar names, and max 3-4 clean hashtags.
    """
    scholar = scholar or {
        "id": "general_sunnah",
        "name": "Maluman Sunnah",
        "short_name": "Maluman Sunnah",
        "specialty": "Sunnah",
        "hashtags": ["#PrincessOfJannah", "#MalumanSunnah", "#Sunnah"],
    }

    scholar_hashtags = scholar.get("hashtags", [])
    clean_tags = _dedupe_hashtags(
        ["#PrincessOfJannah", *scholar_hashtags, "#MalumanSunnah"],
        max_tags=4,
    )

    # 1. Strictly preserve original human caption on shared links/videos
    if is_shared_link and raw_title and len(raw_title.strip()) > 5:
        clean_shared = raw_title.strip()
        if "#" not in clean_shared:
            return f"{clean_shared}\n\n{clean_tags}"
        return clean_shared

    # 2. Pick a style index that never repeats recent history/queue posts
    recent_count = 0
    try:
        if HISTORY_FILE.exists():
            with open(HISTORY_FILE, "r", encoding="utf-8") as f:
                recent_count += len(json.load(f))
        if QUEUE_FILE.exists():
            with open(QUEUE_FILE, "r", encoding="utf-8") as f:
                recent_count += len(json.load(f))
    except Exception:
        recent_count = int(time.time() // 60)

    style_seed = archetype_index if archetype_index is not None else recent_count
    style_idx = style_seed % 6

    topic = clean_raw_title(raw_title, scholar)
    if topic and topic[-1] not in ".?!":
        topic_sentence = f"{topic}."
    else:
        topic_sentence = topic

    raw_name = scholar.get("name", "Maluman Sunnah")
    is_deceased = "rahimahullah" in raw_name.lower()
    display_name = re.sub(r"\s*\(rahimahullah\)\s*", "", raw_name, flags=re.IGNORECASE).strip()

    dua_seed = style_seed * 3 + sum(ord(c) for c in topic[:20])
    if is_deceased:
        dua = DECEASED_SCHOLAR_DUAS[dua_seed % len(DECEASED_SCHOLAR_DUAS)]
        scholar_ref = f"Marigayi {display_name}"
    else:
        dua = LIVING_SCHOLAR_DUAS[dua_seed % len(LIVING_SCHOLAR_DUAS)]
        scholar_ref = display_name

    if style_idx == 0:
        body = f"{topic_sentence}\n\n{scholar_ref}. {dua}"
    elif style_idx == 1:
        body = f"{topic_sentence}\n\nTare da {scholar_ref}. {dua}"
    elif style_idx == 2:
        body = f"{topic} - {scholar_ref}.\n\n{dua}"
    elif style_idx == 3:
        body = f"{topic_sentence}\n\nDaga karatun {scholar_ref}. {dua}"
    elif style_idx == 4:
        body = f"{topic_sentence}\n\n{scholar_ref}.\n{dua}"
    else:
        body = f"{topic} ({scholar.get('short_name') or scholar_ref}).\n\n{dua}"

    return f"{body}\n\n{clean_tags}"


# =====================================================================
# 2. FFMPEG 0.0s HOOK & VOICE CLARITY MASTERING
# =====================================================================

def _probe_video_dimensions(ffmpeg_exe: str, video_path: Path) -> tuple[int, int]:
    """
    Probes (width, height) of the video stream via FFmpeg stderr.
    """
    try:
        probe = subprocess.run(
            [ffmpeg_exe, "-i", str(video_path)],
            capture_output=True,
            text=True,
            timeout=15,
        )
        for line in (probe.stderr or "").splitlines():
            if "Video:" in line:
                m = re.search(r"\b(\d{2,5})x(\d{2,5})\b", line)
                if m:
                    return int(m.group(1)), int(m.group(2))
    except Exception:
        pass
    return 720, 1280


def master_video_for_retention(video_path: str | Path, is_shared_link: bool = False) -> bool:
    """
    Runs an automated FFmpeg mastering & anti-duplicate refresh pass (keeping full video length!):
    1. Strips all hidden social-platform metadata & chapters (-map_metadata -1 -map_chapters -1).
    2. Trims dead opening silence so speech starts cleanly at 0.0s.
    3. Applies 85Hz high-pass filter, +2dB 3kHz vocal clarity boost, and dynamic loudness leveling
       (plus a subtle 1.5% acoustic timing refresh on re-shared clips).
    4. Reframes re-shared clips with a subtle 4% center crop, crisp Lanczos HD scaling (720p-1080p),
       and gentle contrast/saturation polish so Meta's vPDQ filter treats them as fresh HD media.
    Safely falls back to the original file if anything fails.
    """
    target = Path(video_path)
    if not target.exists() or not target.is_file():
        return False

    ffmpeg_exe = _find_ffmpeg_exe()
    if not ffmpeg_exe:
        print("[!] FFmpeg binary not found; skipping audio/retention mastering.")
        return False

    orig_w, orig_h = _probe_video_dimensions(ffmpeg_exe, target)
    if orig_w <= orig_h:
        # Vertical 9:16 or square 1:1 -> ensure at least crisp 720p width (capped at 1080p)
        target_w = min(1080, max(720, (orig_w // 2) * 2))
    else:
        # Horizontal 16:9 -> ensure at least 1280p width (capped at 1920p)
        target_w = min(1920, max(1280, (orig_w // 2) * 2))
    target_h = max(2, (round(target_w * orig_h / max(1, orig_w)) // 2) * 2)

    if is_shared_link:
        video_filter = (
            f"crop=trunc(iw*0.96/2)*2:trunc(ih*0.96/2)*2:(iw-trunc(iw*0.96/2)*2)/2:(ih-trunc(ih*0.96/2)*2)/2,"
            f"scale={target_w}:{target_h}:flags=lanczos,"
            f"unsharp=3:3:0.3:3:3:0.0,"
            f"eq=contrast=1.03:saturation=1.05:brightness=0.005,"
            f"format=yuv420p"
        )
        audio_filter = (
            "silenceremove=start_periods=1:start_duration=0.05:start_threshold=-42dB,"
            "highpass=f=85,"
            "equalizer=f=3000:width_type=h:width=1000:g=2,"
            "dynaudnorm=f=150:g=15,"
            "atempo=1.015"
        )
    else:
        video_filter = (
            f"scale={target_w}:{target_h}:flags=lanczos,"
            f"eq=contrast=1.02:saturation=1.03,"
            f"format=yuv420p"
        )
        audio_filter = (
            "silenceremove=start_periods=1:start_duration=0.05:start_threshold=-42dB,"
            "highpass=f=85,"
            "equalizer=f=3000:width_type=h:width=1000:g=2,"
            "dynaudnorm=f=150:g=15"
        )

    temp_out = target.with_suffix(".mastered.mp4")
    cmd = [
        ffmpeg_exe,
        "-y",
        "-i",
        str(target),
        "-map_metadata",
        "-1",
        "-map_chapters",
        "-1",
        "-vf",
        video_filter,
        "-af",
        audio_filter,
        "-c:v",
        "libx264",
        "-preset",
        "veryfast",
        "-crf",
        "22",
        "-c:a",
        "aac",
        "-b:a",
        "192k",
        "-movflags",
        "+faststart",
        str(temp_out),
    ]

    try:
        print(f"[*] Mastering HD video ({orig_w}x{orig_h} -> {target_w}w) & retention audio for: {target.name} ...")
        res = subprocess.run(cmd, capture_output=True, text=True, timeout=420)
        if res.returncode == 0 and temp_out.exists() and temp_out.stat().st_size > 50_000:
            temp_out.replace(target)
            print(f"[+] Mastering complete: {target.name} ({target.stat().st_size / (1024*1024):.2f} MB)")
            return True
        else:
            if temp_out.exists():
                temp_out.unlink(missing_ok=True)
            print(f"[!] FFmpeg mastering returned non-zero ({res.returncode}): {(res.stderr or '')[-250:]}")
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

        # 1. Sanitize shared captions (strip competitor promos / enrich emoji-only) or upgrade fallback captions
        old_caption = item.get("caption", "")
        if is_shared:
            from downloader import clean_caption
            scholar_arg = scholar if scholar_id and scholar_id != "unknown" else None
            new_cap = clean_caption(
                old_caption,
                old_caption,
                scholar_arg,
                is_shared_link=True,
                seed_key=item.get("source_video_id") or item.get("id", ""),
            )
            if new_cap != old_caption:
                item["caption"] = new_cap
                print(f"[+] Sanitized/enriched shared caption for [{item['id']}]")
        elif "@followers" not in old_caption:
            raw_topic = old_caption.split("\n")[0].strip()
            item["caption"] = build_viral_caption(
                raw_title=raw_topic,
                scholar=scholar,
                is_shared_link=False,
                archetype_index=idx % 4,
            )
            item["viral_archetype"] = idx % 4
            print(f"[+] Upgraded caption for [{item['id']}] ({scholar.get('name')}) -> Archetype #{idx % 4}")

        # 2. Run FFmpeg HD & retention mastering if not yet v2-mastered
        vpath = item.get("video_path", "")
        master_key = "hd_v2_mastered" if is_shared else "audio_mastered"
        if vpath and Path(vpath).exists() and not item.get(master_key):
            if master_video_for_retention(vpath, is_shared_link=is_shared):
                item["audio_mastered"] = True
                item[master_key] = True

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
