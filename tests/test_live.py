import os, sys, tempfile, json
from unittest import mock
os.environ["MAGNETO_DB"] = os.path.join(tempfile.mkdtemp(), "t.db")
os.environ["MAGNETO_DOWNLOADS"] = tempfile.mkdtemp()
REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, REPO)
import app
import db  # noqa: E402

client = app.app.test_client()


def fake_ytdlp(info):
    """Answers in place of yt-dlp, so as not to depend on the network."""
    done = mock.Mock(returncode=0, stdout=json.dumps(info), stderr="")
    return mock.patch("subprocess.run", return_value=done)


base = {"title": "T", "thumbnail": "t.jpg", "duration": 10, "uploader": "U",
        "description": "D", "upload_date": "20260101", "formats": []}

for status in ("is_live", "is_upcoming"):
    with fake_ytdlp({**base, "live_status": status}):
        r = client.post("/api/info", json={"url": "https://e.com/live"})
    assert r.status_code == 400, r.status_code
    assert "live stream" in r.get_json()["error"], r.get_json()
print("ok: a live and an upcoming live are refused at Fetch")

with db.connect() as conn:
    assert conn.execute("SELECT count(*) FROM entries").fetchone()[0] == 0
print("ok: no refusal left an entry behind")

# A finished live stays downloadable.
with fake_ytdlp({**base, "live_status": "was_live"}):
    r = client.post("/api/info", json={"url": "https://e.com/past"})
assert r.status_code == 200, r.get_json()
d = r.get_json()
assert d["upload_date"] == "20260101" and d["description"] == "D" and d["job_id"]
print("ok: a finished live goes through, with its date and description")

with db.connect() as conn:
    conn.execute("DELETE FROM entries")
