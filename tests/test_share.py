"""Sharing: a public link, bounded in time, that keeps its file alive.

What this test protects above all is that /s/ never asks for an identity: it
is the only route readable without going through the authentication proxy.
"""
import os
import sys
import tempfile
import time

DB = os.path.join(tempfile.mkdtemp(), "t.db")
os.environ["MAGNETO_DB"] = DB
os.environ["MAGNETO_DOWNLOADS"] = tempfile.mkdtemp()
os.environ["MAGNETO_SHARE"] = "1"
os.environ["MAGNETO_SHARE_TTL"] = "3600"
os.environ["MAGNETO_SHARE_MAX"] = "2"
os.environ["MAGNETO_SHORTS_RETENTION"] = "60"
os.environ["MAGNETO_AUTH"] = "proxy"
REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, REPO)
import app  # noqa: E402
import config  # noqa: E402
import db  # noqa: E402
import media  # noqa: E402

DIR = tempfile.mkdtemp()
config.DOWNLOAD_DIR = DIR
CEDRIC = {"Remote-User": "cedric"}
OTHER = {"Remote-User": "other"}


def entry(job_id, owner="cedric", kind="short"):
    path = os.path.join(DIR, f"{job_id}.mp4")
    open(path, "wb").write(b"x" * 10)
    with db.connect() as conn:
        conn.execute(
            "INSERT INTO entries (job_id, owner, url, title, uploader, status, "
            "created_at, path, filename, kind) VALUES (?,?,?,?,?,'done',?,?,?,?)",
            (job_id, owner, f"https://x/{job_id}", "A title", "A channel",
             time.time(), path, f"{job_id}.mp4", kind))
    return path


client = app.app.test_client()
fails = []


def check(label, ok):
    print(f"  {'ok   ' if ok else 'FAIL '} {label}")
    if not ok:
        fails.append(label)


entry("j1")
url = client.post("/api/share/j1", headers=CEDRIC).get_json()["url"]
token = url.rsplit("/", 1)[1]
check("the token cannot be guessed", len(token) >= 20 and "j1" not in url)

# The core: no identity header at all, and yet the page and the file come out.
check("the page reads without an identity", client.get(f"/s/{token}").status_code == 200)
got = client.get(f"/s/{token}/stream")
check("the file reads without an identity", got.status_code == 200 and got.data == b"x" * 10)
check("nothing is indexable", "noindex" in got.headers.get("X-Robots-Tag", ""))
page = client.get(f"/s/{token}").get_data(as_text=True)
check("the page leads nowhere", "/feed" not in page and "/shorts" not in page
      and 'href="/"' not in page)

check("an unknown token is a plain 404", client.get("/s/nosuchtoken").status_code == 404)

# The page cannot load anything from /static, which the proxy keeps closed.
check("the page loads nothing from /static", "/static/" not in page)
css = client.get("/s/asset/style.css")
check("the stylesheet reads without an identity",
      css.status_code == 200 and b"@font-face" in css.data)
check("the fonts read without an identity",
      client.get("/s/asset/mono.woff2").status_code == 200
      and client.get("/s/asset/serif.woff2").status_code == 200)
check("no name from the URL reaches the disk",
      client.get("/s/asset/..%2f..%2fapp.py").status_code == 404
      and client.get("/s/asset/style.css.bak").status_code == 404)
check("the job_id is not enough", client.get("/s/j1").status_code == 404)

# The same clip shared again gives the same link, not a second one to revoke.
again = client.post("/api/share/j1", headers=CEDRIC).get_json()["url"]
check("a second share reuses the link", again == url)

check("nobody shares someone else's file",
      client.post("/api/share/j1", headers=OTHER).status_code == 404)

# Retention: a short lives 60 s, the link 3600. The file must follow the link.
with db.connect() as conn:
    row = conn.execute("SELECT * FROM entries WHERE job_id = 'j1'").fetchone()
check("sharing extends the file", media.retention_for(row) > 3000)
os.utime(row["path"], (time.time() - 300, time.time() - 300))
media.sweep_downloads()
check("the sweep spares a shared file", os.path.exists(row["path"]))

# Revoked: the file falls back to its own deadline and goes at the next sweep.
client.delete("/api/share/j1", headers=CEDRIC)
check("the revoked link is dead", client.get(f"/s/{token}").status_code == 404)
media.sweep_downloads()
check("the revoked file can be swept again", not os.path.exists(row["path"]))

# An expired link is dead without anyone sweeping it.
entry("j2")
t2 = client.post("/api/share/j2", headers=CEDRIC).get_json()["url"].rsplit("/", 1)[1]
with db.connect() as conn:
    conn.execute("UPDATE shares SET expires_at = ? WHERE token = ?", (time.time() - 1, t2))
check("an expired link serves nothing", client.get(f"/s/{t2}").status_code == 404)

# The ceiling counts live links, not the ones that died on their own.
entry("j3"), entry("j4"), entry("j5")
codes = [client.post(f"/api/share/j{n}", headers=CEDRIC).status_code for n in (3, 4, 5)]
check("the ceiling stops the third live link", codes == [200, 200, 400])

# And without the switch, there is no link to create and none to read.
config.SHARE_ENABLED = False
entry("j6")
check("closed by default: no link to create",
      client.post("/api/share/j6", headers=CEDRIC).status_code == 404)
check("closed by default: existing links are not found",
      client.get(f"/s/{token}").status_code == 404)
with db.connect() as conn:
    row6 = conn.execute("SELECT * FROM entries WHERE job_id = 'j6'").fetchone()
check("closed by default: nothing extends a file",
      media.retention_for(row6) == config.SHORTS_RETENTION)
config.SHARE_ENABLED = True

if fails:
    sys.exit(1)
print("ok: a public link, bounded, revocable, and keeping its file alive")
