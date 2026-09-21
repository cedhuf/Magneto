import os
import sys
import time
import tempfile

os.environ["MAGNETO_DB"] = os.path.join(tempfile.mkdtemp(), "t.db")
os.environ["MAGNETO_DOWNLOADS"] = tempfile.mkdtemp()
os.environ["MAGNETO_RETENTION"] = "3600"
os.environ["MAGNETO_LOGOUT_URL"] = "https://auth.example.com/logout"
REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, REPO)
import app  # noqa: E402
import auth  # noqa: E402
import config  # noqa: E402
import db  # noqa: E402
import media  # noqa: E402

client = app.app.test_client()
DL = config.DOWNLOAD_DIR


def seed(job_id, owner, size=2048):
    path = os.path.join(DL, f"{job_id}.mp4")
    with db.connect() as conn:
        conn.execute("INSERT INTO entries (job_id, owner, url, title, status, path,"
                     " filename, created_at) VALUES (?,?,?,?,?,?,?,?)",
                     (job_id, owner, f"https://e.com/{job_id}", f"Clip {job_id}",
                      "done", path, "c.mp4", time.time()))
    open(path, "wb").write(b"x" * size)
    return path


# Without authentication, the single user is admin of their instance.
with app.app.test_request_context("/"):
    me = auth.page_context()
assert me == {"user": "local", "admin": True, "auth": "none",
              "logout_url": "https://auth.example.com/logout",
                  "feed": False, "shorts": False, "tiktok": False, "share": False,
                  "following": False}, me
# And the template really uses it, with no client call.
assert "Sign out" not in client.get("/").get_data(as_text=True), "no proxy, no sign out"
assert client.get("/admin").status_code == 200
print("ok: no auth, implicit admin and /admin reachable")

config.AUTH_MODE = "proxy"
plain = {"Remote-User": "bob", "Remote-Groups": "family"}
boss = {"Remote-User": "cedric", "Remote-Groups": "family,admin"}

assert client.get("/admin").status_code == 401
assert client.get("/admin", headers=plain).status_code == 403
assert client.get("/api/admin/overview", headers=plain).status_code == 403
assert client.post("/api/admin/purge", headers=plain).status_code == 403
assert client.delete("/api/admin/entries/x", headers=plain).status_code == 403
print("ok: 401 without the header, 403 outside the group, on all four routes")

assert client.get("/admin", headers=boss).status_code == 200
assert 'href="/admin"' in client.get("/", headers=boss).get_data(as_text=True)
print("ok: the admin group opens the dashboard")

p1 = seed("adm0000001", "bob", 2048)
p2 = seed("adm0000002", "cedric", 1024)
d = client.get("/api/admin/overview", headers=boss).get_json()
assert d["disk"]["files"] == 2 and d["disk"]["bytes"] == 3072, d["disk"]
assert d["users"]["bob"]["bytes"] == 2048 and d["users"]["cedric"]["entries"] == 1
assert {e["owner"] for e in d["entries"]} == {"bob", "cedric"}
assert d["disk"]["free"] > 0 and d["retention"] == 3600
# Six tiles, so six figures: the two that escape the ordinary deadline are
# there too, or nothing says what grows the disk.
assert d["pinned"] == {"entries": 0, "bytes": 0, "retention": config.PIN_RETENTION}, d["pinned"]
assert set(d["shorts"]) == {"entries", "bytes", "retention", "enabled"}, d["shorts"]
print("ok: overview, sizes per user and free space")

# The admin sees and deletes what is not theirs, unlike a
# ordinary user.
assert client.get("/api/status/adm0000001", headers=boss).status_code == 404
r = client.delete("/api/admin/entries/adm0000001", headers=boss)
assert r.status_code == 200 and not os.path.exists(p1)
assert db.get_entry("adm0000001") is None
print("ok: admin delete, file and entry")

# An orphan counts in the disk total even without a row.
orphan = os.path.join(DL, "admorphan1.mp4")
open(orphan, "wb").write(b"y" * 512)
d = client.get("/api/admin/overview", headers=boss).get_json()
assert d["disk"]["files"] == 2 and d["disk"]["bytes"] == 1536, d["disk"]
assert len(d["entries"]) == 1
print("ok: a file without a row still weighs in the total")

# A download in flight survives the purge: its row is what tells it where to
# write and where to report.
seed("adm0000003", "bob", 256)
with db.connect() as conn:
    conn.execute("UPDATE entries SET status = 'downloading' WHERE job_id = 'adm0000003'")
inflight = os.path.join(DL, "adm0000003.part")
open(inflight, "wb").write(b"z" * 128)

r = client.post("/api/admin/purge", headers=boss)
d = r.get_json()
assert r.status_code == 200, r.status_code
assert d["entries"] == 1 and d["running"] == 1, d
assert d["files"] == 2 and d["bytes"] == 1536, d
assert not os.path.exists(orphan) and not os.path.exists(p2)
assert os.path.exists(inflight), "a download in flight was erased"
assert db.get_entry("adm0000003") is not None
assert len(client.get("/api/admin/overview", headers=boss).get_json()["entries"]) == 1
print("ok: the purge empties everything except what is downloading")

media.remove_quietly(inflight)

with db.connect() as conn:
    conn.execute("DELETE FROM entries")
