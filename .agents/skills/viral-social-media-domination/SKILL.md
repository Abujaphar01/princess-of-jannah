---
name: viral-social-media-domination
description: >-
  Elite algorithmic growth, short-video retention mastering, Hausa/Islamic viral
  hook engineering, adaptive page-stage cadence scaling, and closed-loop Meta
  Graph API analytics for dominating Facebook Reels, YouTube Shorts, TikTok, and
  Instagram in Northern Nigeria and global Muslim markets.
---

# Viral Social Media & Short-Video Domination Skill

This skill synthesizes the highest-performing growth mechanics from **The Agency's** open-source marketing division (`marketing-douyin-strategist`, `marketing-tiktok-strategist`, `marketing-video-optimization-specialist`, `marketing-short-video-editing-coach`, `marketing-growth-hacker`, `marketing-social-media-strategist`) alongside our specialized production skills (`quran-viral-reels` and `abu_jaaphar_car_reels`).

## Dependencies & Referenced Skills
- **`quran-viral-reels`**: Rotating caption archetypes, `@followers` + Arewa regional discovery tags, and strict never-delete policy.
- **`abu_jaaphar_car_reels`**: Mobile screen truncation shield, authentic Hausa curiosity hooks, and 100% Halal audio standards.
- **`agency-growth-marketing`** & **`agency-video-producer`**: Pattern interrupts, 3-second retention hooks, and closed-loop funnel optimization.

---

## 1. Algorithmic Priority Hierarchy (Reels / Shorts / TikTok)

Modern short-video recommendation engines rank and distribute videos to non-followers in this exact priority order:

1. **3-Second Hook Retention Rate (`> 70%` target):** Did the viewer stop scrolling in the first 1.5–3.0 seconds?
2. **Average Watch Time & Completion Rate (`> 45%` for 60s clips, `> 75%` for 30s clips):** Did they watch to the end or loop?
3. **Share & Send Velocity:** How many viewers forwarded the clip to WhatsApp groups, friends, or family?
4. **Save / Bookmark Rate:** Is the knowledge valuable enough to save for later reference?
5. **Organic Comment & Reaction Rate:** Natural viewer reflections and prayers.

---

## 2. FFmpeg 0.0s Hook, Anti-Duplicate Reframing & Voice Clarity Mastering

Many raw lecture recordings suffer from 1–3 seconds of dead silence at the beginning or muffled microphone audio, while re-shared social videos carry hidden platform metadata and raw frame hashes (`vPDQ`) or blurry `360p` vertical streams (`height<=720` bug). Every video must pass through automated pre-publish HD mastering (`width<=1920, height<=1920` Full HD download + FFmpeg pass):

```bash
ffmpeg -y -i input.mp4 -map_metadata -1 -map_chapters -1 \
  -vf "crop=trunc(iw*0.96/2)*2:trunc(ih*0.96/2)*2:(iw-trunc(iw*0.96/2)*2)/2:(ih-trunc(ih*0.96/2)*2)/2,scale=720:1280:flags=lanczos,unsharp=3:3:0.3:3:3:0.0,eq=contrast=1.03:saturation=1.05:brightness=0.005,format=yuv420p" \
  -af "silenceremove=start_periods=1:start_duration=0.05:start_threshold=-42dB,highpass=f=85,equalizer=f=3000:width_type=h:width=1000:g=2,dynaudnorm=f=150:g=15,atempo=1.015" \
  -c:v libx264 -preset veryfast -crf 22 -c:a aac -b:a 192k -movflags +faststart output.mp4
```

- **Metadata & Chapter Strip (`-map_metadata -1 -map_chapters -1`):** Wipes hidden social-platform trace headers.
- **Anti-Duplicate Visual Reframing (`crop` + Lanczos `720p–1080p` HD + `eq`):** Shifts spatial macroblocks by 4% and guarantees crisp vertical HD (`720x1280` / `1080x1920`) without cutting video duration.
- **Leading Dead-Air Removal (`silenceremove`):** Strips opening silence so the scholar's voice hits immediately at `0.0s`.
- **Low-End Rumble Cut (`highpass=f=85`):** Removes microphone stand hum, AC noise, and wind rumble below 85Hz.
- **Vocal Presence Boost (`equalizer=f=3000:g=2`) & Loudness (`dynaudnorm`):** Boosts 3kHz speech intelligibility and normalizes archival audio cleanly.

---

## 3. Natural Human Hausa Copywriting & Anti-Repetition Standard

### Shared Link / Direct Upload Rule
- **Direct Shared Links / Manual Uploads:** If a video is ingested from a shared link or WhatsApp upload with an existing meaningful caption, **preserve that original human caption verbatim**.

### Autonomously Discovered Clips (100% Human, Zero Robotic Phrasing)
Never write stiff, AI-translated clickbait or form-field labels (`Maudu'i:`, `Kan Maudu'in:`, `Daga bakin:`, `Darasi:`), never use AI em-dashes (`—`), never leave raw YouTube brackets/pipes (`[[...]]`, `||`), and never repeat the scholar's name twice in the same caption.

1. **Lead Directly With the Real Topic:** Clean raw YouTube noise (`[[...]]`, `|| Channel`, `#shorts`, ALL-CAPS shouting, and duplicate scholar names) so the very first line states the real subject naturally in everyday Hausa.
2. **Natural Attribution & Varied Du'a:** Mention the scholar once (prefixing deceased scholars with `Marigayi` and pairing with rahama du'as; living scholars with varied health/alkhairi du'as) across 6+ natural human phrasing patterns.
3. **Clean Minimal Hashtags (Max 3–4, Deduplicated):** Keep hashtags concise (`#PrincessOfJannah`, `#ScholarTag`, `#MalumanSunnah`)—never dump 10 city tags or repeat the same hashtag twice.
4. **Triple-Layer Anti-Repetition Shield:**
   - Deduplicate at discovery (`discover.py` / `downloader.py`) by `source_video_id`, normalized URL, AND **topic fingerprint** (preventing re-uploads of the same lecture from different YouTube channels).
   - Verify live `/{PAGE_ID}/published_posts` via Meta Graph API right before upload (`publisher.py`) so an already-live clip can never be uploaded twice.
   - Enforce GitHub Actions `concurrency` + `git pull --rebase --autostash` before every push so cloud state never drifts.

---

## 5. Adaptive Page-Stage Velocity Engine

Never use a rigid one-size-fits-all posting frequency. A brand-new 0-follower page that dumps 7–10 posts on Day 1 risks triggering Meta's anti-spam throttle or splitting its initial seed impression pool. Scale velocity dynamically based on the page's live Graph API follower count:

| Stage | Follower Range | Daily Velocity | Target WAT Slots (`UTC+1`) | Strategic Rationale |
| :--- | :--- | :--- | :--- | :--- |
| **Stage 1: Incubation & Trust** | `0 – 499` | **4 Reels / Day** | `06:30`, `13:30`, `17:30`, `20:30` | 4–6 hour seed windows; builds high completion rate & trains Meta's topic graph safely. |
| **Stage 2: Momentum & Expansion** | `500 – 4,999` | **5 Reels / Day** | `05:30`, `09:30`, `13:30`, `17:30`, `21:00` | Captures Fajr, morning commute, post-Dhuhr, Asr transit, and night peak. |
| **Stage 3: Viral Authority** | `5,000+` | **7 Reels / Day** | `01:15`, `05:30`, `08:30`, `11:45`, `14:45`, `18:00`, `21:15` | Full 24-hour dominance including Tahajjud/global diaspora slots. |

---

## 6. Strict Operational Guardrails

1. **Zero Auto-Comments on Reels:** Do not auto-post comments under published Reels. Keep all engagement invitations inside the video and caption packaging.
2. **Strict Never-Delete Policy:** Never delete a published Reel from the Facebook Page unless explicitly ordered by the user. Low initial views often spike 48–72 hours later when the algorithm finds the right audience cluster.
3. **100% Halal Audio:** Never overlay musical instruments onto scholar clips. Preserve the pure, authoritative voice of the scholar.
4. **Fair 10-Scholar Rotation + Winner Feedback:** Rotate fairly across all 10 Northern Nigerian Sunnah scholars while tracking Meta Graph API performance metrics (`views`, `likes`, `comments`, `shares`) to identify top-performing topics.

---

## 7. Quick Start Commands (`Princess of Jannah` Engine)

```bash
# View live Facebook Page stage, follower count, and Reel performance analytics
python engine.py analytics

# Upgrade all pending videos in data/queue.json (FFmpeg 0.0s hook mastering + viral captions)
python engine.py optimize-queue

# Run standalone viral growth diagnostics
python viral_growth.py --report
```
