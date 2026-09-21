"""TikTok takes the same path as shorts: one slot in the queue, not two, and
its videos land where the shorts page already looks."""
import json
import os
import sys
import tempfile
import time
from unittest import mock

os.environ["MAGNETO_DB"] = os.path.join(tempfile.mkdtemp(), "t.db")
os.environ["MAGNETO_DOWNLOADS"] = tempfile.mkdtemp()
os.environ["MAGNETO_FEED"] = "1"
os.environ["MAGNETO_SHORTS"] = "1"
os.environ["MAGNETO_TIKTOK"] = "1"
REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, REPO)
import app  # noqa: E402
import config  # noqa: E402
import db  # noqa: E402
import feed  # noqa: E402
import tiktok  # noqa: E402

client = app.app.test_client()

assert tiktok.tiktok_user_url("https://www.tiktok.com/@nasa") == "https://www.tiktok.com/@nasa"
assert tiktok.tiktok_user_url("https://www.tiktok.com/@nasa/video/76798") == "https://www.tiktok.com/@nasa"
assert tiktok.tiktok_user_url("https://tiktok.com/@nasa/") == "https://www.tiktok.com/@nasa"
assert tiktok.tiktok_user_url("https://www.tiktok.com/explore") is None
assert tiktok.tiktok_user_url("https://www.youtube.com/@nasa") is None
print("ok: a video URL or an account URL leads to the same account, the rest is refused")

LISTING = {"id": "nasa", "channel": "NASA", "entries": [
    {"id": f"{n}", "url": f"https://www.tiktok.com/@nasa/video/{n}", "title": f"Clip {n}",
     "duration": 30 + n, "timestamp": 1788103920 + n,
     "thumbnails": [{"url": f"https://p16.tiktokcdn.com/{n}.jpg"}]}
    for n in range(3)]}

with mock.patch("subprocess.run",
                return_value=mock.Mock(returncode=0, stdout=json.dumps(LISTING), stderr="")) as run:
    r = client.post("/api/tiktok/accounts", json={"url": "https://www.tiktok.com/@nasa/video/1"})
assert r.status_code == 200, r.get_json()
assert run.call_count == 1, f"{run.call_count} calls to follow an account"
argv = run.call_args[0][0]
assert argv[-1] == "https://www.tiktok.com/@nasa" and "--flat-playlist" in argv, argv
assert "-j" not in argv, "a listing is enough, TikTok already dates its videos"
print("ok: following a TikTok account is one listing and nothing else")

d = client.get("/api/tiktok").get_json()
assert [c["title"] for c in d["clips"]] == ["Clip 0", "Clip 1", "Clip 2"], d["clips"]
assert all(c["platform"] == "tiktok" and c["uploader"] == "NASA" for c in d["clips"]), d["clips"]
assert d["clips"][0]["upload_date"] == "20260830", d["clips"][0]
suivis = client.get("/api/following").get_json()["providers"]
tt = [p for p in suivis if p["platform"] == "tiktok"][0]
assert [a["title"] for a in tt["items"]] == ["NASA"], tt["items"]
print("ok: its videos are on its own page, dated, with the account behind them")

# The shorts page stays YouTube's: the two pages do not mix.
assert client.get("/api/shorts").get_json()["clips"] == []
print("ok: the shorts page ignores TikTok, and the other way round")

# The feed stays for long videos: a TikTok account has no business there.
assert client.get("/api/feed").get_json()["channels"] == []
print("ok: the feed ignores TikTok accounts, they have no long videos")

# Each platform has its queue, and a TikTok account takes one slot in it.
with db.connect() as conn:
    conn.execute("UPDATE channels SET refreshed_at = 0, shorts_refreshed_at = 0")
tabs = []
for _ in range(4):
    slot = feed.stalest_slot("tiktok")
    tabs.append((slot["tab"], slot["platform"]))
    feed.BUDGETS["tiktok"].last_tab = slot["tab"]
assert all(tab == "shorts" and p == "tiktok" for tab, p in tabs), tabs
# And the YouTube queue does not see it: otherwise TikTok would spend YouTube's budget.
for _ in range(4):
    slot = feed.stalest_slot("youtube")
    assert slot is None or slot["platform"] == "youtube", dict(slot)
    if slot:
        feed.BUDGETS["youtube"].last_tab = slot["tab"]
        with db.connect() as conn:
            colonne = "shorts_refreshed_at" if slot["tab"] == "shorts" else "refreshed_at"
            conn.execute(f"UPDATE channels SET {colonne} = ? WHERE channel_id = ?",
                         (time.time(), slot["channel_id"]))
print("ok: one queue per platform, and a TikTok account takes one slot")

# And without the switch, a TikTok URL is refused like any other.
config.TIKTOK_ENABLED = False
assert client.get("/tiktok").status_code == 404
assert client.post("/api/tiktok/accounts", json={"url": "https://www.tiktok.com/@nasa"}).status_code == 404
r = client.post("/api/feed/subscriptions", json={"url": "https://www.tiktok.com/@nasa"})
assert r.status_code == 400, r.get_json()
print("ok: closed by default, the page and its API are not found")
