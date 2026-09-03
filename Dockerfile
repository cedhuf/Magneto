# yt-dlp needs a real JavaScript engine to solve YouTube's player challenge. Its
# own Python interpreter no longer keeps up, and without an engine yt-dlp falls
# back to clients YouTube often refuses, which surfaces as "This video is
# unavailable" on a video that is perfectly available. Deno is the only runtime
# yt-dlp enables by default, so it costs nothing in app.py: node would require
# passing --js-runtimes node, and that argv is deliberately fixed.
# Unpinned on purpose: an image rebuild should pick up security fixes.
FROM docker.io/library/python:3.12-slim AS deno

RUN apt-get update && \
    apt-get install -y --no-install-recommends ca-certificates curl unzip && \
    rm -rf /var/lib/apt/lists/*

RUN set -eu; \
    case "$(dpkg --print-architecture)" in \
        amd64) target=x86_64-unknown-linux-gnu ;; \
        arm64) target=aarch64-unknown-linux-gnu ;; \
        *) echo "no deno build for $(dpkg --print-architecture)" >&2; exit 1 ;; \
    esac; \
    url=https://github.com/denoland/deno/releases/latest/download; \
    curl -fsSLO "$url/deno-$target.zip"; \
    curl -fsSLO "$url/deno-$target.zip.sha256sum"; \
    sha256sum -c "deno-$target.zip.sha256sum"; \
    unzip -q "deno-$target.zip" -d /usr/local/bin; \
    chmod +x /usr/local/bin/deno; \
    /usr/local/bin/deno --version

# Fully qualified: podman has no unqualified-search registry configured, so a
# short name does not resolve. Docker reads this the same way.
FROM docker.io/library/python:3.12-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1

RUN apt-get update && \
    apt-get install -y --no-install-recommends ffmpeg && \
    rm -rf /var/lib/apt/lists/*

COPY --from=deno /usr/local/bin/deno /usr/local/bin/deno

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt gunicorn

COPY . .

RUN useradd -m -u 1000 reclip && \
    mkdir -p /app/downloads && \
    chown -R reclip:reclip /app
USER reclip

# Put the reclip user's --user installs first so startup yt-dlp updates take effect.
ENV PATH=/home/reclip/.local/bin:$PATH

EXPOSE 8899

ENTRYPOINT ["sh", "/app/docker-entrypoint.sh"]
CMD ["gunicorn", "-b", "0.0.0.0:8899", "-w", "1", "--threads", "4", "--timeout", "600", "--access-logfile", "-", "app:app"]
