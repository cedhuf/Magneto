"""The Following page: one place to follow, and the budget in view."""
import os
import sys
import tempfile
import time

os.environ["MAGNETO_DB"] = os.path.join(tempfile.mkdtemp(), "t.db")
os.environ["MAGNETO_DOWNLOADS"] = tempfile.mkdtemp()
os.environ["MAGNETO_FEED"] = "1"
os.environ["MAGNETO_SHORTS"] = "1"
os.environ["MAGNETO_TIKTOK"] = "1"
os.environ["MAGNETO_FEED_POLL"] = "300"
REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, REPO)
import app  # noqa: E402
import config  # noqa: E402
import db  # noqa: E402

client = app.app.test_client()
fails = []


def check(label, ok):
    print(f"  {'ok   ' if ok else 'FAIL '} {label}")
    if not ok:
        fails.append(label)


with db.connect() as conn:
    for n in range(3):
        conn.execute("INSERT INTO channels (channel_id, channel_url, title, videos, "
                     "refreshed_at, shorts_refreshed_at) VALUES (?, ?, ?, '[]', ?, 0)",
                     (f"UC{n}", f"https://www.youtube.com/channel/UC{n}", f"Channel {n}",
                      time.time() if n == 0 else 0))
        conn.execute("INSERT INTO follows (owner, channel_id) VALUES ('local', ?)", (f"UC{n}",))
    conn.execute("INSERT INTO channels (channel_id, channel_url, title, videos, platform) "
                 "VALUES ('tiktok:nasa', 'https://www.tiktok.com/@nasa', 'NASA', '[]', 'tiktok')")
    conn.execute("INSERT INTO follows (owner, channel_id) VALUES ('local', 'tiktok:nasa')")

data = client.get("/api/following").get_json()["providers"]
yt = [p for p in data if p["platform"] == "youtube"][0]
tt = [p for p in data if p["platform"] == "tiktok"][0]

check("both providers are there, each with its own",
      yt["followed"] == 3 and tt["followed"] == 1)
check("a YouTube channel takes two slots when both pages are open",
      yt["slots"] == 6)
check("a TikTok account takes only one", tt["slots"] == 1)
check("the full round is given in seconds, ready to be formatted",
      yt["round"] == 6 * 300 and tt["round"] == 300)
check("the never-read ones are counted", yt["never"] == 2)
check("so is the ceiling", yt["limit"] == config.CHANNELS_MAX["youtube"])

# An abandoned tab no longer counts as a slot: that is the expected gain.
with db.connect() as conn:
    conn.execute("UPDATE channels SET has_shorts = 0 WHERE channel_id = 'UC0'")
yt = [p for p in client.get("/api/following").get_json()["providers"]
      if p["platform"] == "youtube"][0]
check("an abandoned tab gives its slot back", yt["slots"] == 5)
check("and no longer counts as never read", yt["never"] == 2)

# The reading pages no longer serve the follows.
check("the shorts page returns no accounts any more",
      "accounts" not in client.get("/api/shorts").get_json())
check("nor does the tiktok page",
      "accounts" not in client.get("/api/tiktok").get_json())

# Closed when nothing reads it.
config.FEED_ENABLED = config.SHORTS_ENABLED = config.TIKTOK_ENABLED = False
check("closed when no page reads anything", client.get("/following").status_code == 404)

if fails:
    sys.exit(1)
print("ok: one place to follow, and what it costs is shown")
