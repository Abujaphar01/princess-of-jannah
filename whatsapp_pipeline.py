"""
Princess of Jannah — WhatsApp Auto-Queue & Slot Allocation Pipeline
Automatically ingests shared links or direct WhatsApp videos from the
"Princess of Jannah Posts" group, queues them for the next WAT slot
(06:30, 13:30, 20:30 WAT), and returns a clean confirmation card.
"""

import argparse
import json
import shutil
import sys
import uuid
from datetime import datetime, timedelta
from pathlib import Path

from config import (
    QUEUE_FILE,
    HISTORY_FILE,
    MEDIA_DIR,
    POST_TIMES,
    now_wat,
    pull_state_from_github,
    sync_state_to_github,
)
from publisher import publish_next_in_queue
from downloader import (
    download_video,
    load_scholars,
    match_scholar,
    clean_caption,
    find_ffmpeg_location,
)
from viral_growth import (
    get_adaptive_wat_schedule,
    master_video_for_retention,
    format_whatsapp_analytics_card,
    build_viral_caption,
)

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
if hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")

DAYS_HAUSA = [
    "Litinin",
    "Talata",
    "Laraba",
    "Alhamis",
    "Juma'a",
    "Asabar",
    "Lahadi",
]


def _load_queue():
    if QUEUE_FILE.exists():
        try:
            with open(QUEUE_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)
            return data if isinstance(data, list) else []
        except Exception:
            return []
    return []


def _load_history():
    if HISTORY_FILE.exists():
        try:
            with open(HISTORY_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)
            return data if isinstance(data, list) else []
        except Exception:
            return []
    return []


def compute_scheduled_slot_for_queue_position(queue_position: int) -> str:
    """
    Given a 1-based position in the pending queue (1 = next to be published),
    calculates the exact upcoming WAT date & time slot across active adaptive WAT slots.
    """
    now = now_wat()
    active_slots = get_adaptive_wat_schedule().get("slots", POST_TIMES)
    parsed_slots = []
    for t_str in active_slots:
        try:
            h, m = [int(x) for x in t_str.split(":")]
            parsed_slots.append((h, m, t_str))
        except Exception:
            continue

    if not parsed_slots:
        parsed_slots = [(6, 30, "06:30"), (13, 30, "13:30"), (17, 30, "17:30"), (20, 30, "20:30")]

    parsed_slots.sort(key=lambda x: (x[0], x[1]))

    # Collect upcoming slots starting from `now`
    upcoming = []
    day_offset = 0
    while len(upcoming) < max(queue_position, 1) + 3:
        target_day = now + timedelta(days=day_offset)
        for h, m, t_str in parsed_slots:
            slot_dt = target_day.replace(hour=h, minute=m, second=0, microsecond=0)
            if slot_dt > (now + timedelta(minutes=1)):
                upcoming.append((slot_dt, day_offset, t_str))
        day_offset += 1

    chosen_dt, d_off, t_str = upcoming[max(0, queue_position - 1)]
    day_name = DAYS_HAUSA[chosen_dt.weekday()]

    # Format 12-hour display
    ampm_str = chosen_dt.strftime("%I:%M %p")
    if d_off == 0:
        day_label = f"Yau ({day_name})"
    elif d_off == 1:
        day_label = f"Gobe ({day_name})"
    else:
        day_label = f"Ranar {day_name} ({chosen_dt.strftime('%Y-%m-%d')})"

    return f"{day_label} da misalin {ampm_str} WAT"


def _can_instant_publish_now(cooldown_sec: int = 2700) -> bool:
    """
    Returns True if no Reel has been published in the last `cooldown_sec` (45 minutes),
    allowing the first WhatsApp-shared video/link to go live immediately while spacing out batches!
    """
    history = _load_history()
    if not history:
        return True
    try:
        last_pub = history[-1].get("published_at", "")
        if last_pub:
            last_dt = datetime.fromisoformat(last_pub)
            return (now_wat() - last_dt).total_seconds() >= cooldown_sec
    except Exception:
        pass
    return True


def _vip_insert_into_queue(item: dict) -> tuple[list[dict], int]:
    """
    Inserts a WhatsApp-shared item ahead of all auto-discovered items so admin shares
    always publish first instead of waiting behind the auto-discovery buffer.
    Returns (updated_queue, 1-based VIP position).
    """
    queue = _load_queue()
    insert_idx = 0
    for idx, q in enumerate(queue):
        if q.get("is_shared_link") and q.get("status") == "pending":
            insert_idx = idx + 1
        else:
            break
    queue.insert(insert_idx, item)
    with open(QUEUE_FILE, "w", encoding="utf-8") as f:
        json.dump(queue, f, indent=2, ensure_ascii=False)
    return queue, insert_idx + 1


def ingest_whatsapp_link(sender_phone: str, source_url: str, extra_text: str = "") -> str:
    """
    Downloads a shared link sent in 'Princess of Jannah Posts', gives it VIP #1 priority
    ahead of auto-discovered clips (publishing immediately if 45m+ since last post),
    and returns a clean confirmation card.
    """
    import re

    pull_state_from_github()
    scholars = load_scholars()
    scholar_override = None
    if extra_text:
        matched = match_scholar(extra_text, scholars)
        if matched:
            scholar_override = matched["id"]

    item = download_video(
        source_url,
        scholar_override=scholar_override,
        is_shared_link=True,
    )

    if not item:
        return (
            f"*PRINCESS OF JANNAH*\n\n"
            f"Assalamu Alaikum {sender_phone},\n"
            f"⚠️ Ba a sami damar sauke wannan link ba ko kuma an riga an dora shi a shafin:\n"
            f"{source_url}"
        )

    # If the sender typed their own caption alongside the link, preserve their exact caption
    custom_text = re.sub(r"https?://\S+", "", extra_text or "").strip()
    if len(custom_text) > 15:
        scholar_obj = next((s for s in scholars if s["id"] == item.get("scholar_id")), None)
        item["caption"] = clean_caption(custom_text, custom_text, scholar_obj, is_shared_link=True)
        queue = _load_queue()
        for q in queue:
            if q.get("id") == item["id"]:
                q["caption"] = item["caption"]
        with open(QUEUE_FILE, "w", encoding="utf-8") as f:
            json.dump(queue, f, indent=2, ensure_ascii=False)
        sync_state_to_github(f"Auto: Update custom WhatsApp caption for [{item['id']}] [skip ci]")

    caption_preview = item.get("caption", "").split("\n")[0][:110]
    dur = item.get("duration") or 0
    dur_str = f"{int(dur)}s" if dur else "Short Reel"

    queue = _load_queue()
    pending = [q for q in queue if q.get("status") == "pending"]
    pos = next((i + 1 for i, q in enumerate(pending) if q.get("id") == item["id"]), 1)

    if pos == 1 and _can_instant_publish_now():
        pub = publish_next_in_queue()
        if pub and pub.get("fb_video_id"):
            reel_url = f"https://www.facebook.com/reel/{pub['fb_video_id']}/"
            return (
                f"*PRINCESS OF JANNAH — AN WALLAFA KAI TSAYE!*\n\n"
                f"Assalamu Alaikum {sender_phone},\n"
                f"✅ An sauke link dinka kuma an dora shi a *Facebook Reels + Page Story* yanzu!\n\n"
                f"• *Malami*: {pub.get('scholar')}\n"
                f"• *Tsawon Bidiyo*: {dur_str}\n"
                f"• *Taken/Caption*: {caption_preview}\n"
                f"• *Kalli a Facebook*: {reel_url}"
            )

    sched_str = compute_scheduled_slot_for_queue_position(pos)
    return (
        f"*PRINCESS OF JANNAH*\n\n"
        f"Assalamu Alaikum {sender_phone},\n"
        f"✅ An karɓi link kuma an ba shi fifiko na *#{pos}* a gaban Queue (`#{item['id']}`).\n\n"
        f"• *Malami*: {item.get('scholar')}\n"
        f"• *Tsawon Bidiyo*: {dur_str}\n"
        f"• *Taken/Caption*: {caption_preview}\n"
        f"• *Zango a Queue (VIP)*: #{pos}\n"
        f"• *Lokacin Wallafawa*: {sched_str}\n"
        f"• *Cloud Sync*: ✅ An adana a GitHub 24/7 Cloud"
    )


def _probe_video_duration_sec(video_path: Path) -> int:
    """
    Probes the actual duration in seconds of a local video file using FFmpeg.
    """
    import re
    import subprocess

    ffmpeg_bin = find_ffmpeg_location()
    if not ffmpeg_bin or not video_path.exists():
        return 0
    try:
        res = subprocess.run(
            [ffmpeg_bin, "-i", str(video_path)],
            capture_output=True,
            text=True,
            timeout=15,
        )
        m = re.search(r"Duration:\s*(\d+):(\d+):(\d+(?:\.\d+)?)", res.stderr or "")
        if m:
            hrs, mins, secs = int(m.group(1)), int(m.group(2)), float(m.group(3))
            return int(round(hrs * 3600 + mins * 60 + secs))
    except Exception:
        pass
    return 0


def ingest_whatsapp_video(sender_phone: str, video_path: str, raw_caption: str = "") -> str:
    """
    Treats a direct video file uploaded in 'Princess of Jannah Posts' identically to a shared link:
    1. Moves into media_vault/ and runs FFmpeg 0.0s hook & voice clarity mastering.
    2. Probes exact duration in seconds.
    3. Detects scholar & preserves user caption (or builds a rotating Hausa viral caption if none/short).
    4. Queues for the next adaptive WAT slot & syncs the MP4 + queue.json straight to GitHub 24/7 Cloud.
    """
    src_path = Path(video_path)
    if not src_path.exists():
        return (
            f"*PRINCESS OF JANNAH*\n\n"
            f"Assalamu Alaikum {sender_phone},\n"
            f"⚠️ Ba a sami fayil ɗin bidiyon da aka turo ba."
        )

    pull_state_from_github()
    scholars = load_scholars()
    scholar = match_scholar(raw_caption, scholars)

    unique_id = str(uuid.uuid4())[:8]
    output_filename = f"{scholar['id'] if scholar else 'whatsapp'}_{unique_id}.mp4"
    output_path = MEDIA_DIR / output_filename

    shutil.copy2(src_path, output_path)
    try:
        if src_path.resolve() != output_path.resolve():
            src_path.unlink(missing_ok=True)
    except Exception:
        pass

    audio_mastered = master_video_for_retention(output_path)
    duration = _probe_video_duration_sec(output_path)

    clean_raw = (raw_caption or "").strip()
    if len(clean_raw) > 20:
        caption = clean_caption(
            raw_title=clean_raw,
            raw_description=clean_raw,
            scholar=scholar,
            is_shared_link=True,
        )
    else:
        caption = build_viral_caption(
            raw_title=clean_raw,
            scholar=scholar,
            is_shared_link=False,
        )

    item = {
        "id": unique_id,
        "source_video_id": f"wa_{unique_id}",
        "source_url": "whatsapp_direct_upload",
        "video_path": f"media_vault/{output_filename}",
        "caption": caption,
        "duration": duration,
        "scholar": scholar["name"] if scholar else "Maluman Sunnah",
        "scholar_id": scholar["id"] if scholar else "unknown",
        "is_shared_link": True,
        "audio_mastered": audio_mastered,
        "submitted_by": sender_phone,
        "added_at": now_wat().isoformat(),
        "status": "pending",
    }

    queue, pos = _vip_insert_into_queue(item)

    # Sync both the mastered MP4 in media_vault/ and data/queue.json to GitHub 24/7 Cloud
    sync_state_to_github(f"Auto: VIP queue direct WhatsApp video [{unique_id}] for {item['scholar']} [skip ci]")

    caption_preview = caption.split("\n")[0][:110]
    dur_str = f"{int(duration)}s" if duration else "Short Reel"

    if pos == 1 and _can_instant_publish_now():
        pub = publish_next_in_queue()
        if pub and pub.get("fb_video_id"):
            reel_url = f"https://www.facebook.com/reel/{pub['fb_video_id']}/"
            return (
                f"*PRINCESS OF JANNAH — AN WALLAFA KAI TSAYE!*\n\n"
                f"Assalamu Alaikum {sender_phone},\n"
                f"✅ An karɓi bidiyonka kuma an dora shi a *Facebook Reels + Page Story* yanzu!\n\n"
                f"• *Malami*: {pub.get('scholar')}\n"
                f"• *Tsawon Bidiyo*: {dur_str}\n"
                f"• *Taken/Caption*: {caption_preview}\n"
                f"• *Kalli a Facebook*: {reel_url}"
            )

    sched_str = compute_scheduled_slot_for_queue_position(pos)

    card = (
        f"*PRINCESS OF JANNAH*\n\n"
        f"Assalamu Alaikum {sender_phone},\n"
        f"✅ An karɓi bidiyo kai tsaye kuma an ba shi fifiko na *#{pos}* a gaban Queue (`#{unique_id}`).\n\n"
        f"• *Malami*: {item['scholar']}\n"
        f"• *Tsawon Bidiyo*: {dur_str}\n"
        f"• *Taken/Caption*: {caption_preview}\n"
        f"• *Zango a Queue (VIP)*: #{pos}\n"
        f"• *Lokacin Wallafawa*: {sched_str}\n"
        f"• *Cloud Sync*: ✅ An adana a GitHub 24/7 Cloud"
    )
    return card


def get_status_card(sender_phone: str = "@Admin") -> str:
    queue = _load_queue()
    history = _load_history()
    pending = [q for q in queue if q.get("status") == "pending"]
    next_slot = compute_scheduled_slot_for_queue_position(1)
    sched = get_adaptive_wat_schedule()
    active_slots = sched.get("slots", POST_TIMES)

    next_item_line = "Babu (Ana jiran bidiyo ko link daga WhatsApp)"
    if pending:
        first = pending[0]
        next_item_line = f"{first.get('scholar')} (`#{first.get('id')}`)"

    return (
        f"*PRINCESS OF JANNAH — BOT ONLINE*\n\n"
        f"Assalamu Alaikum {sender_phone},\n"
        f"Bot yana aiki 100% a cikin rukunin *Princess of Jannah Posts*.\n\n"
        f"• *Matakin Shafi*: {sched.get('stage_name')} ({sched.get('followers_count', 0)} followers)\n"
        f"• *Bidiyoyi a Queue*: {len(pending)}\n"
        f"• *Na Gaba a Queue*: {next_item_line}\n"
        f"• *Lokacin Wallafawa Na Gaba*: {next_slot}\n"
        f"• *Jimillar Waɗanda Aka Wallafa*: {len(history)}\n"
        f"• *Lokutan Wallafawa Kullum ({len(active_slots)}x)*: {', '.join(active_slots)} WAT\n\n"
        f"_Rubuta *ANALYTICS* don ganin kididdigar Facebook ko turo link/bidiyo don sakawa a Queue._"
    )


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Princess of Jannah WhatsApp Ingestion Pipeline")
    parser.add_argument("--url", default="", help="Shared video link from WhatsApp")
    parser.add_argument("--video", default="", help="Direct video file path from WhatsApp")
    parser.add_argument("--caption", default="", help="Accompanying message or caption")
    parser.add_argument("--phone", default="@Admin", help="Sender phone tag")
    parser.add_argument("--status", action="store_true", help="Print status card")
    parser.add_argument("--analytics", action="store_true", help="Print Facebook Page growth & analytics report")
    args = parser.parse_args()

    if args.analytics:
        print(format_whatsapp_analytics_card())
    elif args.status:
        print(get_status_card(args.phone))
    elif args.url:
        print(ingest_whatsapp_link(args.phone, args.url, args.caption))
    elif args.video:
        print(ingest_whatsapp_video(args.phone, args.video, args.caption))
    else:
        print(get_status_card(args.phone))
