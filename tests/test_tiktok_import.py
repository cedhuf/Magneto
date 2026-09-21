"""The TikTok import: handles only, no lookup, no duplicate."""
import os
import sys
import tempfile

os.environ["MAGNETO_DB"] = os.path.join(tempfile.mkdtemp(), "t.db")
os.environ["MAGNETO_DOWNLOADS"] = tempfile.mkdtemp()
os.environ["MAGNETO_TIKTOK"] = "1"
os.environ["MAGNETO_TIKTOK_ACCOUNTS_MAX"] = "4"
REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, REPO)
import app  # noqa: E402
import config  # noqa: E402
import db  # noqa: E402
import tiktok  # noqa: E402

client = app.app.test_client()
fails = []


def check(label, ok):
    print(f"  {'ok   ' if ok else 'FAIL '} {label}")
    if not ok:
        fails.append(label)


r = client.post("/api/tiktok/import", json={"accounts": ["jane.doe", "nasa"]}).get_json()
check("both accounts are followed", r["added"] == 2)

with db.connect() as conn:
    rows = {row["channel_id"]: row for row in
            conn.execute("SELECT * FROM channels WHERE platform = 'tiktok'")}
first = rows["tiktok:jane.doe"]
check("the account URL is rebuilt from the handle",
      first["channel_url"] == "https://www.tiktok.com/@jane.doe")
check("nothing was looked up, the queue will take them first",
      first["shorts"] == "[]" and first["shorts_refreshed_at"] == 0)
check("the handle stands in for the title", first["title"] == "@jane.doe")

r = client.post("/api/tiktok/import", json={"accounts": ["jane.doe"]}).get_json()
check("a second import does not follow twice", r["already"] == 1 and r["added"] == 0)

r = client.post("/api/tiktok/import",
                json={"accounts": ["a/../b", "with space", "x" * 40, ""]}).get_json()
check("a handle that is not one is set aside", r["skipped"] == 4 and r["added"] == 0)

r = client.post("/api/tiktok/import", json={"accounts": ["one", "two", "three"]}).get_json()
check("the account ceiling holds", r["added"] == 2 and r["full"] is True)

check("an empty body is refused",
      client.post("/api/tiktok/import", json={"accounts": []}).status_code == 400)

# Adding by hand an account already imported updates its row, it does not create
# a second one under the id TikTok itself knows.
tiktok.fetch_tiktok = lambda url, count: {
    "channel_id": "tiktok:MS4wLjAxMjM", "channel_url": url,
    "title": "Jane Doe", "videos": []}
tiktok.follow_tiktok("https://www.tiktok.com/@jane.doe")
with db.connect() as conn:
    same = conn.execute("SELECT count(*) FROM channels WHERE channel_url = ?",
                        ("https://www.tiktok.com/@jane.doe",)).fetchone()[0]
    title = conn.execute("SELECT title FROM channels WHERE channel_id = 'tiktok:jane.doe'"
                         ).fetchone()["title"]
check("adding by hand takes over the imported row", same == 1 and title == "Jane Doe")

# A TikTok instance without the feed keeps what it needs to follow and refresh.
config.FEED_ENABLED = False
check("refresh stays open when only TikTok is on",
      client.post("/api/feed/refresh", json={"channel_id": "tiktok:nasa"}).status_code != 404)
check("the feed itself stays closed", client.get("/api/feed").status_code == 404)
config.FEED_ENABLED = True

# And without the switch, the route does not exist.
config.TIKTOK_ENABLED = False
check("closed by default",
      client.post("/api/tiktok/import", json={"accounts": ["nasa"]}).status_code == 404)

if fails:
    sys.exit(1)
print("ok: handles only, dated zero, with no duplicate and no lookup")

# Manual refresh: it rereads the upright list of a TikTok account,
# not a YouTube Videos tab that does not exist.
config.TIKTOK_ENABLED = True
vus = []
tiktok.fetch_tiktok = lambda url, count: (vus.append(url) or {
    "channel_id": "x", "channel_url": url, "title": "t",
    "videos": [{"id": "v1", "url": url + "/video/1", "title": "A clip",
                "thumbnail": "", "duration": 8, "upload_date": "20260904"}]})
app.fetch_videos = lambda *a, **k: (_ for _ in ()).throw(
    AssertionError("a TikTok account was read as a YouTube channel"))

r = client.post("/api/feed/refresh", json={"channel_id": "tiktok:nasa", "force": True})
check("the manual refresh of a TikTok account succeeds", r.status_code == 200)
check("it is indeed the TikTok account that was read",
      vus == ["https://www.tiktok.com/@nasa"])
with db.connect() as conn:
    row = conn.execute("SELECT * FROM channels WHERE channel_id = 'tiktok:nasa'").fetchone()
check("the clip lands in the column the page reads",
      "A clip" in row["shorts"] and row["videos"] == "[]")
check("and it is the upright clock that moves",
      row["shorts_refreshed_at"] > 0 and row["refreshed_at"] == 0)

# A slot the poller abandoned starts again when asked for by hand.
with db.connect() as conn:
    conn.execute("UPDATE channels SET has_shorts = 0 WHERE channel_id = 'tiktok:nasa'")
client.post("/api/feed/refresh", json={"channel_id": "tiktok:nasa", "force": True})
with db.connect() as conn:
    restored = conn.execute("SELECT has_shorts FROM channels WHERE channel_id = 'tiktok:nasa'"
                          ).fetchone()["has_shorts"]
check("an abandoned tab comes back into the queue after a manual refresh", restored == 1)

if fails:
    sys.exit(1)
print("ok: manual refresh follows the account's platform")
