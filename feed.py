"""What every provider shares: the outbound budget, the queue, the reel.

This module knows there are providers; it never knows which. Each one registers
itself here, so adding a third is a file, not an edit spread over five."""

import json
import logging
import subprocess
from flask import jsonify
import os
import threading
import time
import config
from db import connect, live_shares
from media import variant_of


# Each provider describes itself here, once, at import: what it is called, where
# a URL is added, how its listings are read, and whether its pages are open. The
# queue, the poller and the Following page work from this and never from a list
# of platform names written somewhere else.
PROVIDERS = {}


def register(platform, **spec):
    PROVIDERS[platform] = {"platform": platform, **spec}


class Budget:
    """One platform's outbound allowance: a lock and a clock.

    Spacing exists to avoid being refused by a provider, and a provider only
    sees its own traffic: YouTube does not know what TikTok was asked. Sharing
    one budget made each platform pay for the other's curiosity while
    protecting neither, so every platform holds its own.

    The lock covers a whole lookup, so two refreshes of the same platform can
    never talk to it at once, whoever asked for them.
    """

    def __init__(self):
        self.lock = threading.Lock()
        self.last_call = 0.0
        # Which tab went last, so ties alternate rather than starving one.
        # Only YouTube has two, but every platform carries the field.
        self.last_tab = "shorts"


BUDGETS = {"youtube": Budget(), "tiktok": Budget()}


def channel_call_allowed(platform):
    """Space out lookups of one platform, whatever triggered them."""
    return time.time() - BUDGETS[platform].last_call >= config.POLL[platform]


def get_settings(owner):
    """Per-user feed settings, always within what the instance allows."""
    with connect() as conn:
        row = conn.execute("SELECT * FROM settings WHERE owner = ?", (owner,)).fetchone()
    videos = row["feed_videos"] if row else config.FEED_DEFAULTS["videos"]
    quality = row["feed_quality"] if row else config.FEED_DEFAULTS["quality"]
    return {"videos": max(1, min(videos, config.FEED_VIDEOS_MAX)),
            "quality": quality if quality in config.FEED_QUALITIES else config.FEED_DEFAULTS["quality"]}


def save_settings(owner, videos, quality):
    videos = max(1, min(int(videos), config.FEED_VIDEOS_MAX))
    quality = int(quality)
    if quality not in config.FEED_QUALITIES:
        quality = config.FEED_DEFAULTS["quality"]
    with connect() as conn:
        conn.execute("INSERT INTO settings (owner, feed_videos, feed_quality) "
                     "VALUES (?, ?, ?) ON CONFLICT(owner) DO UPDATE SET "
                     "feed_videos = excluded.feed_videos, "
                     "feed_quality = excluded.feed_quality",
                     (owner, videos, quality))
    return {"videos": videos, "quality": quality}


def slot_query(platform, tab, column, flag):
    return (f"SELECT c.channel_id, c.channel_url, c.platform, '{tab}' AS tab, "
            f"c.{column} AS age FROM channels c "
            "JOIN follows f ON f.channel_id = c.channel_id "
            f"WHERE c.platform = '{platform}' AND c.{flag} = 1")


def stalest_slot(platform):
    """The oldest tab of one platform that somebody still follows.

    A YouTube channel holds two slots, its Videos tab and its Shorts tab; a
    TikTok account holds one, since it has no long videos. Turning shorts on
    therefore halves how often each YouTube tab comes round, it does not double
    how often YouTube is asked.
    """
    cutoff = time.time() - config.FEED_TTL
    spec = PROVIDERS.get(platform)
    queue = []
    if spec and spec["videos_enabled"]:
        queue.append(slot_query(platform, "videos", "refreshed_at", "has_videos"))
    if spec and spec["upright_enabled"]:
        queue.append(slot_query(platform, "shorts", "shorts_refreshed_at", "has_shorts"))
    if not queue:
        return None
    with connect() as conn:
        # A tie goes to the tab that did not go last. Freshly imported channels
        # are all dated zero, so without this the queue does every Videos tab
        # before the first Shorts one: hours before a shorts page shows anything.
        return conn.execute(
            f"SELECT * FROM ({' UNION ALL '.join(queue)}) WHERE age < ? "
            "ORDER BY age, tab = ? LIMIT 1",
            (cutoff, BUDGETS[platform].last_tab)).fetchone()


def note_failure(row, error):
    """A slot that failed must leave the head of the queue, or it holds every
    channel behind it: the queue is ordered by age, so a slot whose age is never
    written is picked again on the next tick, and on every tick after that.

    Not having a tab at all is permanent, so that slot leaves the queue for
    good rather than coming back once a TTL. Everything else is treated as
    passing bad luck and simply waits its turn again.
    """
    column = "shorts_refreshed_at" if row["tab"] == "shorts" else "refreshed_at"
    message = str(error).lower()
    if "does not have a" in message and "tab" in message:
        flag = "has_shorts" if row["tab"] == "shorts" else "has_videos"
        with connect() as conn:
            conn.execute(f"UPDATE channels SET {flag} = 0 WHERE channel_id = ?",
                         (row["channel_id"],))
        return
    with connect() as conn:
        conn.execute(f"UPDATE channels SET {column} = ? WHERE channel_id = ?",
                     (time.time(), row["channel_id"]))


def feed_poller(platform):
    """One tab per tick, oldest first, for one platform.

    This is the whole automatic refresh: no burst when someone opens the page,
    and a ceiling on outbound lookups that does not move with the number of
    users, channels or pages enabled. One of these runs per platform, so a
    platform never waits on another's turn.
    """
    budget = BUDGETS[platform]
    while True:
        time.sleep(config.POLL[platform])
        row = None
        try:
            row = stalest_slot(platform)
            if not row:
                continue
            budget.last_tab = row["tab"]
            if row["tab"] == "shorts":
                refresh_shorts(row["channel_url"], row["channel_id"], row["platform"])
            else:
                PROVIDERS[platform]["refresh_videos"](row["channel_url"], row["channel_id"])
        except Exception as e:
            logging.getLogger("reclip").warning("%s refresh failed: %s", platform, e)
            if row is not None:
                note_failure(row, e)


def refresh_shorts(url, channel_id, platform="youtube"):
    """One account's upright videos, under its own platform's budget."""
    budget = BUDGETS[platform]
    with budget.lock:
        budget.last_call = time.time()
        shorts = PROVIDERS[platform]["list_upright"](url, config.FEED_VIDEOS_MAX)
    with connect() as conn:
        conn.execute("UPDATE channels SET shorts = ?, shorts_refreshed_at = ? "
                     "WHERE channel_id = ?",
                     (json.dumps(shorts), time.time(), channel_id))
    return shorts


def upright_clips(owner, platform, watched=False):
    """Every followed account's upright videos, one from each in turn.

    A round is one video per account, so nobody takes the top of the page, and
    it costs no date: these lists are already newest first, and dating them
    would mean asking the player API about every one of them.

    What has been watched is left out, so scrolling never walks back through it
    and a reload does not fetch it again. Show watched asks for the lot.
    """
    settings = get_settings(owner)
    with connect() as conn:
        rows = conn.execute(
            "SELECT c.channel_id, c.title, c.shorts, c.platform, "
            "c.shorts_refreshed_at, c.has_shorts FROM channels c "
            "JOIN follows f ON f.channel_id = c.channel_id "
            "WHERE f.owner = ? AND c.platform = ? "
            "ORDER BY c.title COLLATE NOCASE", (owner, platform)).fetchall()

    variant = variant_of("video", None, settings["quality"], vertical=True)
    with connect() as conn:
        ready = {r["url"]: r["job_id"] for r in conn.execute(
            "SELECT url, job_id, path FROM entries WHERE variant = ? AND status = 'done' "
            "AND path IS NOT NULL", (variant,)) if os.path.exists(r["path"])}

    with connect() as conn:
        seen = {r["url"] for r in conn.execute(
            "SELECT url FROM seen WHERE owner = ?", (owner,))}

    shared = set(live_shares())
    lists = []
    hidden = 0
    for row in rows:
        clips = json.loads(row["shorts"])[:settings["videos"]]
        if not watched:
            kept = [clip for clip in clips if clip["url"] not in seen]
            hidden += len(clips) - len(kept)
            clips = kept
        lists.append([{**clip, "uploader": row["title"], "platform": row["platform"],
                       "job_id": ready.get(clip["url"]),
                       "seen": clip["url"] in seen,
                       "shared": ready.get(clip["url"]) in shared} for clip in clips])

    interleaved = []
    for rank in range(max((len(one) for one in lists), default=0)):
        for one in lists:
            if rank < len(one):
                interleaved.append(one[rank])
    # How many were left out, so an empty reel can say "you are up to date"
    # rather than "follow some accounts".
    payload = {"clips": interleaved, "quality": settings["quality"],
               "share": config.SHARE_ENABLED, "hidden": hidden, "watched": watched}
    return payload


def followed_count(owner, platform):
    """How many of one platform this account follows.

    Counted per platform because the ceiling protects one provider's patience,
    and a provider only sees its own traffic: following TikTok accounts must
    not cost YouTube channels.
    """
    with connect() as conn:
        return conn.execute(
            "SELECT count(*) FROM follows f JOIN channels c ON c.channel_id = f.channel_id "
            "WHERE f.owner = ? AND c.platform = ?", (owner, platform)).fetchone()[0]


def follow(owner, url, fetch, platform):
    """Record who someone follows, whatever page they follow it from."""
    if followed_count(owner, platform) >= config.CHANNELS_MAX[platform]:
        return jsonify(
            {"error": f"At most {config.CHANNELS_MAX[platform]} {platform} accounts"}), 400
    try:
        channel = fetch(url)
    except subprocess.TimeoutExpired:
        return jsonify({"error": "Timed out fetching channel"}), 400
    except Exception as e:
        return jsonify({"error": str(e)}), 400
    with connect() as conn:
        conn.execute("INSERT OR IGNORE INTO follows (owner, channel_id) VALUES (?, ?)",
                     (owner, channel["channel_id"]))
    return jsonify(channel)


# Started once every provider has registered, which is why this is a call and
# not a line that runs at import: a poller reaches for everything below it, and
# one is started per provider whose pages are open. None at all otherwise:
# nothing must talk to a provider on its own then.
def start_pollers():
    for platform, spec in PROVIDERS.items():
        if spec["videos_enabled"] or spec["upright_enabled"]:
            threading.Thread(target=feed_poller, args=(platform,), daemon=True).start()
