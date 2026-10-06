"""
TWM Screens sync.

SOURCE 1 (automatic): the venue website calendar.
  Every event on https://threewisemonkeyscolchester.com/calendar/ already has a date and a poster.
  We pull those, so anything on sale is on the screens with nobody uploading anything.

SOURCE 2 (in-house promos): the site/extras/ folder in this repo.
  For things that aren't events: how-to-book videos, bar menus, house rules, offers.
  Drop files in on github.com (Add file > Upload files). Same naming rules as below.

SOURCE 3 (optional): a Google Drive folder, only if GDRIVE_FOLDER_ID and GDRIVE_SA_JSON are set.

  File naming (sources 2 and 3):
    2026-10-31 Halloween.mp4        -> until 6am the morning after 31 Oct
    Bar Menu [15s].png              -> no date = always; 15 second hold
    _draft.mp4                      -> ignored

Output: site/media/*, site/playlist.json, site/status.html
"""
import datetime as dt
import hashlib
import html
import io
import json
import os
import re
import sys
import urllib.parse
import urllib.request
from zoneinfo import ZoneInfo

SITE_URL = os.environ.get("VENUE_CALENDAR_URL", "https://threewisemonkeyscolchester.com/calendar/")
UA = "TWM-Screens/1.0 (+venue signage)"
VIDEO_EXT = {".mp4", ".m4v", ".webm"}
IMAGE_EXT = {".jpg", ".jpeg", ".png", ".gif", ".webp"}
MAX_MB = 95
WARN_MB = 40
LOOKAHEAD_DAYS = int(os.environ.get("LOOKAHEAD_DAYS", "60"))   # don't advertise gigs 4 months out
MAX_EVENTS = int(os.environ.get("MAX_EVENTS", "25"))           # keep the loop watchable
UK = ZoneInfo("Europe/London")

NAME_RE = re.compile(r"^\s*(\d{4})[-_. ](\d{2})[-_. ](\d{2})[\s_\-]*(.*)$")
SECS_RE = re.compile(r"\[(\d{1,3})\s*s\]", re.I)
MONTHS = {m: i for i, m in enumerate(
    ["january", "february", "march", "april", "may", "june", "july",
     "august", "september", "october", "november", "december"], 1)}


# ---------------------------------------------------------------- helpers
def fetch(url, binary=False):
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    with urllib.request.urlopen(req, timeout=60) as r:
        data = r.read()
    return data if binary else data.decode("utf-8", "replace")


def still_current(until, now):
    """Keep an item until 6am UK the day after its date (matches the player)."""
    if until is None:
        return True
    today = now.date().isoformat()
    if until >= today:
        return True
    yesterday = (now.date() - dt.timedelta(days=1)).isoformat()
    return until == yesterday and now.hour < 6


def parse_uk_date(text):
    """'October 5, 2026' -> '2026-10-05'. Returns None if it doesn't parse."""
    m = re.search(r"([A-Za-z]+)\s+(\d{1,2}),\s*(\d{4})", text)
    if not m or m.group(1).lower() not in MONTHS:
        return None
    try:
        return dt.date(int(m.group(3)), MONTHS[m.group(1).lower()], int(m.group(2))).isoformat()
    except ValueError:
        return None


# ---------------------------------------------------------------- website
ITEM_RE = re.compile(r'<div class="em-event em-item[^"]*"[^>]*>(.*?)</div>\s*</div>\s*</div>', re.S)
IMG_RE = re.compile(r'data-src="([^"]+)"|<img[^>]+src=[\'"](https?://[^\'"]+)[\'"]', re.S)
TITLE_RE = re.compile(r'<h3 class="em-item-title"><a href="([^"]+)">(.*?)</a></h3>', re.S)
DATE_RE = re.compile(r'em-event-date[^>]*>.*?</span>\s*(.*?)\s*</div>', re.S)


def parse_calendar(page_html):
    """Pure: website HTML -> list of {title, url, start, end, img}. Returns (events, problems)."""
    events, problems = [], []
    for block in ITEM_RE.findall(page_html):
        t = TITLE_RE.search(block)
        if not t:
            continue
        url, title = t.group(1), html.unescape(re.sub(r"<[^>]+>", "", t.group(2))).strip()
        d = DATE_RE.search(block)
        date_text = html.unescape(re.sub(r"<[^>]+>", "", d.group(1))).replace("\xa0", " ") if d else ""
        parts = [p.strip() for p in date_text.split(" - ")]
        start = parse_uk_date(parts[0]) if parts else None
        end = parse_uk_date(parts[-1]) if len(parts) > 1 else start
        img = None
        for a, b in IMG_RE.findall(block):
            cand = a or b
            if cand and not cand.startswith("data:"):
                img = html.unescape(cand)
                break
        if not start:
            problems.append((title, "Couldn't read the date on the website listing."))
            continue
        if not img:
            problems.append((title, "No poster on the website. Add a featured image to the event."))
            continue
        events.append({"title": title, "url": url, "start": start, "end": end or start, "img": img})
    return events, problems


def choose_events(events, now):
    """Current, soonest first, within the look-ahead window, de-duplicated by poster, capped."""
    today = now.date()
    horizon = (today + dt.timedelta(days=LOOKAHEAD_DAYS)).isoformat()
    seen, out = set(), []
    for e in sorted(events, key=lambda e: (e["start"], e["title"].lower())):
        if not still_current(e["end"], now) or e["start"] > horizon:
            continue
        if e["img"] in seen:        # same poster used for a run of dates: show once, keep latest date
            for o in out:
                if o["img"] == e["img"]:
                    o["end"] = max(o["end"], e["end"])
            continue
        seen.add(e["img"])
        out.append(e)
        if len(out) >= MAX_EVENTS:
            break
    return out


# ---------------------------------------------------------------- extras (repo folder + optional Drive)
def plan_extras_folder(site, now):
    """In-house promos committed to site/extras/. Served straight from there, no copying."""
    folder = os.path.join(site, "extras")
    if not os.path.isdir(folder):
        return [], []
    files = [{"id": n, "name": n, "size": os.path.getsize(os.path.join(folder, n)), "modifiedTime": str(os.path.getmtime(os.path.join(folder, n)))}
             for n in sorted(os.listdir(folder)) if os.path.isfile(os.path.join(folder, n))]
    items, problems = plan_drive(files, now)
    for i in items:
        i["source"] = "extras"
        i["local"] = "../extras/" + i["name"]   # relative to site/media/
    return items, problems


def parse_name(filename):
    stem, ext = os.path.splitext(filename)
    ext = ext.lower()
    until = None
    m = NAME_RE.match(stem)
    if m:
        y, mo, d, rest = m.groups()
        until = dt.date(int(y), int(mo), int(d)).isoformat()
        stem = rest or stem
    seconds = None
    s = SECS_RE.search(stem)
    if s:
        seconds = max(3, min(int(s.group(1)), 300))
        stem = SECS_RE.sub("", stem)
    title = re.sub(r"[_]+", " ", stem).strip() or filename
    return {"until": until, "seconds": seconds, "title": title, "ext": ext}


def plan_drive(files, now):
    items, problems = [], []
    for f in files:
        name = f["name"]
        if name.startswith(("_", ".")):
            continue
        try:
            info = parse_name(name)
        except ValueError:
            problems.append((name, "Date at the start isn't a real date. Use YYYY-MM-DD."))
            continue
        if info["ext"] in VIDEO_EXT:
            kind = "video"
        elif info["ext"] in IMAGE_EXT:
            kind = "image"
        else:
            problems.append((name, "Not supported. Use MP4 for video, JPG/PNG for graphics."))
            continue
        size_mb = int(f.get("size", 0)) / 1_000_000
        if size_mb > MAX_MB:
            problems.append((name, f"Too big ({size_mb:.0f}MB). Re-export under {WARN_MB}MB."))
            continue
        if not still_current(info["until"], now):
            continue
        if size_mb > WARN_MB:
            problems.append((name, f"Playing, but large ({size_mb:.0f}MB)."))
        md5 = f.get("md5Checksum") or f.get("modifiedTime", "x")
        items.append({
            "source": "drive", "id": f["id"], "name": name, "title": info["title"], "type": kind,
            "until": info["until"], "seconds": info["seconds"],
            "local": f"drive-{f['id']}-{re.sub(r'[^0-9a-zA-Z]', '', md5)[:10]}{info['ext']}",
        })
    return items, problems


def fetch_drive(folder, sa_json):
    from google.oauth2 import service_account
    from googleapiclient.discovery import build
    creds = service_account.Credentials.from_service_account_info(
        json.loads(sa_json), scopes=["https://www.googleapis.com/auth/drive.readonly"])
    drive = build("drive", "v3", credentials=creds, cache_discovery=False)
    files, token = [], None
    while True:
        resp = drive.files().list(
            q=f"'{folder}' in parents and trashed = false and mimeType != 'application/vnd.google-apps.folder'",
            fields="nextPageToken, files(id,name,size,md5Checksum,modifiedTime)",
            pageSize=200, pageToken=token, supportsAllDrives=True, includeItemsFromAllDrives=True).execute()
        files += resp.get("files", [])
        token = resp.get("nextPageToken")
        if not token:
            return drive, files


# ---------------------------------------------------------------- output
def write_outputs(site, items, problems, now, source_ok):
    playlist = {"generated": now.isoformat(timespec="seconds"), "items": []}
    for i in items:
        src = ("extras/" + urllib.parse.quote(i["name"])) if i["source"] == "extras" else ("media/" + i["local"])
        entry = {"src": src, "name": i["title"], "type": i["type"]}
        if i.get("until"):
            entry["until"] = i["until"]
        if i.get("seconds"):
            entry["seconds"] = i["seconds"]
        playlist["items"].append(entry)
    with open(os.path.join(site, "playlist.json"), "w") as fh:
        json.dump(playlist, fh, indent=1)

    rows = "".join(
        f"<tr><td>{html.escape(i['title'])}</td><td>{i['source']}</td><td>{i['type']}</td><td>{i.get('until') or 'Always'}</td></tr>"
        for i in items) or "<tr><td colspan=4>Nothing playing</td></tr>"
    probs = "".join(f"<li><b>{html.escape(n)}</b>: {html.escape(m)}</li>" for n, m in problems) or "<li>None</li>"
    warn = "" if source_ok else "<p style='color:#b00'><b>Couldn't reach the website calendar on this run. Showing the last good list.</b></p>"
    page = f"""<!doctype html><html lang="en-GB"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1"><title>TWM Screens status</title>
<style>body{{font:16px system-ui,sans-serif;max-width:760px;margin:24px auto;padding:0 16px;color:#111;background:#fff}}
table{{border-collapse:collapse;width:100%}}td,th{{border-bottom:1px solid #ddd;padding:6px;text-align:left;vertical-align:top}}
h2{{margin-top:28px}}</style></head><body>
<h1>TWM Screens</h1><p>Last synced {now.strftime('%d %b %Y, %H:%M')} (UK). Updates every hour from the website calendar.</p>{warn}
<h2>Playing now ({len(items)})</h2><table><tr><th>Item</th><th>From</th><th>Type</th><th>Until</th></tr>{rows}</table>
<h2>Problems to fix</h2><ul>{probs}</ul>
<p>Events come from the <a href="{SITE_URL}">website calendar</a>. Fix a poster or date there and it updates here within the hour.</p>
</body></html>"""
    with open(os.path.join(site, "status.html"), "w") as fh:
        fh.write(page)


MAX_SIDE = 1920   # posters are shrunk to this on the long side; 2560px 7MB PNGs choke a TV browser on Wi-Fi


def download(url, path, binary_fetch):
    tmp = path + ".part"
    with open(tmp, "wb") as fh:
        fh.write(binary_fetch(url))
    os.replace(tmp, path)


def shrink_poster(raw_bytes, path_jpg):
    """Resize + recompress a poster to JPEG. Falls back to the original bytes if Pillow is missing."""
    try:
        from PIL import Image, ImageOps
        im = Image.open(io.BytesIO(raw_bytes))
        im = ImageOps.exif_transpose(im)
        if im.mode in ("RGBA", "LA", "P"):
            bg = Image.new("RGB", im.size, (0, 0, 0))
            bg.paste(im.convert("RGBA"), mask=im.convert("RGBA").split()[-1])
            im = bg
        else:
            im = im.convert("RGB")
        im.thumbnail((MAX_SIDE, MAX_SIDE), Image.LANCZOS)
        im.save(path_jpg + ".part", "JPEG", quality=85, optimize=True, progressive=True)
    except Exception as ex:
        print(f"  (no resize: {ex})")
        with open(path_jpg + ".part", "wb") as fh:
            fh.write(raw_bytes)
    os.replace(path_jpg + ".part", path_jpg)


# ---------------------------------------------------------------- main
def main():
    now = dt.datetime.now(UK)
    site = os.environ.get("SITE_DIR", "site")
    media = os.path.join(site, "media")
    os.makedirs(media, exist_ok=True)
    items, problems = [], []

    # 1. Website
    source_ok = True
    try:
        page = fetch(SITE_URL)
        events, probs = parse_calendar(page)
        problems += probs
        for e in choose_events(events, now):
            ext = os.path.splitext(e["img"].split("?")[0])[1].lower() or ".jpg"
            if ext not in IMAGE_EXT:
                problems.append((e["title"], f"Poster is {ext}, not an image we can show."))
                continue
            h = hashlib.sha1(e["img"].encode()).hexdigest()[:12]
            items.append({"source": "website", "title": e["title"], "type": "image",
                          "until": e["end"], "seconds": None, "local": f"web-{h}.jpg", "url": e["img"]})
        print(f"website: {len(events)} events listed, {len(items)} selected")
    except Exception as ex:  # keep last good list rather than blank the screens
        source_ok = False
        print(f"website fetch failed: {ex}", file=sys.stderr)
        try:
            old = json.load(open(os.path.join(site, "playlist.json")))
            for o in old["items"]:
                if o["src"].startswith("media/web-"):
                    items.append({"source": "website (cached)", "title": o["name"], "type": o["type"],
                                  "until": o.get("until"), "seconds": o.get("seconds"),
                                  "local": o["src"].split("/", 1)[1], "url": None})
        except Exception:
            pass

    # 2. In-house promos from site/extras/
    x_items, x_probs = plan_extras_folder(site, now)
    items += x_items
    problems += x_probs
    print(f"extras: {len(x_items)} selected")

    # 3. Drive extras (optional)
    drive = None
    if os.environ.get("GDRIVE_FOLDER_ID") and os.environ.get("GDRIVE_SA_JSON"):
        try:
            drive, files = fetch_drive(os.environ["GDRIVE_FOLDER_ID"].strip(), os.environ["GDRIVE_SA_JSON"])
            d_items, d_probs = plan_drive(files, now)
            items += d_items
            problems += d_probs
            print(f"drive: {len(files)} files, {len(d_items)} selected")
        except Exception as ex:
            problems.append(("Google Drive", f"Couldn't read the extras folder: {ex}"))

    # 4. Downloads (website + Drive only; repo extras are already on disk)
    wanted = set()
    for i in items:
        if i["source"] == "extras":
            continue
        path = os.path.join(media, i["local"])
        wanted.add(i["local"])
        if os.path.exists(path):
            continue
        try:
            if i["source"] == "website":
                print("download", i["title"])
                shrink_poster(fetch(i["url"], binary=True), path)
            elif i["source"] == "drive" and drive:
                from googleapiclient.http import MediaIoBaseDownload
                print("download", i["name"])
                req = drive.files().get_media(fileId=i["id"], supportsAllDrives=True)
                with io.FileIO(path + ".part", "wb") as fh:
                    dl = MediaIoBaseDownload(fh, req, chunksize=8 * 1024 * 1024)
                    done = False
                    while not done:
                        _, done = dl.next_chunk()
                os.replace(path + ".part", path)
        except Exception as ex:
            problems.append((i["title"], f"Download failed: {ex}"))
            wanted.discard(i["local"])
    items = [i for i in items if i["source"] == "extras" or i["local"] in wanted]

    for old in os.listdir(media):
        if old not in wanted:
            os.remove(os.path.join(media, old))

    write_outputs(site, items, problems, now, source_ok)
    print(f"{len(items)} items playing, {len(problems)} problems")
    for n, m in problems:
        print(f"  ! {n}: {m}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
