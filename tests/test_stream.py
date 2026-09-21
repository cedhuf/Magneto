import os
import sys
import time
import tempfile

os.environ["MAGNETO_DB"] = os.path.join(tempfile.mkdtemp(), "t.db")
os.environ["MAGNETO_DOWNLOADS"] = tempfile.mkdtemp()

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, REPO)
import app  # noqa: E402
import config  # noqa: E402
import db  # noqa: E402
import media  # noqa: E402

DL = config.DOWNLOAD_DIR
os.makedirs(DL, exist_ok=True)
path = os.path.join(DL, "streamtest1.mp4")
# Insert first: the startup sweep runs in its own thread and would take the
# file as an orphan otherwise. start_download has the same ordering.
with db.connect() as conn:
    conn.execute("INSERT INTO entries (job_id, owner, url, status, created_at, path,"
                 " filename) VALUES ('streamtest1', 'local', 'https://e.com/x', 'done',"
                 " ?, ?, 'Clip.mp4')", (time.time(), path))
open(path, "wb").write(b"0123456789" * 10)

client = app.app.test_client()

r = client.get("/api/stream/streamtest1")
assert r.status_code == 200, r.status_code
assert r.headers["Content-Type"].startswith("video/mp4"), r.headers["Content-Type"]
assert "attachment" not in r.headers.get("Content-Disposition", ""), r.headers
assert r.headers.get("Accept-Ranges") == "bytes", r.headers
print("ok: served inline as video/mp4, ranges advertised")

r = client.get("/api/stream/streamtest1", headers={"Range": "bytes=10-19"})
assert r.status_code == 206, r.status_code
assert r.data == b"0123456789", r.data
assert r.headers["Content-Range"] == "bytes 10-19/100", r.headers["Content-Range"]
print("ok: a Range request returns 206 with just that slice, so seeking works")

# Watching must push the deadline back rather than start a countdown.
left = media.seconds_left(db.get_entry("streamtest1"))
assert config.RETENTION - 10 < left <= config.RETENTION, left
print(f"ok: deadline is {left / 3600:.0f}h from the file's date, untouched by a seek")

r = client.get("/api/stream/nosuchjob")
assert r.status_code == 404, r.status_code
with db.connect() as conn:
    conn.execute("INSERT INTO entries (job_id, owner, url, status, created_at)"
                 " VALUES ('pending', 'local', 'https://e.com/y', 'downloading', ?)",
                 (time.time(),))
r = client.get("/api/stream/pending")
assert r.status_code == 404, r.status_code
print("ok: unknown and unfinished jobs both 404")

with db.connect() as conn:
    conn.execute("DELETE FROM entries")
media.sweep_downloads()
assert not os.path.exists(path)
print("ok: swept clean")
