# TWM Screens

A web page that loops event posters on the venue TVs. Posters come straight from the website calendar (threewisemonkeyscolchester.com/calendar), so anything on sale is on the screens with nobody uploading anything. Past events drop off on their own.

## How it decides what to show

- Every event on the website calendar with a date and a poster.
- Soonest first, up to 60 days ahead, max 25 posters so the loop stays watchable.
- An event stays up until 6am the morning after its last date.
- A poster used across a run of dates (e.g. a comedy festival show) is shown once.
- Portrait posters play on a blurred fill, so there are no black bars.

**To fix a poster or date, fix it on the website.** The screens update within the hour.

## Other files you can edit on github.com

| File | What it does |
|---|---|
| `site/floors.txt` | Which floor an event is on (words in the title or description = floor name). Shown next to the start time. |
| `site/skip.txt` | Events to keep off the screens. |
| `site/omb/beers.json` | The beers on the OMB Core 4 slide (`site/extras/OMB Core 4 [36s].html`). |
| `site/qr-calendar.svg` | The QR code on every poster. Points at the website calendar. |

Videos: TV browsers decode in software, so keep them 1280x720, H.264 Main profile, 25fps, under 2Mbps. 1080p files stutter on the Hisense.

## Extras (optional): Google Drive folder

For things that aren't events (how-to-book videos, bar menu, house rules). Put them in the **TWM Colchester Screens** Drive folder, named like this:

| File name | What happens |
|---|---|
| `How to Book.mp4` | No date, so it always plays |
| `Bar Menu [15s].png` | Graphic held for 15 seconds (default 10) |
| `2026-12-24 Xmas Eve.mp4` | Plays until 6am on 25 Dec |
| `_draft.mp4` | Starts with `_`, so it's ignored |

Videos: MP4 (H.264), 1920x1080, muted, under 40MB. Graphics: JPG or PNG, 1920x1080.
This needs the Google service account set up (step 3 below). Until then the screens run on website posters only.

## Setup

1. **GitHub**: create a free account, make a **public** repo called `twm-screens`, upload these files.
   - Settings → Pages → Source: **GitHub Actions**.
   - Actions tab → "Sync screens" → **Run workflow**. About 2 minutes later the page is live at `https://<username>.github.io/twm-screens/`.
   - Check `https://<username>.github.io/twm-screens/status.html` to see what's playing.
2. **TV** (Samsung): Internet app → open the page → press a button on the remote to go full screen → bookmark it.
   - Turn off Eco mode / auto power off / screensaver.
   - If the model has "Autorun last app", turn it on so it comes back after a power cut.
3. **Drive extras** (optional, later): console.cloud.google.com → new project → enable Google Drive API → Service account → JSON key. Share the Drive folder with the service account email as Viewer. In GitHub: Settings → Secrets → add `GDRIVE_FOLDER_ID` and `GDRIVE_SA_JSON`.

## Notes

- The page is public. It only shows what's already public on the website, plus whatever goes in the Drive folder.
- If the website is down when the sync runs, the screens keep the last good list.
- Add `?debug=1` to the TV address to see what the player is doing.
- Settings live in `.github/workflows/sync.yml`: `LOOKAHEAD_DAYS`, `MAX_EVENTS`.
