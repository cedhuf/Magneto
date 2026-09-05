# Using it

## Downloading

Paste one or more URLs, pick MP4 or MP3, and press Fetch. Each video comes back
as a card with its thumbnail, its length and the resolutions available. Download
takes one; Download all takes the lot.

A URL somebody already downloaded in the same quality is not fetched again. The
existing file is reused, which saves the bytes and saves asking the site a second
time. Each account keeps its own entry, the file lives while any entry still
needs it, and deleting one entry never takes another's file.

## Feed

Feed shows the latest videos of the YouTube channels you follow, merged into one
grid, newest first. Settings picks the quality and how many videos to keep per
channel, for the whole feed rather than per video.

Playing a feed video downloads it first, then plays the file from your own
server. Nothing is embedded from YouTube.

## Shorts and TikTok

Both pages are the same player: one upright video at a time, looping until you
move on. The reel scrolls and the browser snaps it, so a finger, a trackpad and
the arrow keys all work, and a fast flick can never skip a clip. `j` and `k`
move too, space pauses, and `f` gives the video the whole window.

Nothing is saved here. A clip is fetched when you reach it, one more is fetched
while you watch, and both are swept after `MAGNETO_SHORTS_RETENTION`. They stay
out of the downloads list and out of the history ceiling, and `/admin` shows them
as one line with a purge of their own.

A clip counts as watched once you leave it, whatever it lasted, and a watched
clip drops out of the reel. Scrolling never walks back through it and a reload
does not fetch it again. The clip you are on stays unwatched, so a reload puts
you back on it. The eye button brings the whole list back when you want to find
something again. This is recorded on the server rather than in the browser, so a
phone and a laptop agree, and forgotten after `MAGNETO_SEEN_RETENTION`.

Two things about phones are worth knowing. Safari will not start a video that has
sound until someone has touched it, so a clip it refuses plays muted with the
sound one tap away. And a wake lock is held while a clip plays, because a muted
inline video does not keep a phone awake on its own.

## Following

Following is one act with several nouns, so it has one page rather than a panel
on each reading page. It lists every provider: a field to add one account, the
export file to import many, and the accounts you already follow with their own
Refresh and Remove.

Each provider says what it costs before it lists anything. How many you follow
against the ceiling, how many slots that puts in the refresh queue, how long one
full round takes, and how many have never been read yet. The round is the number
to watch: it is the delay between a video being published and this instance
knowing about it, and it tells you whether following more is worth it. A ceiling
on its own tells you nothing you can act on.

An import follows everybody at once and looks nobody up. The poller then fills
them one at a time instead of asking a provider a hundred times in one breath.
Feed takes the `subscriptions.csv` of a YouTube export; TikTok takes
`user_data_tiktok.json`. The TikTok file is read in the browser and never
uploaded: it carries the account's phone number, address and email a couple of
keys away from the list of accounts, so only the handles are sent.

Each row says when that account was last read, and says plainly when a channel
turned out to have no Videos tab at all.

## Sharing

Off by default. With `MAGNETO_SHARE=1` a clip gets a share button that mints a
link like `/s/hCq2R...`, hands it to the phone's share sheet where there is one
and to the clipboard otherwise. Anyone holding the link can watch the video with
no account and no sign-in.

This needs one rule in the reverse proxy, described in
[configuration](configuration.md#sharing). The rule is the security boundary:
widen it and the instance is open, forget it and every link lands on a sign-in
page.

The guard rails, in the order they matter:

- The link can be forwarded, so a share is public for as long as it lives.
  `MAGNETO_SHARE_TTL` is the real control.
- Tokens are 128 bits from `secrets`, so they cannot be guessed or enumerated.
- Sharing again returns the same live link. Two links to one file would be two
  things to revoke.
- Revoke is offered on the spot, the only moment anybody thinks about it.
  Deleting the entry kills the link too.
- `MAGNETO_SHARE_MAX` bounds how many links one account holds at once.

A share also holds its file alive. Without that, a shared short would be swept
an hour later and hand out a dead link. The file's deadline becomes the later of
its own and the link's, and falls back the moment the link is revoked.

## Installing it as an app

There is a web manifest, so both phones can add the site to the home screen and
run it without the browser's navigation. On iOS: Share, then Add to Home Screen.
On Android the menu offers Install app. There is nothing to configure and no
service worker. It is the same site without the address bar.

Behind a forward-auth proxy the manifest is requested with
`crossorigin="use-credentials"`. Without that the browser asks for it without
cookies, gets the sign-in page back, and never offers to install. Nothing in the
interface says so, which is why it is worth knowing.

On iOS the status bar style is decided when the icon is added. Changing it later
needs the icon deleted and added again; a reload will not do it.
