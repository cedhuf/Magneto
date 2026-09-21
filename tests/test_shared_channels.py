import os, sys, tempfile, json
from unittest import mock

# Two accounts following the same channel, on a shared cache.
DB = os.path.join(tempfile.mkdtemp(), "shared.db")
os.environ["MAGNETO_DB"] = DB
os.environ["MAGNETO_DOWNLOADS"] = tempfile.mkdtemp()
# The feed is off by default: these tests are about it.
os.environ["MAGNETO_FEED"] = "1"
os.environ["MAGNETO_AUTH"] = "proxy"
REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, REPO)
import app
import config  # noqa: E402
import db  # noqa: E402
import feed  # noqa: E402

ONE = json.dumps([{"id": "v1", "title": "One", "url": "u1", "thumbnail": "",
                   "upload_date": "20260101", "description": "", "duration": 10}])
with db.connect() as conn:
    conn.execute("INSERT INTO channels (channel_id, channel_url, title, videos, refreshed_at) "
                 "VALUES ('UC1', 'https://www.youtube.com/@a/videos', 'A', ?, 111)", (ONE,))
    conn.execute("INSERT INTO channels (channel_id, channel_url, title, refreshed_at) "
                 "VALUES ('UC2', 'https://www.youtube.com/@b/videos', 'B', 111)")
    for owner, channel in (("cedric", "UC1"), ("bob", "UC1"), ("bob", "UC2")):
        conn.execute("INSERT INTO follows (owner, channel_id) VALUES (?, ?)", (owner, channel))

with db.connect() as conn:
    channels = conn.execute("SELECT count(*) FROM channels").fetchone()[0]
    follows = conn.execute("SELECT count(*) FROM follows").fetchone()[0]
assert channels == 2 and follows == 3, (channels, follows)
print("ok: 3 follows fit in 2 cached channels and 3 links")

client = app.app.test_client()
ced, bob = {"Remote-User": "cedric"}, {"Remote-User": "bob"}
assert len(client.get("/api/feed", headers=ced).get_json()["channels"]) == 1
assert len(client.get("/api/feed", headers=bob).get_json()["channels"]) == 2
print("ok: each sees their own follows, on a shared cache")

# A single lookup serves both followers.
CH = {"channel_id": "UC1", "id": "UC1", "channel": "A", "entries": []}
with db.connect() as conn:
    conn.execute("UPDATE channels SET refreshed_at = 0")
feed.BUDGETS["youtube"].last_call = 0
with mock.patch("subprocess.run",
                return_value=mock.Mock(returncode=0, stdout=json.dumps(CH), stderr="")) as run:
    r = client.post("/api/feed/refresh", json={"channel_id": "UC1"}, headers=ced)
    assert r.get_json().get("ok"), r.get_json()
    calls_after_first = run.call_count
    r = client.post("/api/feed/refresh", json={"channel_id": "UC1"}, headers=bob)
assert r.get_json().get("skipped") == "recent", r.get_json()
assert run.call_count == calls_after_first, "the second follower started another lookup"
print("ok: refreshing for one benefits the other, without a second call")

# The cache keeps the instance maximum, the display follows the setting.
VIDEOS = [{"id": f"v{n}", "title": f"V{n}", "url": f"u{n}", "thumbnail": "",
           "upload_date": f"2026010{n}", "description": "", "duration": 10} for n in range(1, 6)]
with db.connect() as conn:
    conn.execute("UPDATE channels SET videos = ? WHERE channel_id = 'UC1'", (json.dumps(VIDEOS),))
client.post("/api/feed/settings", json={"videos": 2, "quality": 720}, headers=ced)
client.post("/api/feed/settings", json={"videos": 5, "quality": 720}, headers=bob)
assert len(client.get("/api/feed", headers=ced).get_json()["videos"]) == 2
assert len(client.get("/api/feed", headers=bob).get_json()["videos"]) == 5
print("ok: one cache, two accounts, two numbers shown without a lookup")

# Unfollowing does not deprive the other, but the last one out clears the cache.
client.delete("/api/feed/subscriptions/UC1", headers=bob)
with db.connect() as conn:
    assert conn.execute("SELECT count(*) FROM channels WHERE channel_id='UC1'").fetchone()[0] == 1
client.delete("/api/feed/subscriptions/UC1", headers=ced)
with db.connect() as conn:
    assert conn.execute("SELECT count(*) FROM channels WHERE channel_id='UC1'").fetchone()[0] == 0
print("ok: the cache survives while a follower remains, and goes with the last")

# The "already on the server" flag, in the quality the account picked.
import time as _t
with db.connect() as conn:
    conn.execute("INSERT INTO follows (owner, channel_id) VALUES ('cedric','UC2')")
    conn.execute("UPDATE channels SET videos = ? WHERE channel_id = 'UC2'",
                 (json.dumps([{"id": "vr", "title": "R", "url": "https://y/watch?v=vr",
                               "thumbnail": "", "upload_date": "20260101",
                               "description": "", "duration": 5}]),))
feed = client.get("/api/feed", headers=ced).get_json()["videos"]
assert all(v["ready"] is False for v in feed), feed
print("ok: nothing is announced ready while no file exists")

# A file downloaded by bob, in cedric's quality, makes the video ready for
# cedric too: files are shared.
quality = client.get("/api/feed", headers=ced).get_json()["settings"]["quality"]
p = os.path.join(config.DOWNLOAD_DIR, "feedready1.mp4")
open(p, "w").write("x")
with db.connect() as conn:
    conn.execute("INSERT INTO entries (job_id, owner, url, status, path, filename,"
                 " variant, created_at) VALUES ('feedready1','bob','https://y/watch?v=vr',"
                 " 'done', ?, 'R.mp4', ?, ?)", (p, f"video:h{quality}", _t.time()))
feed = client.get("/api/feed", headers=ced).get_json()["videos"]
assert [v["ready"] for v in feed] == [True], feed
print("ok: a file downloaded by one is announced ready for the other")

# Changing quality changes the answer: it is no longer the same file.
client.post("/api/feed/settings", json={"videos": 5, "quality": 360}, headers=ced)
assert client.get("/api/feed", headers=ced).get_json()["videos"][0]["ready"] is False
print("ok: another quality is not wrongly announced ready")
os.remove(p)
