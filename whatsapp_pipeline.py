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
from datetime import timedelta
from pathlib import Path

from config import (
    QUEUE_FILE,
    HISTORY_FILE,
    MEDIA_DIR,
    POST_TIMES,
    now_wat,
)
from downloader import (
    download_video,
    load_scholars,
    match_scholar,
    clean_caption,
)
from viral_growth import (
    get_adaptive_wat_schedule,
    master_video_for_retention,
    format_whatsapp_analytics_card,
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


def ingest_whatsapp_link(sender_phone: str, source_url: str, extra_text: str = "") -> str:
    """
    Downloads a shared link sent in 'Princess of Jannah Posts', queues it
    automatically, and formats the WhatsApp confirmation card.
    """
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
            f"⚠️ Ba a sami damar sauke wannan link ba ko kuma an riga an saka shi a Queue:\n"
            f"{source_url}"
        )

    queue = _load_queue()
    pending = [q for q in queue if q.get("status") == "pending"]
    pos = len(pending)
    sched_str = compute_scheduled_slot_for_queue_position(pos)

    caption_preview = item.get("caption", "").split("\n")[0][:110]
    dur = item.get("duration") or 0
    dur_str = f"{int(dur)}s" if dur else "Short Reel"

    card = (
        f"*PRINCESS OF JANNAH*\n\n"
        f"Assalamu Alaikum {sender_phone},\n"
        f"✅ An karɓi link kuma an saka a Queue (`#{item['id']}`).\n\n"
        f"• *Malami*: {item.get('scholar')}\n"
        f"• *Tsawon Bidiyo*: {dur_str}\n"
        f"• *Taken/Caption*: {caption_preview}\n"
        f"• *Zango a Queue*: #{pos}\n"
        f"• *Lokacin Wallafawa*: {sched_str}"
    )
    return card


def ingest_whatsapp_video(sender_phone: str, video_path: str, raw_caption: str = "") -> str:
    """
    Moves a direct video file uploaded in 'Princess of Jannah Posts' into media_vault,
    queues it automatically for the next WAT slot, and returns a confirmation card.
    """
    src_path = Path(video_path)
    if not src_path.exists():
        return (
            f"*PRINCESS OF JANNAH*\n\n"
            f"Assalamu Alaikum {sender_phone},\n"
            f"⚠️ Ba a sami fayil ɗin bidiyon da aka turo ba."
        )

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

    caption = clean_caption(
        raw_title=raw_caption,
        raw_description=raw_caption,
        scholar=scholar,
        is_shared_link=True,
    )

    item = {
        "id": unique_id,
        "source_video_id": f"wa_{unique_id}",
        "source_url": "whatsapp_direct_upload",
        "video_path": str(output_path.resolve()),
        "caption": caption,
        "duration": 0,
        "scholar": scholar["name"] if scholar else "Authentic Islamic Scholar",
        "scholar_id": scholar["id"] if scholar else "unknown",
        "is_shared_link": True,
        "audio_mastered": audio_mastered,
        "submitted_by": sender_phone,
        "added_at": now_wat().isoformat(),
        "status": "pending",
    }

    queue = _load_queue()
    queue.append(item)
    with open(QUEUE_FILE, "w", encoding="utf-8") as f:
        json.dump(queue, f, indent=2, ensure_ascii=False)

    pending = [q for q in queue if q.get("status") == "pending"]
    pos = len(pending)
    sched_str = compute_scheduled_slot_for_queue_position(pos)
    caption_preview = caption.split("\n")[0][:110]

    card = (
        f"*PRINCESS OF JANNAH*\n\n"
        f"Assalamu Alaikum {sender_phone},\n"
        f"✅ An karɓi bidiyo kai tsaye kuma an saka a Queue (`#{unique_id}`).\n\n"
        f"• *Malami*: {item['scholar']}\n"
        f"• *Taken/Caption*: {caption_preview}\n"
        f"• *Zango a Queue*: #{pos}\n"
        f"• *Lokacin Wallafawa*: {sched_str}"
    )
    return card


def get_status_card(sender_phone: str = "@Admin") -> str:
    queue = _load_queue()
    history = _load_history()
    pending = [q for q in queue if q.get("status") == "pending"]
    next_slot = compute_scheduled_slot_for_queue_position(1)
    sched = get_adaptive_wat_schedule()
    active_slots = sched.get("slots", POST_TIMES)

    next_item_line = "Babu (Za a nemo ta atomatik)"
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
