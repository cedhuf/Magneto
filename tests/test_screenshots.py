"""Three screenshots for the docs, taken on a demo instance.

The point is not to test the looks, it is that the pictures in the docs do
not lie: they are retaken from today's code, with data made up here, on an
ephemeral port and a throwaway database.
"""
import json
import os
import socket
import sys
import tempfile
import threading
import time
import wsgiref.simple_server

DIR = tempfile.mkdtemp()
os.environ["MAGNETO_DB"] = os.path.join(DIR, "demo.db")
os.environ["MAGNETO_DOWNLOADS"] = tempfile.mkdtemp()
os.environ["MAGNETO_FEED"] = "1"
os.environ["MAGNETO_SHORTS"] = "1"
os.environ["MAGNETO_TIKTOK"] = "1"
# The poller sleeps MAGNETO_FEED_POLL before its first lookup, and this test
# lasts a few seconds: it asks nobody for anything, and the page shows the
# real cadence rather than a value made up to silence it.
os.environ["MAGNETO_FEED_POLL"] = "300"
REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, REPO)
import app  # noqa: E402
import config  # noqa: E402
import db  # noqa: E402

SHOTS = os.path.join(REPO, "docs/screens")
os.makedirs(SHOTS, exist_ok=True)
config.DOWNLOAD_DIR = DIR

def thumbnail(top, bottom):
    """A thumbnail made here, as a data: URI.

    A real one would fetch an image from someone, which a test has no business
    doing. A plain gradient shows the layout without pretending to show a
    video that exists.
    """
    import base64
    import struct
    import zlib
    width, height = 320, 180
    rows = []
    for y in range(height):
        t = y / (height - 1)
        pixel = bytes(round(top[i] + (bottom[i] - top[i]) * t) for i in range(3))
        rows.append(b"\x00" + pixel * width)

    def chunk(kind, data):
        body = kind + data
        return struct.pack(">I", len(data)) + body + struct.pack(">I", zlib.crc32(body))

    png = (b"\x89PNG\r\n\x1a\n"
           + chunk(b"IHDR", struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0))
           + chunk(b"IDAT", zlib.compress(b"".join(rows), 9))
           + chunk(b"IEND", b""))
    return "data:image/png;base64," + base64.b64encode(png).decode()


TONES = [((214, 205, 190), (176, 160, 138)), ((196, 202, 198), (150, 162, 158)),
        ((222, 200, 186), (188, 152, 130)), ((198, 196, 210), (154, 150, 176)),
        ((210, 210, 196), (168, 168, 148)), ((216, 196, 196), (176, 146, 146)),
        ((200, 208, 214), (156, 168, 180))]


def clip(n, title, duration, date):
    return {"id": f"c{n}", "url": f"https://www.youtube.com/watch?v=c{n}",
            "title": title, "thumbnail": thumbnail(*TONES[n - 1]), "duration": duration,
            "upload_date": date, "description": ""}


CHANNELS = [
    ("UCkitchen", "Kitchen Cabinet", [
        clip(1, "A loaf that fits in a Dutch oven", 731, "20260903"),
        clip(2, "Three sauces from one stock", 1042, "20260828")]),
    ("UCworkshop", "The Wood Whisperer", [
        clip(3, "Squaring stock without a jointer", 1450, "20260902")]),
    ("UCastro", "Deep Sky Notes", [
        clip(4, "What the new telescope actually shows", 2210, "20260901"),
        clip(5, "Reading a light curve", 640, "20260825")]),
]
VERTICAL = [clip(6, "The bread comes out of the oven #bakery", 34, "20260904"),
             clip(7, "A worktop in three cuts", 41, "20260903")]

with db.connect() as conn:
    for channel_id, title, videos in CHANNELS:
        conn.execute("INSERT INTO channels (channel_id, channel_url, title, videos, "
                     "shorts, refreshed_at, shorts_refreshed_at) VALUES (?, ?, ?, ?, ?, ?, ?)",
                     (channel_id, f"https://www.youtube.com/@{channel_id}/videos", title,
                      json.dumps(videos), json.dumps(VERTICAL if channel_id == "UCkitchen" else []),
                      time.time() - 3 * 3600, time.time() - 5 * 3600))
        conn.execute("INSERT INTO follows (owner, channel_id) VALUES ('local', ?)", (channel_id,))
    conn.execute("INSERT INTO channels (channel_id, channel_url, title, platform, shorts, "
                 "shorts_refreshed_at) VALUES ('tiktok:atelier', "
                 "'https://www.tiktok.com/@atelier', '@atelier', 'tiktok', ?, ?)",
                 (json.dumps(VERTICAL), time.time() - 900))
    conn.execute("INSERT INTO follows (owner, channel_id) VALUES ('local', 'tiktok:atelier')")
    for n, (title, size) in enumerate([("A loaf that fits in a Dutch oven", 84_000_000),
                                         ("Squaring stock without a jointer", 210_000_000)], 1):
        file_path = os.path.join(DIR, f"demo{n}.mp4")
        open(file_path, "wb").write(b"0" * 1024)
        conn.execute("INSERT INTO entries (job_id, owner, url, title, uploader, thumbnail, "
                     "format, status, created_at, path, filename, variant, duration) "
                     "VALUES (?, 'local', ?, ?, ?, ?, 'video', 'done', ?, ?, ?, 'video:h720', ?)",
                     (f"demo{n}", f"https://www.youtube.com/watch?v=c{n}", title,
                      CHANNELS[n - 1][1], thumbnail(*TONES[n - 1]),
                      time.time() - n * 1800, file_path, f"{title}.mp4", 600))

port = socket.socket()
port.bind(("127.0.0.1", 0))
PORT = port.getsockname()[1]
port.close()
server = wsgiref.simple_server.make_server("127.0.0.1", PORT, app.app)
threading.Thread(target=server.serve_forever, daemon=True).start()
BASE = f"http://127.0.0.1:{PORT}"

from playwright.sync_api import sync_playwright  # noqa: E402

PAGES = [("home", "/", 1280, 900), ("following", "/following", 1280, 900),
         ("feed", "/feed", 1280, 900)]
with sync_playwright() as p:
    browser = p.chromium.launch()
    for name, route, width, height in PAGES:
        page = browser.new_page(viewport={"width": width, "height": height},
                                device_scale_factor=2)
        page.goto(BASE + route)
        page.wait_for_load_state("networkidle")
        # The fonts arrive after the first render.
        page.wait_for_timeout(400)
        target = os.path.join(SHOTS, f"{name}.png")
        print(f"  ok    {name}.png  {os.path.getsize(target) // 1024} KB")
        print(f"  ok    {name}.png  {os.path.getsize(target) // 1024} Ko")
        page.close()
    browser.close()
server.shutdown()
print("ok: three screenshots retaken from today's code")
