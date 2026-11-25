import json
import os
import sys
import requests
from pathlib import Path
from config import (
    PAGE_ID,
    PAGE_ACCESS_TOKEN,
    QUEUE_FILE,
    HISTORY_FILE,
    MEDIA_DIR,
    now_wat,
)
from downloader import download_media_to_path

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
if hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")

GRAPH_API_VERSION = "v21.0"
BASE_GRAPH_URL = f"https://graph.facebook.com/{GRAPH_API_VERSION}"


def publish_reel_to_facebook(video_path: str, caption: str):
    """
    Publishes a video directly as a Facebook Reel using the official Meta Resumable Video Reels API.
    Falls back to /{page_id}/videos if video_reels endpoint encounters an issue.
    """
    if not PAGE_ID or not PAGE_ACCESS_TOKEN or PAGE_ID == "your_page_id_here":
        raise ValueError("PAGE_ID or PAGE_ACCESS_TOKEN is missing or not configured in .env file.")

    video_file = Path(video_path)
    if not video_file.exists():
        raise FileNotFoundError(f"Video file not found at: {video_path}")

    file_size = os.path.getsize(video_file)
    print(f"[*] Starting Facebook Reel upload: {video_file.name} ({file_size / (1024*1024):.2f} MB)")

    # -------------------------------------------------------------
    # Method A: Meta Graph API /video_reels (Native Facebook Reels)
    # -------------------------------------------------------------
    try:
        print("[*] Initializing Reel upload session...")
        init_url = f"{BASE_GRAPH_URL}/{PAGE_ID}/video_reels"
        init_payload = {
            "upload_phase": "start",
            "access_token": PAGE_ACCESS_TOKEN,
        }
        r_init = requests.post(init_url, data=init_payload, timeout=30)
        init_data = r_init.json()

        if "video_id" in init_data and "upload_url" in init_data:
            video_id = init_data["video_id"]
            upload_url = init_data["upload_url"]
            print(f"[+] Reel session initialized! Video ID: {video_id}")

            # Upload binary
            print("[*] Uploading video binary data...")
            with open(video_file, "rb") as f:
                video_bytes = f.read()

            upload_headers = {
                "Authorization": f"OAuth {PAGE_ACCESS_TOKEN}",
                "offset": "0",
                "file_size": str(file_size),
                "Content-Type": "application/octet-stream",
            }
            r_upload = requests.post(upload_url, headers=upload_headers, data=video_bytes, timeout=300)
            upload_res = r_upload.json()
            print(f"[+] Binary upload response: {upload_res}")

            # Finish and publish
            print("[*] Finalizing and publishing Reel...")
            finish_payload = {
                "upload_phase": "finish",
                "video_id": video_id,
                "video_state": "PUBLISHED",
                "description": caption,
                "access_token": PAGE_ACCESS_TOKEN,
            }
            r_finish = requests.post(init_url, data=finish_payload, timeout=60)
            finish_res = r_finish.json()

            if finish_res.get("success") is True or "video_id" in finish_res:
                print(f"[OK] Successfully published Reel! Video ID: {video_id}")
                return {"success": True, "video_id": video_id, "type": "reel", "response": finish_res}
            else:
                print(f"[!] Reels finish phase returned non-success: {finish_res}, falling back to standard video post...")
    except Exception as e:
        print(f"[!] Reels API attempt failed: {e}. Falling back to standard video API...")

    # -------------------------------------------------------------
    # Method B: Fallback to /{page_id}/videos (Standard Video Upload)
    # -------------------------------------------------------------
    print("[*] Executing fallback upload via /{page_id}/videos...")
    video_endpoint = f"{BASE_GRAPH_URL}/{PAGE_ID}/videos"
    with open(video_file, "rb") as f:
        files = {"source": (video_file.name, f, "video/mp4")}
        data = {
            "description": caption,
            "access_token": PAGE_ACCESS_TOKEN,
        }
        r_vid = requests.post(video_endpoint, data=data, files=files, timeout=300)
        vid_res = r_vid.json()

    if "id" in vid_res:
        vid_id = vid_res["id"]
        print(f"[OK] Successfully published video! Post/Video ID: {vid_id}")
        return {"success": True, "video_id": vid_id, "type": "standard_video", "response": vid_res}
    else:
        raise RuntimeError(f"Failed to publish to Facebook: {vid_res}")


def _upload_story_binary(story_file: Path) -> str | None:
    """
    Uploads a single MP4 file to /{PAGE_ID}/video_stories using Meta's 3-phase Story API.
    Returns the Story video_id on success, or None on failure.
    """
    init_url = f"{BASE_GRAPH_URL}/{PAGE_ID}/video_stories"
    init_resp = requests.post(
        init_url,
        data={"upload_phase": "start", "access_token": PAGE_ACCESS_TOKEN},
        timeout=30,
    ).json()

    if "video_id" not in init_resp or "upload_url" not in init_resp:
        print(f"[!] Could not initialize Story upload session: {init_resp}")
        return None

    story_vid_id = init_resp["video_id"]
    upload_url = init_resp["upload_url"]
    file_size = os.path.getsize(story_file)

    with open(story_file, "rb") as f:
        video_bytes = f.read()

    headers = {
        "Authorization": f"OAuth {PAGE_ACCESS_TOKEN}",
        "offset": "0",
        "file_size": str(file_size),
        "Content-Type": "application/octet-stream",
    }
    upload_resp = requests.post(upload_url, headers=headers, data=video_bytes, timeout=300).json()
    if not upload_resp.get("success", False):
        print(f"[!] Story binary upload returned non-success: {upload_resp}")
        return None

    finish_resp = requests.post(
        init_url,
        data={
            "upload_phase": "finish",
            "video_id": story_vid_id,
            "video_state": "PUBLISHED",
            "access_token": PAGE_ACCESS_TOKEN,
        },
        timeout=60,
    ).json()

    if finish_resp.get("success", False) or "post_id" in finish_resp or "id" in finish_resp:
        print(f"[OK] Successfully shared to Facebook Page Story! Story Video ID: {story_vid_id}")
        return str(story_vid_id)

    print(f"[!] Story finish phase returned: {finish_resp}")
    return None


def publish_story_to_facebook(video_path: str, duration_sec: int = 0) -> str | None:
    """
    Publishes the Reel video to the Facebook Page's Story (/{PAGE_ID}/video_stories).
    Facebook Stories cap single video clips at 60 seconds; if a Reel exceeds 58s,
    automatically creates a clean 58s Story cut via FFmpeg so every post shares to Story!
    """
    import subprocess
    from downloader import find_ffmpeg_location

    video_file = Path(video_path)
    if not video_file.exists():
        return None

    print(f"[*] Sharing video to Facebook Page Story: {video_file.name} ...")
    temp_story_file = None

    try:
        target_for_story = video_file
        ffmpeg_bin = find_ffmpeg_location()

        # Trim to 58s for Page Story if duration > 58s (or probe if duration_sec == 0)
        needs_trim = duration_sec > 58
        if duration_sec == 0 and ffmpeg_bin:
            import re
            probe = subprocess.run([ffmpeg_bin, "-i", str(video_file)], capture_output=True, text=True, timeout=15)
            m = re.search(r"Duration:\s*(\d+):(\d+):(\d+(?:\.\d+)?)", probe.stderr or "")
            if m:
                total_s = int(m.group(1)) * 3600 + int(m.group(2)) * 60 + float(m.group(3))
                needs_trim = total_s > 58

        if needs_trim and ffmpeg_bin:
            temp_story_file = video_file.with_suffix(".story.mp4")
            print("[*] Reel is > 58s; creating 58s Story cut for Facebook Page Story...")
            subprocess.run(
                [
                    ffmpeg_bin,
                    "-y",
                    "-i",
                    str(video_file),
                    "-t",
                    "58",
                    "-c",
                    "copy",
                    "-movflags",
                    "+faststart",
                    str(temp_story_file),
                ],
                capture_output=True,
                timeout=60,
            )
            if temp_story_file.exists() and temp_story_file.stat().st_size > 20_000:
                target_for_story = temp_story_file

        return _upload_story_binary(target_for_story)
    except Exception as e:
        print(f"[!] Page Story upload warning (Reel unaffected): {e}")
        return None
    finally:
        if temp_story_file and temp_story_file.exists():
            try:
                temp_story_file.unlink(missing_ok=True)
            except Exception:
                pass


def _ensure_local_video(item: dict) -> str:
    """
    Verifies the queued video file exists locally (cross-OS Windows/Linux safe).
    If missing, re-downloads it from source_url.
    """
    import re

    raw_path = item.get("video_path", "")
    video_path = Path(raw_path)
    if raw_path and video_path.exists() and video_path.is_file():
        return str(video_path)

    # Cross-OS basename extraction (handles Windows backslashes on Linux runners)
    clean_name = re.split(r"[/\\]", raw_path)[-1] if raw_path else ""
    filename = clean_name if clean_name else f"{item.get('scholar_id', 'scholar')}_{item['id']}.mp4"
    local_target = MEDIA_DIR / filename
    if local_target.exists() and local_target.is_file():
        item["video_path"] = f"media_vault/{filename}"
        return str(local_target.resolve())

    source_url = item.get("source_url")
    if not source_url:
        raise FileNotFoundError(f"Video file missing ({video_path}) and no source_url available to re-download.")

    print(f"[*] Local file missing ({local_target.name}). Re-downloading from source_url: {source_url}")
    if not download_media_to_path(source_url, local_target):
        raise FileNotFoundError(f"Failed to re-download missing video from: {source_url}")

    try:
        from viral_growth import master_video_for_retention
        master_video_for_retention(local_target)
    except Exception:
        pass

    item["video_path"] = str(local_target.resolve())
    return item["video_path"]


def publish_next_in_queue():
    with open(QUEUE_FILE, "r", encoding="utf-8") as f:
        queue = json.load(f)

    if not queue:
        print("[!] Queue is empty. No videos to publish.")
        return None

    # Get first pending item
    item_index = None
    item = None
    for idx, q in enumerate(queue):
        if q.get("status") == "pending":
            item_index = idx
            item = q
            break

    if not item:
        print("[!] No pending videos found in queue.")
        return None

    print(f"\n[>>>] Publishing next item: [{item['id']}] for {item['scholar']}")
    print(f"Caption: {item['caption'][:100]}...")

    try:
        resolved_video_path = _ensure_local_video(item)
        result = publish_reel_to_facebook(resolved_video_path, item["caption"])
        story_id = publish_story_to_facebook(resolved_video_path, int(item.get("duration") or 0))
        item["status"] = "published"
        item["published_at"] = now_wat().isoformat()
        item["fb_video_id"] = result.get("video_id")
        item["fb_story_id"] = story_id
        item["fb_type"] = result.get("type")

        # Save to history
        with open(HISTORY_FILE, "r", encoding="utf-8") as f:
            history = json.load(f)
        history.append(item)
        with open(HISTORY_FILE, "w", encoding="utf-8") as f:
            json.dump(history, f, indent=2, ensure_ascii=False)

        # Remove from queue
        queue.pop(item_index)
        with open(QUEUE_FILE, "w", encoding="utf-8") as f:
            json.dump(queue, f, indent=2, ensure_ascii=False)

        from config import sync_state_to_github
        sync_state_to_github(f"Auto: Published Reel [{item['id']}] -> FB {item.get('fb_video_id')} [skip ci]")

        print(f"[OK] Item [{item['id']}] published and moved to history.")
        return item
    except Exception as e:
        err_str = str(e)
        print(f"[X] Failed to publish [{item['id']}]: {err_str}")
        # If failure is due to an expired OAuth token (code 190) or transient network error,
        # keep the item as 'pending' at the front of the queue so it is not skipped!
        if "190" in err_str or "access token" in err_str.lower() or "OAuthException" in err_str or "Connection" in err_str:
            item["status"] = "pending"
            item["last_error"] = err_str
        else:
            item["status"] = "failed"
            item["error"] = err_str
        queue[item_index] = item
        with open(QUEUE_FILE, "w", encoding="utf-8") as f:
            json.dump(queue, f, indent=2, ensure_ascii=False)
        return None


if __name__ == "__main__":
    publish_next_in_queue()
