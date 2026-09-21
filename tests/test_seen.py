"""A watched clip leaves the reel, and forgetting happens on its own."""
import json
import os
import sys
import tempfile
import time

os.environ["MAGNETO_DB"] = os.path.join(tempfile.mkdtemp(), "t.db")
os.environ["MAGNETO_DOWNLOADS"] = tempfile.mkdtemp()
os.environ["MAGNETO_FEED"] = "1"
os.environ["MAGNETO_SHORTS"] = "1"
os.environ["MAGNETO_SEEN_RETENTION"] = "3600"
REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, REPO)
import app  # noqa: E402
import config  # noqa: E402
import db  # noqa: E402
import feed  # noqa: E402
import media  # noqa: E402

config.DOWNLOAD_DIR = tempfile.mkdtemp()
client = app.app.test_client()
fails = []


def check(label, ok):
    print(f"  {'ok   ' if ok else 'FAIL '} {label}")
    if not ok:
        fails.append(label)


clips = [{"id": f"s{n}", "url": f"https://y/s{n}", "title": f"Clip {n}",
          "thumbnail": "", "duration": 12, "upload_date": "20260904"} for n in range(3)]
with db.connect() as conn:
    conn.execute("INSERT INTO channels (channel_id, channel_url, title, videos, shorts) "
                 "VALUES ('c1', 'https://y/c1', 'A channel', '[]', ?)", (json.dumps(clips),))
    conn.execute("INSERT INTO follows (owner, channel_id) VALUES ('local', 'c1')")

before = client.get("/api/shorts").get_json()
check("the reel starts full", len(before["clips"]) == 3 and before["hidden"] == 0)

client.post("/api/seen", json={"url": "https://y/s0"})
after = client.get("/api/shorts").get_json()
check("a watched clip leaves the reel",
      [c["url"] for c in after["clips"]] == ["https://y/s1", "https://y/s2"])
check("the page knows how many were left out", after["hidden"] == 1)

every = client.get("/api/shorts?watched=1").get_json()
check("Show watched brings them all back", len(every["clips"]) == 3 and every["watched"] is True)
check("and says which ones were seen",
      [c["seen"] for c in every["clips"]] == [True, False, False])

for clip in clips:
    client.post("/api/seen", json={"url": clip["url"]})
done = client.get("/api/shorts").get_json()
check("all watched gives an empty reel, and what it needs to say so",
      done["clips"] == [] and done["hidden"] == 3)

check("marking without a URL is refused",
      client.post("/api/seen", json={}).status_code == 400)

# Each their own: what one account watched hides nothing for another.
with db.connect() as conn:
    conn.execute("INSERT INTO follows (owner, channel_id) VALUES ('other', 'c1')")
check("one account's views hide nothing for another",
      len(feed.upright_clips("other", "youtube")["clips"]) == 3)

# A URL gone from every listing can never come back: its row is dead.
with db.connect() as conn:
    conn.execute("UPDATE seen SET at = ?", (time.time() - 7200,))
media.sweep_downloads()
with db.connect() as conn:
    left = conn.execute("SELECT count(*) FROM seen").fetchone()[0]
check("the janitor forgets views that are too old", left == 0)
check("and the reel comes back full", len(client.get("/api/shorts").get_json()["clips"]) == 3)

# A short now lives as long as a download.
check("a short keeps its file for a day", config.SHORTS_RETENTION == 24 * 3600)

config.SHORTS_ENABLED = config.TIKTOK_ENABLED = False
check("closed by default", client.post("/api/seen", json={"url": "x"}).status_code == 404)

if fails:
    sys.exit(1)
print("ok: seen on the server, shared across devices, forgotten after a week")
