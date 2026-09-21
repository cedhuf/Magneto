import os, sys, tempfile, json
from unittest import mock
os.environ["MAGNETO_DB"] = os.path.join(tempfile.mkdtemp(), "t.db")
os.environ["MAGNETO_DOWNLOADS"] = tempfile.mkdtemp()
REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, REPO)
import app
import config  # noqa: E402

client = app.app.test_client()
BIG = {"entries": [{"url": f"https://www.youtube.com/watch?v=id{n:04d}"} for n in range(460)]}

with mock.patch("subprocess.run",
                return_value=mock.Mock(returncode=0, stdout=json.dumps(BIG), stderr="")) as run:
    r = client.post("/api/playlist", json={"url": "https://www.youtube.com/playlist?list=PL1"})
d = r.get_json()
assert len(d["urls"]) == config.PLAYLIST_MAX, len(d["urls"])
assert d["truncated"] is True and d["limit"] == config.PLAYLIST_MAX
print(f"ok: 460 entries returned as {len(d['urls'])}, flagged truncated")

# yt-dlp itself is bounded, or it lists the whole playlist before we cut.
argv = run.call_args[0][0]
assert "--playlist-end" in argv and argv[argv.index("--playlist-end") + 1] == str(config.PLAYLIST_MAX + 1), argv
print("ok: --playlist-end passed to yt-dlp, the listing is bounded at the source")

SMALL = {"entries": [{"url": "https://www.youtube.com/watch?v=a"},
                     {"url": "https://www.youtube.com/watch?v=b"}]}
with mock.patch("subprocess.run",
                return_value=mock.Mock(returncode=0, stdout=json.dumps(SMALL), stderr="")):
    d = client.post("/api/playlist", json={"url": "https://www.youtube.com/playlist?list=PL2"}).get_json()
assert d["urls"] == ["https://www.youtube.com/watch?v=a", "https://www.youtube.com/watch?v=b"]
assert d["truncated"] is False
print("ok: a small playlist goes through whole, not flagged truncated")
