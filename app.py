"""ReClip: the application, and nothing else.

Every page lives in its own module and arrives as a blueprint. What is left here
is what belongs to no page: the app itself, the gate that closes what an instance
has not asked for, and the home page.
"""

import os
from flask import Flask, render_template, abort, request

import config
from auth import page_context

app = Flask(__name__)

# Imported for their side effects as much as for their routes: opening the
# database migrates it, and a provider registers itself with the feed.
import db  # noqa: E402,F401
import media  # noqa: E402,F401
import feed  # noqa: E402
import youtube  # noqa: E402
import tiktok  # noqa: E402
import follows  # noqa: E402
import share  # noqa: E402
import admin  # noqa: E402
import entries  # noqa: E402

for _page in (youtube, tiktok, follows, share, admin, entries):
    app.register_blueprint(_page.bp)


@app.before_request
def gate_optional_pages():
    """One gate rather than a check on each route, so a route added later
    cannot forget to close behind itself."""
    path = request.path
    if not config.FEED_ENABLED and (path == "/feed" or path.startswith("/api/feed")) \
            and not path.startswith(("/api/feed/subscriptions", "/api/feed/refresh")):
        abort(404)
    if not config.SHORTS_ENABLED and (path == "/shorts" or path.startswith("/api/shorts")):
        abort(404)
    if not config.TIKTOK_ENABLED and (path == "/tiktok" or path.startswith("/api/tiktok")):
        abort(404)
    if not config.SHARE_ENABLED and (path.startswith("/s/") or path.startswith("/api/share")):
        abort(404)
    # Following, refreshing and unfollowing an account are the same routes
    # whichever page follows it, so they open as soon as one of them is on.
    shared = ("/api/feed/subscriptions", "/api/feed/refresh")
    if not (config.FEED_ENABLED or config.TIKTOK_ENABLED) and path.startswith(shared):
        abort(404)
    if not (config.SHORTS_ENABLED or config.TIKTOK_ENABLED) and path == "/api/seen":
        abort(404)
    if not (config.FEED_ENABLED or config.SHORTS_ENABLED or config.TIKTOK_ENABLED) \
            and path in ("/following", "/api/following"):
        abort(404)


@app.route("/")
def index():
    return render_template("index.html", page="home", **page_context())


feed.start_pollers()


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 8899))
    host = os.environ.get("HOST", "127.0.0.1")
    app.run(host=host, port=port)
