"""YouTube: its listings, its two tabs, and the pages that read them."""

import csv
import io
import os
import json
import re
import subprocess
import time
from urllib.parse import urlparse, urlunparse
from flask import Blueprint, request, jsonify, render_template
import config
from db import connect
from auth import current_user, page_context
from media import is_safe_url, variant_of
from feed import (BUDGETS, follow, followed_count, get_settings, save_settings,
                  upright_clips, register)

bp = Blueprint("youtube", __name__)


def youtube_tab_url(url, tab="videos"):
    """Turn any supported channel URL into one of its tabs.

    A channel home page is itself a playlist of tabs (Videos, Shorts, Live),
    which is what yt-dlp returns when asked for it directly. A tab is the
    chronological list we want instead.
    """
    parsed = urlparse(url)
    host = parsed.hostname or ""
    parts = [part for part in parsed.path.split("/") if part]
    if not (host == "youtube.com" or host.endswith(".youtube.com")):
        return None
    if not parts or (parts[0] != "@" and not parts[0].startswith("@") and
                     parts[0] not in ("channel", "c", "user")):
        return None
    if parts[-1] in ("videos", "shorts", "streams", "live", "featured",
                     "playlists", "community"):
        parts.pop()
    if not parts:
        return None
    return urlunparse(parsed._replace(path="/" + "/".join(parts + [tab]),
                                      query="", fragment=""))


def youtube_videos_url(url):
    return youtube_tab_url(url, "videos")


def parse_ytdlp_lines(stdout):
    """Every JSON object yt-dlp printed, keyed by video id.

    With several URLs on one command line it prints one object per line, so a
    batch of videos costs a single process instead of one each.
    """
    resolved = {}
    for line in stdout.splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            info = json.loads(line)
        except ValueError:
            continue
        if info.get("id"):
            resolved[info["id"]] = info
    return resolved


def resolve_videos(urls):
    if not urls:
        return {}
    cmd = [*config.YTDLP, "--no-playlist", "-j", "--", *urls]
    result = subprocess.run(cmd, capture_output=True, text=True, timeout=120)
    return parse_ytdlp_lines(result.stdout)


def fetch_channel(url, known=None, count=None):
    """Return the newest videos of a channel, dated.

    A flat listing is one quick call but YouTube leaves its entries without any
    date at all, which is what the feed sorts on. So: list flat, then resolve
    only the videos never seen before, which on a refresh is usually none.
    """
    videos_url = youtube_videos_url(url)
    if not videos_url:
        raise ValueError("Please enter a YouTube channel URL")
    cmd = [*config.YTDLP, "--flat-playlist", "--playlist-end", str(count or config.FEED_DEFAULTS["videos"]),
           "-J", "--", videos_url]
    result = subprocess.run(cmd, capture_output=True, text=True, timeout=60)
    if result.returncode != 0:
        raise ValueError(result.stderr.strip().split("\n")[-1])
    info = json.loads(result.stdout)
    channel_id = info.get("channel_id") or info.get("id")
    if not channel_id:
        raise ValueError("Could not identify this YouTube channel")

    known = known or {}
    entries = []
    for entry in info.get("entries") or []:
        video_id = entry.get("id")
        video_url = entry.get("webpage_url") or entry.get("url")
        if video_url and not video_url.startswith("http") and video_id:
            video_url = f"https://www.youtube.com/watch?v={video_id}"
        if video_url:
            entries.append((video_id or "", video_url, entry))

    missing = [url for vid, url, _ in entries if vid not in known]
    resolved = resolve_videos(missing)

    videos = []
    for video_id, video_url, entry in entries:
        seen = known.get(video_id, {})
        full = resolved.get(video_id, {})
        upload_date = full.get("upload_date") or seen.get("upload_date") or ""
        if not upload_date and full.get("timestamp"):
            upload_date = time.strftime("%Y%m%d", time.gmtime(full["timestamp"]))
        videos.append({
            "url": video_url,
            "title": entry.get("title") or full.get("title") or "Untitled",
            # Playlist entries often omit the thumbnail even though YouTube
            # exposes a stable image for every video id.
            "thumbnail": entry.get("thumbnail") or full.get("thumbnail") or (
                f"https://i.ytimg.com/vi/{video_id}/hqdefault.jpg" if video_id else ""
            ),
            "upload_date": upload_date,
            "duration": entry.get("duration") or full.get("duration"),
            "description": full.get("description") or seen.get("description") or "",
            "id": video_id,
        })
    return {
        "channel_id": str(channel_id),
        # Keep the Videos tab for later refreshes; the channel home page would
        # send yt-dlp back to its list of category tabs.
        "channel_url": videos_url,
        "title": info.get("channel") or info.get("uploader") or info.get("title") or url,
        "thumbnail": info.get("channel_thumbnail") or info.get("thumbnail") or "",
        "videos": videos,
    }


def fetch_shorts(url, count):
    """List a channel's shorts, and resolve none of them.

    The listing gives an id, a title and a thumbnail, but no date. For videos
    that is what resolve_videos goes and fetch one by one from the player API,
    the endpoint that answers "not a bot". Shorts do without: the tab is already
    newest first, so the channel's own order replaces a date, and the page never
    touches that endpoint for anything nobody has watched.
    """
    shorts_url = youtube_tab_url(url, "shorts")
    if not shorts_url:
        raise ValueError("Please enter a YouTube channel URL")
    cmd = [*config.YTDLP, "--flat-playlist", "--playlist-end", str(count), "-J", "--", shorts_url]
    result = subprocess.run(cmd, capture_output=True, text=True, timeout=60)
    # A channel with no Shorts tab is not a failure, it simply has none.
    if result.returncode != 0:
        return []
    info = json.loads(result.stdout)
    shorts = []
    for entry in info.get("entries") or []:
        short_id = entry.get("id")
        if not short_id:
            continue
        shorts.append({
            "id": short_id,
            "url": entry.get("webpage_url") or entry.get("url")
            or f"https://www.youtube.com/shorts/{short_id}",
            "title": entry.get("title") or "Untitled",
            "thumbnail": entry.get("thumbnail")
            or f"https://i.ytimg.com/vi/{short_id}/hqdefault.jpg",
        })
    return shorts


def refresh_channel(url, channel_id=None):
    """Look a channel up once, for everyone who follows it.

    The cache is keyed by channel, not by subscriber: with the outbound rate
    capped for the whole platform, storing it per account would have spent that
    budget as many times as there are people following the same channel, which
    in a household is the common case rather than the edge one. It holds the
    instance maximum; each account displays as many as it asked for.
    """
    known = {}
    if channel_id:
        with connect() as conn:
            row = conn.execute("SELECT videos FROM channels WHERE channel_id = ?",
                               (channel_id,)).fetchone()
        if row:
            known = {v["id"]: v for v in json.loads(row["videos"]) if v.get("id")}
    budget = BUDGETS["youtube"]
    with budget.lock:
        budget.last_call = time.time()
        channel = fetch_channel(url, known, config.FEED_VIDEOS_MAX)
    with connect() as conn:
        conn.execute("INSERT INTO channels "
                     "(channel_id, channel_url, title, thumbnail, videos, refreshed_at) "
                     "VALUES (?, ?, ?, ?, ?, ?) "
                     "ON CONFLICT(channel_id) DO UPDATE SET "
                     "channel_url = excluded.channel_url, title = excluded.title, "
                     "thumbnail = excluded.thumbnail, videos = excluded.videos, "
                     "refreshed_at = excluded.refreshed_at",
                     (channel["channel_id"], channel["channel_url"], channel["title"],
                      channel["thumbnail"], json.dumps(channel["videos"]), time.time()))
    return channel


@bp.route("/feed")
def feed_page():
    return render_template("feed.html", page="feed", **page_context())


@bp.route("/api/feed")
def feed():
    owner = current_user()
    settings = get_settings(owner)
    with connect() as conn:
        rows = conn.execute(
            "SELECT c.* FROM channels c JOIN follows f ON f.channel_id = c.channel_id "
            "WHERE f.owner = ? AND c.platform = 'youtube' "
            "ORDER BY c.title COLLATE NOCASE", (owner,)).fetchall()
    # What Play would reuse rather than download, in this account's quality.
    # Files are shared, so a video someone else already fetched is ready here
    # too: saying so is the difference between an instant play and a wait.
    variant = variant_of("video", None, settings["quality"])
    with connect() as conn:
        ready = {r["url"] for r in conn.execute(
            "SELECT url, path FROM entries WHERE variant = ? AND status = 'done' "
            "AND path IS NOT NULL", (variant,)) if os.path.exists(r["path"])}
        # Whose entry it is decides what can be done with it: playing reuses
        # anybody's file, but pinning and deleting only ever touch your own row.
        mine = {r["url"]: {"job_id": r["job_id"], "pinned": bool(r["pinned"])}
                for r in conn.execute(
                    "SELECT url, job_id, pinned, path FROM entries WHERE owner = ? "
                    "AND variant = ? AND status = 'done' AND path IS NOT NULL",
                    (owner, variant)) if os.path.exists(r["path"])}

    channels = []
    videos = []
    for row in rows:
        channel = dict(row)
        # The cache holds the instance maximum; the account's own count is a
        # display choice, so changing it needs no lookup at all.
        channel["videos"] = json.loads(channel["videos"])[:settings["videos"]]
        # When this channel's list was last read, and whether it turned out not
        # to have a Videos tab at all: the list below the feed is the only place
        # that says why a channel shows nothing.
        channel["fetched"] = row["refreshed_at"]
        channel["failed"] = not row["has_videos"]
        channels.append(channel)
        videos.extend({**video, "uploader": row["title"], "channel_id": row["channel_id"],
                       "ready": video["url"] in ready,
                       **mine.get(video["url"], {"job_id": None, "pinned": False})}
                      for video in channel["videos"])
    # YYYYMMDD sorts correctly as a string. Unknown dates naturally sink.
    videos.sort(key=lambda video: video["upload_date"], reverse=True)
    return jsonify({"channels": channels, "videos": videos,
                    "settings": settings,
                    "limits": {"videos_max": config.FEED_VIDEOS_MAX,
                               "qualities": config.FEED_QUALITIES}})


@bp.route("/api/feed/settings", methods=["POST"])
def feed_settings():
    owner = current_user()
    data = request.json or {}
    current = get_settings(owner)
    try:
        saved = save_settings(owner, data.get("videos", current["videos"]),
                              data.get("quality", current["quality"]))
    except (TypeError, ValueError):
        return jsonify({"error": "Invalid settings"}), 400
    return jsonify(saved)


@bp.route("/api/feed/subscriptions", methods=["POST"])
def subscribe():
    owner = current_user()
    url = (request.json or {}).get("url", "").strip()
    if not is_safe_url(url) or not youtube_videos_url(url):
        return jsonify({"error": "Please enter a YouTube channel URL"}), 400
    return follow(owner, url, refresh_channel, "youtube")


@bp.route("/api/feed/import", methods=["POST"])
def import_subscriptions():
    """Take the subscriptions.csv of a YouTube export.

    Nothing is looked up here. The file already carries the id, the URL and the
    title, so a channel is followed at once and left empty; the poller fills it
    in its turn like any other. Looking a hundred channels up on import would be
    a hundred requests to YouTube in one breath, which is exactly what gets an
    address refused.
    """
    owner = current_user()
    text = (request.json or {}).get("csv", "")
    if not isinstance(text, str) or not text.strip():
        return jsonify({"error": "Empty file"}), 400
    if len(text) > config.IMPORT_MAX_BYTES:
        return jsonify({"error": "File too large"}), 400

    with connect() as conn:
        followed = {r["channel_id"] for r in conn.execute(
            "SELECT channel_id FROM follows WHERE owner = ?", (owner,))}
    held = followed_count(owner, "youtube")

    added, already, skipped, full = 0, 0, 0, False
    for row in csv.reader(io.StringIO(text)):
        # The header is localised, so it is recognised by its shape rather than
        # by its wording: a channel id is the only first cell that looks like one.
        if len(row) < 2 or not re.fullmatch(r"UC[\w-]{22}", row[0].strip()):
            continue
        channel_id = row[0].strip()
        url = row[1].strip()
        # A title may hold commas, so it is whatever is left of the line.
        title = ",".join(row[2:]).strip() or channel_id
        if not is_safe_url(url) or not youtube_videos_url(url):
            skipped += 1
            continue
        if channel_id in followed:
            already += 1
            continue
        if held >= config.CHANNELS_MAX["youtube"]:
            full = True
            break
        with connect() as conn:
            # An empty cache dated zero makes the channel the stalest there is,
            # so the poller takes the freshly imported ones first.
            conn.execute("INSERT INTO channels "
                         "(channel_id, channel_url, title, thumbnail, videos, refreshed_at) "
                         "VALUES (?, ?, ?, '', '[]', 0) "
                         "ON CONFLICT(channel_id) DO NOTHING",
                         (channel_id, url, title))
            conn.execute("INSERT OR IGNORE INTO follows (owner, channel_id) VALUES (?, ?)",
                         (owner, channel_id))
        followed.add(channel_id)
        held += 1
        added += 1

    if not (added or already or skipped):
        return jsonify({"error": "No channels found in this file"}), 400
    return jsonify({"added": added, "already": already, "skipped": skipped,
                    "full": full, "limit": config.CHANNELS_MAX["youtube"],
                    "every": config.POLL["youtube"]})


@bp.route("/shorts")
def shorts_page():
    return render_template(
        "vertical.html", page="shorts", heading="Shorts",
        tagline="Shorts from your channels", source="/api/shorts",
        empty_note="Follow channels on the Following page, then wait for their "
                   "shorts to be listed. One comes round every few minutes.",
        **page_context())


@bp.route("/api/shorts")
def shorts_list():
    return jsonify(upright_clips(current_user(), "youtube",
                                 watched=request.args.get("watched") == "1"))


register(
    "youtube",
    label="YouTube",
    noun="Channel",
    add="/api/feed/subscriptions",
    imports="/api/feed/import",
    accept=".csv,text/csv",
    file="subscriptions.csv of a YouTube export",
    hint="Paste a YouTube channel URL\u2026",
    list_upright=fetch_shorts,
    refresh_videos=refresh_channel,
    videos_enabled=config.FEED_ENABLED,
    upright_enabled=config.SHORTS_ENABLED,
)
