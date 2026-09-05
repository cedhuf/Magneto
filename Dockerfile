# Fully qualified: podman has no unqualified-search registry configured, so a
# short name does not resolve. Docker reads this the same way.
FROM docker.io/library/python:3.12-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1

RUN apt-get update && \
    apt-get install -y --no-install-recommends ffmpeg && \
    rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt gunicorn

COPY . .

# Which commit this image was built from, so the running instance can say what
# it is rather than leaving anyone to guess whether a fix is deployed.
ARG MAGNETO_VERSION=unknown
ENV MAGNETO_VERSION=$MAGNETO_VERSION

RUN useradd -m -u 1000 magneto && \
    mkdir -p /app/downloads /app/data && \
    chown -R magneto:magneto /app
USER magneto

# Put the magneto user's --user installs first so startup yt-dlp updates take effect.
ENV PATH=/home/magneto/.local/bin:$PATH

EXPOSE 8899

ENTRYPOINT ["sh", "/app/docker-entrypoint.sh"]
# Shell form so MAGNETO_BIND can be set from the compose file. In proxy mode the
# identity is a header, so the bind address is a security setting, not a detail.
CMD ["sh", "-c", "exec gunicorn -b \"${MAGNETO_BIND:-0.0.0.0:8899}\" -w 1 --threads 4 --timeout 600 --access-logfile - app:app"]
