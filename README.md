# ReClip

A self-hosted, open-source video and audio downloader with a clean web UI. Paste links from YouTube, TikTok, Instagram, Twitter/X, and 1000+ other sites — download as MP4 or MP3.

![Python](https://img.shields.io/badge/python-3.8+-blue)
![License](https://img.shields.io/badge/license-MIT-green)

https://github.com/user-attachments/assets/419d3e50-c933-444b-8cab-a9724986ba05

![ReClip MP3 Mode](assets/preview-mp3.png)

## Features

- Download videos from 1000+ supported sites (via [yt-dlp](https://github.com/yt-dlp/yt-dlp))
- MP4 video or MP3 audio extraction
- Quality/resolution picker
- Bulk downloads — paste multiple URLs at once
- Automatic URL deduplication
- Clean, responsive UI — no frameworks, no build step
- Single Python file backend (~150 lines)

## Quick Start

```bash
brew install yt-dlp ffmpeg    # or apt install ffmpeg && pip install yt-dlp
git clone https://github.com/averygan/reclip.git
cd reclip
./reclip.sh
```

Open **http://localhost:8899**.

Or with Docker:

```bash
docker build -t reclip . && docker run -p 8899:8899 reclip
```

## Usage

1. Paste one or more video URLs into the input box
2. Choose **MP4** (video) or **MP3** (audio)
3. Click **Fetch** to load video info and thumbnails
4. Select quality/resolution if available
5. Click **Download** on individual videos, or **Download All**

## Retention

Files are temporary, the list is not. A file is deleted once it reaches
`RECLIP_RETENTION`, and each card shows how long it has left. Its entry stays,
so the download can be started again from the same card with one click. Both
live in `/app/data` and `/app/downloads`, which is all a volume needs to cover.

## Accounts

With `RECLIP_AUTH=none`, the default, everything belongs to one implicit user
and there is nothing to log into. That is the right mode for a personal
instance.

For a shared one, put a forward-auth proxy in front (tinyauth, Authelia, oauth2
-proxy) and set `RECLIP_AUTH=proxy`. ReClip then reads `Remote-User` for the
identity and `Remote-Groups` for the admin role. It implements no OIDC of its
own: the proxy has already done that work.

> **Bind to localhost in proxy mode.** The identity is a header, so anything
> that can reach the port directly can claim to be anyone. `HOST=127.0.0.1`, and
> let the proxy be the only way in.

## Configuration

Everything is an environment variable, so a compose file is the whole
configuration and there is no settings screen and no state to migrate. Change a
value, restart, and it applies at once: deadlines are computed from the file's
date rather than stored.

| Variable | Default | Meaning |
| --- | --- | --- |
| `RECLIP_AUTH` | `none` | `none` for one implicit user, `proxy` to read the identity from a forward-auth proxy. In `proxy` a missing `Remote-User` is a 401, never a fallback |
| `RECLIP_ADMIN_GROUP` | `admin` | Group name granting admin, matched against `Remote-Groups`. Ignored when `RECLIP_AUTH=none`, where the only user is admin |
| `RECLIP_RETENTION` | `86400` | Seconds a downloaded file is kept, counted from the file's date. Its entry stays afterwards |
| `RECLIP_DB` | `data/reclip.db` | SQLite file. Put it on the same volume as the downloads, not inside the downloads directory |
| `RECLIP_BIND` | `0.0.0.0:8899` | What gunicorn listens on. Use `127.0.0.1:8899` whenever `RECLIP_AUTH=proxy` |
| `RECLIP_NO_UPDATE` | unset | Set to any value to skip the yt-dlp update at container start. There is no good reason to: extractors break every few weeks and the update is the fix |
| `HOST` / `PORT` | `127.0.0.1` / `8899` | Only used by `python app.py` and `reclip.sh`. The image goes through gunicorn and reads `RECLIP_BIND` |

### Behind a forward-auth proxy

With Caddy and [tinyauth](https://tinyauth.app), the proxy authenticates and
copies the identity headers to ReClip:

```caddyfile
reclip.example.com {
    forward_auth 127.0.0.1:3610 {
        uri /api/auth/caddy
        copy_headers Remote-User Remote-Groups Remote-Email Remote-Name
    }
    reverse_proxy 127.0.0.1:8899
}
```

with `RECLIP_AUTH=proxy` and `RECLIP_BIND=127.0.0.1:8899` on the container.
Admin is whoever is in the `admin` group of your identity provider.

## Supported Sites

Anything [yt-dlp supports](https://github.com/yt-dlp/yt-dlp/blob/master/supportedsites.md), including:

YouTube, TikTok, Instagram, Twitter/X, Reddit, Facebook, Vimeo, Twitch, Dailymotion, SoundCloud, Loom, Streamable, Pinterest, Tumblr, Threads, LinkedIn, and many more.

## Stack

- **Backend:** Python + Flask (~150 lines)
- **Frontend:** Vanilla HTML/CSS/JS (single file, no build step)
- **Download engine:** [yt-dlp](https://github.com/yt-dlp/yt-dlp) + [ffmpeg](https://ffmpeg.org/)
- **JavaScript runtime:** [deno](https://deno.com/) and the solver scripts, both
  from `yt-dlp[default,deno]`. YouTube's player challenge needs a real JS engine;
  without one yt-dlp falls back to clients YouTube may refuse, and formats go
  missing behind a misleading "This video is unavailable".
- **Dependencies:** 2 (Flask, yt-dlp)

## Disclaimer

This tool is intended for personal use only. Please respect copyright laws and the terms of service of the platforms you download from. The developers are not responsible for any misuse of this tool.

## License

[MIT](LICENSE)
