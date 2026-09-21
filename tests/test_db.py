import os
import sys
import time
import tempfile

DB = os.path.join(tempfile.mkdtemp(), "t.db")
os.environ["MAGNETO_DB"] = DB
os.environ["MAGNETO_DOWNLOADS"] = tempfile.mkdtemp()
os.environ["MAGNETO_RETENTION"] = "3600"
REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, REPO)
import app  # noqa: E402
import auth  # noqa: E402
import config  # noqa: E402
import db  # noqa: E402
import media  # noqa: E402

DL = config.DOWNLOAD_DIR
client = app.app.test_client()

with db.connect() as c:
    assert c.execute("PRAGMA user_version").fetchone()[0] == len(db.MIGRATIONS)
    cols = [r[1] for r in c.execute("PRAGMA table_info(entries)")]
assert "owner" in cols and "path" in cols, cols
print(f"ok: migrations applied, user_version = {len(db.MIGRATIONS)}")

# No-auth mode: one implicit user, admin of their instance.
assert config.AUTH_MODE == "none"
with app.app.test_request_context("/"):
    assert auth.current_user() == "local" and auth.is_admin()
print("ok: no auth, single user 'local' and admin")

# Proxy mode: missing header = 401, never a silent fallback.
config.AUTH_MODE = "proxy"
with app.app.test_request_context("/"):
    try:
        auth.current_user()
        raise AssertionError("a missing header should cut")
    except Exception as e:
        assert "401" in repr(e) or getattr(e, "code", None) == 401, repr(e)
with app.app.test_request_context("/", headers={"Remote-User": "alice"}):
    assert auth.current_user() == "alice"
    assert not auth.is_admin()
with app.app.test_request_context("/", headers={"Remote-User": "cedric",
                                                "Remote-Groups": "family, admin"}):
    assert auth.is_admin()
print("ok: proxy mode, 401 without the header, identity and admin group read")

# Two accounts, each sees only its own entries.
def as_user(name, groups=""):
    return {"Remote-User": name, "Remote-Groups": groups}

r = client.post("/api/download", json={"url": "https://example.com/a", "title": "A"},
                headers=as_user("alice"))
alice_job = r.get_json()["job_id"]
r = client.post("/api/download", json={"url": "https://example.com/b", "title": "B"},
                headers=as_user("bob"))
bob_job = r.get_json()["job_id"]
time.sleep(0.3)

seen = [e["job_id"] for e in client.get("/api/entries", headers=as_user("alice")).get_json()["entries"]]
assert seen == [alice_job], seen
print("ok: /api/entries returns only the caller's entries")

assert client.get(f"/api/status/{bob_job}", headers=as_user("alice")).status_code == 404
assert client.get(f"/api/file/{bob_job}", headers=as_user("alice")).status_code == 404
assert client.get(f"/api/stream/{bob_job}", headers=as_user("alice")).status_code == 404
print("ok: someone else's job is not found, not just hidden")

# Restarting an entry reuses its row instead of creating a second one.
r = client.post("/api/download", json={"url": "https://example.com/a", "title": "A",
                                       "job_id": alice_job}, headers=as_user("alice"))
assert r.get_json()["job_id"] == alice_job
time.sleep(0.3)
entries = client.get("/api/entries", headers=as_user("alice")).get_json()["entries"]
assert len(entries) == 1, entries
print("ok: restarting from the history reuses the row")

# The file goes, the entry stays with what it needs to restart.
path = os.path.join(DL, f"{alice_job}.mp4")
open(path, "w").write("x")
db.update_entry(alice_job, status="done", path=path, filename="A.mp4")
row = db.get_entry(alice_job)
assert 3590 < media.seconds_left(row) <= 3600
old = time.time() - 7200
os.utime(path, (old, old))
media.sweep_downloads()
assert not os.path.exists(path)
e = client.get("/api/entries", headers=as_user("alice")).get_json()["entries"][0]
assert e["has_file"] is False and e["expires_in"] == 0
assert e["url"] == "https://example.com/a" and e["title"] == "A"
print("ok: file swept, entry kept with its URL and title")

# A file without a row is an orphan and goes.
orphan = os.path.join(DL, "orphan0001.mp4")
open(orphan, "w").write("x")
media.sweep_downloads()
assert not os.path.exists(orphan)
print("ok: orphan removed")

for j in (alice_job, bob_job):
    for f in __import__("glob").glob(os.path.join(DL, f"{j}.*")):
        os.remove(f)
