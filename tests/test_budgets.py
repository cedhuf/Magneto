"""One outbound budget per platform.

Spacing exists to avoid being refused by a provider, and a provider only sees
its own traffic. A shared budget made YouTube pay for the curiosity we had for
TikTok, while protecting nothing.
"""
import json
import os
import sys
import tempfile
import threading
import time

os.environ["MAGNETO_DB"] = os.path.join(tempfile.mkdtemp(), "t.db")
os.environ["MAGNETO_DOWNLOADS"] = tempfile.mkdtemp()
os.environ["MAGNETO_FEED"] = "1"
os.environ["MAGNETO_TIKTOK"] = "1"
os.environ["MAGNETO_FEED_CHANNELS_MAX"] = "2"
os.environ["MAGNETO_TIKTOK_ACCOUNTS_MAX"] = "3"
os.environ["MAGNETO_FEED_POLL"] = "300"
os.environ["MAGNETO_TIKTOK_POLL"] = "120"
REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, REPO)
import app  # noqa: E402
import config  # noqa: E402
import feed  # noqa: E402
import tiktok  # noqa: E402
import youtube  # noqa: E402

client = app.app.test_client()
fails = []


def check(label, ok):
    print(f"  {'ok   ' if ok else 'FAIL '} {label}")
    if not ok:
        fails.append(label)


# The ceiling: two per platform, not two in all.
youtube.fetch_channel = lambda url, known, count: {
    "channel_id": url.rsplit("/", 1)[1], "channel_url": url, "title": "c",
    "thumbnail": "", "videos": []}
tiktok.fetch_tiktok = lambda url, count: {
    "channel_id": "tiktok:" + url.rsplit("@", 1)[1], "channel_url": url,
    "title": "t", "videos": []}

for n in ("a", "b"):
    client.post("/api/feed/subscriptions",
                json={"url": f"https://www.youtube.com/channel/UC{n}"})
full = client.post("/api/feed/subscriptions",
                    json={"url": "https://www.youtube.com/channel/UCc"})
check("the YouTube ceiling holds", full.status_code == 400)
r = client.post("/api/tiktok/accounts", json={"url": "https://www.tiktok.com/@nasa"})
check("and does not stop following a TikTok account", r.status_code == 200)
check("the message names the platform", "youtube" in full.get_json()["error"])

# Imports count per platform too.
# Each platform has its own ceiling, with its own value: 300 YouTube channels
# have neither the cost nor the risk of 150 of each.
check("the ceilings are distinct",
      config.CHANNELS_MAX == {"youtube": 2, "tiktok": 3})
r = client.post("/api/tiktok/import", json={"accounts": ["one", "two", "three"]}).get_json()
check("the TikTok import counts TikTok accounts, under the TikTok ceiling",
      r["added"] == 2 and r["full"] is True and r["limit"] == 3)

# Each platform has its cadence, with its own value: both pollers run side by
# side, so a more tolerant provider can be asked more often without spending
# the other's patience.
check("the cadences are distinct", config.POLL == {"youtube": 300, "tiktok": 120})
feed.BUDGETS["tiktok"].last_call = time.time() - 200
check("200 s are enough for TikTok", feed.channel_call_allowed("tiktok") is True)
feed.BUDGETS["youtube"].last_call = time.time() - 200
check("but not YouTube", feed.channel_call_allowed("youtube") is False)

# The clocks are distinct: a YouTube lookup does not space out TikTok.
feed.BUDGETS["youtube"].last_call = time.time()
feed.BUDGETS["tiktok"].last_call = 0
check("YouTube just spoke, so it waits",
      feed.channel_call_allowed("youtube") is False)
check("TikTok asked for nothing, so it may speak",
      feed.channel_call_allowed("tiktok") is True)

# And so are the locks: a TikTok read must not block a YouTube one.
feed.BUDGETS["tiktok"].lock.acquire()
free = feed.BUDGETS["youtube"].lock.acquire(timeout=0.2)
check("the TikTok lock does not close the door on YouTube", free)
if free:
    feed.BUDGETS["youtube"].lock.release()
feed.BUDGETS["tiktok"].lock.release()

# One polling thread per platform switched on, none when everything is off.
check("one queue per platform switched on",
      {p: s["videos_enabled"] or s["upright_enabled"]
       for p, s in feed.PROVIDERS.items()} == {"youtube": True, "tiktok": True})

if fails:
    sys.exit(1)
print("ok: one clock, one lock and one ceiling per platform")
