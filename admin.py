"""What the instance is doing, and the two ways to empty it."""

import glob
import os
import time
import shutil
from flask import Blueprint, jsonify, render_template
import config
from db import connect, get_entry
from auth import page_context, require_admin
from media import drop_file, entry_json, file_size, remove_quietly

bp = Blueprint("admin", __name__)


@bp.route("/admin")
def admin_page():
    require_admin()
    return render_template("admin.html", page="admin", **page_context())


@bp.route("/api/admin/overview")
def admin_overview():
    require_admin()

    on_disk = [p for p in glob.glob(os.path.join(config.DOWNLOAD_DIR, "*"))]
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
        "version": config.VERSION,
        "retention": config.RETENTION,
        "auth": config.AUTH_MODE,
        "pinned": {"entries": len(pinned),
                   "bytes": sum(file_size(r["path"]) for r in pinned if r["path"]),
                   "retention": config.PIN_RETENTION},
        "shorts": {"entries": len(shorts),
                   "bytes": sum(file_size(r["path"]) for r in shorts if r["path"]),
                   "retention": config.SHORTS_RETENTION,
                   "enabled": config.SHORTS_ENABLED},
        # Counted from the directory rather than from the rows, so a file no row
        # claims still shows up in the total.
        "disk": {
            "files": len(on_disk),
            "bytes": sum(file_size(p) for p in on_disk),
            "free": shutil.disk_usage(config.DOWNLOAD_DIR).free,
        },
        "users": users,
        "entries": entries,
    })


@bp.route("/api/admin/purge", methods=["POST"])
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
    for path in glob.glob(os.path.join(config.DOWNLOAD_DIR, "*")):
        if os.path.basename(path).split(".")[0] in running:
            continue
        freed += file_size(path)
        remove_quietly(path)
        files += 1
    return jsonify({"entries": entries, "files": files, "bytes": freed,
                    "running": len(running)})


@bp.route("/api/admin/shorts", methods=["DELETE"])
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


@bp.route("/api/admin/entries/<job_id>", methods=["DELETE"])
def admin_delete_entry(job_id):
    require_admin()
    row = get_entry(job_id)
    if row is None:
        return jsonify({"error": "Not found"}), 404
    drop_file(row["path"], keeping=job_id)
    with connect() as conn:
        conn.execute("DELETE FROM entries WHERE job_id = ?", (job_id,))
    return jsonify({"ok": True})
