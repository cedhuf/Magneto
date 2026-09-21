import os, sys, tempfile
os.environ["MAGNETO_DB"] = os.path.join(tempfile.mkdtemp(), "t.db")
os.environ["MAGNETO_DOWNLOADS"] = tempfile.mkdtemp()
REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, REPO)
import app
import db  # noqa: E402
import entries  # noqa: E402
import media  # noqa: E402

# remember() is the only new thing testable without the network: /api/info calls yt-dlp.
FORMATS = [{"id": "137", "label": "1080p", "height": 1080},
           {"id": "136", "label": "720p", "height": 720}]
CARD = {"title": "One", "thumbnail": "t1.jpg", "formats": FORMATS,
        "uploader": "Some Channel", "duration": 212.5,
        "description": "Line one\nLine two", "upload_date": "20091025"}
a = entries.remember("local", "https://e.com/one", CARD)
b = entries.remember("local", "https://e.com/one", {**CARD, "title": "One renamed",
                                                "thumbnail": "t2.jpg"})
assert a == b, "fetching the same URL again must reuse the row"
row = db.get_entry(a)
assert row["status"] == "ready" and row["title"] == "One renamed" and row["path"] is None
print("ok: a Fetch creates the entry, a second one updates it without a duplicate")

c = entries.remember("bob", "https://e.com/one", {**CARD, "formats": []})
assert c != a, "each user has their own entry for the same URL"
print("ok: same URL, two users, two entries")

client = app.app.test_client()
entries = client.get("/api/entries").get_json()["entries"]
assert [e["job_id"] for e in entries] == [a], entries
assert entries[0]["status"] == "ready" and entries[0]["has_file"] is False
assert entries[0]["formats"] == FORMATS, entries[0]["formats"]
assert entries[0]["uploader"] == "Some Channel" and entries[0]["duration"] == 212.5
assert entries[0]["upload_date"] == "20091025"
assert entries[0]["description"] == "Line one\nLine two"
print("ok: the undownloaded entry comes back with formats, channel and duration")

# An entry from before v3 has no formats and must not break reading.
with db.connect() as conn:
    conn.execute("UPDATE entries SET formats = NULL WHERE job_id = ?", (a,))
assert client.get("/api/entries").get_json()["entries"][0]["formats"] == []
print("ok: missing formats read as an empty list")

# It can be swept like the others, with no file to delete.
media.sweep_downloads()
assert db.get_entry(a) is not None
print("ok: the sweep leaves an entry without a file alone")
with db.connect() as conn:
    conn.execute("DELETE FROM entries")
