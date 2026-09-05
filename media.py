"""Files: what to fetch, how long to keep it, and the sweep that enforces it."""

import glob
import json
import logging
import os
import re
import shutil
import subprocess
import threading
import time
from urllib.parse import urlparse, urlunparse
import config
from db import connect, live_shares, update_entry


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


def retention_for(row, shares=None):
    """A short is watched once, in the minutes after it is fetched, and never
    pinned: it has its own, much shorter deadline.

    A file someone has shared outlives all of that until the link does. A short
    lasts an hour, so without this a link handed out at noon would be dead by
    one, which is worse than not being able to share at all.
    """
    if row["kind"] == "short":
        ttl = config.SHORTS_RETENTION
    else:
        ttl = config.PIN_RETENTION if row["pinned"] else config.RETENTION
    until = (shares if shares is not None else live_shares()).get(row["job_id"])
    if until and row["path"]:
        try:
            ttl = max(ttl, until - os.path.getmtime(row["path"]))
        except OSError:
            pass
    return ttl


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
    """Delete files past config.RETENTION, and files no row claims.

    The entry outlives its file: it keeps the title and the URL so the download
    can be started again, which costs a row rather than gigabytes.
    """
    now = time.time()
    with connect() as conn:
        conn.execute("DELETE FROM seen WHERE at < ?", (now - config.SEEN_RETENTION,))
        # A file can be referenced by several entries, so the deadline is keyed
        # by path and the most generous reference wins: nobody's pin may be
        # undone by somebody else's expiry.
        deadlines = {}
        shares = live_shares()
        for row in conn.execute(
                "SELECT job_id, path, pinned, kind FROM entries WHERE path IS NOT NULL"):
            ttl = retention_for(row, shares)
            deadlines[row["path"]] = max(deadlines.get(row["path"], 0), ttl)
        # A download in flight has no path yet, and is recognised by its name.
        running = {r["job_id"] for r in
                   conn.execute("SELECT job_id FROM entries WHERE status = 'downloading'")}

    for path in glob.glob(os.path.join(config.DOWNLOAD_DIR, "*")):
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


def janitor():
    while True:
        try:
            sweep_downloads()
        except Exception as e:
            logging.getLogger("reclip").warning("sweep failed: %s", e)
        time.sleep(config.SWEEP_INTERVAL)


def run_download(job_id, url, format_choice, format_id, title, max_height=None,
                 vertical=False):
    out_template = os.path.join(config.DOWNLOAD_DIR, f"{job_id}.%(ext)s")

    cmd = [*config.YTDLP, "--no-playlist", "-o", out_template]

    if format_choice == "audio":
        cmd += ["-x", "--audio-format", "mp3"]
    elif format_id:
        # Prefer m4a audio: Opus is legal in an mp4 container but Apple devices
        # read it poorly, and the merge is a stream copy either way.
        cmd += ["-f", f"{format_id}+bestaudio[ext=m4a]/{format_id}+bestaudio/best",
                "--merge-output-format", "mp4"]
    elif max_height:
        # The feed asks for a size rather than a format id: it never looked the
        # video up, so it has no ids to choose from. A short is filmed upright,
        # where "720p" names the width: bounding its height would ask for a
        # 405x720 copy of a 720x1280 video, or for nothing at all.
        # Two codecs decide whether a file plays at all, and the ladder answers
        # both before it answers anything else. H.264 first, because HEVC is
        # decoded by Apple and almost nobody else: TikTok serves it, and Firefox
        # gives it sound and a black picture. Then a progressive file before
        # merging with whatever audio is left, because that merge can put Opus
        # in an mp4, which an iPhone plays without any sound at all.
        side = "width" if vertical else "height"
        size = f"[{side}<={max_height}]"
        wide = "[vcodec!*=hev][vcodec!*=hvc][vcodec!*=265]"
        cmd += ["-f", f"bestvideo{size}[vcodec^=avc1]+bestaudio[ext=m4a]/"
                      f"best{size}[vcodec^=avc1]/"
                      f"bestvideo{size}{wide}+bestaudio[ext=m4a]/"
                      f"best{size}{wide}/"
                      f"bestvideo{size}+bestaudio/"
                      f"best{size}/best",
                "--merge-output-format", "mp4"]
    else:
        cmd += ["-f", "bestvideo+bestaudio/best", "--merge-output-format", "mp4"]

    cmd += ["--", url]

    try:
        result = subprocess.run(cmd, capture_output=True, text=True,
                                timeout=config.DOWNLOAD_TIMEOUT)
        if result.returncode != 0:
            update_entry(job_id, status="error", error=result.stderr.strip().split("\n")[-1])
            return

        files = glob.glob(os.path.join(config.DOWNLOAD_DIR, f"{job_id}.*"))
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
                     error=f"Download timed out ({config.DOWNLOAD_TIMEOUT // 60} min limit)")
    except Exception as e:
        update_entry(job_id, status="error", error=str(e))


def trim_history():
    """Keep the newest config.HISTORY_MAX entries per user.

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
            "  ) WHERE rank <= ?)", (config.HISTORY_MAX,)).fetchall()
        for row in stale:
            drop_file(row["path"], keeping=row["job_id"])
            conn.execute("DELETE FROM entries WHERE job_id = ?", (row["job_id"],))


threading.Thread(target=janitor, daemon=True).start()
