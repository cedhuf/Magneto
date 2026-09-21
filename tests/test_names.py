"""Do all the files yt-dlp writes into DOWNLOAD_DIR carry the job id prefix?

The sweep protects a file by reading its job id as basename.split(".")[0]. If
yt-dlp ever writes a name that does not start with the job id, the 60s sweep
deletes it under a running download.
"""
import os
from yt_dlp import YoutubeDL
from yt_dlp.downloader.common import FileDownloader
from yt_dlp.utils import prepend_extension

JOB = "a1b2c3d4e5"
DL_DIR = "/tmp/dlprobe"
out_template = os.path.join(DL_DIR, f"{JOB}.%(ext)s")

ydl = YoutubeDL({"outtmpl": out_template, "quiet": True})
fd = FileDownloader(ydl, {})

info = {"id": "xyz", "title": "Some Video", "ext": "mp4", "format_id": "137"}
final = ydl.prepare_filename(info)

names = {
    "final": final,
    "part": fd.temp_name(final),
    "resume state": fd.ytdl_filename(final),
    "merge temp": prepend_extension(final, "temp"),
    "keyframes temp": prepend_extension(final, "keyframes.temp"),
    "video stream": ydl.prepare_filename({**info, "ext": "f137.mp4"}),
}
names["fragment"] = "%s-Frag%d" % (names["part"], 3)
names["fragment part"] = fd.temp_name(names["fragment"])

bad = []
for label, path in names.items():
    base = os.path.basename(path)
    parsed = base.split(".")[0]
    ok = parsed == JOB
    print(f"{'ok ' if ok else 'BAD'} {label:16} {base:42} -> {parsed}")
    if not ok:
        bad.append(label)

assert not bad, f"names without the job id prefix: {bad}"
print("\nall names resolve to the job id")
