import os, sys, tempfile, json
from unittest import mock
os.environ["MAGNETO_DB"] = os.path.join(tempfile.mkdtemp(), "t.db")
os.environ["MAGNETO_DOWNLOADS"] = tempfile.mkdtemp()
REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, REPO)
import app
import media  # noqa: E402

client = app.app.test_client()

# A faithful extract of what YouTube publishes: no H.264 above 1080p, and at
# 1080p an avc1 with a higher bitrate than the av01.
FORMATS = [
    {"format_id": "401", "height": 2160, "vcodec": "av01.0.12M.08", "tbr": 9024, "filesize": 240000000},
    {"format_id": "400", "height": 1440, "vcodec": "av01.0.12M.08", "tbr": 4000, "filesize": 120000000},
    # As in real life: the high-bitrate H.264 announces no size.
    {"format_id": "270", "height": 1080, "vcodec": "avc1.640028", "tbr": 4688},
    {"format_id": "399", "height": 1080, "vcodec": "av01.0.08M.0", "tbr": 1142, "filesize": 30000000},
    {"format_id": "136", "height": 720, "vcodec": "avc1.4d401f", "tbr": 2000, "filesize": 50000000},
]
INFO = {"title": "T", "thumbnail": "", "duration": 213, "uploader": "U", "description": "",
        "upload_date": "20260101", "live_status": "not_live", "formats": FORMATS}

with mock.patch("subprocess.run",
                return_value=mock.Mock(returncode=0, stdout=json.dumps(INFO), stderr="")):
    d = client.post("/api/info", json={"url": "https://www.youtube.com/watch?v=x"}).get_json()

by_height = {f["height"]: f for f in d["formats"]}
assert by_height[1080]["id"] == "270", by_height[1080]
assert by_height[1080]["compatible"] is True
print("ok: at 1080p, H.264 is picked explicitly")
assert by_height[2160]["compatible"] is False and by_height[1440]["compatible"] is False
print("ok: 1440p and 2160p are flagged incompatible")

# A size is shown even when yt-dlp announces none.
assert by_height[1080]["size"] == int(4688 * 125 * 213), by_height[1080]["size"]
assert by_height[720]["size"] == 50000000, by_height[720]["size"]
assert all(f["size"] for f in d["formats"]), d["formats"]
print("ok: size announced when it exists, computed otherwise, never empty")

# The height selector, the feed's, asks for H.264 first.
captured = {}
with mock.patch("subprocess.run",
                side_effect=lambda cmd, **kw: captured.setdefault("cmd", cmd) or
                mock.Mock(returncode=1, stdout="", stderr="stop")):
    media.run_download("j1", "https://e.com/v", "video", None, "T", 1080)
sel = captured["cmd"][captured["cmd"].index("-f") + 1]
assert sel.split("/")[0] == "bestvideo[height<=1080][vcodec^=avc1]+bestaudio[ext=m4a]", sel
assert sel.endswith("/best"), sel
print("ok: the feed asks for H.264 then falls back, never failing for lack of a fallback")

# An mp4 whose audio is Opus plays without any sound on an iPhone. YouTube's
# progressive file is H.264 and AAC by construction, so it comes before a
# merge with whatever audio.
captured = {}
with mock.patch("subprocess.run",
                side_effect=lambda cmd, **kw: captured.setdefault("cmd", cmd) or
                mock.Mock(returncode=1, stdout="", stderr="stop")):
    media.run_download("j2", "https://e.com/v", "video", None, "T", 720, vertical=True)
rungs = captured["cmd"][captured["cmd"].index("-f") + 1].split("/")
assert all("width" in r for r in rungs[:-1]), rungs
# An mp4 whose audio is Opus plays silent on an iPhone: a progressive file,
# AAC by construction, must come before a merge with whatever audio.
opus = rungs.index("bestvideo[width<=720]+bestaudio")
progressif = [i for i, r in enumerate(rungs)
              if r.startswith("best[width<=720]") and i < opus]
assert progressif, rungs
# And HEVC is decoded by Apple only: Firefox gives it sound and a black
# picture. Any rung that allows it comes after the ones that exclude it.
hevc_ok = [i for i, r in enumerate(rungs)
           if "vcodec" not in r or r.count("vcodec!*=") == 0 and "avc1" not in r]
exclus = [i for i, r in enumerate(rungs) if "vcodec^=avc1" in r or "vcodec!*=hev" in r]
assert exclus and max(exclus) < min(hevc_ok), rungs
print("ok: H.264 first, never HEVC or Opus while a choice remains")

# And a format picked by hand never falls back to audio alone.
captured.clear()
with mock.patch("subprocess.run",
                side_effect=lambda cmd, **kw: captured.setdefault("cmd", cmd) or
                mock.Mock(returncode=1, stdout="", stderr="stop")):
    media.run_download("j3", "https://e.com/v", "video", "270", "T")
rungs = captured["cmd"][captured["cmd"].index("-f") + 1].split("/")
assert "bestaudio" not in rungs, rungs
assert all(r.startswith("270+") or r == "best" for r in rungs), rungs
print("ok: a picked format does not fall back to a file with no picture")
