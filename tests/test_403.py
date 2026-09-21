import os, sys, tempfile
os.environ["MAGNETO_DB"] = os.path.join(tempfile.mkdtemp(), "t.db")
os.environ["MAGNETO_DOWNLOADS"] = tempfile.mkdtemp()
REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, REPO)
import app
import config  # noqa: E402
config.AUTH_MODE = "proxy"
c = app.app.test_client()

# Groups received, but not the right one.
r = c.get("/admin", headers={"Remote-User": "bob", "Remote-Groups": "family,guests"})
body = r.get_data(as_text=True)
assert r.status_code == 403
assert "admin" in body and "family, guests" in body, body
assert "not copying" not in body, "wrong cause named"
print("ok: groups received, the refusal lists them")

# No group at all: point at the proxy rather than the identity provider.
r = c.get("/admin", headers={"Remote-User": "bob"})
body = r.get_data(as_text=True)
assert r.status_code == 403 and "no groups received" in body
print("ok: no group, the refusal names the proxy")

# Spaces around the names, a real case with copy_headers.
r = c.get("/admin", headers={"Remote-User": "cedric", "Remote-Groups": " family , admin "})
assert r.status_code == 200
print("ok: spaces around the names are tolerated")

page = c.get("/", headers={"Remote-User": "bob", "Remote-Groups": "family"}).get_data(as_text=True)
assert 'href="/admin"' not in page and ">bob<" in page
page = c.get("/", headers={"Remote-User": "cedric", "Remote-Groups": "admin"}).get_data(as_text=True)
assert 'href="/admin"' in page and "cedric" in page
print("ok: the admin link is rendered by the server, according to the right")
