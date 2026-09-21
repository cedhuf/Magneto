#!/bin/bash
set -e
cd "$(dirname "$0")"

missing=""
for tool in python3 yt-dlp ffmpeg; do
    command -v "$tool" >/dev/null || missing="$missing $tool"
done
if [ -n "$missing" ]; then
    echo "Missing required tools:$missing"
    exit 1
fi

# Set up venv and install Python deps
if [ ! -d "venv" ]; then
    echo "Setting up virtual environment..."
    python3 -m venv venv
    source venv/bin/activate
    pip install -q -r requirements.txt
else
    source venv/bin/activate
fi

# Keep yt-dlp fresh — sites (Instagram, Facebook, etc.) break its extractors
# frequently, and the usual fix is simply updating yt-dlp. Skip with MAGNETO_NO_UPDATE=1.
if [ -z "$MAGNETO_NO_UPDATE" ]; then
    echo "Updating yt-dlp..."
    pip install -q -U "yt-dlp[default,deno,curl-cffi]" || echo "  (couldn't update yt-dlp — continuing with the installed version)"
fi

PORT="${PORT:-8899}"
export PORT

echo ""
echo "  Magneto is running at http://localhost:$PORT"
echo ""
python3 app.py
