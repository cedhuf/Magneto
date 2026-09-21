import os, sys, tempfile, importlib, time
DB = os.path.join(tempfile.mkdtemp(), "t.db")
os.environ["MAGNETO_DB"] = DB
os.environ["MAGNETO_DOWNLOADS"] = tempfile.mkdtemp()
REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, REPO)
import app
import db  # noqa: E402

with db.connect() as c:
    c.execute("INSERT INTO entries (job_id, owner, url, status, created_at) "
              "VALUES ('stuck00001', 'local', 'https://e.com/a', 'downloading', ?)",
              (time.time(),))
    c.execute("INSERT INTO entries (job_id, owner, url, status, created_at) "
              "VALUES ('fine000001', 'local', 'https://e.com/b', 'done', ?)",
              (time.time(),))

# Restart: the database is opened again, as gunicorn would.
db.recover_interrupted()

rows = {r["job_id"]: r for r in db.connect().execute("SELECT * FROM entries")}
assert rows["stuck00001"]["status"] == "error", dict(rows["stuck00001"])
assert "restart" in rows["stuck00001"]["error"]
print("ok: a row left in downloading becomes an error on start")
assert rows["fine000001"]["status"] == "done"
print("ok: the other rows are not touched")

client = app.app.test_client()
entry = [e for e in client.get("/api/entries").get_json()["entries"]
         if e["job_id"] == "stuck00001"][0]
assert entry["status"] == "error"
print("ok: the page will not poll it any more, it offers a retry")
