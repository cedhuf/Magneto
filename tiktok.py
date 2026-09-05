"""TikTok: its listings and the page that reads them."""

import json
import re
import subprocess
import time
from urllib.parse import urlparse
from flask import Blueprint, request, jsonify, render_template
import config
from db import connect
from auth import current_user, page_context
from media import is_safe_url
from feed import BUDGETS, follow, followed_count, upright_clips, register

bp = Blueprint("tiktok", __name__)


def tiktok_user_url(url):
    """Turn any TikTok URL into the account it belongs to.

    A video URL is /@name/video/123, an account is /@name: pasting either one
    means the same thing, follow this person.
    """
    parsed = urlparse(url)
    host = parsed.hostname or ""
    if not (host == "tiktok.com" or host.endswith(".tiktok.com")):
        return None
    parts = [part for part in parsed.path.split("/") if part]
    if not parts or not parts[0].startswith("@") or len(parts[0]) < 2:
        return None
    return f"https://www.tiktok.com/{parts[0]}"


def fetch_tiktok(url, count):
    """List an account's latest videos, and resolve none of them.

    TikTok gives more in a listing than YouTube does: a duration and a
    timestamp come with it, so nothing has to be looked up one video at a time.
    """
    account_url = tiktok_user_url(url)
    if not account_url:
        raise ValueError("Please enter a TikTok account URL")
    cmd = [*config.YTDLP, "--flat-playlist", "--playlist-end", str(count), "-J", "--", account_url]
    result = subprocess.run(cmd, capture_output=True, text=True, timeout=90)
    if result.returncode != 0:
        raise ValueError(result.stderr.strip().split("\n")[-1])
    info = json.loads(result.stdout)
    videos = []
    for entry in info.get("entries") or []:
        video_id = entry.get("id")
        if not video_id:
            continue
        thumbnails = entry.get("thumbnails") or []
        stamp = entry.get("timestamp")
        videos.append({
            "id": video_id,
            "url": entry.get("url") or f"{account_url}/video/{video_id}",
            "title": entry.get("title") or "Untitled",
            "thumbnail": entry.get("thumbnail")
            or (thumbnails[-1].get("url") if thumbnails else ""),
            "duration": entry.get("duration"),
            "upload_date": time.strftime("%Y%m%d", time.gmtime(stamp)) if stamp else "",
        })
    return {
        "channel_id": f"tiktok:{info.get('id') or info.get('uploader') or account_url}",
        "channel_url": account_url,
        "title": info.get("channel") or info.get("uploader") or info.get("title") or account_url,
        "videos": videos,
    }


def tiktok_channel_id(account_url, minted):
    """Reuse the row an import already made for this account rather than mint a
    second id for it: the import knows the handle, a lookup knows TikTok's own
    id, and the same person must not end up followed twice."""
    with connect() as conn:
        row = conn.execute(
            "SELECT channel_id FROM channels WHERE channel_url = ? AND platform = 'tiktok'",
            (account_url,)).fetchone()
    return row["channel_id"] if row else minted


def follow_tiktok(url):
    """Record a TikTok account, its videos already in the shorts column.

    An upright video is an upright video: putting them where the shorts page
    already looks is what makes one page serve both sources.
    """
    budget = BUDGETS["tiktok"]
    with budget.lock:
        budget.last_call = time.time()
        account = fetch_tiktok(url, config.FEED_VIDEOS_MAX)
    account["channel_id"] = tiktok_channel_id(account["channel_url"], account["channel_id"])
    with connect() as conn:
        conn.execute(
            "INSERT INTO channels (channel_id, channel_url, title, thumbnail, videos, "
            "refreshed_at, shorts, shorts_refreshed_at, platform) "
            "VALUES (?, ?, ?, '', '[]', ?, ?, ?, 'tiktok') "
            "ON CONFLICT(channel_id) DO UPDATE SET title = excluded.title, "
            "shorts = excluded.shorts, shorts_refreshed_at = excluded.shorts_refreshed_at",
            (account["channel_id"], account["channel_url"], account["title"],
             time.time(), json.dumps(account["videos"]), time.time()))
    return account


@bp.route("/api/tiktok/accounts", methods=["POST"])
def add_tiktok_account():
    owner = current_user()
    url = (request.json or {}).get("url", "").strip()
    if not is_safe_url(url) or not tiktok_user_url(url):
        return jsonify({"error": "Please enter a TikTok account URL"}), 400
    return follow(owner, url, follow_tiktok, "tiktok")


@bp.route("/api/tiktok/import", methods=["POST"])
def import_tiktok():
    """Take the handles read out of a TikTok export.

    The file itself never comes here: it carries the account's phone number,
    address and email a couple of keys away from the list of accounts, so the
    page reads it and sends the handles alone. Nothing is looked up either, for
    the same reason the YouTube import looks nothing up: a hundred requests in
    one breath is how an address gets refused.
    """
    owner = current_user()
    names = (request.json or {}).get("accounts")
    if not isinstance(names, list) or not names:
        return jsonify({"error": "No accounts found in this file"}), 400

    with connect() as conn:
        followed = {r["channel_id"] for r in conn.execute(
            "SELECT channel_id FROM follows WHERE owner = ?", (owner,))}
    held = followed_count(owner, "tiktok")

    added, already, skipped, full = 0, 0, 0, False
    for name in names[:1000]:
        if not isinstance(name, str) or not re.fullmatch(r"[A-Za-z0-9._]{1,24}", name):
            skipped += 1
            continue
        url = f"https://www.tiktok.com/@{name}"
        channel_id = tiktok_channel_id(url, f"tiktok:{name}")
        if channel_id in followed:
            already += 1
            continue
        if held >= config.CHANNELS_MAX["tiktok"]:
            full = True
            break
        with connect() as conn:
            # Dated zero, so the poller takes the freshly imported ones first.
            # The handle stands as the title until it does.
            conn.execute(
                "INSERT INTO channels (channel_id, channel_url, title, thumbnail, "
                "videos, refreshed_at, shorts, shorts_refreshed_at, platform) "
                "VALUES (?, ?, ?, '', '[]', 0, '[]', 0, 'tiktok') "
                "ON CONFLICT(channel_id) DO NOTHING", (channel_id, url, f"@{name}"))
            conn.execute("INSERT OR IGNORE INTO follows (owner, channel_id) VALUES (?, ?)",
                         (owner, channel_id))
        followed.add(channel_id)
        held += 1
        added += 1

    if not (added or already or skipped):
        return jsonify({"error": "No accounts found in this file"}), 400
    return jsonify({"added": added, "already": already, "skipped": skipped,
                    "full": full, "limit": config.CHANNELS_MAX["tiktok"],
                    "every": config.POLL["tiktok"]})


@bp.route("/tiktok")
def tiktok_page():
    return render_template(
        "vertical.html", page="tiktok", heading="TikTok",
        tagline="The accounts you follow", source="/api/tiktok",
        empty_note="Add a TikTok account on the Following page. Its latest videos "
                   "are listed shortly after, and fetched only when you watch one.",
        **page_context())


@bp.route("/api/tiktok")
def tiktok_list():
    """The followed accounts and their videos, newest of each in turn."""
    return jsonify(upright_clips(current_user(), "tiktok",
                                 watched=request.args.get("watched") == "1"))


def list_upright(url, count):
    """A TikTok account has no long videos: its listing is the upright one."""
    return fetch_tiktok(url, count)["videos"]


register(
    "tiktok",
    label="TikTok",
    noun="Account",
    add="/api/tiktok/accounts",
    imports="/api/tiktok/import",
    accept=".json,application/json",
    file="user_data_tiktok.json of a TikTok export",
    hint="Paste a TikTok account URL\u2026",
    list_upright=list_upright,
    refresh_videos=None,
    videos_enabled=False,
    upright_enabled=config.TIKTOK_ENABLED,
)
