import os, sys, tempfile, time
from unittest import mock
os.environ["MAGNETO_DB"] = os.path.join(tempfile.mkdtemp(), "t.db")
os.environ["MAGNETO_DOWNLOADS"] = tempfile.mkdtemp()
os.environ["MAGNETO_AUTH"] = "proxy"
REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, REPO)
import app
import config  # noqa: E402
import db  # noqa: E402
import media  # noqa: E402

client = app.app.test_client()
ced, bob = {"Remote-User": "cedric"}, {"Remote-User": "bob"}
URL = "https://www.youtube.com/watch?v=shared"


def ask(headers, **extra):
    body = {"url": URL, "format": "video", "max_height": 720, "title": "Shared"}
    body.update(extra)
    with mock.patch("threading.Thread") as thread:
        r = client.post("/api/download", json=body, headers=headers)
    return r.get_json(), thread


# The first one really downloads.
first, thread = ask(ced)
assert thread.called and not first.get("reused")
path = os.path.join(config.DOWNLOAD_DIR, first["job_id"] + ".mp4")
open(path, "w").write("x" * 10)
db.update_entry(first["job_id"], status="done", path=path, filename="Shared.mp4")
print("ok: the first download does happen")

# The second, same URL and same quality, reuses the file without starting anything.
second, thread = ask(bob)
assert second["reused"] is True and not thread.called, (second, thread.called)
assert db.get_entry(second["job_id"])["path"] == path
print("ok: the second account reuses the file, without calling YouTube")

# A different quality stays a separate download.
other, thread = ask(bob, max_height=1080)
assert not other.get("reused") and thread.called
print("ok: another quality is not mistaken for the first")

# Deleting one entry must not take the other's file.
client.delete(f"/api/entries/{second['job_id']}", headers=bob)
assert os.path.exists(path), "the first one's file was deleted with the second one's entry"
print("ok: deleting a shared entry leaves the file to the other")

# The last entry to go takes the file.
client.delete(f"/api/entries/{first['job_id']}", headers=ced)
assert not os.path.exists(path)
print("ok: the last delete frees the file")

# The sweep: one entry's pin protects the other's file.
a, _ = ask(ced)
p2 = os.path.join(config.DOWNLOAD_DIR, a["job_id"] + ".mp4")
open(p2, "w").write("x")
db.update_entry(a["job_id"], status="done", path=p2, filename="S.mp4")
b, _ = ask(bob)
assert db.get_entry(b["job_id"])["path"] == p2
db.update_entry(a["job_id"], pinned=1)
old = time.time() - config.RETENTION - 10
os.utime(p2, (old, old))
media.sweep_downloads()
assert os.path.exists(p2), "one entry's pin did not protect the file"
print("ok: at sweep time, the most generous reference wins")

db.update_entry(a["job_id"], pinned=0)
os.utime(p2, (old, old))
media.sweep_downloads()
assert not os.path.exists(p2)
assert db.get_entry(a["job_id"])["path"] is None and db.get_entry(b["job_id"])["path"] is None
print("ok: without a pin, the file goes and both entries know it")

# A download in flight has no path yet: it must survive.
running, _ = ask(ced, url="https://www.youtube.com/watch?v=inflight")
part = os.path.join(config.DOWNLOAD_DIR, running["job_id"] + ".mp4.part")
open(part, "w").write("x")
os.utime(part, (old, old))
media.sweep_downloads()
assert os.path.exists(part), "a download in flight was swept"
os.remove(part)
print("ok: a file being downloaded is not swept")
