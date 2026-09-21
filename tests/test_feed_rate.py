import os, sys, tempfile, json, time
from unittest import mock
os.environ["MAGNETO_DB"] = os.path.join(tempfile.mkdtemp(), "t.db")
os.environ["MAGNETO_DOWNLOADS"] = tempfile.mkdtemp()
# The feed is off by default: these tests are about it.
os.environ["MAGNETO_FEED"] = "1"
os.environ["MAGNETO_FEED_CHANNELS_MAX"] = "2"
REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, REPO)
import app
import config  # noqa: E402
import db  # noqa: E402
import feed  # noqa: E402
import youtube  # noqa: E402

client = app.app.test_client()
CH = lambda cid: {"channel_id": cid, "id": cid, "channel": cid, "entries": []}


def fake(cid):
    return mock.patch("subprocess.run",
                      return_value=mock.Mock(returncode=0, stdout=json.dumps(CH(cid)), stderr=""))


for n in range(2):
    with fake(f"UC{n}"):
        r = client.post("/api/feed/subscriptions", json={"url": f"https://www.youtube.com/@c{n}"})
    assert r.status_code == 200, r.get_json()
with mock.patch("subprocess.run") as never:
    r = client.post("/api/feed/subscriptions", json={"url": "https://www.youtube.com/@c9"})
assert r.status_code == 400 and "At most 2" in r.get_json()["error"]
assert not never.called, "the ceiling must cut before any outbound call"
print("ok: channel ceiling per account, refused without calling YouTube")

# A refresh right after adding is refused by the cooldown.
with mock.patch("subprocess.run") as never:
    r = client.post("/api/feed/refresh", json={"channel_id": "UC0"})
assert r.get_json()["skipped"] == "recent", r.get_json()
assert not never.called
print("ok: two clicks in a row do not cost two lookups")

# Old enough to be refreshed, but the global spacing still objects.
with db.connect() as c:
    c.execute("UPDATE channels SET refreshed_at = ? WHERE channel_id = 'UC0'",
              (time.time() - config.FEED_COOLDOWN - 1,))
feed.BUDGETS["youtube"].last_call = time.time()
with mock.patch("subprocess.run") as never:
    r = client.post("/api/feed/refresh", json={"channel_id": "UC0"})
assert r.get_json()["skipped"] == "busy", r.get_json()
assert not never.called
print("ok: the global spacing wins, whichever account asks")

feed.BUDGETS["youtube"].last_call = 0
with fake("UC0") as run:
    r = client.post("/api/feed/refresh", json={"channel_id": "UC0"})
assert r.get_json().get("ok") and not r.get_json().get("skipped")
assert run.called
print("ok: past both guards, the lookup does happen")

# The background thread only picks channels that are really stale.
assert feed.stalest_slot("youtube") is None, "none is stale right after a refresh"
with db.connect() as c:
    c.execute("UPDATE channels SET refreshed_at = ? WHERE channel_id = 'UC1'",
              (time.time() - config.FEED_TTL - 1,))
row = feed.stalest_slot("youtube")
assert row and row["channel_url"].endswith("/@c1/videos"), dict(row) if row else None
print("ok: the background thread targets the oldest, and only if it is stale")

# Outbound rate depends neither on the number of accounts nor of channels.
print(f"   outbound ceiling: 1 lookup / {config.FEED_POLL}s, "
      f"so {round(86400 / config.FEED_POLL)} a day at most")

# A refresh asked for on one channel overrides the spacing: it is a
# deliberate act on one channel, not the automatic loop.
feed.BUDGETS["youtube"].last_call = time.time()
with db.connect() as conn:
    conn.execute("UPDATE channels SET refreshed_at = ?", (time.time(),))
r = client.post("/api/feed/refresh", json={"channel_id": "UC1"})
assert r.get_json().get("skipped"), r.get_json()
with mock.patch("youtube.fetch_channel", return_value={**CH("UC1"), "channel_url": "u", "title": "t", "thumbnail": "", "videos": []}) as fetch:
    r = client.post("/api/feed/refresh", json={"channel_id": "UC1", "force": True})
assert r.status_code == 200 and not r.get_json().get("skipped"), r.get_json()
assert fetch.called, "forcing looked nothing up"
# and it pushes back the clock the poller reads, so the automatic pace holds.
assert time.time() - feed.BUDGETS["youtube"].last_call < 1
print("ok: forcing ignores the spacing but resets the clock")
