"""Public links. Nothing here asks who is reading, which is the point."""

import os
import secrets
import time
from flask import Blueprint, request, jsonify, send_file, render_template, abort, make_response, current_app
import config
from db import connect, get_entry
from auth import current_user

bp = Blueprint("share", __name__)


# Sharing: a token is the whole credential, so it names its own file and never
# takes a job id or a user from the caller. Nothing under /s/ asks who is
# reading, which is the point, and nothing under it leads anywhere else.
def shared_entry(token):
    with connect() as conn:
        row = conn.execute(
            "SELECT e.* FROM shares s JOIN entries e ON e.job_id = s.job_id "
            "WHERE s.token = ? AND s.expires_at > ?",
            (token, time.time())).fetchone()
    if row is None or not row["path"] or not os.path.exists(row["path"]):
        return None
    return row


def unindexed(response):
    response.headers["X-Robots-Tag"] = "noindex, nofollow"
    response.headers["Referrer-Policy"] = "no-referrer"
    return response


# What the shared page is allowed to load, by name rather than by path: /static
# is behind the proxy's authentication, so these few files are served again from
# under /s. A fixed table, so no name from the URL ever reaches the filesystem.
SHARED_ASSETS = {
    "style.css": ("shared.css", "text/css"),
    "mono.woff2": ("fonts/dmmono-400-latin.woff2", "font/woff2"),
    "serif.woff2": ("fonts/instrumentserif-400-latin.woff2", "font/woff2"),
}


@bp.route("/s/asset/<name>")
def shared_asset(name):
    found = SHARED_ASSETS.get(name)
    if not found:
        abort(404)
    path = os.path.join(current_app.static_folder, found[0])
    response = make_response(send_file(path, mimetype=found[1]))
    response.headers["Cache-Control"] = "public, max-age=86400"
    return unindexed(response)


@bp.route("/s/<token>")
def shared_page(token):
    row = shared_entry(token)
    if row is None:
        abort(404)
    return unindexed(make_response(render_template(
        "shared.html", token=token, title=row["title"], uploader=row["uploader"],
        kind=row["kind"])))


@bp.route("/s/<token>/stream")
def shared_stream(token):
    row = shared_entry(token)
    if row is None:
        abort(404)
    # Conditional, so a phone can seek instead of pulling the whole file.
    return unindexed(make_response(send_file(row["path"], conditional=True)))


@bp.route("/api/share/<job_id>", methods=["POST"])
def create_share(job_id):
    """Reuses the live link rather than minting a second one: two links to the
    same file are two things to revoke and one more chance to miss one."""
    owner = current_user()
    row = get_entry(job_id, owner)
    if row is None or not row["path"] or not os.path.exists(row["path"]):
        return jsonify({"error": "File not ready"}), 404
    now = time.time()
    with connect() as conn:
        conn.execute("DELETE FROM shares WHERE expires_at <= ?", (now,))
        live = conn.execute(
            "SELECT token, expires_at FROM shares WHERE job_id = ? AND owner = ?",
            (job_id, owner)).fetchone()
        if live:
            return jsonify({"url": f"/s/{live['token']}",
                            "expires_in": int(live["expires_at"] - now)})
        held = conn.execute("SELECT count(*) FROM shares WHERE owner = ?",
                            (owner,)).fetchone()[0]
        if held >= config.SHARE_MAX:
            return jsonify({"error": f"At most {config.SHARE_MAX} links at a time"}), 400
        token = secrets.token_urlsafe(16)
        conn.execute("INSERT INTO shares (token, job_id, owner, created_at, expires_at) "
                     "VALUES (?, ?, ?, ?, ?)", (token, job_id, owner, now, now + config.SHARE_TTL))
    return jsonify({"url": f"/s/{token}", "expires_in": config.SHARE_TTL})


@bp.route("/api/share/<job_id>", methods=["DELETE"])
def revoke_share(job_id):
    """The file goes back to its own deadline, and may be swept within the hour
    if it was a short."""
    owner = current_user()
    with connect() as conn:
        conn.execute("DELETE FROM shares WHERE job_id = ? AND owner = ?", (job_id, owner))
    return jsonify({"ok": True})
