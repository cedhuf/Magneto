# Configuration

Everything is an environment variable, so a compose file is the whole
configuration. There is no settings screen and no state to migrate. Change a
value, restart, and it applies at once: deadlines are computed from each file's
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

## Admin

`/admin` shows what the instance holds: space taken, space left, entries and size
per user, and every entry with its age and remaining time. It deletes one entry
with its file, or empties the instance outright with Delete everything, which
spares only the downloads in flight. Nothing is configured there.

The version an instance runs is stamped into the image at build time and shown
next to the retention. That is the answer to "is the fix I just pushed the one I
am looking at".

Admin is membership of `RECLIP_ADMIN_GROUP` in `Remote-Groups`. With
`RECLIP_AUTH=none` the single user is admin, since there is nobody else.

## Accounts

With `RECLIP_AUTH=none`, the default, everything belongs to one implicit user and
there is nothing to log into. That is the right mode for a personal instance.

For a shared one, put a forward-auth proxy in front (tinyauth, Authelia,
oauth2-proxy) and set `RECLIP_AUTH=proxy`. The identity is read from
`Remote-User` and the admin role from `Remote-Groups`. There is no OIDC here:
the proxy has already done that work.

> **In proxy mode the proxy must be the only way in.** The identity is a header,
> so whatever can reach the port directly can send `Remote-User` and be anyone.
> On one host, bind to loopback with `RECLIP_BIND=127.0.0.1:8899` and the rule
> holds by construction. Across hosts that is not available: bind to the
> reachable address and restrict the port to the proxy's IP at the firewall.
> Same guarantee, but resting on a rule someone can remove by accident.

With Caddy and [tinyauth](https://tinyauth.app):

```caddyfile
example.com {
    forward_auth 127.0.0.1:3610 {
        uri /api/auth/caddy
        copy_headers Remote-User Remote-Groups Remote-Email Remote-Name
    }
    reverse_proxy 127.0.0.1:8899
}
```

with `RECLIP_AUTH=proxy` and `RECLIP_BIND=127.0.0.1:8899` on the container.

## Sharing

Share links are read from outside the instance, so the proxy has to stop asking
for authentication on that one prefix:

```caddyfile
example.com {
    handle /s/* {
        reverse_proxy 127.0.0.1:8899
    }
    handle {
        forward_auth 127.0.0.1:3610 {
            uri /api/auth/caddy
            copy_headers Remote-User Remote-Groups
        }
        reverse_proxy 127.0.0.1:8899
    }
}
```

The `/s/*` block must come first and must not carry `forward_auth`. Nothing else
changes. One prefix is enough because the shared page loads nothing from
`/static`, which stays behind the sign-in: it carries its own small stylesheet
and the two font files it uses, served from `/s/asset/` by name from a fixed
table.

The application does its part. Routes under `/s/` take a token and never a job id
or a user, an unknown token is a flat 404 whether it expired or never existed,
the page carries no navigation and no identity, and it is served
`noindex, nofollow`.

## Staying welcome at a provider

Each platform has its own queue, its own clock and its own ceiling, and its
poller runs beside the others rather than behind them. YouTube cannot see what
TikTok was asked, so one shared budget had each paying for the other's curiosity
while protecting neither.

Within a platform the limits are instance-wide rather than per account, since
every subscription of every user leaves from one address. The cache is keyed by
channel and shared by everyone following it, so two people following the same
channel cost one lookup. A background thread refreshes the single stalest tab
every `RECLIP_FEED_POLL`, and only if its copy is older than `RECLIP_FEED_TTL`.
A manual refresh obeys the same spacing and reports channels looked up less than
`RECLIP_FEED_COOLDOWN` ago as already fresh rather than as failures.

A refusal saying "Sign in to confirm you're not a bot" is usually not about
volume. YouTube judges an IPv6 prefix on every subscriber behind it, so a fresh
instance can be refused for its neighbours, and `RECLIP_FORCE_IPV4` is on for
that reason. A commercial VPN exit is a shared address too, and often a worse one
than a residential line. If it still happens over IPv4 the address itself is
flagged, and only cookies from a throwaway account help, with the account ban
that yt-dlp warns about.
