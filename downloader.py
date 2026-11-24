import html
import json
import re
import shutil
import subprocess
import urllib.parse
import urllib.request
import uuid
from pathlib import Path
from config import MEDIA_DIR, QUEUE_FILE, HISTORY_FILE, SCHOLARS_FILE, now_wat

BROWSER_UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
)


def find_ffmpeg_location():
    """
    Finds an ffmpeg binary on PATH or via imageio_ffmpeg so yt-dlp can merge
    separate HD video + audio DASH streams into MP4 without manual setup.
    """
    sys_ffmpeg = shutil.which("ffmpeg")
    if sys_ffmpeg:
        return sys_ffmpeg
    try:
        import imageio_ffmpeg

        exe = imageio_ffmpeg.get_ffmpeg_exe()
        if exe and Path(exe).exists():
            return exe
    except Exception:
        pass
    return None

GENERIC_TITLES = {
    "facebook",
    "watch",
    "reel",
    "video",
    "instagram",
    "tiktok",
    "youtube",
    "log in or sign up to view",
    "log into facebook",
}


def load_scholars():
    if SCHOLARS_FILE.exists():
        with open(SCHOLARS_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    return []


def match_scholar(text, scholars):
    if not text:
        return None
    lower_text = text.lower()
    for s in scholars:
        for kw in s.get("keywords", []):
            if kw.lower() in lower_text:
                return s
    return None


def resolve_shared_url(url: str) -> str:
    """
    Follows redirects on shared links (e.g., facebook.com/share/..., fb.watch/..., short links)
    so yt-dlp and OpenGraph extraction receive the canonical destination URL.
    """
    try:
        req = urllib.request.Request(url, headers={"User-Agent": BROWSER_UA})
        with urllib.request.urlopen(req, timeout=15) as resp:
            resolved = resp.geturl()
            if resolved and resolved != url:
                print(f"[*] Resolved shared link -> {resolved}")
            return resolved or url
    except Exception:
        return url


def fetch_opengraph_caption(url: str) -> str:
    """
    Fallback extractor when yt-dlp returns empty description or generic title
    on shared Facebook / social links.
    """
    try:
        req = urllib.request.Request(url, headers={"User-Agent": BROWSER_UA})
        with urllib.request.urlopen(req, timeout=15) as resp:
            raw_html = resp.read().decode("utf-8", errors="ignore")

        for pattern in [
            r'<meta[^>]+property=["\']og:description["\'][^>]+content=["\']([^"\']+)["\']',
            r'<meta[^>]+content=["\']([^"\']+)["\'][^>]+property=["\']og:description["\']',
            r'<meta[^>]+property=["\']og:title["\'][^>]+content=["\']([^"\']+)["\']',
            r'<meta[^>]+content=["\']([^"\']+)["\'][^>]+property=["\']og:title["\']',
        ]:
            m = re.search(pattern, raw_html, flags=re.IGNORECASE)
            if m:
                candidate = html.unescape(m.group(1)).strip()
                if candidate and candidate.lower() not in GENERIC_TITLES:
                    return candidate
    except Exception:
        pass
    return ""


def _is_generic(text: str) -> bool:
    if not text:
        return True
    cleaned = text.strip().lower()
    return cleaned == "" or cleaned in GENERIC_TITLES


def _normalize_url(url: str) -> str:
    """
    Normalizes a video URL while preserving essential video identifiers (e.g. ?v=...)
    and stripping tracking parameters so distinct videos never collide.
    """
    if not url:
        return ""
    parsed = urllib.parse.urlparse(url.strip())
    path = parsed.path.rstrip("/")
    qs = urllib.parse.parse_qs(parsed.query)
    if "v" in qs and qs["v"]:
        return f"{parsed.netloc.lower()}{path}?v={qs['v'][0]}"
    return f"{parsed.netloc.lower()}{path}"


def is_already_processed(source_url: str, video_id: str) -> bool:
    """
    Checks both QUEUE_FILE and HISTORY_FILE so duplicate videos are never queued twice.
    """
    records = []
    for path in (QUEUE_FILE, HISTORY_FILE):
        if path.exists():
            try:
                with open(path, "r", encoding="utf-8") as f:
                    data = json.load(f)
                if isinstance(data, list):
                    records.extend(data)
            except Exception:
                pass

    norm_url = _normalize_url(source_url)
    for item in records:
        if video_id and item.get("source_video_id") == video_id:
            return True
        item_url = _normalize_url(item.get("source_url") or "")
        if norm_url and item_url and norm_url == item_url:
            return True
    return False


def clean_caption(raw_title, raw_description, scholar, is_shared_link=True):
    """
    User directive:
    'Short videos, no need of long caption, If its by shared link, then just use the caption on the shared link'
    """
    caption = ""
    desc = (raw_description or "").strip()
    title = (raw_title or "").strip()

    if is_shared_link:
        if not _is_generic(desc):
            caption = desc
        elif not _is_generic(title):
            caption = title
    else:
        if not _is_generic(title):
            caption = title
        elif not _is_generic(desc):
            first_part = desc.split("\n\n")[0].strip()
            if len(first_part) > 200:
                lines = [l.strip() for l in desc.split("\n") if l.strip()]
                first_part = lines[0] if lines else first_part[:200].rstrip()
            caption = first_part

    # Strip raw http/https URLs and normalize blank lines
    caption = re.sub(r"https?://\S+", "", caption)
    caption = re.sub(r"\n{3,}", "\n\n", caption).strip()

    if not caption:
        caption = scholar["name"] if scholar else "Wa'azi da Nasiha"

    # Only append scholar hashtags if the caption does not already contain hashtags
    if "#" not in caption:
        hashtags = (
            scholar.get("hashtags", ["#PrincessOfJannah", "#Sunnah", "#Arewa"])
            if scholar
            else ["#PrincessOfJannah", "#Sunnah", "#Arewa"]
        )
        return f"{caption}\n\n{' '.join(hashtags)}".strip()

    return caption


def download_media_to_path(url: str, output_path: Path) -> bool:
    """
    Downloads a video stream to the specified MP4 output path via yt-dlp.
    Uses ffmpeg (system PATH or imageio_ffmpeg) to merge HD MP4+AAC DASH streams when available.
    """
    output_path.parent.mkdir(parents=True, exist_ok=True)
    target_url = resolve_shared_url(url)
    ffmpeg_bin = find_ffmpeg_location()
    print(f"[*] Downloading short video to: {output_path}")

    if ffmpeg_bin:
        cmd_dl = [
            "yt-dlp",
            "--no-plugin-dirs",
            "--ffmpeg-location", ffmpeg_bin,
            "-f", "bestvideo[height<=720][ext=mp4]+bestaudio[ext=m4a]/bestvideo[height<=720]+bestaudio/best[ext=mp4]/best",
            "--merge-output-format", "mp4",
            "-o", str(output_path),
            "--no-playlist",
            "--no-warnings",
            target_url,
        ]
    else:
        cmd_dl = [
            "yt-dlp",
            "--no-plugin-dirs",
            "-f", "best[ext=mp4]/best",
            "-o", str(output_path),
            "--no-playlist",
            "--no-warnings",
            target_url,
        ]

    try:
        subprocess.run(cmd_dl, check=True)
    except subprocess.CalledProcessError as e:
        print(f"[!] Error downloading video: {e}")
        return False

    if not output_path.exists():
        print(f"[!] Downloaded file not found: {output_path}")
        return False
    return True


def download_video(url, scholar_override=None, is_shared_link=True, allow_duplicate=False):
    scholars = load_scholars()
    target_url = resolve_shared_url(url)

    print(f"[*] Extracting metadata for: {target_url}")
    cmd_meta = [
        "yt-dlp",
        "--no-plugin-dirs",
        "--dump-json",
        "--no-playlist",
        "--no-warnings",
        target_url,
    ]
    try:
        proc = subprocess.run(cmd_meta, capture_output=True, text=True, check=True, encoding="utf-8")
        meta = json.loads(proc.stdout)
    except Exception as e:
        print(f"[!] Error fetching metadata with yt-dlp: {e}")
        return None

    title = meta.get("title", "") or ""
    description = meta.get("description", "") or ""
    duration = meta.get("duration") or 0
    webpage_url = meta.get("webpage_url", target_url)
    source_video_id = str(meta.get("id") or "")

    if not allow_duplicate and is_already_processed(webpage_url, source_video_id):
        print(f"[!] Skipping duplicate video [{source_video_id or webpage_url}] (already queued or published).")
        return None

    if _is_generic(description) and _is_generic(title):
        og_caption = fetch_opengraph_caption(target_url)
        if og_caption:
            description = og_caption
    elif is_shared_link and _is_generic(description):
        og_caption = fetch_opengraph_caption(target_url)
        if og_caption:
            description = og_caption

    # Detect scholar
    scholar = None
    if scholar_override:
        for s in scholars:
            if s["id"] == scholar_override or scholar_override.lower() in s["name"].lower():
                scholar = s
                break
    if not scholar:
        uploader = meta.get("uploader", "") or ""
        scholar = match_scholar(f"{title} {description} {uploader}", scholars)

    unique_id = str(uuid.uuid4())[:8]
    output_filename = f"{scholar['id'] if scholar else 'scholar'}_{unique_id}.mp4"
    output_path = MEDIA_DIR / output_filename

    if not download_media_to_path(target_url, output_path):
        return None

    # Viral Social Media Expert Mastering: 0.0s hook silence trimming + voice clarity EQ & loudness boost
    from viral_growth import build_viral_caption, master_video_for_retention

    audio_mastered = master_video_for_retention(output_path)

    base_caption = clean_caption(title, description, scholar, is_shared_link=is_shared_link)
    if is_shared_link:
        caption = base_caption
    else:
        caption = build_viral_caption(
            raw_title=title if not _is_generic(title) else base_caption,
            scholar=scholar,
            is_shared_link=False,
        )

    item = {
        "id": unique_id,
        "source_video_id": source_video_id,
        "source_url": webpage_url,
        "video_path": str(output_path.resolve()),
        "caption": caption,
        "duration": duration,
        "scholar": scholar["name"] if scholar else "Authentic Islamic Scholar",
        "scholar_id": scholar["id"] if scholar else "unknown",
        "is_shared_link": is_shared_link,
        "audio_mastered": audio_mastered,
        "added_at": now_wat().isoformat(),
        "status": "pending",
    }

    with open(QUEUE_FILE, "r", encoding="utf-8") as f:
        queue = json.load(f)

    queue.append(item)

    with open(QUEUE_FILE, "w", encoding="utf-8") as f:
        json.dump(queue, f, indent=2, ensure_ascii=False)

    from config import sync_state_to_github
    sync_state_to_github(f"Auto: Queue video [{unique_id}] for {item['scholar']} [skip ci]")

    print(f"[+] Successfully queued video [{unique_id}] for {item['scholar']} ({duration}s)!")
    return item


if __name__ == "__main__":
    import sys

    if len(sys.argv) > 1:
        test_url = sys.argv[1]
        scholar_id = sys.argv[2] if len(sys.argv) > 2 else None
        download_video(test_url, scholar_id)
    else:
        print("Usage: python downloader.py <video_or_post_url> [scholar_id]")
