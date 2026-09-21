"""Importing a subscriptions export never looks YouTube up.

That is the only thing that matters here: a hundred channels imported would be
a hundred requests in a burst if the import resolved them, and that is exactly
what gets an address flagged.
"""
import os
import sys
import tempfile
from unittest import mock

os.environ["MAGNETO_DB"] = os.path.join(tempfile.mkdtemp(), "t.db")
os.environ["MAGNETO_DOWNLOADS"] = tempfile.mkdtemp()
# The feed is off by default: these tests are about it.
os.environ["MAGNETO_FEED"] = "1"
os.environ["MAGNETO_FEED_CHANNELS_MAX"] = "4"
REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, REPO)
import app  # noqa: E402
import config  # noqa: E402
import feed  # noqa: E402

client = app.app.test_client()


def ids(n):
    return [f"UC{str(i).rjust(22, 'x')}" for i in range(n)]


# A real export header, localised: it must be recognised by shape, not wording.
def csv_of(rows, header="ID des chaînes,URL des chaînes,Titres des chaînes"):
    lines = [header]
    for cid, title in rows:
        lines.append(f"{cid},http://www.youtube.com/channel/{cid},{title}")
    return "\n".join(lines) + "\n"


def post(text):
    with mock.patch("subprocess.run") as run:
        res = client.post("/api/feed/import", json={"csv": text})
    assert not run.called, "the import looked YouTube up"
    return res


three = list(zip(ids(3), ["A channel", "Title, with a comma", "Other"]))
d = post(csv_of(three)).get_json()
assert d == {"added": 3, "already": 0, "skipped": 0, "full": False,
             "limit": 4, "every": config.FEED_POLL}, d
print("ok: three channels followed without a single outbound call")

page = client.get("/api/feed").get_json()
assert len(page["channels"]) == 3 and page["videos"] == [], page["videos"]
titles = sorted(c["title"] for c in page["channels"])
assert titles == ["A channel", "Other", "Title, with a comma"], titles
print("ok: a title with a comma survives, and the feed is empty until the poller comes")

# Dated zero, imported channels go ahead of everything else.
assert feed.stalest_slot("youtube")["channel_id"] in [c for c, _ in three]
print("ok: an imported channel is the stalest, so the next one polled")

d = post(csv_of(three)).get_json()
assert d["added"] == 0 and d["already"] == 3, d
print("ok: reimporting the same file follows nothing twice")

more = list(zip(ids(9)[3:], ["C" + str(i) for i in range(6)]))
d = post(csv_of(more)).get_json()
assert d["added"] == 1 and d["full"] is True and d["limit"] == 4, d
assert len(client.get("/api/feed").get_json()["channels"]) == 4
print("ok: the channel ceiling stops the import and says so")

# A row whose URL does not lead to YouTube is counted, not followed: the
# file stays readable, it is that one row that is not.
r = post("ID,URL,Title\nUCzzzzzzzzzzzzzzzzzzzzzz,file:///etc/passwd,Z\n")
assert r.status_code == 200, r.status_code
assert r.get_json()["added"] == 0 and r.get_json()["skipped"] == 1, r.get_json()
assert len(client.get("/api/feed").get_json()["channels"]) == 4

# A file where nothing looks like a channel is not an export.
r = post("name,first_name\nDoe,John\n")
assert r.status_code == 400 and "No channels" in r.get_json()["error"], r.get_json()
assert post("").status_code == 400
assert post("x" * (config.IMPORT_MAX_BYTES + 1)).status_code == 400
print("ok: an unreadable row is counted, an empty or huge file is refused")
