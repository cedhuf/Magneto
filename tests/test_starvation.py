"""A slot that fails must not keep the head of the queue.

The defect measured on 2026-09-04: a channel with no Videos tab, never marked,
so always the oldest, retried every ten minutes for ten hours while 71
channels waited behind it.
"""
import os
import sys
import tempfile
import time

os.environ["MAGNETO_DB"] = os.path.join(tempfile.mkdtemp(), "t.db")
os.environ["MAGNETO_DOWNLOADS"] = tempfile.mkdtemp()
os.environ["MAGNETO_FEED"] = "1"
os.environ["MAGNETO_SHORTS"] = "1"
REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, REPO)
import app  # noqa: E402
import db  # noqa: E402
import feed  # noqa: E402

fails = []


def check(label, ok):
    print(f"  {'ok   ' if ok else 'FAIL '} {label}")
    if not ok:
        fails.append(label)


with db.connect() as conn:
    for n in ("dead", "alive"):
        conn.execute("INSERT INTO channels (channel_id, channel_url, title, videos, "
                     "refreshed_at, shorts_refreshed_at) VALUES (?, ?, ?, '[]', 0, 0)",
                     (n, f"https://www.youtube.com/channel/{n}", n))
        conn.execute("INSERT INTO follows (owner, channel_id) VALUES ('local', ?)", (n,))

# The queue takes the dead one first: at equal age, row order decides.
first = feed.stalest_slot("youtube")
feed.note_failure(first, ValueError(
    "ERROR: [youtube:tab] UC5: This channel does not have a videos tab"))
following = feed.stalest_slot("youtube")
check("after a failure, the queue moves to another slot",
      (following["channel_id"], following["tab"]) != (first["channel_id"], first["tab"]))

# A missing tab is permanent: that slot never comes back.
remaining = set()
while True:
    slot = feed.stalest_slot("youtube")
    if slot is None:
        break
    remaining.add((slot["channel_id"], slot["tab"]))
    feed.note_failure(slot, ValueError("boom"))
check("the missing tab left the queue for good",
      (first["channel_id"], first["tab"]) not in remaining)
check("the three other slots are still served", len(remaining) == 3)

# A passing failure, on the other hand, comes back in turn: it is simply dated.
with db.connect() as conn:
    conn.execute("UPDATE channels SET refreshed_at = 0, shorts_refreshed_at = 0, "
                 "has_videos = 1, has_shorts = 1")
one = feed.stalest_slot("youtube")
feed.note_failure(one, ValueError("boom"))
with db.connect() as conn:
    column = "shorts_refreshed_at" if one["tab"] == "shorts" else "refreshed_at"
    date = conn.execute(f"SELECT {column} AS d FROM channels WHERE channel_id = ?",
                        (one["channel_id"],)).fetchone()["d"]
check("a passing failure is dated, so it waits its turn", date > time.time() - 5)

# And the full loop: four slots, four failures, four distinct slots.
with db.connect() as conn:
    conn.execute("UPDATE channels SET refreshed_at = 0, shorts_refreshed_at = 0")
seen = []
for _ in range(4):
    slot = feed.stalest_slot("youtube")
    if slot is None:
        break
    seen.append((slot["channel_id"], slot["tab"]))
    feed.note_failure(slot, ValueError("boom"))
check("the queue turns instead of blocking", len(set(seen)) == len(seen) == 4)

if fails:
    sys.exit(1)
print("ok: a failure frees the slot, a missing tab removes it for good")

# A manual refresh that fails must show in the list, or the channel says
# "never" forever without ever saying why.
import app as _app  # noqa: E402
import db as _db  # noqa: E402
import youtube  # noqa: E402
client = _app.app.test_client()
with _db.connect() as conn:
    conn.execute("UPDATE channels SET has_videos = 1, refreshed_at = 0 "
                 "WHERE channel_id = 'alive'")
feed.PROVIDERS["youtube"]["refresh_videos"] = lambda *a, **k: (_ for _ in ()).throw(
    ValueError("ERROR: [youtube:tab] UC1: This channel does not have a videos tab"))
r = client.post("/api/feed/refresh", json={"channel_id": "alive", "force": True})
check("the manual refresh reports the failure", r.status_code == 400)
with _db.connect() as conn:
    after = conn.execute("SELECT has_videos, refreshed_at FROM channels "
                         "WHERE channel_id = 'alive'").fetchone()
check("the missing tab is recorded, the list can say so", after["has_videos"] == 0)

feed.PROVIDERS["youtube"]["refresh_videos"] = lambda *a, **k: (_ for _ in ()).throw(ValueError("boom"))
with _db.connect() as conn:
    conn.execute("UPDATE channels SET has_videos = 1, refreshed_at = 0 "
                 "WHERE channel_id = 'alive'")
client.post("/api/feed/refresh", json={"channel_id": "alive", "force": True})
with _db.connect() as conn:
    after = conn.execute("SELECT has_videos, refreshed_at FROM channels "
                         "WHERE channel_id = 'alive'").fetchone()
check("a passing failure dates the channel without condemning it",
      after["has_videos"] == 1 and after["refreshed_at"] > 0)

if fails:
    sys.exit(1)
print("ok: a manual failure shows in the list like a poller failure")
