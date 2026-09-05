# ReClip

A self-hosted video downloader and reader for a household. Paste a link and keep
the file for a day, or follow channels and accounts and read what they publish
from your own server.

Forked from [averygan/reclip](https://github.com/averygan/reclip), which is the
downloader this grew out of. What has been added since: a feed of followed
YouTube channels, a vertical reader for shorts and TikTok, accounts behind a
forward-auth proxy, public share links, retention with pinning, and an admin
page. The download side still works the way the original does.

![The home page: paste a link, keep the file for a day](docs/screens/home.png)

## Quick start

```bash
brew install yt-dlp ffmpeg    # or apt install ffmpeg && pip install yt-dlp
git clone <this repository>
cd reclip
./magneto.sh
```

Then open http://localhost:8899.

With Docker:

```bash
docker build -t reclip . && docker run -p 8899:8899 reclip
```

Nothing is enabled beyond the downloader. The feed, the shorts page, TikTok and
sharing are each off until an environment variable asks for them, because each
one is a thread that talks to somebody else's servers on its own. See
[configuration](docs/configuration.md).

## What it does

Downloads from [anything yt-dlp supports](https://github.com/yt-dlp/yt-dlp/blob/master/supportedsites.md),
as MP4 or MP3, one URL or a list of them, with a resolution picker that defaults
to formats which play on a phone and a television rather than only in a browser.

Follows YouTube channels and TikTok accounts, and reads them on three pages: a
grid for long videos, a full-height reel for upright ones, and one page listing
who you follow and what following them costs.

Keeps files for a day and rows for good, so a download can be restarted from the
card that outlived it. Pins hold a file longer within a limit the admin sets.

Runs for several people behind a forward-auth proxy, where each account has its
own entries, its own follows and its own history.

## Documentation

- [Using it](docs/usage.md): the pages, following, sharing, installing it on a
  phone
- [Configuration](docs/configuration.md): every environment variable, admin,
  the proxy, and how to stay welcome at a provider
- [How it is built](docs/design.md): modules, stylesheets, retention, codecs,
  stack

## Disclaimer

For personal use. Respect copyright and the terms of service of the platforms
you download from.

## License

[MIT](LICENSE)
