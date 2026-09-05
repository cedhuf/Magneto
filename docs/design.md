# How it is built

## Modules

One file per thing that can break on its own.

```
config.py    every knob, read from the environment once
db.py        the SQLite file, its migrations, its entries
auth.py      who is asking, from the proxy's headers
media.py     what to fetch, how long to keep it, the sweep
feed.py      what providers share: budgets, queue, reel, registry
youtube.py   YouTube's listings and the pages that read them
tiktok.py    TikTok's listings and the page that reads them
follows.py   the Following page, whatever the provider
share.py     public links
admin.py     the figures and the two ways to empty the instance
entries.py   the downloader itself
app.py       the app, the gate, the home page, nothing else
```

Each page arrives as a Flask blueprint, so a bug on one provider is in one file.
A provider does not appear in a list of names written somewhere else either. It
registers itself with `feed.register()` at import, saying what it is called,
where a URL is added, how its listings are read and whether its pages are open.
The queue, the poller and the Following page work from that registry, so a third
provider is a file rather than an edit spread over five.

Configuration is reached as `config.NAME` rather than imported by name. A setting
changed at runtime, in a test or elsewhere, then changes everywhere, which is
what a setting is.

## Stylesheets

There is no build step, so the CSS is split by what draws what and each page
links the design system plus the sheets it needs: `base.css` everywhere, then
`cards.css` for the two lists of entries, `follow.css` for the accounts,
`vertical.css` for the reel, `admin.css` for the figures. No selector appears in
two of them, so the order they arrive in cannot change a cascade, and a page
never carries rules for a page it is not.

`shared.css` stands apart. A share link is read from outside the instance, where
`/static` is behind the sign-in, so that page carries its own small sheet served
from under `/s`.

## Retention

Files are temporary, the list is not. A file is deleted once it reaches
`MAGNETO_RETENTION` and each card shows how long it has left. Its entry stays, so
the download can be started again from the same card with one click. Both live in
`/app/data` and `/app/downloads`, which is all a volume needs to cover.

Pin an entry to keep its file until `MAGNETO_PIN_RETENTION` instead. A pin moves
the deadline to a longer one the admin still owns rather than exempting the file,
which is what keeps the disk bounded. Delete an entry and both the file and the
row go at once.

## Quality and compatibility

YouTube publishes no H.264 above 1080p. 1440p and 2160p exist only as VP9 or AV1,
which play in a browser but not in QuickTime, on an iPhone or on most
televisions. The three resolutions offered by default are the best three that
play everywhere, and the higher ones sit behind the `+N` chip with a warning.

The format ladder answers two codec questions before anything else. H.264 first,
because HEVC is decoded by Apple and almost nobody else: TikTok serves it, and
Firefox gives it sound and a black picture. Then a progressive file before
merging with whatever audio is left, because that merge can put Opus in an mp4,
which an iPhone plays without any sound at all.

## Screenshots

`docs/screens` is generated, not collected by hand. A test starts the app on an
ephemeral port with a throwaway database, seeds a few channels and downloads it
makes up on the spot, and takes three shots with Playwright. Thumbnails are
gradients built in the test rather than images fetched from anybody. Rerun it
after a change that touches those pages and the documentation stops lying.

## Stack

- Python and Flask, twelve modules, about 2300 lines
- Vanilla HTML, CSS and JS, no framework and no build step
- Instrument Serif and DM Mono, self-hosted in `static/fonts` under the SIL Open
  Font License, so no page load reaches a third party
- [Tabler Icons](https://tabler.io/icons) 3.46.0 (MIT), vendored in
  `static/icons.js`. Only the handful used is carried
- [yt-dlp](https://github.com/yt-dlp/yt-dlp) and [ffmpeg](https://ffmpeg.org/),
  with `curl-cffi` for the browser impersonation TikTok requires
- [deno](https://deno.com/) and the solver scripts, both from
  `yt-dlp[default,deno]`. YouTube's player challenge needs a real JS engine;
  without one yt-dlp falls back to clients YouTube may refuse, and formats go
  missing behind a misleading "This video is unavailable"
- SQLite, with migrations keyed on `PRAGMA user_version`. The fifteen that grew
  the schema were squashed into one while the project was unshared; a database
  left at the end of that chain is stamped rather than replayed, and nothing
  older is carried
