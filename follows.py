"""Following, whatever the provider: the page, the queue state, the refresh."""

import subprocess
import time
from flask import Blueprint, request, jsonify, render_template
import config
from db import connect
from auth import current_user, page_context
from feed import PROVIDERS, channel_call_allowed, note_failure, refresh_shorts

bp = Blueprint("follows", __name__)


def provider_state(owner, provider):
    """What one provider costs right now.

    The ceiling on its own says nothing anybody can act on. What a round takes
    does: it is the delay between a video being published and this instance
    knowing about it, and it is what says whether following more is worth it.
    """
    platform = provider["platform"]
    with connect() as conn:
        rows = conn.execute(
            "SELECT c.channel_id, c.title, c.refreshed_at, c.shorts_refreshed_at, "
            "c.has_videos, c.has_shorts FROM channels c "
            "JOIN follows f ON f.channel_id = c.channel_id "
            "WHERE f.owner = ? AND c.platform = ? ORDER BY c.title COLLATE NOCASE",
            (owner, platform)).fetchall()
    # A channel holds one slot per list its provider offers and its own row still
    # has. A tab found not to exist holds none.
    tabs = []
    if provider["videos_enabled"]:
        tabs.append("has_videos")
    if provider["upright_enabled"]:
        tabs.append("has_shorts")
    slots = sum(bool(row[tab]) for row in rows for tab in tabs)
    # The list a provider's own page reads is the one this page reports on.
    listed = "refreshed_at" if provider["videos_enabled"] else "shorts_refreshed_at"
    seen_tab = "has_videos" if provider["videos_enabled"] else "has_shorts"
    return {"platform": platform,
            **{k: v for k, v in provider.items() if isinstance(v, (str, bool))},
            "items": [{"channel_id": r["channel_id"], "title": r["title"],
                       "fetched": r[listed], "failed": not r[seen_tab]} for r in rows],
            "followed": len(rows), "limit": config.CHANNELS_MAX[platform],
            "slots": slots, "round": slots * config.POLL[platform],
            "every": config.POLL[platform],
            "never": sum(1 for r in rows if not r[listed] and r[seen_tab])}


@bp.route("/api/seen", methods=["POST"])
def mark_seen():
    """Recorded when a clip is left, never when it is reached: the one being
    watched is not finished, and leaving it unmarked is what puts the reader
    back on it after a reload."""
    owner = current_user()
    url = (request.json or {}).get("url", "")
    if not isinstance(url, str) or not url.strip():
        return jsonify({"error": "No clip"}), 400
    with connect() as conn:
        conn.execute("INSERT INTO seen (owner, url, at) VALUES (?, ?, ?) "
                     "ON CONFLICT(owner, url) DO UPDATE SET at = excluded.at",
                     (owner, url.strip(), time.time()))
    return jsonify({"ok": True})


@bp.route("/following")
def following_page():
    return render_template("following.html", page="following", **page_context())


@bp.route("/api/following")
def following():
    """Every provider in one place: following is one act, not a page's feature."""
    owner = current_user()
    live = [p for p in PROVIDERS.values() if p["videos_enabled"] or p["upright_enabled"]]
    return jsonify({"providers": [provider_state(owner, p) for p in live]})


@bp.route("/api/feed/refresh", methods=["POST"])
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
            "SELECT c.channel_url, c.platform, c.refreshed_at, c.shorts_refreshed_at "
            "FROM channels c JOIN follows f ON f.channel_id = c.channel_id "
            "WHERE f.owner = ? AND c.channel_id = ?", (owner, channel_id)).fetchone()
    if row is None:
        return jsonify({"error": "Unknown channel"}), 404
    # A provider with no long videos has one list, the upright one, and it is
    # that lookup and that clock rather than the feed's.
    upright = PROVIDERS[row["platform"]]["refresh_videos"] is None
    last = row["shorts_refreshed_at"] if upright else row["refreshed_at"]
    # Clicking twice must not cost two lookups, and a page full of channels must
    # not become a burst of them.
    if not force and time.time() - last < config.FEED_COOLDOWN:
        return jsonify({"ok": True, "skipped": "recent"})
    if not force and not channel_call_allowed(row["platform"]):
        return jsonify({"ok": True, "skipped": "busy"})
    try:
        if upright:
            refresh_shorts(row["channel_url"], channel_id, row["platform"])
        else:
            PROVIDERS[row["platform"]]["refresh_videos"](row["channel_url"], channel_id)
        # A tab the poller gave up on is worth one more try when someone asks
        # for it by hand, otherwise dropping it is a door that never reopens.
        flag = "has_shorts" if upright else "has_videos"
        with connect() as conn:
            conn.execute(f"UPDATE channels SET {flag} = 1 WHERE channel_id = ?",
                         (channel_id,))
        return jsonify({"ok": True})
    except subprocess.TimeoutExpired:
        return jsonify({"error": "Timed out"}), 400
    except Exception as e:
        # Recorded like the poller's own failures, or a channel asked for by
        # hand would keep saying it was never read and never say why.
        note_failure({"channel_id": channel_id,
                      "tab": "shorts" if upright else "videos"}, e)
        return jsonify({"error": str(e)}), 400


@bp.route("/api/feed/subscriptions/<channel_id>", methods=["DELETE"])
def unsubscribe(channel_id):
    with connect() as conn:
        conn.execute("DELETE FROM follows WHERE owner = ? AND channel_id = ?",
                     (current_user(), channel_id))
        # A channel nobody follows any more stops being refreshed, and stops
        # taking space.
        conn.execute("DELETE FROM channels WHERE channel_id NOT IN "
                     "(SELECT channel_id FROM follows)")
    return jsonify({"ok": True})
