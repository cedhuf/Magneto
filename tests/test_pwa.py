"""The manifest: installable, and readable behind the authentication proxy.

The trap is not the JSON, it is crossorigin: without it the browser asks for
the manifest without cookies, gets the login page, and installing is never
offered. Nothing in the interface says so.
"""
import json
import os
import re
import sys
import tempfile

os.environ["MAGNETO_DB"] = os.path.join(tempfile.mkdtemp(), "t.db")
os.environ["MAGNETO_DOWNLOADS"] = tempfile.mkdtemp()
REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, REPO)
import app  # noqa: E402

client = app.app.test_client()
fails = []


def check(label, ok):
    print(f"  {'ok   ' if ok else 'FAIL '} {label}")
    if not ok:
        fails.append(label)


page = client.get("/").get_data(as_text=True)
link = re.search(r'<link rel="manifest"[^>]*>', page).group(0)
check("the manifest is requested with cookies", 'crossorigin="use-credentials"' in link)

manifest = json.load(open(REPO + "/static/manifest.webmanifest"))
check("the app opens without the browser navigation",
      manifest["display"] == "standalone")
check("it opens on the home, and the rest of the site is in its scope",
      manifest["start_url"] == "/" and manifest["scope"] == "/")

STATIC = REPO + "/static"
missing = [i["src"] for i in manifest["icons"]
           if not os.path.exists(STATIC + i["src"].replace("/static", ""))]
check("every announced icon exists", not missing)
check("android a de quoi masquer",
      any(i["purpose"] == "maskable" for i in manifest["icons"]))
check("iOS has its own, opaque and square",
      'rel="apple-touch-icon"' in page and os.path.exists(f"{STATIC}/apple-touch-icon.png"))
check("the status bar follows the theme",
      page.count('name="theme-color"') == 2)

# The shared page is not the application: it must offer nothing to install.
check("a shared link does not offer to install the app",
      "manifest" not in open(REPO + "/templates/shared.html").read())

if fails:
    sys.exit(1)
print("ok: installable on iOS and Android, including behind the proxy")
