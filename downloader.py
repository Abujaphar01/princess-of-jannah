import html
import json
import re
import shutil
import subprocess
import urllib.parse
import urllib.request
import uuid
from pathlib import Path
from config import MEDIA_DIR, QUEUE_FILE, HISTORY_FILE, SCHOLARS_FILE, PAGE_ID, PAGE_ACCESS_TOKEN, now_wat

_LIVE_FB_FP_CACHE = {"ts": 0.0, "fps": set()}


def _get_live_facebook_fingerprints() -> set[str]:
    """
    Fetches normalized topic fingerprints of the last 25 live posts on the Facebook Page
    (cached for 10 minutes) so clips already on the page are never re-queued.
    """
    import time
    import requests
    from viral_growth import topic_fingerprint

    now_ts = time.time()
    if now_ts - _LIVE_FB_FP_CACHE["ts"] < 600 and _LIVE_FB_FP_CACHE["fps"]:
        return _LIVE_FB_FP_CACHE["fps"]

    fps = set()
    if PAGE_ID and PAGE_ACCESS_TOKEN and PAGE_ID != "your_page_id_here":
        try:
            r = requests.get(
                f"https://graph.facebook.com/v21.0/{PAGE_ID}/published_posts",
                params={"fields": "id,message", "limit": 25, "access_token": PAGE_ACCESS_TOKEN},
                timeout=12,
            )
            if r.status_code == 200:
                for p in r.json().get("data", []):
                    msg = p.get("message") or ""
                    for line in msg.splitlines():
                        fp = topic_fingerprint(line)
                        if len(fp) >= 8:
                            fps.add(fp)
        except Exception:
            pass
    _LIVE_FB_FP_CACHE["ts"] = now_ts
    _LIVE_FB_FP_CACHE["fps"] = fps
    return fps

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

NATURAL_SHARED_FALLBACKS = [
    "Tunatarwa mai ratsa zuciya ga kowane Musulmi. Allah ya sa mu dace, ya amfane mu.",
    "Nasiha mai matukar amfani a rayuwarmu ta yau da kullum. Allah ya kara mana imani.",
    "Kalmomi masu amfani duniya da lahira. Allah ya ba mu ikon aiki da abin da muka ji.",
    "Wa'azi mai shiga rai da fadakarwa. Allah ya shirye mu bisa tafarkin Sunnah.",
    "Tunatarwa mai muhimmanci ga iyali da al'umma. Allah ya saka da alkhairi.",
    "Ilmantarwa mai amfani ga rayuwar Musulmi. Allah ya kara mana tsoronsa da ikhlasi.",
    "Fadakarwa mai amfani kan gyaran zuciya da mu'amala. Allah ya sa mu rabauta.",
    "Nasiha mai daraja ga masu neman tsira. Allah ya sa mu cika da imani.",
]

COMPETITOR_PROMO_PATTERNS = [
    r"(?im)^.*?\bfollow\s+(?:up|us|me|our\s+page|page|for\s+more)\b.*$",
    r"(?im)^.*?\b(?:like|share)\s+(?:and|&)\s+follow\b.*$",
    r"(?im)^.*?\bsubscribe\s+to\s+(?:our|my|this)\b.*$",
    r"(?im)^.*?\bku\s+biyo\s+shafin.*$",
]


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


def _strip_social_stats_boilerplate(text: str) -> str:
    """
    Strips Facebook/Instagram `<X> views · <Y> reactions | <Author> on Reels` HTML title boilerplate
    when a shared Reel has no real post text, while preserving any real caption segment.
    """
    if not text:
        return ""
    s = text.strip()
    s = re.sub(
        r"^\s*[\d.,]+[KMB]?\s+views\s*(?:[·•|-]\s*[\d.,]+[KMB]?\s+(?:reactions|likes|comments)\s*)?\|\s*",
        "",
        s,
        flags=re.IGNORECASE,
    )
    # If the entire remaining string is just "<Uploader> on Reels", treat as empty boilerplate
    if re.match(r"^[^|\n]{1,60}\s+on\s+reels\s*$", s, flags=re.IGNORECASE):
        return ""
    s = re.sub(r"\s*\|\s*[^|\n]{1,60}\s+on\s+reels\s*$", "", s, flags=re.IGNORECASE)
    return s.strip()


def _is_generic(text: str) -> bool:
    if not text:
        return True
    cleaned = _strip_social_stats_boilerplate(text).lower()
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


def is_already_processed(source_url: str, video_id: str, candidate_title: str = "") -> bool:
    """
    Checks QUEUE_FILE, HISTORY_FILE, AND live Facebook posts by video ID, URL, and
    normalized topic fingerprint so the same lecture clip is never queued twice
    (even when re-uploaded under a different YouTube Short ID).
    """
    from viral_growth import topic_fingerprint

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
    cand_fp = topic_fingerprint(candidate_title) if candidate_title else ""

    for item in records:
        if video_id and item.get("source_video_id") == video_id:
            return True
        item_url = _normalize_url(item.get("source_url") or "")
        if norm_url and item_url and norm_url == item_url:
            return True
        if len(cand_fp) >= 10:
            existing_cap = item.get("caption") or ""
            for line in existing_cap.splitlines():
                ex_fp = topic_fingerprint(line)
                if len(ex_fp) >= 10 and (cand_fp == ex_fp or cand_fp in ex_fp or ex_fp in cand_fp):
                    return True

    if len(cand_fp) >= 10:
        for live_fp in _get_live_facebook_fingerprints():
            if cand_fp == live_fp or cand_fp in live_fp or live_fp in cand_fp:
                return True

    return False


def _sanitize_competitor_promo(text: str) -> str:
    """
    Removes forwarded competitor page CTAs (e.g. 'Follow up <Other Network> for more...')
    while preserving genuine Islamic/Hausa caption lines.
    """
    if not text:
        return ""
    cleaned = text
    for pat in COMPETITOR_PROMO_PATTERNS:
        cleaned = re.sub(pat, "", cleaned)
    cleaned = re.sub(r"\n{3,}", "\n\n", cleaned).strip()
    return cleaned


def clean_caption(raw_title, raw_description, scholar, is_shared_link=True, seed_key: str = ""):
    """
    User directive:
    'Short videos, no need of long caption, If its by shared link, then just use the caption on the shared link'
    Also strips forwarded competitor 'Follow...' promos and enriches emoji-only/empty captions
    with natural Hausa search keywords so Facebook indexes the Reel accurately.
    """
    raw_combined_lower = f"{raw_description or ''} {raw_title or ''}".lower()
    caption = ""
    desc = _sanitize_competitor_promo(_strip_social_stats_boilerplate(raw_description or ""))
    title = _sanitize_competitor_promo(_strip_social_stats_boilerplate(raw_title or ""))

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

    # Count actual alphabetic characters (excluding hashtags) to detect emoji-only or ultra-short captions
    text_no_tags = re.sub(r"#\S+", "", caption).strip()
    alpha_count = sum(1 for c in text_no_tags if c.isalpha())

    seed_num = sum(ord(c) for c in (seed_key or raw_title or raw_description or "poj"))
    fallback_line = NATURAL_SHARED_FALLBACKS[seed_num % len(NATURAL_SHARED_FALLBACKS)]
    if any(k in raw_combined_lower for k in ("dua", "du'a", "addu'a", "zikir", "dhikr", "azkar")):
        fallback_line = "Addu'a da zikiri masu matukar amfani a rayuwar Musulmi. Allah ya karba mana."

    if not caption or alpha_count == 0:
        emoji_prefix = f"{text_no_tags} " if text_no_tags else ""
        if scholar:
            caption = f"{emoji_prefix}Tunatarwa mai amfani daga {scholar['name']}. Allah ya saka da alkhairi, ya sa mu amfana.".strip()
        else:
            caption = f"{emoji_prefix}{fallback_line}".strip()
    elif alpha_count < 16 and is_shared_link:
        # Preserve short human prompt (e.g. 'Saurara Kaji 👂') and add natural Hausa context for search/SEO
        caption = f"{caption}\n\n{fallback_line}"

    # Ensure clean discovery hashtags if none present
    if "#" not in caption:
        hashtags = (
            scholar.get("hashtags", ["#PrincessOfJannah", "#MalumanSunnah", "#Tunatarwa", "#Arewa"])
            if scholar
            else ["#PrincessOfJannah", "#MalumanSunnah", "#Tunatarwa", "#Arewa"]
        )
        return f"{caption}\n\n{' '.join(hashtags[:4])}".strip()

    return caption


def download_media_to_path(url: str, output_path: Path) -> bool:
    """
    Downloads a video stream to the specified MP4 output path via yt-dlp in Full HD (up to 1080p
    for both vertical 9:16 1080x1920 Reels and horizontal 16:9 1920x1080 videos).
    """
    output_path.parent.mkdir(parents=True, exist_ok=True)
    target_url = resolve_shared_url(url)
    ffmpeg_bin = find_ffmpeg_location()
    print(f"[*] Downloading HD video to: {output_path}")

    yt_extra = ["--extractor-args", "youtube:player_client=android_vr,tv,web"] if __import__("os").environ.get("GITHUB_ACTIONS") else []
    hd_format = (
        "bestvideo[width<=1920][height<=1920][vcodec^=avc1][ext=mp4]+bestaudio[ext=m4a]/"
        "bestvideo[width<=1920][height<=1920][ext=mp4]+bestaudio[ext=m4a]/"
        "bestvideo[width<=1920][height<=1920]+bestaudio/"
        "best[width<=1920][height<=1920][ext=mp4]/best[ext=mp4]/best"
    )

    if ffmpeg_bin:
        cmd_dl = [
            "yt-dlp",
            "--no-plugin-dirs",
            *yt_extra,
            "--ffmpeg-location", ffmpeg_bin,
            "-f", hd_format,
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
            *yt_extra,
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

    yt_extra = ["--extractor-args", "youtube:player_client=android_vr,tv,web"] if __import__("os").environ.get("GITHUB_ACTIONS") else []
    print(f"[*] Extracting metadata for: {target_url}")
    cmd_meta = [
        "yt-dlp",
        "--no-plugin-dirs",
        *yt_extra,
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

    if not allow_duplicate and is_already_processed(webpage_url, source_video_id, title):
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

    audio_mastered = master_video_for_retention(output_path, is_shared_link=is_shared_link)

    base_caption = clean_caption(
        title,
        description,
        scholar,
        is_shared_link=is_shared_link,
        seed_key=source_video_id or unique_id,
    )
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
        "video_path": f"media_vault/{output_filename}",
        "caption": caption,
        "duration": duration,
        "scholar": scholar["name"] if scholar else "Authentic Islamic Scholar",
        "scholar_id": scholar["id"] if scholar else "unknown",
        "is_shared_link": is_shared_link,
        "audio_mastered": audio_mastered,
        "hd_v2_mastered": audio_mastered,
        "added_at": now_wat().isoformat(),
        "status": "pending",
    }

    with open(QUEUE_FILE, "r", encoding="utf-8") as f:
        queue = json.load(f)

    if is_shared_link:
        # VIP Priority: insert WhatsApp-shared links BEFORE all auto-discovered items
        insert_idx = 0
        for idx, q in enumerate(queue):
            if q.get("is_shared_link"):
                insert_idx = idx + 1
            else:
                break
        queue.insert(insert_idx, item)
    else:
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
