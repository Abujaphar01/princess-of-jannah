import json
import subprocess
import urllib.parse
from config import (
    QUEUE_FILE,
    HISTORY_FILE,
    MIN_REEL_DURATION_SEC,
    MAX_REEL_DURATION_SEC,
)
from downloader import (
    load_scholars,
    download_video,
    is_already_processed,
)


def _load_json_list(path):
    if path.exists():
        try:
            with open(path, "r", encoding="utf-8") as f:
                data = json.load(f)
            return data if isinstance(data, list) else []
        except Exception:
            return []
    return []


def _matches_scholar_keywords(text: str, scholar: dict) -> bool:
    if not text:
        return False
    lower_text = text.lower()
    norm_text = lower_text.replace("'", "").replace("’", "")
    for kw in scholar.get("keywords", []):
        kw_l = kw.lower()
        kw_n = kw_l.replace("'", "").replace("’", "")
        if kw_l in lower_text or kw_n in norm_text:
            return True
    return False


def get_next_scholars_in_rotation(count: int = 3):
    """
    Inspects QUEUE_FILE and HISTORY_FILE to prioritize scholars with the fewest
    queued/recent items so all 10 scholars rotate evenly.
    """
    scholars = load_scholars()
    if not scholars:
        return []

    queue = _load_json_list(QUEUE_FILE)
    history = _load_json_list(HISTORY_FILE)

    counts = {s["id"]: 0 for s in scholars}
    last_seen = {s["id"]: -1 for s in scholars}

    combined = history + queue
    for idx, item in enumerate(combined):
        sid = item.get("scholar_id")
        if sid in counts:
            counts[sid] += 1
            last_seen[sid] = idx

    ordered = sorted(scholars, key=lambda s: (counts[s["id"]], last_seen[s["id"]]))
    if count <= len(ordered):
        return ordered[:count]

    result = []
    while len(result) < count:
        result.extend(ordered)
    return result[:count]


def discover_short_video_for_scholar(scholar: dict):
    """
    Searches for an authentic short video (MIN_REEL_DURATION_SEC .. MAX_REEL_DURATION_SEC)
    matching the scholar's keywords and not yet queued or published, then downloads & queues it.
    """
    queries = scholar.get("search_queries", [])
    if not queries:
        queries = [f"{scholar['name']} shorts"]

    print(f"\n[*] Discovering short video for: {scholar['name']}")

    for query in queries:
        search_targets = [
            (
                "short-filter",
                f"https://www.youtube.com/results?search_query={urllib.parse.quote_plus(query)}&sp=EgIYAQ%3D%3D",
            ),
            ("ytsearch10", f"ytsearch10:{query}"),
        ]

        for label, target in search_targets:
            print(f"    -> Searching ({label}): {query}")
            cmd = [
                "yt-dlp",
                "--no-plugin-dirs",
                "--dump-json",
                "--flat-playlist",
                "--playlist-end", "10",
                "--no-warnings",
                target,
            ]
            try:
                proc = subprocess.run(
                    cmd,
                    capture_output=True,
                    text=True,
                    timeout=60,
                    encoding="utf-8",
                    errors="replace",
                )
            except Exception as e:
                print(f"    [!] Search error for '{query}' ({label}): {e}")
                continue

            for line in proc.stdout.strip().splitlines():
                if not line.strip():
                    continue
                try:
                    entry = json.loads(line)
                except json.JSONDecodeError:
                    continue

                vid_id = str(entry.get("id") or "")
                title = entry.get("title") or ""
                description = entry.get("description") or ""
                uploader = entry.get("uploader") or entry.get("channel") or ""
                duration = entry.get("duration") or 0
                candidate_url = entry.get("url") or (
                    f"https://www.youtube.com/watch?v={vid_id}" if vid_id else ""
                )

                if not candidate_url:
                    continue

                try:
                    duration_val = float(duration)
                except (TypeError, ValueError):
                    duration_val = 0

                if not (MIN_REEL_DURATION_SEC <= duration_val <= MAX_REEL_DURATION_SEC):
                    continue

                search_blob = f"{title} {description} {uploader}"
                if not _matches_scholar_keywords(search_blob, scholar):
                    continue

                if is_already_processed(candidate_url, vid_id, title):
                    continue

                print(f"    [+] Candidate found ({int(duration_val)}s): {title}")
                queued_item = download_video(
                    candidate_url,
                    scholar_override=scholar["id"],
                    is_shared_link=False,
                )
                if queued_item:
                    return queued_item

    print(f"    [!] No new matching short video found for {scholar['short_name']}.")
    return None


def discover_and_refill(count: int = 3, scholar_id: str = None):
    """
    Autonomously discovers and queues `count` short videos.
    If `scholar_id` is specified, focuses on that scholar; otherwise rotates evenly across all 10.
    """
    all_scholars = load_scholars()
    if not all_scholars:
        print("[!] No scholars found in registry.")
        return []

    queued_items = []

    if scholar_id:
        target = next(
            (
                s
                for s in all_scholars
                if s["id"] == scholar_id or scholar_id.lower() in s["name"].lower()
            ),
            None,
        )
        if not target:
            print(f"[!] Scholar not found: {scholar_id}")
            return []
        for _ in range(count):
            item = discover_short_video_for_scholar(target)
            if item:
                queued_items.append(item)
            else:
                break
        return queued_items

    # Rotate across all scholars until `count` videos are queued
    ordered = get_next_scholars_in_rotation(len(all_scholars))
    attempts = 0
    max_attempts = max(len(ordered) * 2, count * 2)
    idx = 0

    while len(queued_items) < count and attempts < max_attempts:
        scholar = ordered[idx % len(ordered)]
        item = discover_short_video_for_scholar(scholar)
        if item:
            queued_items.append(item)
        idx += 1
        attempts += 1

    print(f"\n[*] Discovery finished: queued {len(queued_items)}/{count} short video(s).")
    return queued_items


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="Autonomous Short-Video Discovery Engine")
    parser.add_argument("--count", type=int, default=3, help="Number of short videos to queue")
    parser.add_argument("--scholar", type=str, default=None, help="Optional scholar ID filter")
    args = parser.parse_args()
    discover_and_refill(count=args.count, scholar_id=args.scholar)
