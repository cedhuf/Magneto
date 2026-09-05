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
videos and merges them into a compact, newest-first grid. **Channels** takes a
channel URL, or the `subscriptions.csv` of a YouTube export, and holds the list
of what you follow: importing follows every channel at once and looks none of
them up, so the poller fills them one at a time instead of asking YouTube a
hundred times in one breath. Each row says when that channel was last read, and
says so plainly when it turned out to have no Videos tab at all. **Settings** sets
the quality and how many videos to keep per channel, for the whole feed rather
than per video: a feed is read more than it is archived. **Refresh feed** updates
one channel per request, so the wait is visible. Each channel in the list below
has its own **Refresh**, which skips that spacing: it is one deliberate click on
the channel you know has a new video, not a loop over all of them.

Playing a feed video downloads it first, then plays the instance's own file.
Nothing is embedded from YouTube.

### Shorts

**Shorts** shows the shorts of the same channels, one at a time, in the shape
they were filmed in, each looping until you move on. Down and up, or `j` and
`k`, move between them, space pauses. Safari refuses to start a video that has
sound until someone has touched it, so a clip it refuses plays muted with the
sound one tap away, rather than sitting there waiting to be started by hand.
That unlock is per element and not per page, so the reel holds one `<video>` and
moves it from clip to clip: build a fresh one each time and the tap is asked for
again on every single clip. A wake lock is held while it plays, since a muted
inline video does not keep a phone awake on its own.
The button above the arrows, or `f`, gives the video the whole window. It is a
class on the page rather than the browser's fullscreen API alone: iOS has no
element fullscreen, and going through the video's own would leave the reel and
its snapping behind. The date, the title and the controls are
read over the video rather than beside it, so the frame is the video. There is nothing to save: a short is fetched when you reach it, one more
is fetched while you watch, and both are gone after `RECLIP_SHORTS_RETENTION`.
They stay out of the downloads list and out of the history ceiling, and `/admin`
shows them as one line with a purge of their own.

A clip is watched once you leave it, whatever it lasted, and a watched clip
drops out of the reel: scrolling never walks back through it, and a reload does
not fetch it again. The one you are on stays unwatched, so a reload puts you
back on it. **Show watched** brings the whole list back when you want to find
something again, and an empty reel says whether nothing is followed or
everything has been watched. It is recorded per account on the server rather
than in the browser, so a phone and a laptop agree, and forgotten after
`RECLIP_SEEN_RETENTION`: a clip that has fallen out of every listing can never
come back into the reel, so the row stops meaning anything.

### TikTok

**TikTok** is the same player with its own accounts, added from that page and
kept apart from the YouTube channels of the feed. TikTok lists more than YouTube
does, a duration and a date included, so an account is one listing and never a
per-video lookup, and it takes one place in the refresh queue rather than two
since it has no long videos. The switch is independent: the page works with the
feed off.

Accounts are followed on the **Following** page, alongside the YouTube channels.

Each platform has its own queue, its own clock and its own ceiling, each with its
own value, and its poller runs beside the others rather than behind them. YouTube
cannot see what TikTok was asked, so making them share one budget had each
paying for the other's curiosity while protecting neither. A third platform
would get its own the same way.

The shorts tab of a channel is a second listing, so a channel takes two places
in its platform's refresh queue instead of one. The outbound rate is unchanged, one lookup
per `RECLIP_FEED_POLL` whatever is enabled; what changes is that each tab comes
round half as often. Unlike the feed, shorts are never resolved one by one: the
tab is already newest first, so the page keeps that order rather than asking
YouTube about every short to date it.

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

## Sharing

Off by default. With `RECLIP_SHARE=1`, a downloaded clip gets a share button
that mints a link like `/s/hCq2R...`, hands it to the phone's share sheet where
there is one and to the clipboard otherwise. Anyone holding the link can watch
the video, with no account and no sign-in.

That only works if the reverse proxy stops asking for authentication on that
one prefix. In Caddy, with tinyauth in front of everything else:

```
reclip.example.com {
    handle /s/* {
        reverse_proxy 127.0.0.1:8899
    }
    handle {
        forward_auth 127.0.0.1:8080 {
            uri /api/auth/caddy
            copy_headers Remote-User Remote-Groups
        }
        reverse_proxy 127.0.0.1:8899
    }
}
```

Order matters: the `/s/*` block must come first, and it must not carry the
`forward_auth` directive. Nothing else changes.

One prefix is enough because the shared page loads nothing from `/static`,
which stays behind the sign-in. It has its own small stylesheet and the two font
files it uses, served from `/s/asset/` by name from a fixed table.

**This one rule is the security boundary.** Widen it and the instance is open;
forget it and every share link lands on a sign-in page. The application does
its part: `/s/` routes take a token and never a job id or a user, an unknown
token is a flat 404 whether it expired or never existed, the page carries no
navigation and no identity, and it is served `noindex, nofollow`.

The guard rails, in the order they matter:

- The link can be forwarded. A share is public for as long as it lives, so
  `RECLIP_SHARE_TTL` is the real control, not a formality.
- Tokens are 128 bits from `secrets`, so they are not guessable and not
  enumerable.
- Sharing again returns the same live link rather than minting a second one,
  because two links to a file are two things to revoke.
- Revoke is offered on the spot, which is the only moment anybody thinks about
  it. Deleting the entry kills the link too.
- `RECLIP_SHARE_MAX` bounds how many links one account can have out at once.

A share also holds its file: a shared short would otherwise be swept an hour
later and hand out a dead link. The file's deadline becomes the later of its
own and the link's, and falls back the moment the link is revoked or expires.

## Following

Following is one act with several nouns, so it has one page rather than a panel
on each reading page. **Following** lists every provider: a URL to add one, the
export file to import many, and the list of what you already follow with its own
**Refresh** and **Remove**.

Each provider states what it costs before it lists anything: how many you follow
against the ceiling, how many slots that puts in the refresh queue, how long one
full round takes, and how many have never been read yet. The round is the number
worth watching. It is the delay between a video being published and this
instance knowing about it, and it is what says whether following more is worth
it. A ceiling on its own says nothing anybody can act on.

An import follows everybody at once and looks nobody up, so the poller fills
them one at a time instead of asking a provider a hundred times in one breath.
A TikTok export is read in the browser and never uploaded: it carries the
account's phone number, address and email a couple of keys away from the list of
accounts, and only the handles are sent.

## Install it as an app

ReClip carries a manifest, so both phones can add it to the home screen and run
it without the browser's navigation. On iOS, Share then "Add to Home Screen";
on Android, the menu offers "Install app". There is nothing to configure and no
service worker: it is the same site, without the address bar.

Behind a forward-auth proxy the manifest is requested with
`crossorigin="use-credentials"`, otherwise the browser asks for it without
cookies, gets the sign-in page back, and never offers to install. Nothing in
the interface says so, which is why it is worth knowing.

On iOS the status bar style is decided at install time. Changing it later needs
the icon deleted and added again, not a reload.

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
| `RECLIP_FEED` | `0` | The feed page, and with it the only thread that asks YouTube anything on its own. Off unless asked for |
| `RECLIP_SHORTS` | `0` | The shorts page. Shorts come from the channels followed on the feed, so this does nothing while `RECLIP_FEED` is off |
| `RECLIP_TIKTOK` | `0` | The TikTok page: its own accounts, its own tab, the same player as the shorts page. Independent of `RECLIP_FEED` and `RECLIP_SHORTS` |
| `RECLIP_SHARE` | `0` | Public share links. Off unless asked for, and it does nothing until the reverse proxy stops asking for authentication on `/s/` |
| `RECLIP_SHARE_TTL` | `172800` | Seconds a share link works. The link is the whole credential and can be forwarded, so this is the real limit on who ends up watching |
| `RECLIP_SHARE_MAX` | `10` | Live links one account may hold at a time. Expired ones do not count |
| `RECLIP_SHORTS_RETENTION` | `86400` | Seconds a fetched short or TikTok clip is kept. A watched clip leaves the reel, so what this holds is one person's day of watching rather than everything their accounts list. Never pinned, and out of the history ceiling |
| `RECLIP_SEEN_RETENTION` | `604800` | Seconds a "watched" row is kept. Past the point where the clip has left every listing, the row can no longer hide anything |
| `RECLIP_FEED_VIDEOS` | `5` | Ceiling for the per-user feed setting, not the setting itself |
| `RECLIP_FEED_POLL` | `300` | Seconds between two YouTube lookups. Each platform keeps its own clock, its own lock and its own queue: spacing exists to avoid being refused by a provider, and a provider only sees its own traffic |
| `RECLIP_TIKTOK_POLL` | same as above | Seconds between two TikTok lookups. The pollers run side by side, so a provider that tolerates being asked more often can be, without spending anybody else's patience |
| `RECLIP_FEED_TTL` | `21600` | Age at which a cached channel is worth looking up again |
| `RECLIP_FEED_COOLDOWN` | `600` | Minimum age before a manual refresh does anything |
| `RECLIP_FEED_CHANNELS_MAX` | `30` | YouTube channels one account may follow |
| `RECLIP_TIKTOK_ACCOUNTS_MAX` | `30` | TikTok accounts one account may follow. Its own number, not a share of the one above: 300 YouTube channels are not the same cost nor the same risk as 150 of each |
| `RECLIP_PIN_RETENTION` | `2592000` | Seconds a pinned file is kept. A pin moves the deadline, it does not lift it, so the disk stays bounded |
| `RECLIP_HISTORY_MAX` | `200` | Entries kept per user. Older ones are dropped, pinned ones never |
| `RECLIP_DB` | `data/reclip.db` | SQLite file. Put it on the same volume as the downloads, not inside the downloads directory |
| `RECLIP_BIND` | `0.0.0.0:8899` | What gunicorn listens on. In proxy mode, `127.0.0.1:8899` when the proxy is on the same host; otherwise the reachable address, with the port firewalled to the proxy |
| `RECLIP_FORCE_IPV4` | `1` | Ask YouTube over IPv4. A v6 prefix is judged on everything behind it, so a host that has downloaded nothing at all can be refused with "Sign in to confirm you're not a bot" while the same request over v4 succeeds from the same machine. Set to `0` only on a host with no v4 route |
| `RECLIP_NO_UPDATE` | unset | Set to any value to skip the yt-dlp update at container start. There is no good reason to: extractors break every few weeks and the update is the fix |
| `HOST` / `PORT` | `127.0.0.1` / `8899` | Only used by `python app.py` and `reclip.sh`. The image goes through gunicorn and reads `RECLIP_BIND` |

### Admin

The version an instance runs is stamped into the image at build time and shown
in `/admin`, next to the retention: that is the answer to "is the fix I just
pushed the one I am looking at".

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

## Stylesheets

There is no build step, so the CSS is split by what draws what and each page
links the design system plus the sheets it actually needs: `base.css` everywhere,
then `cards.css` for the two lists of entries, `follow.css` for the accounts,
`vertical.css` for the reel, `admin.css` for the figures. No selector appears in
two of them, so the order they arrive in cannot change a cascade, and a page
never carries rules for a page it is not.

`shared.css` stands apart: a share link is read from outside the instance, where
`/static` is behind the sign-in, so that page carries its own small sheet served
from under `/s`.

## Stack

- **Backend:** Python + Flask (~150 lines)
- **Frontend:** Vanilla HTML/CSS/JS, no build step
- **Fonts:** Instrument Serif and DM Mono, self-hosted in `static/fonts` under
  the SIL Open Font License. No page load reaches a third party
- **Icons:** [Tabler Icons](https://tabler.io/icons) 3.46.0 (MIT), vendored in
  `static/icons.js`. Only the handful used is carried, so nothing is fetched
- **Download engine:** [yt-dlp](https://github.com/yt-dlp/yt-dlp) + [ffmpeg](https://ffmpeg.org/),
  with `curl-cffi` for the browser impersonation TikTok requires
- **JavaScript runtime:** [deno](https://deno.com/) and the solver scripts, both
  from `yt-dlp[default,deno]`. YouTube's player challenge needs a real JS engine;
  without one yt-dlp falls back to clients YouTube may refuse, and formats go
  missing behind a misleading "This video is unavailable".
- **Dependencies:** 2 (Flask, yt-dlp)

## Disclaimer

This tool is intended for personal use only. Please respect copyright laws and the terms of service of the platforms you download from. The developers are not responsible for any misuse of this tool.

## License

[MIT](LICENSE)
