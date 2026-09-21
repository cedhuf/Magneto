"""The shorts page: one more slot in the same rotation, never one more rate.
And none of it exists while both switches are off."""
import json
import os
import sys
import tempfile
import time
from unittest import mock

DB = os.path.join(tempfile.mkdtemp(), "t.db")
os.environ["MAGNETO_DB"] = DB
os.environ["MAGNETO_DOWNLOADS"] = tempfile.mkdtemp()
os.environ["MAGNETO_FEED"] = "1"
os.environ["MAGNETO_SHORTS"] = "1"
os.environ["MAGNETO_SHORTS_RETENTION"] = "60"
REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, REPO)
import app  # noqa: E402
import config  # noqa: E402
import db  # noqa: E402
import feed  # noqa: E402
import media  # noqa: E402

client = app.app.test_client()
DL = config.DOWNLOAD_DIR

CHANNEL = {"channel_id": "UC1", "id": "UC1", "channel": "A channel", "entries": [
    {"id": "v1", "url": "https://www.youtube.com/watch?v=v1", "title": "Video"}]}
SHORTS = {"entries": [
    {"id": f"s{n}", "url": f"https://www.youtube.com/shorts/s{n}", "title": f"Short {n}"}
    for n in range(3)]}


def run_returns(payload):
    return mock.patch("subprocess.run",
                      return_value=mock.Mock(returncode=0, stdout=json.dumps(payload), stderr=""))


with run_returns(CHANNEL):
    assert client.post("/api/feed/subscriptions",
                       json={"url": "https://www.youtube.com/@some"}).status_code == 200

# Listing shorts resolves no video: a single call, on the targeted tab.
with run_returns(SHORTS) as run:
    feed.refresh_shorts("https://www.youtube.com/@some/videos", "UC1")
assert run.call_count == 1, f"{run.call_count} outbound calls to list shorts"
argv = run.call_args[0][0]
assert argv[-1].endswith("/shorts") and "--flat-playlist" in argv, argv
assert "-j" not in argv, "per-video resolution is the watched call, it must not happen"
print("ok: listing shorts is one listing call and nothing else")

d = client.get("/api/shorts").get_json()
assert [s["title"] for s in d["clips"]] == ["Short 0", "Short 1", "Short 2"], d["clips"]
assert all(s["uploader"] == "A channel" and s["job_id"] is None for s in d["clips"]), d
print("ok: the page renders the shorts, none downloaded in advance")

# Everything arrives dated zero after an import: without a tie-break, the queue
# would do the 88 Videos tabs before the first Shorts tab, hours of empty page.
with db.connect() as conn:
    conn.execute("UPDATE channels SET refreshed_at = 0, shorts_refreshed_at = 0")
seen = []
for _ in range(4):
    slot = feed.stalest_slot("youtube")
    seen.append(slot["tab"])
    feed.BUDGETS["youtube"].last_tab = slot["tab"]
assert seen == ["videos", "shorts", "videos", "shorts"], seen
print("ok: on a tie, both tabs alternate instead of starving")

# Both tabs share one queue: the rate does not change, freshness does.
with db.connect() as conn:
    conn.execute("UPDATE channels SET refreshed_at = ?, shorts_refreshed_at = 0", (time.time(),))
slot = feed.stalest_slot("youtube")
assert slot["tab"] == "shorts", dict(slot)
with db.connect() as conn:
    conn.execute("UPDATE channels SET shorts_refreshed_at = ?, refreshed_at = 0", (time.time(),))
assert feed.stalest_slot("youtube")["tab"] == "videos"
print("ok: one queue for both tabs, the stalest goes first")

# A downloaded short stays out of the downloads list.
with mock.patch("threading.Thread"):
    r = client.post("/api/download", json={"url": "https://www.youtube.com/shorts/s0",
                                           "format": "video", "kind": "short",
                                           "title": "Short 0", "max_height": 720})
job = r.get_json()["job_id"]
assert [e["job_id"] for e in client.get("/api/entries").get_json()["entries"]] == [], "a short leaked into the downloads"
assert db.get_entry(job)["kind"] == "short"
print("ok: a short does not show in the ordinary downloads")

# Its retention is its own, much shorter, and it cannot be pinned.
path = os.path.join(DL, f"{job}.mp4")
open(path, "wb").write(b"x" * 2048)
db.update_entry(job, status="done", path=path, filename="s.mp4")
row = db.get_entry(job)
assert media.retention_for(row) == 60, media.retention_for(row)
assert 0 < media.seconds_left(row) <= 60
print("ok: the short has its own deadline, not the downloads one")

# The admin sees it on one aggregate row, and purges it without touching the rest.
boss = client.get("/api/admin/overview").get_json()
assert boss["shorts"] == {"entries": 1, "bytes": 2048, "retention": 60, "enabled": True}, boss["shorts"]
assert all(e["job_id"] != job for e in boss["entries"]), "the short is listed with the downloads"
assert client.delete("/api/admin/shorts").get_json() == {"entries": 1}
assert db.get_entry(job) is None and not os.path.exists(path)
print("ok: admin aggregates the shorts on one row and purges them alone")

# And without the switches, none of this exists.
config.FEED_ENABLED = config.SHORTS_ENABLED = False
for path in ("/shorts", "/api/shorts", "/feed", "/api/feed"):
    assert client.get(path).status_code == 404, path
config.FEED_ENABLED = True
assert client.get("/feed").status_code == 200 and client.get("/shorts").status_code == 404
print("ok: closed by default, page and API are 404, and shorts depend on the feed")
