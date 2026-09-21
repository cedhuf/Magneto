import os
import sys
import tempfile

os.environ["MAGNETO_DB"] = os.path.join(tempfile.mkdtemp(), "t.db")
os.environ["MAGNETO_DOWNLOADS"] = tempfile.mkdtemp()

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, REPO)
import app  # noqa: E402
import config  # noqa: E402
import db  # noqa: E402
import media  # noqa: E402

ACCEPT = [
    "https://www.youtube.com/watch?v=dQw4w9WgXcQ",
    "http://example.com/v.mp4",
    "https://x.com/user/status/1?a=-b",
]
REJECT = [
    "--exec=touch /tmp/pwned",
    "--version",
    "-o/tmp/x",
    "file:///etc/passwd",
    "ftp://host/f",
    "javascript:alert(1)",
    "not a url",
    "",
    "https://",
]

for u in ACCEPT:
    assert media.is_safe_url(u), f"should accept: {u}"
for u in REJECT:
    assert not media.is_safe_url(u), f"should reject: {u!r}"
print(f"ok: is_safe_url accepts {len(ACCEPT)}, rejects {len(REJECT)}")

client = app.app.test_client()
for route in ("/api/info", "/api/playlist", "/api/download"):
    for u in ("--exec=touch /tmp/pwned", "file:///etc/passwd"):
        r = client.post(route, json={"url": u})
        assert r.status_code == 400, f"{route} {u!r} -> {r.status_code}"
        assert r.get_json()["error"] == "Invalid URL", r.get_json()
print("ok: the three endpoints answer 400 Invalid URL")

with db.connect() as conn:
    assert conn.execute("SELECT count(*) FROM entries").fetchone()[0] == 0, "no entry should exist"
assert not os.path.exists("/tmp/pwned"), "the payload must not have run"
print("ok: no job started, no payload executed")

# Every yt-dlp argv must put "--" before the URLs, whatever the branch. Read
# from the syntax tree: a regex over the source trips on brackets in the code.
import ast  # noqa: E402
import inspect  # noqa: E402

# Spread over several modules since the split: they are all read, or the
# guard only protects the file where nothing is left.
import glob  # noqa: E402
sources = [open(f).read() for f in glob.glob(REPO + "/*.py")]
trees = [ast.parse(s) for s in sources]
def is_argv(node):
    """A yt-dlp argv starts with *YTDLP, the base that carries --force-ipv4."""
    return (isinstance(node, ast.List) and node.elts
            and isinstance(node.elts[0], ast.Starred)
            and getattr(node.elts[0].value, "attr", getattr(node.elts[0].value, "id", None)) == "YTDLP")


argvs = [n for tree in trees for n in ast.walk(tree) if is_argv(n)]
assert len(argvs) == 7, f"{len(argvs)} yt-dlp call sites; a new one must be checked too"
assert config.YTDLP[0] == "yt-dlp" and "--force-ipv4" in config.YTDLP, config.YTDLP
print("ok: all 5 invocations start from the same base, with --force-ipv4")
for argv in argvs:
    values = [e.value if isinstance(e, ast.Constant) else None for e in argv.elts]
    if "-o" in values:          # the download appends "--" and the URL later
        assert any('cmd += ["--", url]' in one for one in sources)
        continue
    assert values[-2] == "--", ast.unparse(argv)
print(f"ok: {len(argvs)} invocations, each with -- before the URLs")
