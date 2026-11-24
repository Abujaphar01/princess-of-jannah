import json
import argparse
from pathlib import Path
from config import QUEUE_FILE, HISTORY_FILE
from downloader import download_video, load_scholars
from discover import discover_and_refill
from publisher import publish_next_in_queue
from scheduler import run_scheduler_loop, auto_post_once
from viral_growth import format_whatsapp_analytics_card, optimize_existing_queue


def show_scholars():
    scholars = load_scholars()
    print("\n" + "=" * 65)
    print("   10 Northern Nigerian Scholars Registry (Princess of Jannah)")
    print("=" * 65)
    for idx, s in enumerate(scholars, 1):
        print(f"{idx}. {s['name']}")
        print(f"   - ID: {s['id']}")
        print(f"   - Specialty: {s['specialty']}")
        print(f"   - Hashtags: {' '.join(s['hashtags'])}")
        if s.get("social_handles"):
            print(f"   - Handles:  {', '.join(s['social_handles'])}")
        if s.get("search_queries"):
            print(f"   - Queries:  {len(s['search_queries'])} discovery queries configured")
    print("=" * 65 + "\n")


def show_queue():
    with open(QUEUE_FILE, "r", encoding="utf-8") as f:
        queue = json.load(f)
    print("\n" + "=" * 65)
    print(f"   Upcoming Publication Queue ({len(queue)} items)")
    print("=" * 65)
    if not queue:
        print("Queue is empty. Add videos using: python engine.py add <link>")
        print("Or run autonomous discovery:      python engine.py discover --count 3")
    else:
        for idx, item in enumerate(queue, 1):
            status = item.get("status", "pending").upper()
            duration = item.get("duration", 0)
            print(f"{idx}. [{item['id']}] {item['scholar']} ({duration}s) | Status: {status}")
            print(f"   File:    {item['video_path']}")
            print(f"   Caption: {item['caption'][:120]}...")
            print(f"   Source:  {item['source_url']}")
            print("-" * 65)
    print("\n")


def show_history():
    with open(HISTORY_FILE, "r", encoding="utf-8") as f:
        history = json.load(f)
    print("\n" + "=" * 65)
    print(f"   Published History ({len(history)} items)")
    print("=" * 65)
    if not history:
        print("No published posts yet.")
    else:
        for idx, item in enumerate(reversed(history), 1):
            published_at = item.get("published_at", "N/A")
            fb_id = item.get("fb_video_id", "N/A")
            print(f"{idx}. [{item['id']}] {item['scholar']} | Published: {published_at}")
            print(f"   FB Video ID: {fb_id}")
            print(f"   Caption: {item['caption'][:100]}...")
            print("-" * 65)
    print("\n")


def batch_add(filepath):
    p = Path(filepath)
    if not p.exists():
        print(f"[!] Links file not found: {filepath}")
        return
    with open(p, "r", encoding="utf-8") as f:
        urls = [line.strip() for line in f if line.strip() and not line.startswith("#")]
    print(f"[*] Found {len(urls)} links to process.")
    for idx, u in enumerate(urls, 1):
        print(f"\n--- Processing Link {idx}/{len(urls)}: {u} ---")
        try:
            download_video(u, is_shared_link=True)
        except Exception as e:
            print(f"[!] Failed to ingest {u}: {e}")


def main():
    parser = argparse.ArgumentParser(description="Princess of Jannah - Islamic Scholars Video Automation Engine")
    subparsers = parser.add_subparsers(dest="command", help="Available subcommands")

    # add
    parser_add = subparsers.add_parser("add", help="Download and queue a shared video link")
    parser_add.add_argument("url", help="Shared URL (Facebook, YouTube Shorts, Instagram, etc.)")
    parser_add.add_argument("--scholar", help="Scholar ID override (e.g. jaafar_mahmud_adam, albani_zaria, rijiyar_lemo)", default=None)

    # batch
    parser_batch = subparsers.add_parser("batch", help="Batch add links from a text file")
    parser_batch.add_argument("file", help="Path to text file containing URLs (one per line)")

    # discover
    parser_discover = subparsers.add_parser("discover", help="Autonomously discover and queue short videos across the 10 scholars")
    parser_discover.add_argument("--count", type=int, default=3, help="Number of short videos to discover and queue (default: 3)")
    parser_discover.add_argument("--scholar", default=None, help="Optional scholar ID to target specifically")

    # auto-post
    subparsers.add_parser("auto-post", help="Refill queue via discovery if empty, then publish the next pending video")

    # queue
    subparsers.add_parser("queue", help="View current pending queue")

    # history
    subparsers.add_parser("history", help="View published history")

    # publish
    subparsers.add_parser("publish", help="Publish the next pending video immediately")

    # schedule
    subparsers.add_parser("schedule", help="Start the continuous 3-times daily automated scheduler (WAT)")

    # scholars
    subparsers.add_parser("scholars", help="List the 10 Northern Nigerian scholars registry")

    # analytics
    subparsers.add_parser("analytics", help="View live Facebook Page growth stage, follower count, and Reel analytics")

    # optimize-queue
    subparsers.add_parser("optimize-queue", help="Upgrade pending videos in queue with viral captions & FFmpeg 0.0s hook mastering")

    args = parser.parse_args()

    if args.command == "add":
        download_video(args.url, args.scholar, is_shared_link=True)
    elif args.command == "batch":
        batch_add(args.file)
    elif args.command == "discover":
        discover_and_refill(count=args.count, scholar_id=args.scholar)
    elif args.command == "auto-post":
        auto_post_once()
    elif args.command == "queue":
        show_queue()
    elif args.command == "history":
        show_history()
    elif args.command == "publish":
        publish_next_in_queue()
    elif args.command == "schedule":
        run_scheduler_loop()
    elif args.command == "scholars":
        show_scholars()
    elif args.command == "analytics":
        print("\n" + format_whatsapp_analytics_card() + "\n")
    elif args.command == "optimize-queue":
        count = optimize_existing_queue()
        print(f"\n[OK] Optimized {count} pending video(s) in queue with viral captions & FFmpeg mastering.\n")
    else:
        parser.print_help()


if __name__ == "__main__":
    main()
