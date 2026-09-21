import os
import sys
import time
import tempfile

os.environ["MAGNETO_DB"] = os.path.join(tempfile.mkdtemp(), "t.db")
os.environ["MAGNETO_DOWNLOADS"] = tempfile.mkdtemp()
os.environ["MAGNETO_RETENTION"] = "3600"
os.environ["MAGNETO_PIN_RETENTION"] = "86400"
os.environ["MAGNETO_HISTORY_MAX"] = "3"
REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, REPO)
import app  # noqa: E402
import config  # noqa: E402
import db  # noqa: E402
import media  # noqa: E402

client = app.app.test_client()
DL = config.DOWNLOAD_DIR


def seed(job_id, owner="local", created=None, with_file=True):
    path = os.path.join(DL, f"{job_id}.mp4") if with_file else None
    with db.connect() as conn:
        conn.execute("INSERT INTO entries (job_id, owner, url, title, status, path,"
                     " filename, created_at) VALUES (?,?,?,?,?,?,?,?)",
                     (job_id, owner, f"https://e.com/{job_id}", job_id, "done",
                      path, "c.mp4", created or time.time()))
    if path:
        open(path, "wb").write(b"x")
    return path


with db.connect() as c:
    assert c.execute("PRAGMA user_version").fetchone()[0] == len(db.MIGRATIONS)
    assert "pinned" in [r[1] for r in c.execute("PRAGMA table_info(entries)")]
print(f"ok: migrations applied (v{len(db.MIGRATIONS)}), pinned column present")

# A v1 database upgrades without losing its rows.
old = os.path.join(tempfile.mkdtemp(), "v1.db")
import sqlite3
conn = sqlite3.connect(old)
conn.executescript(db.MIGRATIONS[0])
conn.execute("INSERT INTO entries (job_id, owner, url, status, created_at)"
             " VALUES ('legacy0001','local','https://e.com/l','done', ?)", (time.time(),))
conn.execute("PRAGMA user_version = 1")
conn.commit(); conn.close()
saved = config.DB_PATH
config.DB_PATH = old
db.migrate()
with db.connect() as c:
    assert c.execute("PRAGMA user_version").fetchone()[0] == len(db.MIGRATIONS)
    row = c.execute("SELECT * FROM entries WHERE job_id='legacy0001'").fetchone()
    assert row["pinned"] == 0
config.DB_PATH = saved
print("ok: a v1 database migrates to the latest version and keeps its rows")

p = seed("pin0000001")
assert media.seconds_left(db.get_entry("pin0000001")) <= 3600
r = client.post("/api/entries/pin0000001/pin", json={"pinned": True})
assert r.status_code == 200 and r.get_json()["pinned"] is True
left = media.seconds_left(db.get_entry("pin0000001"))
assert 86390 < left <= 86400, left
print(f"ok: pinned, the deadline moves to {left / 3600:.0f}h without passing the admin ceiling")

# A pinned file survives the short retention, not the ceiling.
past = time.time() - 7200
os.utime(p, (past, past))
media.sweep_downloads()
assert os.path.exists(p)
past = time.time() - 2 * 86400
os.utime(p, (past, past))
media.sweep_downloads()
assert not os.path.exists(p)
print("ok: pinning moves the deadline, it does not exempt")

# Deleting by the user, and walls between accounts.
p2 = seed("pin0000002")
config.AUTH_MODE = "proxy"
assert client.delete("/api/entries/pin0000002",
                     headers={"Remote-User": "bob"}).status_code == 404
assert os.path.exists(p2)
config.AUTH_MODE = "none"
assert client.delete("/api/entries/pin0000002").status_code == 200
assert not os.path.exists(p2) and db.get_entry("pin0000002") is None
print("ok: users delete their own, not other people's")

# History ceiling, pinned ones excluded.
with db.connect() as c:
    c.execute("DELETE FROM entries")
now = time.time()
for i in range(6):
    seed(f"hist00000{i}", created=now - (10 - i), with_file=False)
client.post("/api/entries/hist000000/pin", json={"pinned": True})
media.trim_history()
with db.connect() as c:
    kept = sorted(r["job_id"] for r in c.execute("SELECT job_id FROM entries"))
assert kept == ["hist000000", "hist000003", "hist000004", "hist000005"], kept
print("ok: ceiling at 3 per user, the oldest pinned one survives")

with db.connect() as c:
    c.execute("DELETE FROM entries")
