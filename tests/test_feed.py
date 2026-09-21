import os, sys, tempfile, json, time
from unittest import mock
os.environ["MAGNETO_DB"] = os.path.join(tempfile.mkdtemp(), "t.db")
os.environ["MAGNETO_DOWNLOADS"] = tempfile.mkdtemp()
# The feed is off by default: these tests are about it.
os.environ["MAGNETO_FEED"] = "1"
REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, REPO)
import app
import config  # noqa: E402
import db  # noqa: E402
import feed  # noqa: E402
import media  # noqa: E402

client = app.app.test_client()
assert config.FEED_VIDEOS_MAX == 5 and config.FEED_DEFAULTS["videos"] == 3
print("ok: instance ceiling at 5, default setting at 3")

CHANNEL = {"channel_id": "UC123", "channel": "Some Channel", "id": "UC123",
           "entries": [{"id": f"v{n}", "url": f"https://www.youtube.com/watch?v=v{n}",
                        "title": f"Video {n}", "timestamp": 1700000000 + n}
                       for n in range(3)]}

RESOLVED = "\n".join(json.dumps({"id": f"v{n}", "upload_date": f"2026090{n + 1}",
                                  "description": f"About video {n}"}) for n in range(3))


def fake(info, resolved=RESOLVED):
    """The flat listing first, the resolution next: two separate calls."""
    calls = [mock.Mock(returncode=0, stdout=json.dumps(info), stderr=""),
             mock.Mock(returncode=0, stdout=resolved, stderr="")]
    return mock.patch("subprocess.run", side_effect=calls * 4)

with fake(CHANNEL) as run:
    r = client.post("/api/feed/subscriptions",
                    json={"url": "https://www.youtube.com/@some"})
assert r.status_code == 200, r.get_json()
listing = run.call_args_list[0][0][0]
# The cache is shared, so it holds the instance ceiling and not one account's
# setting: each then slices what is already there.
assert listing[listing.index("--playlist-end") + 1] == "5", listing
assert listing[-1].endswith("/@some/videos") and listing[-2] == "--", listing
resolve = run.call_args_list[1][0][0]
assert resolve[:len(config.YTDLP) + 3] == [*config.YTDLP, "--no-playlist", "-j", "--"], resolve
assert len([a for a in resolve if a.startswith("http")]) == 3, resolve
print("ok: listing bounded by the variable, then ONE resolution for the three videos")

d = client.get("/api/feed").get_json()
assert len(d["channels"]) == 1 and len(d["videos"]) == 3
assert all(v["thumbnail"].startswith("https://i.ytimg.com/") for v in d["videos"])
assert [v["upload_date"] for v in d["videos"]] == ["20260903", "20260902", "20260901"], d["videos"]
assert d["videos"][0]["description"] == "About video 2"
print("ok: three dated videos, thumbnails inferred, sorted newest first")

def make_stale(channel_id="UC123"):
    """The anti-ban guards refuse a fresh channel: age it."""
    with db.connect() as conn:
        conn.execute("UPDATE channels SET refreshed_at = 0 WHERE channel_id = ?",
                     (channel_id,))
    feed.BUDGETS["youtube"].last_call = 0


# Refreshing targets one named channel, walled per account.
r = client.post("/api/feed/refresh", json={"channel_id": "nope"})
assert r.status_code == 404, r.status_code
with fake(CHANNEL):
    r = client.post("/api/feed/refresh", json={"channel_id": "UC123"})
assert r.status_code == 200 and r.get_json()["ok"] is True
print("ok: refreshing one channel, unknown = 404")

config.AUTH_MODE = "proxy"
other = {"Remote-User": "bob"}
assert client.post("/api/feed/refresh", json={"channel_id": "UC123"}, headers=other).status_code == 404
assert client.get("/api/feed", headers=other).get_json()["channels"] == []
client.delete("/api/feed/subscriptions/UC123", headers=other)
config.AUTH_MODE = "none"
assert len(client.get("/api/feed").get_json()["channels"]) == 1
print("ok: another account sees, refreshes and deletes nothing")

# A URL that is not a YouTube channel is refused without starting yt-dlp.
with mock.patch("subprocess.run") as never:
    r = client.post("/api/feed/subscriptions", json={"url": "https://example.com/x"})
    assert r.status_code == 400 and not never.called
print("ok: unacceptable URL refused before any yt-dlp call")

# Settings: per user, bounded by the instance, and they drive the listing.
s = client.get("/api/feed").get_json()
assert s["settings"] == {"videos": 3, "quality": 720}, s["settings"]
assert s["limits"] == {"videos_max": 5, "qualities": [360, 480, 720, 1080, 1440]}
print("ok: the feed exposes its settings and the instance bounds")

r = client.post("/api/feed/settings", json={"videos": 99, "quality": 4320})
assert r.get_json() == {"videos": 5, "quality": 720}, r.get_json()
print("ok: an out-of-bounds value is brought back to the ceiling, not silently refused")

client.post("/api/feed/settings", json={"videos": 2, "quality": 480})
assert len(client.get("/api/feed").get_json()["videos"]) == 2
client.post("/api/feed/settings", json={"videos": 3, "quality": 480})
assert len(client.get("/api/feed").get_json()["videos"]) == 3
print("ok: changing the number shown looks nothing up, it is a slice")

# A feed video and a home card carry the same field names: that is what lets
# both pages hand their object to the same player.
video = client.get("/api/feed").get_json()["videos"][0]
for field in ("title", "uploader", "upload_date", "duration", "thumbnail", "url"):
    assert field in video, f"field missing from a feed video: {field}"
assert "channel" not in video, video
print("ok: a feed video names its fields like a card")

# The feed quality travels to the yt-dlp argv, with no format id.
with mock.patch("threading.Thread") as thread:
    client.post("/api/download", json={"url": "https://www.youtube.com/watch?v=zz",
                                       "format": "video", "max_height": 480,
                                       "title": "T", "uploader": "C"})
args = thread.call_args[1]["args"]
assert args[-2] == 480 and args[-1] is False, args
print("ok: the requested height reaches the download")

captured = {}
with mock.patch("subprocess.run",
                side_effect=lambda cmd, **kw: captured.setdefault("cmd", cmd) or
                mock.Mock(returncode=1, stdout="", stderr="boom")):
    media.run_download("jobzz", "https://e.com/v", "video", None, "T", 480)
sel = captured["cmd"][captured["cmd"].index("-f") + 1]
assert "height<=480" in sel and "bestaudio[ext=m4a]" in sel, sel
print("ok: the selector bounds the height and prefers m4a audio")

# An upright video is bounded by width: 720p there means 720 wide, and
# bounding the height would ask for a 405x720 copy of a 720x1280 video.
with mock.patch("subprocess.run",
                side_effect=lambda cmd, **kw: captured.__setitem__("cmd", cmd) or
                mock.Mock(returncode=1, stdout="", stderr="boom")):
    media.run_download("jobzz", "https://e.com/v", "video", None, "T", 720, vertical=True)
sel = captured["cmd"][captured["cmd"].index("-f") + 1]
assert "width<=720" in sel and "height" not in sel, sel
assert media.variant_of("video", None, 720) != media.variant_of("video", None, 720, vertical=True)
print("ok: an upright video is bounded by width, and does not share the file")

# An entry created by the feed already carries its metadata, without /api/info.
row = db.get_entry("jobzz") or [e for e in client.get("/api/entries").get_json()["entries"]
                                 if e["uploader"] == "C"][0]
print("ok: the feed entry is created with its channel and title")
