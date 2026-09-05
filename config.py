"""Every knob, read from the environment once.

Imported as a module rather than by name so that changing a value in a test
changes it everywhere, which is what a setting is."""

import os
import time


DOWNLOAD_DIR = os.path.join(os.path.dirname(__file__), "downloads")


DATA_DIR = os.path.join(os.path.dirname(__file__), "data")


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


# One clock per platform, and its own value: the pollers already run side by
# side, so a provider that tolerates being asked more often should be asked more
# often, without that spending anybody else's patience. TikTok falls back to
# YouTube's spacing rather than to a number of its own invention.
POLL = {
    "youtube": FEED_POLL,
    "tiktok": int(os.environ.get("RECLIP_TIKTOK_POLL", FEED_POLL)),
}


FEED_TTL = int(os.environ.get("RECLIP_FEED_TTL", 6 * 3600))


FEED_COOLDOWN = int(os.environ.get("RECLIP_FEED_COOLDOWN", 600))


# One ceiling per platform, not one for the lot: what a ceiling protects is one
# provider's patience, and following 300 YouTube channels is not the same cost
# nor the same risk as following 150 of each. A platform added later gets its
# own entry rather than a share of somebody else's.
CHANNELS_MAX = {
    "youtube": int(os.environ.get("RECLIP_FEED_CHANNELS_MAX", 30)),
    "tiktok": int(os.environ.get("RECLIP_TIKTOK_ACCOUNTS_MAX", 30)),
}


# Both off unless asked for: they are the only parts of the app that talk to
# YouTube on their own, and an instance that only downloads what it is given
# should not be doing that in the background.
def enabled(name):
    return os.environ.get(name, "0") not in ("0", "false", "no", "")


FEED_ENABLED = enabled("RECLIP_FEED")


# Shorts come from the channels followed on the feed page, so there is nothing
# to show without it.
SHORTS_ENABLED = FEED_ENABLED and enabled("RECLIP_SHORTS")


# A short is downloaded when it is watched, and a watched clip leaves the reel,
# so what the disk holds is what one person actually watched in a day rather
# than everything their accounts listed. That is bounded by use, which is why
# this can sit at the same day as a download instead of an hour.
SHORTS_RETENTION = int(os.environ.get("RECLIP_SHORTS_RETENTION", 24 * 3600))


# A clip that has fallen out of every listing can never come back into the reel,
# so the row saying it was watched stops meaning anything. A week is far past
# the point where that is true for every account.
SEEN_RETENTION = int(os.environ.get("RECLIP_SEEN_RETENTION", 7 * 24 * 3600))


# TikTok has its own page, its own accounts and its own switch: it shares the
# player and the outbound budget with the shorts page, nothing else.
TIKTOK_ENABLED = enabled("RECLIP_TIKTOK")


# A share hands a file to whoever holds the link, so it is off unless an
# instance asks for it, and it only means anything once the reverse proxy
# excludes /s/ from its forward auth. The link is the whole credential: it can
# be forwarded, so the expiry is the real setting, not a formality.
SHARE_ENABLED = enabled("RECLIP_SHARE")


SHARE_TTL = int(os.environ.get("RECLIP_SHARE_TTL", 48 * 3600))


SHARE_MAX = int(os.environ.get("RECLIP_SHARE_MAX", 10))


# A pin does not exempt a file, it moves its deadline within a limit the admin
# still owns. Otherwise the disk stops being bounded.
PIN_RETENTION = int(os.environ.get("RECLIP_PIN_RETENTION", 30 * 24 * 3600))


HISTORY_MAX = int(os.environ.get("RECLIP_HISTORY_MAX", 200))


SWEEP_INTERVAL = 60


# The commit this image was built from, stamped at build time. Falling back to
# the date of the code itself is enough to answer the only question anyone asks
# of it: is what I am looking at the version I just deployed?
VERSION = os.environ.get("RECLIP_VERSION") or time.strftime(
    "%Y-%m-%d %H:%M", time.localtime(os.path.getmtime(__file__)))


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
