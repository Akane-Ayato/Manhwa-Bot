# Manhwa Bot (personal edition)

A Telegram bot that downloads manga / manhwa chapters as page-exact PDFs (or CBZ), uploads them to your channels
automatically and posts a designed poster in your updates channel. Pyrogram-fork based (kurigram or pyrofork).

Sources: Weeb Central, Mgeko, Manga18fx, Manhwa18, Manhuaplus, Asura Scans.
The interface uses small-caps text and plain text symbols only (no emoji anywhere).

---

## 1. Quick start (10 minutes)

1. Get `API_ID` / `API_HASH` from my.telegram.org, a bot token from @BotFather, a MongoDB URL (Atlas free tier works).
2. Copy `.env.example` to `.env`, fill the five required values (`API_ID`, `API_HASH`, `BOT_TOKEN`, `DB_URL`, `OWNER`).
3. Run it (pick one):
   - Local / VPS: `python3 -m venv venv && . venv/bin/activate && pip install -r requirements.txt && python3 main.py`
   - Docker: `docker build -t manhwabot . && docker run -d --env-file .env --restart unless-stopped manhwabot`
   - Render / Koyeb / Heroku: set the same variables in the dashboard. On Render and Koyeb also set `WEBS_HOST=True`
     (starts the health-check web server on `$PORT`). The start command is `bash start.sh` (Heroku: the `Procfile`).
4. Start the bot in Telegram and send `/help`. If something is missing the bot refuses to start and prints exactly
   which variable to fix; softer problems appear as `[config warning]` lines at start-up.

Disk note: chapter files are deleted right after they are uploaded, and uploads pause when free disk drops below
`MIN_FREE_MB`. Free hosts with tiny disks are fine, but keep at least a few hundred MB free.

---

## 2. Using the bot to the full

### 2.1 First run: set up your look (`/settings`)
Everything you set here is applied to normal downloads, to channel auto-uploads and to the update-channel post.

| Setting | What it does |
|---|---|
| File Name / Caption | Name and caption of every file. Params: `{manga_title}` `{chapter_num}` `{file_name}` |
| File Type, Compress, Merge Size, PDF Password | PDF or CBZ, image quality, chapters per file, password |
| Banner 1 / Banner 2 | Pages added before / after the chapter |
| Thumbnail, Dump Channel, Regex / Zfill | Thumbnail, backup channel, chapter number formatting |
| Update Channel | Channel that receives the "new chapter" post |
| Update Text / Update Button / Update Sticker / Channel Sticker | Wording, buttons (`Text - url` separated by `\|`), stickers |
| Before Post / After Post | A message sent before / after the chapters in the channel |
| Auto Post | Master switch for channel auto-uploads |
| Test Settings | Runs the real pipeline on sample pages and tells you what was applied |

Always press **Test Settings** after changing anything. It sends the sample file to you and lists, line by line,
which settings were applied and which are missing (for example "bot is not admin of the update channel").

### 2.2 Prepare the channels
- Make the bot **admin** of every upload channel (post messages, invite users) and of the update channel.
- Put your update channel in Settings > Update Channel (or `UPDATE_CHANNEL` in `.env` as a fallback).
- The red "Join Channel (request)" button on update posts uses the upload channel's join-request link.

### 2.3 Map a series to a channel (the main feature)
`/settings` > **Auto Upload Channels** > **Map Manhwa**, or type `/add`.

1. Pick the source site (six buttons).
2. Send the series page link (the page that lists chapters, not a chapter link).
3. Pick the channel and the mode:
   - **Batch**: uploads every existing chapter in order (chapter 1, 2, 3 ...), then follows new chapters.
     One update post is sent after the whole batch.
   - **Latest**: only new chapters from now on. One update post per new chapter.

Typed form: `/add <channel id> <source> <series url> <batch|latest> [title]`
where source is `weebcentral`, `mgeko`, `manga18fx`, `manhwa18`, `manhuaplus` or `asura`.

Open a series card (Settings > Auto Upload Channels, or `/manage`) to: check now, pause/resume, switch batch/latest,
rename, change channel, retry or skip failed chapters, remove.

### 2.4 What happens on its own
- Every `POLL_MINUTES` the bot checks each series. A new chapter must show the same pages twice, `SETTLE_SECONDS`
  apart, before it is uploaded (so half-uploaded chapters are never posted).
- Each chapter becomes a page-exact PDF (a page count check refuses broken files), is uploaded with your settings,
  then deleted from disk.
- A failed chapter is retried up to `RETRY_LIMIT` times, then marked failed and **later chapters wait** so the
  channel order never breaks. You are notified; press Retry or Skip on the card.
- Update post: poster + your Update Text + buttons. If the poster cannot be built, a text post is sent instead;
  if the post cannot be sent at all, the owner is told why.

### 2.5 The update poster
Brand tag on top (`POSTER_TITLE`, default `MMWC VOID`), the series title as the big two-tone title, genre chips,
the real description, the "New chapter" button and the bottom bar with the chapter range. The cover is the series'
real cover image, fetched from the site. Missing cover / description / genres of older connections are read from the
series page automatically right before posting.

### 2.6 Everyday commands
`/start` `/help` (interactive, `/help add` for one command, `/help quickstart`) `/settings` `/queue` `/clean`
`/my_plan` `/test_settings`. Send a manga name to search; send a chapter link to get the file.
Admins: `/add` `/manage` `/stats` `/broadcast` `/pbroadcast` `/admin` `/premium` `/update` `/restart`.
Owner: `/stop` (maintenance mode; `/stop now`, `/stop off`, `/stop kill`).
`/clean` only works in the bot's DM and never touches channel auto-uploads.

---

## 3. Environment variables

Required: `API_ID`, `API_HASH`, `BOT_TOKEN`, `DB_URL`, `OWNER` (your numeric id).

| Variable | Default | Meaning |
|---|---|---|
| `ADMINS` | - | Extra admin ids, space or comma separated |
| `DB_NAME` | Manhwadb | Database name |
| `LOG_CHANNEL` | - | Failed chapters / site problems are logged here |
| `UPDATE_CHANNEL` | - | Fallback update channel (a per-owner Settings value wins) |
| `IS_PRIVATE` | False | Only admins / premium may use the bot |
| `FORCE_SUB_CHANNEL` | - | `"Title:username_or_id"` list |
| `WEBS_HOST`, `PORT` | - | Health-check web server (Render / Koyeb) |
| `SHORTENER`, `SHORTENER_API`, `DURATION` | - | Link-shortener token gate (`{}` in the API url is the link) |
| `STYLE_UI` | True | Small caps and symbols (False = plain text) |
| `MAP_SITES` | all six | Site codes allowed for mapping: `weebc mgeko 18fx ma18 mhpu as` |
| `POSTER_TITLE` | MMWC VOID | Brand tag on the poster |
| `POLL_MINUTES` | 20 | Check interval per series |
| `SETTLE_SECONDS` | 90 | Double-check delay for new chapters |
| `BATCH_DEPTH` | 2 | Chapters of one batch kept in the queue |
| `MIN_FREE_MB` | 300 | Uploads wait below this free disk |
| `SITE_CONCURRENCY`, `SITE_DELAY` | 2, 2 | Politeness limits per site |
| `AUTO_MAX_PARALLEL` | 6 | Channel uploads at once (workers stay free for users) |
| `RETRY_LIMIT` | 3 | Attempts per chapter |
| `ANNOUNCE` | True | Post update cards |
| `UPSTREAM_REPO`, `UPSTREAM_BRANCH` | - | Optional self-update. **Replaces local code with that repo on every start**; point it at your own fork or leave empty |

---

## 4. Troubleshooting

| Symptom | Cause / fix |
|---|---|
| Bot exits at start with a list | A required variable is missing; fix what it prints |
| "bot is not admin" when mapping | Make it admin of the channel, then press "I gave the rights - retry" |
| Nothing is posted after mapping in Latest mode | Expected: existing chapters are the baseline; only new ones are posted |
| Update post missing | Set Settings > Update Channel and make the bot admin there; the owner gets a DM explaining the reason when a post is skipped |
| Poster has a plain colour instead of the cover | The site blocked the cover download; it retries on the next post. Description and genres still appear |
| Chapter marked failed | The site returned no pages or broken images. Open the series card, Retry once the site works, or Skip |
| Uploads paused | Disk below `MIN_FREE_MB`; free space |
| A chapter without a number (for example "Prologue") is never posted | Chapters are ordered by number; unnumbered ones are skipped on purpose |
| Poster fonts look plain | `Tools/fonts` is missing; keep that folder (it is bundled) |

---

## 5. Development and tests

```bash
pip install -r requirements.txt -r requirements-dev.txt
python -m pytest -q          # no Telegram, MongoDB or internet needed (mongomock + fakes)
```
The suite covers the PDF pipeline, batch/latest engine, settings-applied checks, update posts, poster details,
guide, style and a source scan that fails on any emoji. It cannot verify live sites, real Telegram behaviour or a
real MongoDB; use Settings > Test Settings and one real mapping to confirm your own setup.

Layout: `TG/` handlers and panels, `Tools/` engines (poller, announce, poster, pdf, settings test), `Webs/` one
scraper per site (`search`, `get_chapters`, `iter_chapters`, `get_pictures`), `tests/`.

Credit: based on the open-source Manhwa-Bot by Dra-Sama (MIT, see `LICENSE`).
