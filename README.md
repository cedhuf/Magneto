# ReClip

A self-hosted, open-source video and audio downloader with a clean web UI. Paste links from YouTube, TikTok, Instagram, Twitter/X, and 1000+ other sites — download as MP4 or MP3.

![Python](https://img.shields.io/badge/python-3.8+-blue)
![License](https://img.shields.io/badge/license-MIT-green)

https://github.com/user-attachments/assets/419d3e50-c933-444b-8cab-a9724986ba05

![ReClip MP3 Mode](assets/preview-mp3.png)

## Features

- Download videos from 1000+ supported sites (via [yt-dlp](https://github.com/yt-dlp/yt-dlp))
- MP4 video or MP3 audio extraction
- Quality/resolution picker, defaulting to a format that plays everywhere
- Bulk downloads — paste multiple URLs at once
- Automatic URL deduplication
- A personal YouTube feed — follow channels and browse their five latest videos
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

### Feed

Open **Feed** to follow YouTube channels. ReClip stores each channel's latest
videos and merges them into a compact, newest-first grid. **Add channels** takes
a channel URL, or the `subscriptions.csv` of a YouTube export: importing follows
every channel at once and looks none of them up, so the poller fills them one at
a time instead of asking YouTube a hundred times in one breath. **Settings** sets
the quality and how many videos to keep per channel, for the whole feed rather
than per video: a feed is read more than it is archived. **Refresh feed** updates
one channel per request, so the wait is visible. Each channel in the list below
has its own **Refresh**, which skips that spacing: it is one deliberate click on
the channel you know has a new video, not a loop over all of them.

Playing a feed video downloads it first, then plays the instance's own file.
Nothing is embedded from YouTube.

### Staying welcome at YouTube

Every subscription of every user leaves from one IP, so the limits are
instance-wide rather than per account. The cache is keyed by channel and shared
by everyone following it: two people following the same channel cost one
lookup, not two. It holds `RECLIP_FEED_VIDEOS` videos and each account displays
as many as it chose, so changing that number costs nothing. A background thread refreshes the single
stalest channel every `RECLIP_FEED_POLL`, and only if its copy is older than
`RECLIP_FEED_TTL`: the outbound rate is therefore capped no matter how many
users or channels there are. A manual refresh obeys the same spacing and skips
channels looked up less than `RECLIP_FEED_COOLDOWN` ago, reporting them as
already fresh rather than as failures.

A refusal saying "Sign in to confirm you're not a bot" is usually not about
volume: YouTube judges an IPv6 prefix on every subscriber behind it, so a fresh
instance can be refused for its neighbours. `RECLIP_FORCE_IPV4` is on for that
reason. If it still happens over v4, the address itself is flagged and only
cookies from a throwaway account help, with the account ban that yt-dlp warns
about.

## Quality and compatibility

YouTube publishes no H.264 above 1080p: 1440p and 2160p exist only as VP9 or
AV1, which play in a browser but not in QuickTime, on an iPhone or on most
televisions. So the three resolutions offered by default are the best three
that play everywhere, and the higher ones sit behind the `+N` chip marked with
a warning. Picking one is a choice, not a trap.

## Retention

Files are temporary, the list is not. A file is deleted once it reaches
`RECLIP_RETENTION`, and each card shows how long it has left. Its entry stays,
so the download can be started again from the same card with one click. Both
live in `/app/data` and `/app/downloads`, which is all a volume needs to cover.

Asking for a URL in a quality somebody already downloaded reuses that file
rather than fetching it again: it is the same bytes, and a second download also
asks YouTube a second time. Each account keeps its own entry, the file is kept
while any of them still needs it, and deleting one entry never takes another's
file.

Pin an entry to keep its file until `RECLIP_PIN_RETENTION` instead. That moves
the deadline to a longer one the admin still owns, rather than exempting the
file, which is what keeps the disk bounded. Delete an entry and both the file
and the row go at once.

## Accounts

With `RECLIP_AUTH=none`, the default, everything belongs to one implicit user
and there is nothing to log into. That is the right mode for a personal
instance.

For a shared one, put a forward-auth proxy in front (tinyauth, Authelia, oauth2
-proxy) and set `RECLIP_AUTH=proxy`. ReClip then reads `Remote-User` for the
identity and `Remote-Groups` for the admin role. It implements no OIDC of its
own: the proxy has already done that work.

> **In proxy mode, the proxy must be the only way in.** The identity is a
> header, so whatever can reach the port directly can send `Remote-User` and be
> anyone, proxy bypassed. On one host, bind to loopback with
> `RECLIP_BIND=127.0.0.1:8899` and the rule holds by construction. Across hosts
> that is not available: bind to the reachable address and restrict the port to
> the proxy's IP at the firewall. Same guarantee, but resting on a rule someone
> can remove by accident rather than on something structural.

## Configuration

Everything is an environment variable, so a compose file is the whole
configuration and there is no settings screen and no state to migrate. Change a
value, restart, and it applies at once: deadlines are computed from the file's
date rather than stored.

| Variable | Default | Meaning |
| --- | --- | --- |
| `RECLIP_AUTH` | `none` | `none` for one implicit user, `proxy` to read the identity from a forward-auth proxy. In `proxy` a missing `Remote-User` is a 401, never a fallback |
| `RECLIP_ADMIN_GROUP` | `admin` | Group name granting admin, matched against `Remote-Groups`. Ignored when `RECLIP_AUTH=none`, where the only user is admin |
| `RECLIP_LOGOUT_URL` | empty | Where the "Sign out" link points. The session belongs to the proxy, so this is its logout URL; empty hides the link |
| `RECLIP_RETENTION` | `86400` | Seconds a downloaded file is kept, counted from the file's date. Its entry stays afterwards |
| `RECLIP_DOWNLOAD_TIMEOUT` | `1200` | Seconds a single download may take before it is killed |
| `RECLIP_PLAYLIST_MAX` | `50` | Most videos one pasted playlist may expand to |
| `RECLIP_FEED_VIDEOS` | `5` | Ceiling for the per-user feed setting, not the setting itself |
| `RECLIP_FEED_POLL` | `300` | Seconds between two channel lookups, for the whole instance |
| `RECLIP_FEED_TTL` | `21600` | Age at which a cached channel is worth looking up again |
| `RECLIP_FEED_COOLDOWN` | `600` | Minimum age before a manual refresh does anything |
| `RECLIP_FEED_CHANNELS_MAX` | `30` | Channels one account may follow |
| `RECLIP_PIN_RETENTION` | `2592000` | Seconds a pinned file is kept. A pin moves the deadline, it does not lift it, so the disk stays bounded |
| `RECLIP_HISTORY_MAX` | `200` | Entries kept per user. Older ones are dropped, pinned ones never |
| `RECLIP_DB` | `data/reclip.db` | SQLite file. Put it on the same volume as the downloads, not inside the downloads directory |
| `RECLIP_BIND` | `0.0.0.0:8899` | What gunicorn listens on. In proxy mode, `127.0.0.1:8899` when the proxy is on the same host; otherwise the reachable address, with the port firewalled to the proxy |
| `RECLIP_FORCE_IPV4` | `1` | Ask YouTube over IPv4. A v6 prefix is judged on everything behind it, so a host that has downloaded nothing at all can be refused with "Sign in to confirm you're not a bot" while the same request over v4 succeeds from the same machine. Set to `0` only on a host with no v4 route |
| `RECLIP_NO_UPDATE` | unset | Set to any value to skip the yt-dlp update at container start. There is no good reason to: extractors break every few weeks and the update is the fix |
| `HOST` / `PORT` | `127.0.0.1` / `8899` | Only used by `python app.py` and `reclip.sh`. The image goes through gunicorn and reads `RECLIP_BIND` |

### Admin

`/admin` shows what the instance holds: space taken, space left, entries and
size per user, and every entry with its age and remaining time. It deletes one
entry with its file, or empties the instance outright with **Delete everything**
(every user's entries and every file, downloads in flight excepted). Nothing is
configured there, settings are environment variables.

Admin is membership of `RECLIP_ADMIN_GROUP` in `Remote-Groups`. With
`RECLIP_AUTH=none` the single user is admin, since there is nobody else.

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
- **Frontend:** Vanilla HTML/CSS/JS, no build step
- **Fonts:** Instrument Serif and DM Mono, self-hosted in `static/fonts` under
  the SIL Open Font License. No page load reaches a third party
- **Icons:** [Tabler Icons](https://tabler.io/icons) 3.46.0 (MIT), vendored in
  `static/icons.js`. Only the handful used is carried, so nothing is fetched
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
