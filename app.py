import os
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
# A pin does not exempt a file, it moves its deadline within a limit the admin
# still owns. Otherwise the disk stops being bounded.
PIN_RETENTION = int(os.environ.get("RECLIP_PIN_RETENTION", 30 * 24 * 3600))
HISTORY_MAX = int(os.environ.get("RECLIP_HISTORY_MAX", 200))
SWEEP_INTERVAL = 60

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
    CREATE TABLE settings (
        owner        TEXT PRIMARY KEY,
        feed_videos  INTEGER NOT NULL,
        feed_quality INTEGER NOT NULL
    );
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
        known = {r["job_id"]: r["pinned"] for r in
                 conn.execute("SELECT job_id, pinned FROM entries")}

    for path in glob.glob(os.path.join(DOWNLOAD_DIR, "*")):
        job_id = os.path.basename(path).split(".")[0]
        try:
            age = now - os.path.getmtime(path)
        except OSError:
            continue
        if job_id in known:
            if age < (PIN_RETENTION if known[job_id] else RETENTION):
                continue
        remove_quietly(path)
        if job_id in known:
            update_entry(job_id, path=None)

    trim_history()


def trim_history():
    """Keep the newest HISTORY_MAX entries per user.

    A row is a few bytes, but without a ceiling the list grows for the life of
    the instance. Pinned entries are never trimmed: pinning says keep it.
    """
    with connect() as conn:
        stale = conn.execute(
            "SELECT job_id, path FROM entries WHERE pinned = 0 AND job_id NOT IN ("
            "  SELECT job_id FROM ("
            "    SELECT job_id, row_number() OVER ("
            "      PARTITION BY owner ORDER BY created_at DESC) AS rank FROM entries"
            "  ) WHERE rank <= ?)", (HISTORY_MAX,)).fetchall()
        for row in stale:
            if row["path"]:
                remove_quietly(row["path"])
            conn.execute("DELETE FROM entries WHERE job_id = ?", (row["job_id"],))


def janitor():
    while True:
        try:
            sweep_downloads()
        except Exception as e:
            app.logger.warning("sweep failed: %s", e)
        time.sleep(SWEEP_INTERVAL)


threading.Thread(target=janitor, daemon=True).start()


def run_download(job_id, url, format_choice, format_id, title, max_height=None):
    out_template = os.path.join(DOWNLOAD_DIR, f"{job_id}.%(ext)s")

    cmd = ["yt-dlp", "--no-playlist", "-o", out_template]

    if format_choice == "audio":
        cmd += ["-x", "--audio-format", "mp3"]
    elif format_id:
        # Prefer m4a audio: Opus is legal in an mp4 container but Apple devices
        # read it poorly, and the merge is a stream copy either way.
        cmd += ["-f", f"{format_id}+bestaudio[ext=m4a]/bestaudio/best",
                "--merge-output-format", "mp4"]
    elif max_height:
        # The feed asks for a height rather than a format id: it never looked
        # the video up, so it has no ids to choose from.
        cmd += ["-f", f"bestvideo[height<={max_height}]+bestaudio[ext=m4a]/"
                      f"bestvideo[height<={max_height}]+bestaudio/"
                      f"best[height<={max_height}]/best",
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


def youtube_videos_url(url):
    """Turn any supported channel URL into its Videos tab.

    A channel home page is itself a playlist of tabs (Videos, Shorts, Live),
    which is what yt-dlp returns when asked for it directly. The Videos tab is
    the chronological feed we want instead.
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
    return urlunparse(parsed._replace(path="/" + "/".join(parts + ["videos"]),
                                      query="", fragment=""))


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
    cmd = ["yt-dlp", "--no-playlist", "-j", "--", *urls]
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
    cmd = ["yt-dlp", "--flat-playlist", "--playlist-end", str(count or FEED_DEFAULTS["videos"]),
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


def refresh_subscription(owner, url, channel_id=None):
    known = {}
    if channel_id:
        with connect() as conn:
            row = conn.execute("SELECT videos FROM subscriptions "
                               "WHERE owner = ? AND channel_id = ?",
                               (owner, channel_id)).fetchone()
        if row:
            known = {v["id"]: v for v in json.loads(row["videos"]) if v.get("id")}
    channel = fetch_channel(url, known, get_settings(owner)["videos"])
    with connect() as conn:
        conn.execute("INSERT INTO subscriptions "
                     "(owner, channel_id, channel_url, title, thumbnail, videos, refreshed_at) "
                     "VALUES (?, ?, ?, ?, ?, ?, ?) "
                     "ON CONFLICT(owner, channel_id) DO UPDATE SET "
                     "channel_url = excluded.channel_url, title = excluded.title, "
                     "thumbnail = excluded.thumbnail, videos = excluded.videos, "
                     "refreshed_at = excluded.refreshed_at",
                     (owner, channel["channel_id"], channel["channel_url"], channel["title"],
                      channel["thumbnail"], json.dumps(channel["videos"]), time.time()))
    return channel


def page_context():
    """What the header needs. Rendered server-side: the identity is known here,
    so asking for it from the browser only bought a flash of empty header."""
    return {"auth": AUTH_MODE, "user": current_user(),
            "admin": is_admin(), "logout_url": LOGOUT_URL}


@app.route("/")
def index():
    return render_template("index.html", page="home", **page_context())


@app.route("/feed")
def feed_page():
    return render_template("feed.html", page="feed", **page_context())


@app.route("/api/feed")
def feed():
    owner = current_user()
    with connect() as conn:
        rows = conn.execute("SELECT * FROM subscriptions WHERE owner = ? "
                            "ORDER BY title COLLATE NOCASE", (owner,)).fetchall()
    channels = []
    videos = []
    for row in rows:
        channel = dict(row)
        channel["videos"] = json.loads(channel["videos"])
        channels.append(channel)
        videos.extend({**video, "channel": row["title"], "channel_id": row["channel_id"]}
                      for video in channel["videos"])
    # YYYYMMDD sorts correctly as a string. Unknown dates naturally sink.
    videos.sort(key=lambda video: video["upload_date"], reverse=True)
    return jsonify({"channels": channels, "videos": videos,
                    "settings": get_settings(owner),
                    "limits": {"videos_max": FEED_VIDEOS_MAX,
                               "qualities": FEED_QUALITIES}})


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
    owner = current_user()
    url = (request.json or {}).get("url", "").strip()
    if not is_safe_url(url) or not youtube_videos_url(url):
        return jsonify({"error": "Please enter a YouTube channel URL"}), 400
    try:
        return jsonify(refresh_subscription(owner, url))
    except subprocess.TimeoutExpired:
        return jsonify({"error": "Timed out fetching channel"}), 400
    except Exception as e:
        return jsonify({"error": str(e)}), 400


@app.route("/api/feed/refresh", methods=["POST"])
def refresh_feed():
    """Refresh one channel per call.

    Refreshing every channel in a single request took as long as the slowest
    lookup times the channel count, with nothing on screen in the meantime and
    the worker timeout waiting at the end of it.
    """
    owner = current_user()
    channel_id = (request.json or {}).get("channel_id")
    with connect() as conn:
        row = conn.execute("SELECT channel_url FROM subscriptions "
                           "WHERE owner = ? AND channel_id = ?",
                           (owner, channel_id)).fetchone()
    if row is None:
        return jsonify({"error": "Unknown channel"}), 404
    try:
        refresh_subscription(owner, row["channel_url"], channel_id)
        return jsonify({"ok": True})
    except subprocess.TimeoutExpired:
        return jsonify({"error": "Timed out"}), 400
    except Exception as e:
        return jsonify({"error": str(e)}), 400


@app.route("/api/feed/subscriptions/<channel_id>", methods=["DELETE"])
def unsubscribe(channel_id):
    with connect() as conn:
        conn.execute("DELETE FROM subscriptions WHERE owner = ? AND channel_id = ?",
                     (current_user(), channel_id))
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
        rows = conn.execute("SELECT * FROM entries ORDER BY created_at DESC").fetchall()

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


@app.route("/api/admin/sweep", methods=["POST"])
def admin_sweep():
    require_admin()
    sweep_downloads()
    return jsonify({"ok": True})


@app.route("/api/admin/entries/<job_id>", methods=["DELETE"])
def admin_delete_entry(job_id):
    require_admin()
    row = get_entry(job_id)
    if row is None:
        return jsonify({"error": "Not found"}), 404
    if row["path"]:
        remove_quietly(row["path"])
    with connect() as conn:
        conn.execute("DELETE FROM entries WHERE job_id = ?", (job_id,))
    return jsonify({"ok": True})


@app.route("/api/entries")
def list_entries():
    owner = current_user()
    with connect() as conn:
        rows = conn.execute(
            "SELECT * FROM entries WHERE owner = ? ORDER BY created_at", (owner,)
        ).fetchall()
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
    if row["path"]:
        remove_quietly(row["path"])
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

    cmd = ["yt-dlp", "--no-playlist", "-j", "--", url]
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=60)
        if result.returncode != 0:
            return jsonify({"error": result.stderr.strip().split("\n")[-1]}), 400

        info = parse_ytdlp_json(result.stdout)

        # A live stream has no end, so the download would run into the 300s
        # timeout and fail with something unreadable. Refuse it now instead.
        if info.get("live_status") in ("is_live", "is_upcoming"):
            return jsonify({"error": "This is a live stream, not a finished video"}), 400

        # Build quality options, keeping the best format per resolution
        best_by_height = {}
        for f in info.get("formats", []):
            height = f.get("height")
            if height and f.get("vcodec", "none") != "none":
                tbr = f.get("tbr") or 0
                if height not in best_by_height or tbr > (best_by_height[height].get("tbr") or 0):
                    best_by_height[height] = f

        formats = []
        for height, f in best_by_height.items():
            formats.append({
                "id": f["format_id"],
                "label": f"{height}p",
                "height": height,
                # Video stream only, and often an estimate. It is an order of
                # magnitude, not an accounting figure.
                "size": f.get("filesize") or f.get("filesize_approx"),
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

    cmd = ["yt-dlp", "--flat-playlist", "--playlist-end", str(PLAYLIST_MAX + 1),
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
                " upload_date, description, format, format_id, status, created_at)"
                " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (job_id, owner, url, title, data.get("thumbnail", ""),
                 data.get("uploader", ""), data.get("upload_date", ""),
                 data.get("description", ""), format_choice, format_id,
                 "downloading", time.time()))

    thread = threading.Thread(target=run_download,
                              args=(job_id, url, format_choice, format_id, title,
                                    max_height))
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


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 8899))
    host = os.environ.get("HOST", "127.0.0.1")
    app.run(host=host, port=port)
