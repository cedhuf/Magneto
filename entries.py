"""The downloader itself: ask, fetch, list, play, keep, delete."""

import os
import json
import re
import subprocess
import threading
import time
import uuid
from flask import Blueprint, request, jsonify, send_file
import config
from db import connect, get_entry, update_entry
from auth import current_user
from media import drop_file, entry_json, is_safe_url, parse_ytdlp_json, run_download, seconds_left, twin_of, variant_of

bp = Blueprint("entries", __name__)


@bp.route("/api/entries")
def list_entries():
    owner = current_user()
    with connect() as conn:
        rows = conn.execute(
            "SELECT * FROM entries WHERE owner = ? AND kind = 'video' "
            "ORDER BY created_at", (owner,)).fetchall()
    return jsonify({"entries": [entry_json(r) for r in rows], "user": owner})


@bp.route("/api/entries/<job_id>/pin", methods=["POST"])
def pin_entry(job_id):
    row = get_entry(job_id, current_user())
    if row is None:
        return jsonify({"error": "Not found"}), 404
    pinned = 1 if request.json.get("pinned") else 0
    update_entry(job_id, pinned=pinned)
    return jsonify(entry_json(get_entry(job_id)))


@bp.route("/api/entries/<job_id>", methods=["DELETE"])
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


@bp.route("/api/info", methods=["POST"])
def get_info():
    owner = current_user()
    data = request.json
    url = data.get("url", "").strip()
    if not url:
        return jsonify({"error": "No URL provided"}), 400
    if not is_safe_url(url):
        return jsonify({"error": "Invalid URL"}), 400

    cmd = [*config.YTDLP, "--no-playlist", "-j", "--", url]
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


@bp.route("/api/playlist", methods=["POST"])
def get_playlist_info():
    current_user()
    data = request.json
    url = data.get("url", "").strip()
    if not url:
        return jsonify({"error": "No URL provided"}), 400
    if not is_safe_url(url):
        return jsonify({"error": "Invalid URL"}), 400

    cmd = [*config.YTDLP, "--flat-playlist", "--playlist-end", str(config.PLAYLIST_MAX + 1),
           "-J", "--", url]
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=60)
        if result.returncode != 0:
            return jsonify({"error": result.stderr.strip().split("\n")[-1]}), 400

        info = json.loads(result.stdout)
        entries = info.get("entries", [])
        urls = [entry.get("url") for entry in entries if entry.get("url")]
        return jsonify({"urls": urls[:config.PLAYLIST_MAX],
                        "truncated": len(urls) > config.PLAYLIST_MAX,
                        "limit": config.PLAYLIST_MAX})
    except subprocess.TimeoutExpired:
        return jsonify({"error": "Timed out fetching playlist info"}), 400
    except Exception as e:
        return jsonify({"error": str(e)}), 400


@bp.route("/api/download", methods=["POST"])
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


@bp.route("/api/status/<job_id>")
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


@bp.route("/api/stream/<job_id>")
def stream_file(job_id):
    row = get_entry(job_id, current_user())
    if row is None or not row["path"] or not os.path.exists(row["path"]):
        return jsonify({"error": "File not ready"}), 404
    # Inline rather than an attachment, and conditional so the browser can seek
    # with Range requests instead of pulling the whole file first.
    return send_file(row["path"], conditional=True)


@bp.route("/api/file/<job_id>")
def download_file(job_id):
    row = get_entry(job_id, current_user())
    if row is None or not row["path"] or not os.path.exists(row["path"]):
        return jsonify({"error": "File not ready"}), 404
    return send_file(row["path"], as_attachment=True, download_name=row["filename"])
