"""
Princess of Jannah — 24/7 Cloud Dashboard, QR Pairing Server & WAT Auto-Scheduler
Serves:
1. /qr           — Live WhatsApp QR code scanner & connection status
2. /queue        — Live view of pending short videos & published history
3. /bot-logs     — Real-time WhatsApp & Scheduler logs
4. /send-test    — Sends a test message to "Princess of Jannah Posts"
5. /reset-session— Resets WhatsApp credentials for fresh QR pairing
6. Background 3x Daily WAT Auto-Scheduler (06:30, 13:30, 20:30 WAT)
"""

import json
import os
import shutil
import threading
import time
import urllib.parse
from contextlib import asynccontextmanager
from fastapi import FastAPI
from fastapi.responses import HTMLResponse, JSONResponse

from config import (
    QUEUE_FILE,
    HISTORY_FILE,
    POST_TIMES,
    now_wat,
)
from scheduler import auto_post_once, get_queue_status, get_due_or_missed_slot_today
from whatsapp_pipeline import compute_scheduled_slot_for_queue_position
from viral_growth import get_adaptive_wat_schedule, fetch_page_analytics
from reaction_invite_watcher import check_and_trigger_instant_invite

LOG_FILE = "bot.log"
QR_FILE = "qr_code.txt"
STATUS_FILE = "bot_status.txt"
GROUP_JID_FILE = "matched_group_jid.txt"
SEND_QUEUE_FILE = "send_queue.json"


def append_server_log(msg: str):
    ts = now_wat().isoformat()
    line = f"[{ts}] [SCHEDULER] {msg}"
    print(line)
    try:
        with open(LOG_FILE, "a", encoding="utf-8") as f:
            f.write(line + "\n")
    except Exception:
        pass


def background_wat_scheduler():
    """
    Runs 24/7 inside the FastAPI server process, checking WAT time every 25 seconds
    and firing auto_post_once() across the active adaptive WAT slots.
    """
    sched = get_adaptive_wat_schedule()
    active_slots = sched.get("slots", POST_TIMES)
    append_server_log(
        f"Adaptive WAT Auto-Scheduler started ({sched.get('stage_name')}). Target slots: {', '.join(active_slots)} WAT"
    )
    last_posted_slot = None
    last_failed_attempt_ts = 0.0

    while True:
        try:
            active_slots = get_adaptive_wat_schedule().get("slots", POST_TIMES)
            due_slot_key = get_due_or_missed_slot_today(active_slots)

            if due_slot_key and last_posted_slot != due_slot_key and (time.time() - last_failed_attempt_ts) >= 900:
                append_server_log(f"Triggered due/catch-up WAT slot: {due_slot_key}. Publishing next Reel...")
                item = auto_post_once()
                if item:
                    last_posted_slot = due_slot_key
                    last_failed_attempt_ts = 0.0
                    append_server_log(
                        f"Successfully published [{item.get('id')}] ({item.get('scholar')}) -> FB ID: {item.get('fb_video_id')}"
                    )
                else:
                    last_failed_attempt_ts = time.time()
                    append_server_log("Scheduled slot ran, but publication returned None (backing off 15m before retry; check PAGE_ACCESS_TOKEN).")
        except Exception as e:
            append_server_log(f"Scheduler error: {e}")

        time.sleep(25)


def background_reaction_invite_watcher():
    """
    Zero-Token WhatsApp Batch Like-Invite Watcher (polls Meta Graph API every 3 minutes).
    Whenever 10+ new Likes accumulate across Reels, sends a 1-tap WhatsApp alert card!
    """
    append_server_log("Zero-Token WhatsApp Batch Like-Invite Watcher started (alerts at 10+ new Likes).")
    while True:
        try:
            res = check_and_trigger_instant_invite(min_batch_likes=10)
            if res.get("triggered"):
                append_server_log(
                    f"[BATCH-INVITE ALERT] +{res.get('new_likes', 0)} new Likes across {res.get('pending_count')} Reel(s) -> Queued WhatsApp alert!"
                )
        except Exception as e:
            append_server_log(f"Invite watcher error: {e}")
        time.sleep(180)


@asynccontextmanager
async def lifespan(app: FastAPI):
    t = threading.Thread(target=background_wat_scheduler, daemon=True)
    t.start()
    t_inv = threading.Thread(target=background_reaction_invite_watcher, daemon=True)
    t_inv.start()
    yield


app = FastAPI(title="Princess of Jannah 24/7 Cloud Engine", lifespan=lifespan)


def get_bot_status() -> str:
    if os.path.exists(STATUS_FILE):
        try:
            with open(STATUS_FILE, "r", encoding="utf-8") as f:
                return f.read().strip() or "STARTING"
        except Exception:
            pass
    return "STARTING"


def get_matched_group_jid() -> str:
    env_jid = os.environ.get("WHATSAPP_ADMIN_GROUP_ID", "").strip()
    if env_jid:
        return env_jid
    if os.path.exists(GROUP_JID_FILE):
        try:
            with open(GROUP_JID_FILE, "r", encoding="utf-8") as f:
                return f.read().strip()
        except Exception:
            pass
    return ""


@app.api_route("/", methods=["GET", "HEAD"], response_class=HTMLResponse)
def index():
    status = get_bot_status()
    pending_count = get_queue_status()
    next_slot = compute_scheduled_slot_for_queue_position(1)
    sched = get_adaptive_wat_schedule()
    active_slots = sched.get("slots", POST_TIMES)
    wat_now = now_wat().strftime("%Y-%m-%d %I:%M:%S %p WAT")
    status_color = "#4ade80" if status == "CONNECTED" else "#f59e0b"

    return f"""
    <!DOCTYPE html>
    <html>
        <head>
            <meta charset="UTF-8">
            <meta name="viewport" content="width=device-width, initial-scale=1.0">
            <title>Princess of Jannah — 24/7 Cloud Engine</title>
        </head>
        <body style="font-family:sans-serif; text-align:center; padding:40px 15px; background:#0b0f14; color:#eee;">
            <div style="max-width:560px; margin:0 auto; background:#161f28; padding:30px; border-radius:14px; box-shadow:0 4px 24px rgba(0,0,0,0.5);">
                <h2 style="margin:0 0 8px 0; color:#f8fafc;">Princess of Jannah — Viral Growth Engine</h2>
                <p style="color:#94a3b8; font-size:13px; margin:0 0 20px 0;">WhatsApp Group: <b>Princess of Jannah Posts</b></p>

                <div style="background:#0f172a; padding:16px; border-radius:10px; text-align:left; font-size:14px; line-height:1.8; margin-bottom:24px;">
                    <div>• <b>WhatsApp Status:</b> <span style="color:{status_color}; font-weight:bold;">{status}</span></div>
                    <div>• <b>Growth Stage:</b> <span style="color:#38bdf8;">{sched.get('stage_name')}</span> ({sched.get('followers_count', 0)} followers)</div>
                    <div>• <b>Current WAT Time:</b> {wat_now}</div>
                    <div>• <b>Pending Videos in Queue:</b> {pending_count}</div>
                    <div>• <b>Next Auto-Publish Slot:</b> {next_slot}</div>
                    <div>• <b>Daily WAT Windows ({len(active_slots)}x):</b> {', '.join(active_slots)} WAT</div>
                </div>

                <div style="display:flex; flex-wrap:wrap; gap:10px; justify-content:center;">
                    <a href="/qr" style="color:#0b0f14; background:#4ade80; text-decoration:none; font-weight:bold; padding:10px 18px; border-radius:8px; font-size:14px;">WhatsApp QR / Status</a>
                    <a href="/analytics" style="color:#0b0f14; background:#38bdf8; text-decoration:none; font-weight:bold; padding:10px 18px; border-radius:8px; font-size:14px;">Growth &amp; Analytics</a>
                    <a href="/queue" style="color:#eee; background:#1e293b; border:1px solid #334155; text-decoration:none; font-weight:bold; padding:10px 18px; border-radius:8px; font-size:14px;">View Video Queue</a>
                    <a href="/bot-logs" style="color:#eee; background:#1e293b; border:1px solid #334155; text-decoration:none; font-weight:bold; padding:10px 18px; border-radius:8px; font-size:14px;">Live Bot Logs</a>
                    <a href="/send-test" style="color:#38bdf8; background:#0f172a; border:1px solid #38bdf8; text-decoration:none; font-weight:bold; padding:10px 18px; border-radius:8px; font-size:14px;">Send Group Test</a>
                </div>
            </div>
        </body>
    </html>
    """


@app.get("/analytics", response_class=HTMLResponse)
def view_analytics():
    data = fetch_page_analytics()
    sched = data["schedule"]
    totals = data["totals"]

    reel_rows = ""
    for idx, r in enumerate(data["reels"], 1):
        reel_rows += f"""
        <tr style="border-bottom:1px solid #1e293b;">
            <td style="padding:10px;">#{idx} (<code>{r['video_id']}</code>)</td>
            <td style="padding:10px;">{r['scholar']}</td>
            <td style="padding:10px;">{r['duration']}s</td>
            <td style="padding:10px; color:#4ade80;">{r['status'].upper()}</td>
            <td style="padding:10px;">{r['views']}</td>
            <td style="padding:10px;">{r['likes']}</td>
            <td style="padding:10px;">{r['comments']}</td>
            <td style="padding:10px;"><a href="{r['permalink']}" target="_blank" style="color:#38bdf8;">Watch Reel &rarr;</a></td>
        </tr>
        """

    if not reel_rows:
        reel_rows = "<tr><td colspan='8' style='padding:20px; text-align:center; color:#94a3b8;'>No published reels recorded yet.</td></tr>"

    return f"""
    <!DOCTYPE html>
    <html>
        <head>
            <meta charset="UTF-8">
            <meta name="viewport" content="width=device-width, initial-scale=1.0">
            <title>Viral Growth &amp; Analytics — Princess of Jannah</title>
        </head>
        <body style="font-family:sans-serif; padding:30px 15px; background:#0b0f14; color:#eee;">
            <div style="max-width:960px; margin:0 auto; background:#161f28; padding:25px; border-radius:12px;">
                <h2 style="margin-top:0;">Facebook Page Growth &amp; Reels Analytics</h2>
                <div style="background:#0f172a; padding:16px; border-radius:10px; font-size:14px; line-height:1.8; margin-bottom:24px;">
                    <div>• <b>Page:</b> {sched['page_name']} (ID: <code>{sched['page_id']}</code>)</div>
                    <div>• <b>Followers:</b> {sched['followers_count']}</div>
                    <div>• <b>Active Growth Stage:</b> <span style="color:#4ade80; font-weight:bold;">{sched['stage_name']}</span></div>
                    <div>• <b>Adaptive Daily Velocity:</b> {sched['posts_per_day']} Reels/day ({', '.join(sched['slots_12h'])} WAT)</div>
                    <div>• <b>Total Published:</b> {data['total_published']} | <b>Pending in Queue:</b> {data['pending_in_queue']}</div>
                    <div>• <b>Cumulative Engagement:</b> {totals['views']} Views | {totals['likes']} Likes | {totals['comments']} Comments</div>
                </div>
                <table style="width:100%; border-collapse:collapse; font-size:13px; text-align:left;">
                    <thead>
                        <tr style="background:#0f172a; color:#94a3b8;">
                            <th style="padding:10px;">Reel ID</th>
                            <th style="padding:10px;">Scholar</th>
                            <th style="padding:10px;">Length</th>
                            <th style="padding:10px;">Status</th>
                            <th style="padding:10px;">Views</th>
                            <th style="padding:10px;">Likes</th>
                            <th style="padding:10px;">Comments</th>
                            <th style="padding:10px;">Link</th>
                        </tr>
                    </thead>
                    <tbody>{reel_rows}</tbody>
                </table>
                <p style="margin-top:20px;"><a href="/" style="color:#38bdf8; text-decoration:none;">&larr; Back to Dashboard</a></p>
            </div>
        </body>
    </html>
    """


@app.api_route("/health", methods=["GET", "HEAD"])
def health():
    return {
        "status": "ok",
        "service": "Princess of Jannah Cloud Engine",
        "whatsapp_status": get_bot_status(),
        "pending_queue": get_queue_status(),
        "wat_time": now_wat().isoformat(),
    }


@app.get("/qr", response_class=HTMLResponse)
def view_qr():
    status = get_bot_status()
    group_jid = get_matched_group_jid()

    if status == "CONNECTED":
        group_line = (
            f"<p style='color:#4ade80; font-size:13px;'>Locked Group JID: <code>{group_jid}</code></p>"
            if group_jid
            else "<p style='color:#f59e0b; font-size:13px;'>Listening for group: <b>Princess of Jannah Posts</b></p>"
        )
        return f"""
        <!DOCTYPE html>
        <html>
            <head>
                <meta charset="UTF-8">
                <meta name="viewport" content="width=device-width, initial-scale=1.0">
                <title>WhatsApp Bot — Connected</title>
            </head>
            <body style="font-family:sans-serif; text-align:center; padding:40px 15px; background:#0b0f14; color:#eee;">
                <div style="max-width:420px; margin:0 auto; background:#161f28; padding:30px; border-radius:12px; box-shadow:0 4px 20px rgba(0,0,0,0.5);">
                    <div style="font-size:48px; margin-bottom:15px;">✅</div>
                    <h2 style="color:#4ade80; margin:0 0 10px 0;">WhatsApp Bot is Connected!</h2>
                    <p style="color:#cbd5e1; font-size:14px; line-height:1.5;">Active 24/7 in the <b>Princess of Jannah Posts</b> group.</p>
                    {group_line}
                    <p style="margin-top:20px;"><a href="/" style="color:#38bdf8; text-decoration:none;">&larr; Back to Dashboard</a></p>
                </div>
            </body>
        </html>
        """

    if os.path.exists(QR_FILE):
        try:
            with open(QR_FILE, "r", encoding="utf-8") as f:
                qr_data = f.read().strip()
            if qr_data:
                encoded = urllib.parse.quote(qr_data)
                qr_img_url = f"https://api.qrserver.com/v1/create-qr-code/?size=320x320&data={encoded}"
                return f"""
                <!DOCTYPE html>
                <html>
                    <head>
                        <meta charset="UTF-8">
                        <meta name="viewport" content="width=device-width, initial-scale=1.0">
                        <meta http-equiv="refresh" content="12">
                        <title>Scan QR — Princess of Jannah</title>
                    </head>
                    <body style="font-family:sans-serif; text-align:center; padding:30px 15px; background:#0b0f14; color:#eee;">
                        <div style="max-width:420px; margin:0 auto; background:#161f28; padding:25px; border-radius:12px; box-shadow:0 4px 20px rgba(0,0,0,0.5);">
                            <h2 style="margin:0 0 10px 0; font-size:20px;">Scan to Link WhatsApp</h2>
                            <p style="color:#94a3b8; font-size:13px; margin:0 0 20px 0;">Open WhatsApp &gt; Linked Devices &gt; Link a Device</p>
                            <div style="background:#fff; display:inline-block; padding:15px; border-radius:12px;">
                                <img src="{qr_img_url}" width="280" height="280" alt="WhatsApp QR Code"/>
                            </div>
                            <p style="color:#64748b; font-size:12px; margin-top:20px;">Refreshing automatically every 12 seconds...</p>
                        </div>
                    </body>
                </html>
                """
        except Exception:
            pass

    return """
    <!DOCTYPE html>
    <html>
        <head>
            <meta charset="UTF-8">
            <meta name="viewport" content="width=device-width, initial-scale=1.0">
            <meta http-equiv="refresh" content="5">
            <title>Starting WhatsApp Bot...</title>
        </head>
        <body style="font-family:sans-serif; text-align:center; padding:50px 15px; background:#0b0f14; color:#eee;">
            <h2>WhatsApp Bot Initializing...</h2>
            <p style="color:#94a3b8;">Generating QR code or syncing session credentials. Please wait 5 seconds...</p>
        </body>
    </html>
    """


@app.get("/queue", response_class=HTMLResponse)
def view_queue():
    try:
        with open(QUEUE_FILE, "r", encoding="utf-8") as f:
            queue = json.load(f)
    except Exception:
        queue = []

    rows = ""
    for idx, item in enumerate(queue, 1):
        slot_str = compute_scheduled_slot_for_queue_position(idx)
        cap = (item.get("caption") or "").split("\n")[0][:90]
        rows += f"""
        <tr style="border-bottom:1px solid #1e293b;">
            <td style="padding:10px;">#{idx} (<code>{item.get('id')}</code>)</td>
            <td style="padding:10px;">{item.get('scholar')}</td>
            <td style="padding:10px;">{item.get('duration', 0)}s</td>
            <td style="padding:10px;">{cap}</td>
            <td style="padding:10px; color:#4ade80;">{slot_str}</td>
        </tr>
        """

    if not rows:
        rows = "<tr><td colspan='5' style='padding:20px; text-align:center; color:#94a3b8;'>Queue is empty — will auto-refill at next WAT slot or when a link is shared in WhatsApp.</td></tr>"

    return f"""
    <!DOCTYPE html>
    <html>
        <head>
            <meta charset="UTF-8">
            <meta name="viewport" content="width=device-width, initial-scale=1.0">
            <title>Publication Queue — Princess of Jannah</title>
        </head>
        <body style="font-family:sans-serif; padding:30px 15px; background:#0b0f14; color:#eee;">
            <div style="max-width:900px; margin:0 auto; background:#161f28; padding:25px; border-radius:12px;">
                <h2 style="margin-top:0;">Upcoming Publication Queue ({len(queue)} Videos)</h2>
                <table style="width:100%; border-collapse:collapse; font-size:13px; text-align:left;">
                    <thead>
                        <tr style="background:#0f172a; color:#94a3b8;">
                            <th style="padding:10px;">Slot</th>
                            <th style="padding:10px;">Scholar</th>
                            <th style="padding:10px;">Length</th>
                            <th style="padding:10px;">Caption</th>
                            <th style="padding:10px;">Scheduled WAT Time</th>
                        </tr>
                    </thead>
                    <tbody>{rows}</tbody>
                </table>
                <p style="margin-top:20px;"><a href="/" style="color:#38bdf8; text-decoration:none;">&larr; Back to Dashboard</a></p>
            </div>
        </body>
    </html>
    """


@app.get("/bot-logs", response_class=HTMLResponse)
def view_bot_logs():
    if os.path.exists(LOG_FILE):
        try:
            with open(LOG_FILE, "r", encoding="utf-8", errors="ignore") as f:
                lines = f.readlines()
            content = "".join(lines[-120:])
            return f"""
            <!DOCTYPE html>
            <html>
                <head>
                    <meta charset="UTF-8">
                    <meta name="viewport" content="width=device-width, initial-scale=1.0">
                    <meta http-equiv="refresh" content="5">
                    <title>Live Bot &amp; Scheduler Logs</title>
                </head>
                <body style="background:#0b0f14; color:#4ade80; padding:20px; font-family:monospace; font-size:12px;">
                    <h3>=== PRINCESS OF JANNAH LIVE LOGS (Auto-refresh 5s) ===</h3>
                    <p><a href="/" style="color:#38bdf8;">&larr; Dashboard</a></p>
                    <pre style="white-space:pre-wrap; word-break:break-all;">{content}</pre>
                </body>
            </html>
            """
        except Exception as e:
            return f"<pre>Error: {e}</pre>"
    return "<pre>No bot logs recorded yet.</pre>"


@app.get("/send-test", response_class=HTMLResponse)
def trigger_send_test():
    target_jid = get_matched_group_jid()
    if not target_jid:
        return """
        <html>
            <body style="font-family:sans-serif; text-align:center; padding:50px; background:#0b0f14; color:#eee;">
                <h2 style="color:#f59e0b;">⚠️ Group JID Not Discovered Yet</h2>
                <p>Ensure the WhatsApp account is paired at <a href="/qr" style="color:#4ade80;">/qr</a> and is a member of <b>Princess of Jannah Posts</b> (or send "PING" inside the group once).</p>
                <p><a href="/" style="color:#38bdf8;">&larr; Back to Dashboard</a></p>
            </body>
        </html>
        """

    msg_item = {
        "to": target_jid,
        "text": (
            "*PRINCESS OF JANNAH — CLOUD TEST*\n\n"
            "Assalamu Alaikum!\n"
            "Wannan sakon gwaji ne kai tsaye daga Princess of Jannah 24/7 Server.\n"
            "Bot yana aiki 100% a cikin rukunin *Princess of Jannah Posts*!"
        ),
    }

    current = []
    if os.path.exists(SEND_QUEUE_FILE):
        try:
            with open(SEND_QUEUE_FILE, "r", encoding="utf-8") as f:
                current = json.load(f)
        except Exception:
            current = []
    current.append(msg_item)
    with open(SEND_QUEUE_FILE, "w", encoding="utf-8") as f:
        json.dump(current, f)

    return """
    <!DOCTYPE html>
    <html>
        <head><meta charset="UTF-8"><title>Test Message Queued</title></head>
        <body style="font-family:sans-serif; text-align:center; padding:50px 15px; background:#0b0f14; color:#eee;">
            <div style="max-width:400px; margin:0 auto; background:#161f28; padding:30px; border-radius:12px;">
                <h2 style="color:#4ade80;">✅ Test Message Queued!</h2>
                <p style="color:#94a3b8; font-size:14px;">The message will be delivered to <b>Princess of Jannah Posts</b> in ~2 seconds.</p>
                <p style="margin-top:20px;"><a href="/bot-logs" style="color:#38bdf8; text-decoration:none;">View Live Bot Logs &rarr;</a></p>
            </div>
        </body>
    </html>
    """


@app.get("/reset-session", response_class=HTMLResponse)
def reset_session_endpoint():
    auth_dir = "auth_info_baileys"
    if os.path.exists(auth_dir):
        try:
            shutil.rmtree(auth_dir)
        except Exception:
            pass
    for f in [QR_FILE, STATUS_FILE, SEND_QUEUE_FILE, GROUP_JID_FILE]:
        if os.path.exists(f):
            try:
                os.remove(f)
            except Exception:
                pass

    threading.Timer(0.5, lambda: os._exit(0)).start()

    return """
    <!DOCTYPE html>
    <html>
        <head>
            <meta http-equiv="refresh" content="6; url=/qr">
            <title>Resetting Session...</title>
        </head>
        <body style="font-family:sans-serif; text-align:center; padding:50px 15px; background:#0b0f14; color:#eee;">
            <div style="max-width:400px; margin:0 auto; background:#161f28; padding:30px; border-radius:12px;">
                <h2 style="color:#f59e0b;">🔄 Session Reset</h2>
                <p style="color:#cbd5e1; font-size:14px;">Clearing old session credentials and generating a fresh QR code...</p>
                <p style="color:#94a3b8; font-size:12px;">Redirecting you to /qr in 6 seconds...</p>
            </div>
        </body>
    </html>
    """


if __name__ == "__main__":
    import uvicorn

    port = int(os.environ.get("PORT", 7860))
    uvicorn.run(app, host="0.0.0.0", port=port)
