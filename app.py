import io
import os
import re
import csv
import time
import uuid
import glob
import json
import shutil
import sqlite3
import subprocess
import threading
from urllib.parse import urlparse, urlunparse
from flask import Flask, request, jsonify, send_file, render_template, abort

app = Flask(__name__)
DOWNLOAD_DIR = os.path.join(os.path.dirname(__file__), "downloads")
DATA_DIR = os.path.join(os.path.dirname(__file__), "data")
os.makedirs(DOWNLOAD_DIR, exist_ok=True)
os.makedirs(DATA_DIR, exist_ok=True)

DB_PATH = os.environ.get("RECLIP_DB", os.path.join(DATA_DIR, "reclip.db"))
RETENTION = int(os.environ.get("RECLIP_RETENTION", 24 * 3600))
# A 1440p film over a domestic line does not fit in five minutes, which is what
# the upstream default allowed. The download runs in its own thread, so this
# does not tie up a gunicorn worker.
DOWNLOAD_TIMEOUT = int(os.environ.get("RECLIP_DOWNLOAD_TIMEOUT", 20 * 60))
# A playlist expansion costs one yt-dlp process per entry afterwards, so an
# uncapped one is a way to bring the server down by pasting a link.
PLAYLIST_MAX = int(os.environ.get("RECLIP_PLAYLIST_MAX", 50))
# Ceiling for the per-user setting, not the setting itself. The feed is what is
# new, not an archive, and every extra video is fetched, stored and rendered for
# every channel a user follows.
FEED_VIDEOS_MAX = int(os.environ.get("RECLIP_FEED_VIDEOS", 5))
FEED_DEFAULTS = {"videos": 3, "quality": 720}
FEED_QUALITIES = [360, 480, 720, 1080, 1440]
# YouTube bans by IP, and every subscription of every user leaves from the same
# one. So the guard rails are instance-wide, never per account: one channel
# refreshed at a time, at most one every FEED_POLL seconds, and only when its
# cached copy is older than FEED_TTL.
FEED_POLL = int(os.environ.get("RECLIP_FEED_POLL", 300))
FEED_TTL = int(os.environ.get("RECLIP_FEED_TTL", 6 * 3600))
FEED_COOLDOWN = int(os.environ.get("RECLIP_FEED_COOLDOWN", 600))
FEED_CHANNELS_MAX = int(os.environ.get("RECLIP_FEED_CHANNELS_MAX", 30))
# Both off unless asked for: they are the only parts of the app that talk to
# YouTube on their own, and an instance that only downloads what it is given
# should not be doing that in the background.
def enabled(name):
    return os.environ.get(name, "0") not in ("0", "false", "no", "")


FEED_ENABLED = enabled("RECLIP_FEED")
# Shorts come from the channels followed on the feed page, so there is nothing
# to show without it.
SHORTS_ENABLED = FEED_ENABLED and enabled("RECLIP_SHORTS")
# A short is downloaded when it is watched and needed only for that. An hour
# outlives a session and nothing more.
SHORTS_RETENTION = int(os.environ.get("RECLIP_SHORTS_RETENTION", 3600))
# TikTok accounts are followed like channels and read on the shorts page: it is
# the same thing, an upright video watched once.
TIKTOK_ENABLED = SHORTS_ENABLED and enabled("RECLIP_TIKTOK")
# A pin does not exempt a file, it moves its deadline within a limit the admin
# still owns. Otherwise the disk stops being bounded.
PIN_RETENTION = int(os.environ.get("RECLIP_PIN_RETENTION", 30 * 24 * 3600))
HISTORY_MAX = int(os.environ.get("RECLIP_HISTORY_MAX", 200))
SWEEP_INTERVAL = 60

# YouTube judges an IPv6 prefix on the whole neighbourhood behind it, so a host
# that has never asked for anything is refused with "Sign in to confirm you're
# not a bot" while the same request over v4, from the same machine, goes
# through. Set RECLIP_FORCE_IPV4=0 on a host that has no v4 route at all.
# A subscriptions export is a few kilobytes; anything far past that is not one.
IMPORT_MAX_BYTES = 2 * 1024 * 1024

FORCE_IPV4 = os.environ.get("RECLIP_FORCE_IPV4", "1") not in ("0", "false", "no", "")
# Every invocation starts from here, so the flag cannot be forgotten on one.
YTDLP = ["yt-dlp"] + (["--force-ipv4"] if FORCE_IPV4 else [])

# "proxy" reads the identity a forward_auth proxy puts in front of us. Anything
# else means a single implicit user. The switch is explicit on purpose: falling
# back to that user when the header is merely missing would silently merge every
# account on a shared instance the day the proxy is misconfigured.
AUTH_MODE = os.environ.get("RECLIP_AUTH", "none")
ADMIN_GROUP = os.environ.get("RECLIP_ADMIN_GROUP", "admin")
# The session belongs to the proxy, so signing out is a link to it, not
# something this app can do. Empty means no button.
LOGOUT_URL = os.environ.get("RECLIP_LOGOUT_URL", "")
SOLO_USER = "local"


def connect():
    conn = sqlite3.connect(DB_PATH, timeout=10)
    conn.row_factory = sqlite3.Row
    # WAL so the sweep thread and request threads do not block each other.
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA busy_timeout=5000")
    return conn


# Append only. A version number is a position in this list, so inserting one in
# the middle rewrites the past of every database already migrated: it replays a
# different script under a number they have already recorded. Adding settings
# above subscriptions did exactly that and crashed the container on import.
MIGRATIONS = [
    """
    CREATE TABLE entries (
        job_id     TEXT PRIMARY KEY,
        owner      TEXT NOT NULL,
        url        TEXT NOT NULL,
        title      TEXT,
        thumbnail  TEXT,
        format     TEXT,
        format_id  TEXT,
        filename   TEXT,
        path       TEXT,
        status     TEXT NOT NULL,
        error      TEXT,
        created_at REAL NOT NULL
    );
    CREATE INDEX entries_owner ON entries (owner, created_at DESC);
    """,
    """
    ALTER TABLE entries ADD COLUMN pinned INTEGER NOT NULL DEFAULT 0;
    """,
    """
    ALTER TABLE entries ADD COLUMN formats TEXT;
    """,
    """
    ALTER TABLE entries ADD COLUMN uploader TEXT;
    ALTER TABLE entries ADD COLUMN duration REAL;
    """,
    """
    ALTER TABLE entries ADD COLUMN description TEXT;
    ALTER TABLE entries ADD COLUMN upload_date TEXT;
    """,
    """
    CREATE TABLE subscriptions (
        owner        TEXT NOT NULL,
        channel_id   TEXT NOT NULL,
        channel_url  TEXT NOT NULL,
        title        TEXT,
        thumbnail    TEXT,
        videos       TEXT NOT NULL DEFAULT '[]',
        refreshed_at REAL NOT NULL DEFAULT 0,
        PRIMARY KEY (owner, channel_id)
    );
    """,
    """
    CREATE TABLE settings (
        owner        TEXT PRIMARY KEY,
        feed_videos  INTEGER NOT NULL,
        feed_quality INTEGER NOT NULL
    );
    """,
    """
    CREATE TABLE channels (
        channel_id   TEXT PRIMARY KEY,
        channel_url  TEXT NOT NULL,
        title        TEXT,
        thumbnail    TEXT,
        videos       TEXT NOT NULL DEFAULT '[]',
        refreshed_at REAL NOT NULL DEFAULT 0
    );
    INSERT OR IGNORE INTO channels
        (channel_id, channel_url, title, thumbnail, videos, refreshed_at)
        SELECT channel_id, channel_url, title, thumbnail, videos, refreshed_at
        FROM subscriptions;
    CREATE TABLE follows (
        owner      TEXT NOT NULL,
        channel_id TEXT NOT NULL,
        PRIMARY KEY (owner, channel_id)
    );
    INSERT OR IGNORE INTO follows (owner, channel_id)
        SELECT owner, channel_id FROM subscriptions;
    DROP TABLE subscriptions;
    """,
    """
    ALTER TABLE entries ADD COLUMN variant TEXT;
    """,
    """
    ALTER TABLE channels ADD COLUMN shorts TEXT NOT NULL DEFAULT '[]';
    ALTER TABLE channels ADD COLUMN shorts_refreshed_at REAL NOT NULL DEFAULT 0;
    """,
    """
    ALTER TABLE entries ADD COLUMN kind TEXT NOT NULL DEFAULT 'video';
    """,
    """
    ALTER TABLE channels ADD COLUMN platform TEXT NOT NULL DEFAULT 'youtube';
    """,
]


def migrate():
    with connect() as conn:
        version = conn.execute("PRAGMA user_version").fetchone()[0]
        for i, script in enumerate(MIGRATIONS[version:], start=version):
            conn.executescript(script)
            conn.execute(f"PRAGMA user_version = {i + 1}")


migrate()


def recover_interrupted():
    with connect() as conn:
        conn.execute("UPDATE entries SET status = 'error', error = ? "
                     "WHERE status = 'downloading'",
                     ("Interrupted by a server restart",))


recover_interrupted()


def current_user():
    if AUTH_MODE != "proxy":
        return SOLO_USER
    user = (request.headers.get("Remote-User") or "").strip()
    if not user:
        abort(401)
    return user


def user_groups():
    return [g.strip() for g in (request.headers.get("Remote-Groups") or "").split(",")
            if g.strip()]


def is_admin():
    if AUTH_MODE != "proxy":
        return True
    return ADMIN_GROUP in user_groups()


def require_admin():
    current_user()
    if is_admin():
        return
    # A bare 403 cannot tell "the group is missing from the provider" from
    # "the proxy is not copying the header", which are fixed in different
    # places. Showing the caller its own groups gives that away for free.
    groups = user_groups()
    if groups:
        detail = f"groups received: {', '.join(groups)}"
    else:
        detail = "no groups received at all, so the proxy is not copying Remote-Groups"
    abort(403, f"Admin needs the {ADMIN_GROUP} group. For {current_user()}, {detail}.")


def variant_of(format_choice, format_id, max_height, vertical=False):
    """What was actually asked for, as one comparable string.

    Two accounts asking for the same URL in the same variant deserve one file,
    not two: it is the same bytes, and downloading it twice also asks YouTube
    twice. The same number bounds the width of an upright video and the height
    of a wide one, so the two cannot share a name.
    """
    if format_choice == "audio":
        return "audio"
    if format_id:
        return f"video:{format_id}"
    if max_height:
        return f"video:{'w' if vertical else 'h'}{max_height}"
    return "video:best"


def twin_of(url, variant):
    """A finished entry, any owner, holding the very same file."""
    with connect() as conn:
        rows = conn.execute(
            "SELECT path, filename FROM entries WHERE url = ? AND variant = ? "
            "AND status = 'done' AND path IS NOT NULL ORDER BY created_at DESC",
            (url, variant)).fetchall()
    for row in rows:
        if os.path.exists(row["path"]):
            return row
    return None


def file_size(path):
    try:
        return os.path.getsize(path)
    except (OSError, TypeError):
        return 0


def get_entry(job_id, owner=None):
    with connect() as conn:
        row = conn.execute("SELECT * FROM entries WHERE job_id = ?", (job_id,)).fetchone()
    if row is None or (owner is not None and row["owner"] != owner):
        return None
    return row


def update_entry(job_id, **fields):
    assignments = ", ".join(f"{k} = ?" for k in fields)
    with connect() as conn:
        conn.execute(f"UPDATE entries SET {assignments} WHERE job_id = ?",
                     (*fields.values(), job_id))


def retention_for(row):
    """A short is watched once, in the minutes after it is fetched, and never
    pinned: it has its own, much shorter deadline."""
    if row["kind"] == "short":
        return SHORTS_RETENTION
    return PIN_RETENTION if row["pinned"] else RETENTION


def seconds_left(row):
    """Seconds until the sweep takes this row's file."""
    if not row["path"]:
        return 0
    try:
        deadline = os.path.getmtime(row["path"]) + retention_for(row)
    except OSError:
        return 0
    return max(0, int(deadline - time.time()))


def entry_json(row):
    return {
        "job_id": row["job_id"],
        "url": row["url"],
        "title": row["title"],
        "thumbnail": row["thumbnail"],
        "uploader": row["uploader"],
        "duration": row["duration"],
        "description": row["description"],
        "upload_date": row["upload_date"],
        "format": row["format"],
        "format_id": row["format_id"],
        "formats": json.loads(row["formats"]) if row["formats"] else [],
        "filename": row["filename"],
        "status": row["status"],
        "error": row["error"],
        "pinned": bool(row["pinned"]),
        "kind": row["kind"],
        "has_file": bool(row["path"]) and os.path.exists(row["path"]),
        "expires_in": seconds_left(row),
    }


def is_safe_url(url):
    """Reject anything that is not a plain http(s) URL.

    yt-dlp reads an argv item starting with "-" as an option, so a URL of
    "--exec=..." would run a command. Every invocation also passes "--" before
    the URL; this check exists to answer with a 400 rather than a yt-dlp error.
    """
    try:
        parsed = urlparse(url)
    except ValueError:
        return False
    return parsed.scheme in ("http", "https") and bool(parsed.netloc)


def parse_ytdlp_json(stdout):
    """Parse yt-dlp JSON output.

    With ``-j`` yt-dlp prints one JSON object per line. Some extractors
    emit multiple videos even with ``--no-playlist``, so stdout contains
    several objects and a plain ``json.loads`` raises "Extra data".
    Return the first valid object.
    """
    for line in stdout.splitlines():
        line = line.strip()
        if not line:
            continue
        return json.loads(line)
    raise ValueError("yt-dlp returned no data")


def drop_file(path, keeping=None):
    """Remove a file only when no other entry still points at it."""
    if not path:
        return
    with connect() as conn:
        others = conn.execute(
            "SELECT count(*) FROM entries WHERE path = ? AND job_id != ?",
            (path, keeping or "")).fetchone()[0]
    if not others:
        remove_quietly(path)


def remove_quietly(path):
    try:
        os.remove(path)
    except OSError:
        pass


def sweep_downloads():
    """Delete files past RETENTION, and files no row claims.

    The entry outlives its file: it keeps the title and the URL so the download
    can be started again, which costs a row rather than gigabytes.
    """
    now = time.time()
    with connect() as conn:
        # A file can be referenced by several entries, so the deadline is keyed
        # by path and the most generous reference wins: nobody's pin may be
        # undone by somebody else's expiry.
        deadlines = {}
        for row in conn.execute(
                "SELECT path, pinned, kind FROM entries WHERE path IS NOT NULL"):
            ttl = retention_for(row)
            deadlines[row["path"]] = max(deadlines.get(row["path"], 0), ttl)
        # A download in flight has no path yet, and is recognised by its name.
        running = {r["job_id"] for r in
                   conn.execute("SELECT job_id FROM entries WHERE status = 'downloading'")}

    for path in glob.glob(os.path.join(DOWNLOAD_DIR, "*")):
        try:
            age = now - os.path.getmtime(path)
        except OSError:
            continue
        if os.path.basename(path).split(".")[0] in running:
            continue
        if path in deadlines and age < deadlines[path]:
            continue
        remove_quietly(path)
        with connect() as conn:
            conn.execute("UPDATE entries SET path = NULL WHERE path = ?", (path,))

    trim_history()


def trim_history():
    """Keep the newest HISTORY_MAX entries per user.

    A row is a few bytes, but without a ceiling the list grows for the life of
    the instance. Pinned entries are never trimmed: pinning says keep it. Shorts
    are counted apart, so watching a hundred of them cannot push a download out
    of somebody's history.
    """
    with connect() as conn:
        stale = conn.execute(
            "SELECT job_id, path FROM entries WHERE pinned = 0 AND job_id NOT IN ("
            "  SELECT job_id FROM ("
            "    SELECT job_id, row_number() OVER ("
            "      PARTITION BY owner, kind ORDER BY created_at DESC) AS rank FROM entries"
            "  ) WHERE rank <= ?)", (HISTORY_MAX,)).fetchall()
        for row in stale:
            drop_file(row["path"], keeping=row["job_id"])
            conn.execute("DELETE FROM entries WHERE job_id = ?", (row["job_id"],))


def stalest_slot():
    """The oldest tab somebody still follows, videos and shorts in one queue.

    A channel holds two slots when shorts are on. Putting them in the same queue
    is what keeps the outbound rate at one lookup per FEED_POLL whatever is
    enabled: turning shorts on halves how often each tab comes round, it does
    not double how often YouTube is asked.
    """
    cutoff = time.time() - FEED_TTL
    # A TikTok account has no Videos tab, so it takes one place in the queue
    # rather than two: what it has is what the shorts page reads.
    queue = ["SELECT c.channel_id, c.channel_url, c.platform, 'videos' AS tab, "
             "c.refreshed_at AS age FROM channels c "
             "JOIN follows f ON f.channel_id = c.channel_id "
             "WHERE c.platform = 'youtube'"]
    if SHORTS_ENABLED:
        queue.append("SELECT c.channel_id, c.channel_url, c.platform, 'shorts', "
                     "c.shorts_refreshed_at FROM channels c "
                     "JOIN follows f ON f.channel_id = c.channel_id")
    with connect() as conn:
        # A tie goes to the tab that did not go last. Freshly imported channels
        # are all dated zero, so without this the queue does every Videos tab
        # before the first Shorts one: hours before a shorts page shows anything.
        return conn.execute(
            f"SELECT * FROM ({' UNION ALL '.join(queue)}) WHERE age < ? "
            "ORDER BY age, tab = ? LIMIT 1", (cutoff, last_tab)).fetchone()


def feed_poller():
    """One tab per tick, oldest first, for the whole instance.

    This is the whole automatic refresh: no burst when someone opens the page,
    and a ceiling on outbound lookups that does not move with the number of
    users, channels or pages enabled.
    """
    global last_tab
    while True:
        time.sleep(FEED_POLL)
        try:
            row = stalest_slot()
            if not row:
                continue
            last_tab = row["tab"]
            if row["tab"] == "shorts":
                refresh_shorts(row["channel_url"], row["channel_id"], row["platform"])
            else:
                refresh_channel(row["channel_url"], row["channel_id"])
        except Exception as e:
            app.logger.warning("feed refresh failed: %s", e)


def janitor():
    while True:
        try:
            sweep_downloads()
        except Exception as e:
            app.logger.warning("sweep failed: %s", e)
        time.sleep(SWEEP_INTERVAL)


threading.Thread(target=janitor, daemon=True).start()


def run_download(job_id, url, format_choice, format_id, title, max_height=None,
                 vertical=False):
    out_template = os.path.join(DOWNLOAD_DIR, f"{job_id}.%(ext)s")

    cmd = [*YTDLP, "--no-playlist", "-o", out_template]

    if format_choice == "audio":
        cmd += ["-x", "--audio-format", "mp3"]
    elif format_id:
        # Prefer m4a audio: Opus is legal in an mp4 container but Apple devices
        # read it poorly, and the merge is a stream copy either way.
        cmd += ["-f", f"{format_id}+bestaudio[ext=m4a]/bestaudio/best",
                "--merge-output-format", "mp4"]
    elif max_height:
        # The feed asks for a size rather than a format id: it never looked the
        # video up, so it has no ids to choose from. A short is filmed upright,
        # where "720p" names the width: bounding its height would ask for a
        # 405x720 copy of a 720x1280 video, or for nothing at all.
        side = "width" if vertical else "height"
        cmd += ["-f", f"bestvideo[{side}<={max_height}][vcodec^=avc1]+bestaudio[ext=m4a]/"
                      f"bestvideo[{side}<={max_height}]+bestaudio[ext=m4a]/"
                      f"bestvideo[{side}<={max_height}]+bestaudio/"
                      f"best[{side}<={max_height}]/best",
                "--merge-output-format", "mp4"]
    else:
        cmd += ["-f", "bestvideo+bestaudio/best", "--merge-output-format", "mp4"]

    cmd += ["--", url]

    try:
        result = subprocess.run(cmd, capture_output=True, text=True,
                                timeout=DOWNLOAD_TIMEOUT)
        if result.returncode != 0:
            update_entry(job_id, status="error", error=result.stderr.strip().split("\n")[-1])
            return

        files = glob.glob(os.path.join(DOWNLOAD_DIR, f"{job_id}.*"))
        if not files:
            update_entry(job_id, status="error",
                         error="Download completed but no file was found")
            return

        wanted = ".mp3" if format_choice == "audio" else ".mp4"
        target = [f for f in files if f.endswith(wanted)]
        chosen = target[0] if target else files[0]

        for f in files:
            if f != chosen:
                remove_quietly(f)

        ext = os.path.splitext(chosen)[1]
        title = (title or "").strip()
        # Sanitize title for filename
        safe_title = "".join(c for c in title if c not in r'\/:*?"<>|').strip()[:100].strip()
        filename = f"{safe_title}{ext}" if safe_title else os.path.basename(chosen)

        update_entry(job_id, status="done", path=chosen, filename=filename, error=None)
    except subprocess.TimeoutExpired:
        update_entry(job_id, status="error",
                     error=f"Download timed out ({DOWNLOAD_TIMEOUT // 60} min limit)")
    except Exception as e:
        update_entry(job_id, status="error", error=str(e))


# Held for the whole of a channel lookup, so two refreshes can never talk to
# YouTube at the same time whoever asked for them.
feed_lock = threading.Lock()
# Which tab the last lookup was for, so ties alternate rather than starving one.
last_tab = "shorts"
last_channel_call = 0.0


def channel_call_allowed():
    """Space out lookups, whatever triggered them."""
    return time.time() - last_channel_call >= FEED_POLL


def get_settings(owner):
    """Per-user feed settings, always within what the instance allows."""
    with connect() as conn:
        row = conn.execute("SELECT * FROM settings WHERE owner = ?", (owner,)).fetchone()
    videos = row["feed_videos"] if row else FEED_DEFAULTS["videos"]
    quality = row["feed_quality"] if row else FEED_DEFAULTS["quality"]
    return {"videos": max(1, min(videos, FEED_VIDEOS_MAX)),
            "quality": quality if quality in FEED_QUALITIES else FEED_DEFAULTS["quality"]}


def save_settings(owner, videos, quality):
    videos = max(1, min(int(videos), FEED_VIDEOS_MAX))
    quality = int(quality)
    if quality not in FEED_QUALITIES:
        quality = FEED_DEFAULTS["quality"]
    with connect() as conn:
        conn.execute("INSERT INTO settings (owner, feed_videos, feed_quality) "
                     "VALUES (?, ?, ?) ON CONFLICT(owner) DO UPDATE SET "
                     "feed_videos = excluded.feed_videos, "
                     "feed_quality = excluded.feed_quality",
                     (owner, videos, quality))
    return {"videos": videos, "quality": quality}


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
    cmd = [*YTDLP, "--flat-playlist", "--playlist-end", str(count), "-J", "--", account_url]
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
    cmd = [*YTDLP, "--no-playlist", "-j", "--", *urls]
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
    cmd = [*YTDLP, "--flat-playlist", "--playlist-end", str(count or FEED_DEFAULTS["videos"]),
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
    cmd = [*YTDLP, "--flat-playlist", "--playlist-end", str(count), "-J", "--", shorts_url]
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


def refresh_shorts(url, channel_id, platform="youtube"):
    """One account's upright videos, under the same lock and the same clock as a
    feed refresh: every source shares one outbound budget."""
    global last_channel_call
    with feed_lock:
        last_channel_call = time.time()
        shorts = (fetch_tiktok(url, FEED_VIDEOS_MAX)["videos"] if platform == "tiktok"
                  else fetch_shorts(url, FEED_VIDEOS_MAX))
    with connect() as conn:
        conn.execute("UPDATE channels SET shorts = ?, shorts_refreshed_at = ? "
                     "WHERE channel_id = ?",
                     (json.dumps(shorts), time.time(), channel_id))
    return shorts


def refresh_channel(url, channel_id=None):
    """Look a channel up once, for everyone who follows it.

    The cache is keyed by channel, not by subscriber: with the outbound rate
    capped instance-wide, storing it per account would have spent that budget
    as many times as there are people following the same channel, which in a
    household is the common case rather than the edge one. It holds the
    instance maximum; each account displays as many as it asked for.
    """
    global last_channel_call
    known = {}
    if channel_id:
        with connect() as conn:
            row = conn.execute("SELECT videos FROM channels WHERE channel_id = ?",
                               (channel_id,)).fetchone()
        if row:
            known = {v["id"]: v for v in json.loads(row["videos"]) if v.get("id")}
    with feed_lock:
        last_channel_call = time.time()
        channel = fetch_channel(url, known, FEED_VIDEOS_MAX)
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


def page_context():
    """What the header needs. Rendered server-side: the identity is known here,
    so asking for it from the browser only bought a flash of empty header."""
    return {"auth": AUTH_MODE, "user": current_user(),
            "admin": is_admin(), "logout_url": LOGOUT_URL,
            "feed": FEED_ENABLED, "shorts": SHORTS_ENABLED, "tiktok": TIKTOK_ENABLED}


@app.before_request
def gate_optional_pages():
    """One gate rather than a check on each route, so a route added later
    cannot forget to close behind itself."""
    path = request.path
    if not FEED_ENABLED and (path == "/feed" or path.startswith("/api/feed")):
        abort(404)
    if not SHORTS_ENABLED and (path == "/shorts" or path.startswith("/api/shorts")):
        abort(404)


@app.route("/")
def index():
    return render_template("index.html", page="home", **page_context())


@app.route("/feed")
def feed_page():
    return render_template("feed.html", page="feed", **page_context())


@app.route("/api/feed")
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
        channels.append(channel)
        videos.extend({**video, "uploader": row["title"], "channel_id": row["channel_id"],
                       "ready": video["url"] in ready,
                       **mine.get(video["url"], {"job_id": None, "pinned": False})}
                      for video in channel["videos"])
    # YYYYMMDD sorts correctly as a string. Unknown dates naturally sink.
    videos.sort(key=lambda video: video["upload_date"], reverse=True)
    return jsonify({"channels": channels, "videos": videos,
                    "settings": settings,
                    "limits": {"videos_max": FEED_VIDEOS_MAX,
                               "qualities": FEED_QUALITIES}})


@app.route("/shorts")
def shorts_page():
    return render_template("shorts.html", page="shorts", **page_context())


@app.route("/api/shorts")
def shorts_list():
    """Every followed channel's shorts, one from each in turn.

    A round is one short per channel, so no channel takes the top of the page,
    and it costs no date: the shorts tab is already newest first, and dating
    them would mean asking the player API about every one of them.
    """
    owner = current_user()
    settings = get_settings(owner)
    with connect() as conn:
        rows = conn.execute(
            "SELECT c.title, c.shorts, c.platform FROM channels c "
            "JOIN follows f ON f.channel_id = c.channel_id "
            "WHERE f.owner = ? ORDER BY c.title COLLATE NOCASE", (owner,)).fetchall()

    variant = variant_of("video", None, settings["quality"], vertical=True)
    with connect() as conn:
        ready = {r["url"]: r["job_id"] for r in conn.execute(
            "SELECT url, job_id, path FROM entries WHERE variant = ? AND status = 'done' "
            "AND path IS NOT NULL", (variant,)) if os.path.exists(r["path"])}

    lists = []
    for row in rows:
        shorts = json.loads(row["shorts"])[:settings["videos"]]
        lists.append([{**short, "uploader": row["title"], "platform": row["platform"],
                       "job_id": ready.get(short["url"])} for short in shorts])

    interleaved = []
    for rank in range(max((len(one) for one in lists), default=0)):
        for one in lists:
            if rank < len(one):
                interleaved.append(one[rank])
    return jsonify({"shorts": interleaved, "quality": settings["quality"]})


@app.route("/api/feed/settings", methods=["POST"])
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


@app.route("/api/feed/subscriptions", methods=["POST"])
def subscribe():
    """Follow a channel, from whichever platform its URL names."""
    owner = current_user()
    url = (request.json or {}).get("url", "").strip()
    tiktok = TIKTOK_ENABLED and tiktok_user_url(url)
    if not is_safe_url(url) or not (tiktok or youtube_videos_url(url)):
        return jsonify({"error": "Please enter a YouTube channel URL"
                        + (" or a TikTok account" if TIKTOK_ENABLED else "")}), 400
    with connect() as conn:
        followed = conn.execute("SELECT count(*) FROM follows WHERE owner = ?",
                                (owner,)).fetchone()[0]
    if followed >= FEED_CHANNELS_MAX:
        return jsonify({"error": f"At most {FEED_CHANNELS_MAX} channels"}), 400
    try:
        channel = follow_tiktok(url) if tiktok else refresh_channel(url)
    except subprocess.TimeoutExpired:
        return jsonify({"error": "Timed out fetching channel"}), 400
    except Exception as e:
        return jsonify({"error": str(e)}), 400
    with connect() as conn:
        conn.execute("INSERT OR IGNORE INTO follows (owner, channel_id) VALUES (?, ?)",
                     (owner, channel["channel_id"]))
    return jsonify(channel)


def follow_tiktok(url):
    """Record a TikTok account, its videos already in the shorts column.

    An upright video is an upright video: putting them where the shorts page
    already looks is what makes one page serve both sources.
    """
    global last_channel_call
    with feed_lock:
        last_channel_call = time.time()
        account = fetch_tiktok(url, FEED_VIDEOS_MAX)
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


@app.route("/api/feed/import", methods=["POST"])
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
    if len(text) > IMPORT_MAX_BYTES:
        return jsonify({"error": "File too large"}), 400

    with connect() as conn:
        followed = {r["channel_id"] for r in conn.execute(
            "SELECT channel_id FROM follows WHERE owner = ?", (owner,))}

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
        if len(followed) >= FEED_CHANNELS_MAX:
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
        added += 1

    if not (added or already or skipped):
        return jsonify({"error": "No channels found in this file"}), 400
    return jsonify({"added": added, "already": already, "skipped": skipped,
                    "full": full, "limit": FEED_CHANNELS_MAX,
                    "every": FEED_POLL})


@app.route("/api/feed/refresh", methods=["POST"])
def refresh_feed():
    """Refresh one channel per call.

    Refreshing every channel in a single request took as long as the slowest
    lookup times the channel count, with nothing on screen in the meantime and
    the worker timeout waiting at the end of it.
    """
    owner = current_user()
    data = request.json or {}
    channel_id = data.get("channel_id")
    # One deliberate click on one channel, when the user knows a video is out.
    # It skips the spacing rather than removing it: the lookup still takes the
    # instance lock and still resets the clock the poller reads, so the
    # automatic rate is unchanged afterwards.
    force = bool(data.get("force"))
    with connect() as conn:
        row = conn.execute(
            "SELECT c.channel_url, c.refreshed_at FROM channels c "
            "JOIN follows f ON f.channel_id = c.channel_id "
            "WHERE f.owner = ? AND c.channel_id = ?", (owner, channel_id)).fetchone()
    if row is None:
        return jsonify({"error": "Unknown channel"}), 404
    # Clicking twice must not cost two lookups, and a page full of channels must
    # not become a burst of them.
    if not force and time.time() - row["refreshed_at"] < FEED_COOLDOWN:
        return jsonify({"ok": True, "skipped": "recent"})
    if not force and not channel_call_allowed():
        return jsonify({"ok": True, "skipped": "busy"})
    try:
        refresh_channel(row["channel_url"], channel_id)
        return jsonify({"ok": True})
    except subprocess.TimeoutExpired:
        return jsonify({"error": "Timed out"}), 400
    except Exception as e:
        return jsonify({"error": str(e)}), 400


@app.route("/api/feed/subscriptions/<channel_id>", methods=["DELETE"])
def unsubscribe(channel_id):
    with connect() as conn:
        conn.execute("DELETE FROM follows WHERE owner = ? AND channel_id = ?",
                     (current_user(), channel_id))
        # A channel nobody follows any more stops being refreshed, and stops
        # taking space.
        conn.execute("DELETE FROM channels WHERE channel_id NOT IN "
                     "(SELECT channel_id FROM follows)")
    return jsonify({"ok": True})


@app.route("/admin")
def admin_page():
    require_admin()
    return render_template("admin.html", page="admin", **page_context())


@app.route("/api/admin/overview")
def admin_overview():
    require_admin()

    on_disk = [p for p in glob.glob(os.path.join(DOWNLOAD_DIR, "*"))]
    with connect() as conn:
        rows = conn.execute("SELECT * FROM entries WHERE kind = 'video' "
                            "ORDER BY created_at DESC").fetchall()
        # Shorts are listed as one line, not one row each: a hundred of them
        # would bury the entries somebody actually asked for.
        shorts = conn.execute("SELECT path FROM entries WHERE kind = 'short'").fetchall()
        # What escapes the ordinary deadline, and so what can grow the disk
        # without anybody deciding to.
        pinned = conn.execute("SELECT path FROM entries WHERE pinned = 1").fetchall()

    users = {}
    entries = []
    for row in rows:
        size = file_size(row["path"]) if row["path"] else 0
        stats = users.setdefault(row["owner"], {"entries": 0, "files": 0, "bytes": 0})
        stats["entries"] += 1
        if size:
            stats["files"] += 1
            stats["bytes"] += size
        entries.append({**entry_json(row), "owner": row["owner"],
                        "created_at": row["created_at"], "bytes": size})

    return jsonify({
        "retention": RETENTION,
        "auth": AUTH_MODE,
        "pinned": {"entries": len(pinned),
                   "bytes": sum(file_size(r["path"]) for r in pinned if r["path"]),
                   "retention": PIN_RETENTION},
        "shorts": {"entries": len(shorts),
                   "bytes": sum(file_size(r["path"]) for r in shorts if r["path"]),
                   "retention": SHORTS_RETENTION,
                   "enabled": SHORTS_ENABLED},
        # Counted from the directory rather than from the rows, so a file no row
        # claims still shows up in the total.
        "disk": {
            "files": len(on_disk),
            "bytes": sum(file_size(p) for p in on_disk),
            "free": shutil.disk_usage(DOWNLOAD_DIR).free,
        },
        "users": users,
        "entries": entries,
    })


@app.route("/api/admin/purge", methods=["POST"])
def admin_purge():
    """Empty the instance: every entry of every user, every file on disk.

    A download in flight is left alone. Its row is what tells it where to write
    and where to report, so removing it mid-way would leave a process writing a
    file nobody claims.
    """
    require_admin()
    with connect() as conn:
        running = {r["job_id"] for r in conn.execute(
            "SELECT job_id FROM entries WHERE status = 'downloading'")}
        entries = conn.execute(
            "DELETE FROM entries WHERE status != 'downloading'").rowcount

    files, freed = 0, 0
    for path in glob.glob(os.path.join(DOWNLOAD_DIR, "*")):
        if os.path.basename(path).split(".")[0] in running:
            continue
        freed += file_size(path)
        remove_quietly(path)
        files += 1
    return jsonify({"entries": entries, "files": files, "bytes": freed,
                    "running": len(running)})


@app.route("/api/admin/shorts", methods=["DELETE"])
def admin_clear_shorts():
    """Drop every watched short, whoever watched it.

    They are disposable by design, so this is the sweep done early rather than a
    decision: nothing here is anybody's library.
    """
    require_admin()
    with connect() as conn:
        rows = conn.execute("SELECT job_id, path FROM entries WHERE kind = 'short'").fetchall()
        for row in rows:
            drop_file(row["path"], keeping=row["job_id"])
        conn.execute("DELETE FROM entries WHERE kind = 'short'")
    return jsonify({"entries": len(rows)})


@app.route("/api/admin/entries/<job_id>", methods=["DELETE"])
def admin_delete_entry(job_id):
    require_admin()
    row = get_entry(job_id)
    if row is None:
        return jsonify({"error": "Not found"}), 404
    drop_file(row["path"], keeping=job_id)
    with connect() as conn:
        conn.execute("DELETE FROM entries WHERE job_id = ?", (job_id,))
    return jsonify({"ok": True})


@app.route("/api/entries")
def list_entries():
    owner = current_user()
    with connect() as conn:
        rows = conn.execute(
            "SELECT * FROM entries WHERE owner = ? AND kind = 'video' "
            "ORDER BY created_at", (owner,)).fetchall()
    return jsonify({"entries": [entry_json(r) for r in rows], "user": owner})


@app.route("/api/entries/<job_id>/pin", methods=["POST"])
def pin_entry(job_id):
    row = get_entry(job_id, current_user())
    if row is None:
        return jsonify({"error": "Not found"}), 404
    pinned = 1 if request.json.get("pinned") else 0
    update_entry(job_id, pinned=pinned)
    return jsonify(entry_json(get_entry(job_id)))


@app.route("/api/entries/<job_id>", methods=["DELETE"])
def delete_entry(job_id):
    row = get_entry(job_id, current_user())
    if row is None:
        return jsonify({"error": "Not found"}), 404
    drop_file(row["path"], keeping=job_id)
    with connect() as conn:
        conn.execute("DELETE FROM entries WHERE job_id = ?", (job_id,))
    return jsonify({"ok": True})


def remember(owner, url, info):
    """Record a fetched URL, so it survives the tab without being downloaded.

    Fetching the same URL twice returns the same row rather than a second card,
    which also means a URL already downloaded comes back with its state. The
    whole card is stored, quality list included: whatever is missing here is
    what a restored card will not be able to show.
    """
    values = (info["title"], info["thumbnail"], json.dumps(info["formats"]),
              info["uploader"], info["duration"], info["description"],
              info["upload_date"])
    with connect() as conn:
        row = conn.execute(
            "SELECT job_id FROM entries WHERE owner = ? AND url = ?"
            " ORDER BY created_at DESC LIMIT 1", (owner, url)).fetchone()
        if row:
            conn.execute("UPDATE entries SET title = ?, thumbnail = ?, formats = ?,"
                         " uploader = ?, duration = ?, description = ?,"
                         " upload_date = ? WHERE job_id = ?",
                         (*values, row["job_id"]))
            return row["job_id"]
        job_id = uuid.uuid4().hex[:10]
        conn.execute(
            "INSERT INTO entries (job_id, owner, url, title, thumbnail, formats,"
            " uploader, duration, description, upload_date, status, created_at)"
            " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'ready', ?)",
            (job_id, owner, url, *values, time.time()))
        return job_id


@app.route("/api/info", methods=["POST"])
def get_info():
    owner = current_user()
    data = request.json
    url = data.get("url", "").strip()
    if not url:
        return jsonify({"error": "No URL provided"}), 400
    if not is_safe_url(url):
        return jsonify({"error": "Invalid URL"}), 400

    cmd = [*YTDLP, "--no-playlist", "-j", "--", url]
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=60)
        if result.returncode != 0:
            return jsonify({"error": result.stderr.strip().split("\n")[-1]}), 400

        info = parse_ytdlp_json(result.stdout)

        # A live stream has no end, so the download would run into the 300s
        # timeout and fail with something unreadable. Refuse it now instead.
        if info.get("live_status") in ("is_live", "is_upcoming"):
            return jsonify({"error": "This is a live stream, not a finished video"}), 400

        # One format per resolution. H.264 first, then bitrate: YouTube stops
        # publishing H.264 above 1080p, and VP9 or AV1 in an mp4 plays in a
        # browser but not in QuickTime, on an iPhone or on most televisions.
        def rank(f):
            return (f.get("vcodec", "").startswith("avc1"), f.get("tbr") or 0)

        # YouTube names a rung after its 16:9 equivalent, so 1920x960 on a 2:1
        # video is "1080p" and not "960p". It puts that name on one format of
        # the rung and leaves the others without, so the name is read from the
        # whole rung rather than from the format we happen to prefer.
        rung_names = {}
        best_by_height = {}
        for f in info.get("formats", []):
            height = f.get("height")
            if not height or f.get("vcodec", "none") == "none":
                continue
            named = re.match(r"(\d+p\d*)", f.get("format_note") or "")
            if named:
                rung_names.setdefault(height, named.group(1))
            if height not in best_by_height or rank(f) > rank(best_by_height[height]):
                best_by_height[height] = f

        duration = info.get("duration") or 0

        def approx_size(f):
            """yt-dlp leaves filesize empty on several formats, including the
            high-bitrate H.264 we now prefer. Bitrate times duration matches the
            announced sizes to the decimal wherever both exist."""
            known = f.get("filesize") or f.get("filesize_approx")
            if known:
                return known
            tbr = f.get("tbr") or 0
            return int(tbr * 125 * duration) or None

        formats = []
        for height, f in best_by_height.items():
            formats.append({
                "id": f["format_id"],
                "label": rung_names.get(height, f"{height}p"),
                "height": height,
                # Video stream only, and often an estimate. It is an order of
                # magnitude, not an accounting figure.
                "size": approx_size(f),
                "compatible": f.get("vcodec", "").startswith("avc1"),
            })
        formats.sort(key=lambda x: x["height"], reverse=True)

        card = {
            "title": info.get("title", ""),
            "thumbnail": info.get("thumbnail", ""),
            "duration": info.get("duration"),
            "uploader": info.get("uploader", ""),
            "description": info.get("description", ""),
            "upload_date": info.get("upload_date", ""),
            "formats": formats,
        }
        return jsonify({"job_id": remember(owner, url, card), **card})
    except subprocess.TimeoutExpired:
        return jsonify({"error": "Timed out fetching video info"}), 400
    except Exception as e:
        return jsonify({"error": str(e)}), 400


@app.route("/api/playlist", methods=["POST"])
def get_playlist_info():
    current_user()
    data = request.json
    url = data.get("url", "").strip()
    if not url:
        return jsonify({"error": "No URL provided"}), 400
    if not is_safe_url(url):
        return jsonify({"error": "Invalid URL"}), 400

    cmd = [*YTDLP, "--flat-playlist", "--playlist-end", str(PLAYLIST_MAX + 1),
           "-J", "--", url]
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=60)
        if result.returncode != 0:
            return jsonify({"error": result.stderr.strip().split("\n")[-1]}), 400

        info = json.loads(result.stdout)
        entries = info.get("entries", [])
        urls = [entry.get("url") for entry in entries if entry.get("url")]
        return jsonify({"urls": urls[:PLAYLIST_MAX],
                        "truncated": len(urls) > PLAYLIST_MAX,
                        "limit": PLAYLIST_MAX})
    except subprocess.TimeoutExpired:
        return jsonify({"error": "Timed out fetching playlist info"}), 400
    except Exception as e:
        return jsonify({"error": str(e)}), 400


@app.route("/api/download", methods=["POST"])
def start_download():
    owner = current_user()
    data = request.json
    url = data.get("url", "").strip()
    format_choice = data.get("format", "video")
    format_id = data.get("format_id")
    title = data.get("title", "")
    retry_of = data.get("job_id")
    # A short is an entry like any other, but it stays out of the downloads
    # list: a page of them would bury what someone actually asked for.
    kind = "short" if data.get("kind") == "short" else "video"
    try:
        max_height = int(data.get("max_height") or 0) or None
    except (TypeError, ValueError):
        max_height = None

    if not url:
        return jsonify({"error": "No URL provided"}), 400
    if not is_safe_url(url):
        return jsonify({"error": "Invalid URL"}), 400

    # Starting a history entry again reuses its row, so the list does not grow a
    # duplicate every time a swept file is fetched anew.
    existing = get_entry(retry_of, owner) if retry_of else None
    if existing:
        job_id = existing["job_id"]
        update_entry(job_id, status="downloading", error=None, path=None,
                     format=format_choice, format_id=format_id)
    else:
        job_id = uuid.uuid4().hex[:10]
        with connect() as conn:
            conn.execute(
                "INSERT INTO entries (job_id, owner, url, title, thumbnail, uploader,"
                " upload_date, description, format, format_id, kind, status, created_at)"
                " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (job_id, owner, url, title, data.get("thumbnail", ""),
                 data.get("uploader", ""), data.get("upload_date", ""),
                 data.get("description", ""), format_choice, format_id, kind,
                 "downloading", time.time()))

    variant = variant_of(format_choice, format_id, max_height, kind == "short")
    update_entry(job_id, variant=variant)

    twin = twin_of(url, variant)
    if twin:
        # The same bytes already exist. Point at them instead of asking YouTube
        # for a second copy; the sweep keeps the file while either entry needs
        # it, and deleting one entry never takes the other's file.
        update_entry(job_id, status="done", path=twin["path"],
                     filename=twin["filename"], error=None)
        return jsonify({"job_id": job_id, "reused": True})

    thread = threading.Thread(target=run_download,
                              args=(job_id, url, format_choice, format_id, title,
                                    max_height, kind == "short"))
    thread.daemon = True
    thread.start()

    return jsonify({"job_id": job_id})


@app.route("/api/status/<job_id>")
def check_status(job_id):
    row = get_entry(job_id, current_user())
    if row is None:
        return jsonify({"error": "Job not found"}), 404
    return jsonify({
        "status": row["status"],
        "error": row["error"],
        "filename": row["filename"],
        "expires_in": seconds_left(row),
    })


@app.route("/api/stream/<job_id>")
def stream_file(job_id):
    row = get_entry(job_id, current_user())
    if row is None or not row["path"] or not os.path.exists(row["path"]):
        return jsonify({"error": "File not ready"}), 404
    # Inline rather than an attachment, and conditional so the browser can seek
    # with Range requests instead of pulling the whole file first.
    return send_file(row["path"], conditional=True)


@app.route("/api/file/<job_id>")
def download_file(job_id):
    row = get_entry(job_id, current_user())
    if row is None or not row["path"] or not os.path.exists(row["path"]):
        return jsonify({"error": "File not ready"}), 404
    return send_file(row["path"], as_attachment=True, download_name=row["filename"])


# Started last: the poller reaches for everything below it, and a thread that
# outruns its own module is a bug waiting for a slow import. Not started at all
# when the feed is off: nothing must talk to YouTube on its own then.
if FEED_ENABLED:
    threading.Thread(target=feed_poller, daemon=True).start()


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 8899))
    host = os.environ.get("HOST", "127.0.0.1")
    app.run(host=host, port=port)
