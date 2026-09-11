# ☁️ Run Nice Bingo 24/7 on PythonAnywhere — free, no PC, no credit card

PythonAnywhere's free tier runs your web app **24/7 without sleeping** and
gives you a permanent `https://<username>.pythonanywhere.com` address (HTTPS —
required by Telegram for the Mini App button). No credit card, ever.

| | |
|---|---|
| **Host** | PythonAnywhere — free **Beginner** account |
| **Always on?** | ✅ Web apps never sleep (the game loop + bot stay alive) |
| **Credit card?** | ❌ Not needed |
| **Public HTTPS URL** | ✅ `https://<username>.pythonanywhere.com` |
| **Database** | SQLite in your home directory (persists across reloads) |
| **How it deploys** | You copy the code to the server once; updates = `git pull` + Reload |

> **Why webhook mode?** Free PythonAnywhere cannot run *background processes*
> (that needs their paid Hacker plan), so the Telegram bot cannot poll. This
> repo now supports **webhook mode**: Telegram pushes each update to
> `APP_URL/webhook/<secret>`, `server.py` forwards it to the in-process bot —
> same handlers, same announcer, same commands. Local/desktop usage keeps
> polling, so nothing changes on your PC.

> **📘 Documentation rule — next programmer or AI:** after **ANY** change to
> this system, update **all** docs in the *same* change: `README.md`,
> `TECHNICAL_DOCS2.md` (incl. its changelog), `BOT_SYSTEM.md`, this guide, and
> `.env.example`. The goal is that anyone can recreate the entire system —
> including this PythonAnywhere side — by reading the docs alone. An
> out-of-date document is worse than no document.

---

## What changed in the repo (for this host)

| File | Change |
|---|---|
| `bot.py` | Webhook mode: `start_webhook()` / `dispatch_webhook()`; polling stays the default |
| `config.py` | `BOT_WEBHOOK` + `WEBHOOK_SECRET` settings; maintenance/reliability settings (`PRUNE_HISTORY_DAYS`, `DB_BACKUP_DIR`, `MAINTENANCE_MIN_FREE_MB`, …) |
| `server.py` | `POST /webhook/<secret>` endpoint that feeds updates to the bot |
| `game_loop.py` | `start()` made idempotent (safe across WSGI reloads); heartbeat + scheduler watchdog in `tick()` |
| `wsgi.py` | **New** — the WSGI entry PythonAnywhere serves (migrate → loop → bot → maintenance). No hardcoded bot token: `BOT_TOKEN` comes **only** from the environment |
| `maintenance.py` | **New** — automatic housekeeping: low-disk guard, integrity probe, daily backup snapshot, corrupt-player-row cleanup, stale-room purge, history pruning, WAL checkpoint (runs on boot + every `MAINTENANCE_INTERVAL_MIN`) |

---

## Step-by-step (≈ 30 minutes)

### 1. Create the account (instant, no card)
Go to **https://www.pythonanywhere.com** → **Start running Python online in
less than a minute!** → free account. Pick a username — your URL becomes
`https://<username>.pythonanywhere.com`.

### 2. Stop your PC version first
Run `stop_all.bat` on your Windows machine. Telegram allows only **one**
bot connection at a time — the cloud webhook and a local poller would fight
(`409 Conflict: terminated by other getUpdates`).

### 3. Get the code onto the server
Open a **Bash** console from the dashboard, then:

```bash
cd ~
curl -L https://codeload.github.com/nicebingogit/nicebingo/zip/refs/heads/main -o bingo.zip
unzip bingo.zip && mv nicebingo-main nicebingo && rm bingo.zip
cd ~/nicebingo
# the built Mini App is already in frontend/dist — no npm build needed
```

> If you prefer git: `git clone --depth 1 https://github.com/nicebingogit/nicebingo.git`

> **Private repo?** The `curl`/zip download above only works for **public**
> repos — a private repo returns `404: Not Found` (a 14-byte file that `unzip`
> rejects with *"End-of-central-directory signature not found"*). Use git with
> a **personal access token** instead:
> `git clone --depth 1 https://<USERNAME>:<TOKEN>@github.com/nicebingogit/nicebingo.git`
> (create the token at https://github.com/settings/tokens → *Generate new
> token (classic)* → tick `repo`; or a fine-grained token with *Contents:
> Read-only* on this repo).

### 4. Python environment (use 3.11 so every pinned wheel exists)
```bash
cd ~/nicebingo
python3.11 -m venv venv
source venv/bin/activate
pip install --upgrade pip
pip install -r requirements.txt
```
> If `numpy==1.24.3` refuses to install (no wheel for a newer Python),
> run `pip install numpy==1.26.4` and then `pip install -r requirements.txt` again.

### 5. Create the web app
Dashboard → **Web** tab → **Add a new web app** → Next → choose
**Manual configuration** → **Python 3.11** → Next → **Create**.

### 6. Point it at our WSGI file
On the web app page:
- **Code → WSGI configuration file**: change the path to
  `/home/<username>/nicebingo/wsgi.py`
- **Virtualenv**: `/home/<username>/nicebingo/venv`
- **Security → Force HTTPS**: tick it (Telegram needs https on the button)

### 7. Environment variables
On the same page, **Environment variables → Add**:

```
BOT_TOKEN     = <your token>
ADMIN_IDS     = <your ids, comma separated>
SUPER_ADMIN_IDS = <your super-admin ids, comma separated>   # REQUIRED — see below
APP_URL       = https://<username>.pythonanywhere.com
BOT_WEBHOOK   = 1
SERVER_HOST   = 0.0.0.0
```
(`WEBHOOK_SECRET` is auto-derived from the bot token.)

> **Super admin:** since 2026-09-12 `config.py` has **no hardcoded super-admins
> and warns loudly if none are set**. Set `SUPER_ADMIN_IDS` above (your numeric
> Telegram ids, comma separated), or they fall back to the ids embedded in
> `wsgi.py` via `setdefault`.

> **Database location (important for the 512 MB quota):** the default DB lives
> at `~/nicebingo/bingo_bot.db`, **inside the code folder**. That is fine, but
> for a deploy that copies the project, prefer an absolute `DB_PATH` *outside*
> the project, e.g. `DB_PATH=/home/<username>/bingo_data/bingo_bot.db` (create
> the folder with `mkdir -p ~/bingo_data` first; `move_db.py` moves an
> existing database and keeps an audit log of moves). Backups go to
> `DB_BACKUP_DIR=/home/<username>/bingo_backups` (also outside the code folder)
> so daily snapshots survive any project re-copy.

> **Tip:** If you can't find the Environment Variables section in the Web tab,
> add them directly in the WSGI file using `os.environ.setdefault(...)` at the
> top (see the `wsgi.py` file in the repo for the pattern).

### 8. Reload and check the logs
Click the green **Reload** button. Then open **Web → Error log** and
**Server log**. You should see:

```
[1/3] Schema ready ...
[3/3] Room by 10 reset → preparation (selections cleared)
Game loop started · rooms=[10]
🎰 Bingo bot running in WEBHOOK mode
🎰 Bingo bot webhook registered → https://<username>.pythonanywhere.com/webhook/<secret>
```

### 9. Verify end-to-end
1. Open `https://<username>.pythonanywhere.com` in a browser → the arena loads.
2. Visit `https://<username>.pythonanywhere.com/health` — you should see
   `"status":"ok"`, `"game_loop":true`, `"database":true`,
   `"bot.thread_alive":true`, and `"bot.webhook_registered":true`.
3. In Telegram send the bot `/play` → tap **🎮 OPEN BINGO ARENA** → the Mini
   App opens on the cloud URL.
4. `/status` answers; rounds run automatically; bots join every round (even
   with **0 humans** the room still fills with players and plays). Your PC
   can stay off. 🎉

---

## Keeping it running

- The free web app **never sleeps** — the game loop ticks 24/7.
- **Self-healing by design** — the system is built to keep running with **no
  technical professional**: every room tick is isolated in its own `try/except`
  so one bad room can't stall the others; stale/missing timestamps self-heal
  (a stuck room force-starts / force-calls / ends winless); the SQLite
  connection reconnects on any DB error; `_repair_schema()` rebuilds a
  corrupted DB and `migrate_db.main()` runs on every reload (seeds cards,
  purges stale bot rows). `maintenance.py` runs on every boot **and** every
  `MAINTENANCE_INTERVAL_MIN` (default 6 h): it refuses to write when the disk
  runs low, checks integrity, takes a **daily backup snapshot**, deletes
  corrupted player rows ("credit shows a date / users are just numbers"),
  removes stuck rooms that are no longer configured, prunes old games /
  activity / called balls (`PRUNE_HISTORY_DAYS`), and TRUNCATEs the WAL so the
  freed space is returned to the quota. There is nothing to click, restart, or
  monitor manually in normal operation. The `/health` endpoint tells you in one
  glance if the web process, the game loop, the database, and the bot thread
  are all alive.
- **Optional tuning** via env vars (defaults are already sensible): set
  `TICK_INTERVAL=3` on the free tier to cut CPU ~3× (balls still land on the
  `CALL_INTERVAL_SECONDS` schedule, just with a tick of jitter); lower
  `MAX_TOTAL_PLAYERS` for fewer bots; `MIN_CALLS_BEFORE_WIN` (default `10`)
  sets how many balls must be called before a round can end.
- **Updating the game:** SSH or Bash console → download the zip to your **home
  folder**, extract it, and copy the files over the existing `~/nicebingo`
  (never download/unzip *inside* `~/nicebingo` — the zip extracts to a
  `nicebingo-main/` subfolder and the old code would stay in place!):

  ```bash
  cd ~
curl -L https://codeload.github.com/nicebingogit/nicebingo/zip/refs/heads/main -o bingo.zip
unzip -o bingo.zip
cp -r nicebingo-main/. nicebingo/    # overwrite code only — bingo_bot.db, .env, venv survive
rm -rf nicebingo-main bingo.zip
  ```

  (If you cloned with git, `cd ~/nicebingo && git pull` does the same.) If
  `requirements.txt` changed, re-run `pip install -r requirements.txt` inside
  the venv. Then press **Reload** on the web app page.

  **Private repo?** The zip download 404s (GitHub returns a 14-byte
  `404: Not Found` — unzip says *"End-of-central-directory signature not
  found"*). Use git with a token instead — set it once, then `git pull`:

  ```bash
  cd ~/nicebingo
  git remote set-url origin https://<USERNAME>:<TOKEN>@github.com/nicebingogit/nicebingo.git
  git pull
  ```

  (or just `git pull` and type your GitHub username + the token as the
  password each time).
- **Backups:** automatic — `maintenance.py` writes a daily snapshot to
  `DB_BACKUP_DIR` (default `~/nicebingo/backups/`; the newest `DB_BACKUP_KEEP`
  = 14 copies are kept, oldest deleted). Download those to your PC whenever
  you like. You can also download `~/nicebingo/bingo_bot.db` directly (copy
  the file while running — SQLite handles it). To take a snapshot right now:
  `python -c "import maintenance; maintenance.run(force_backup=True)"`.

---

## Free-tier limits (fine for this game)

- **512 MB disk** — keep the repo lean (that's why we removed
  `frontend/node_modules` and `tools/`; the venv is the big chunk and fits).
  The database no longer grows forever: `maintenance.py` prunes old games /
  activity / called balls every 6 h and checkpoints the WAL, and it **stops
  writing** below `MAINTENANCE_MIN_FREE_MB` (default 25 MB) instead of
  corrupting the file on a full disk.
- **1 web app**, CPU is throttled (still plenty for a low-traffic bingo room).
- No background tasks — that's exactly why the bot runs in webhook mode here.

## Troubleshooting

| Symptom | Fix |
|---|---|
| `409 Conflict: terminated by other getUpdates` | A local bot instance is still running → `stop_all.bat` on your PC |
| Error log shows `ModuleNotFoundError` | Venv not set (Web tab → Virtualenv) or `pip install -r requirements.txt` didn't finish |
| Log shows no "webhook registered" line | `BOT_WEBHOOK=1` missing from env vars, or `APP_URL` wrong → fix, **Reload** |
| Telegram: "only https links are allowed" | `APP_URL` must start with `https://` and **Force HTTPS** must be on → reload, then send `/play` again (old buttons keep the old URL) |
| Mini App opens but API errors | Check the **Error log**; make sure `WSGI configuration file` points to `wsgi.py` (not the default) |
| Bot answers nothing after Reload | Telegram needs the webhook re-registered — it happens on every Reload; give it a few seconds and retry `/play` |
| Bot still not responding after Reload | Visit `https://<username>.pythonanywhere.com/health` — check `bot.thread_alive` and `bot.webhook_registered`; if thread is dead, Reload again |
| Error log shows a `setWebhook` / connection failure to `api.telegram.org` | Free accounts can normally reach Telegram; if the bank of the account blocks it, contact PythonAnywhere support and ask them to whitelist `api.telegram.org` |
| Updated the code but the game still runs the old version | The zip was unzipped *inside* `~/nicebingo` (it lands in `~/nicebingo/nicebingo-main/` and nothing is replaced). Run the corrected update command above from `cd ~`, then **Reload**. Verify the new code is there: `grep -n superadmin ~/nicebingo/server.py` should print lines |
| `unzip` says `End-of-central-directory signature not found` and the download is only 14 bytes | Your repo is **private** — the anonymous zip URL returns `404: Not Found`. Don't use the zip; use git with a personal access token (see *Keeping it running* → *Private repo?*) |
| Log shows `Disk quota exceeded` / `cp: failed to close` / `SQL error: disk I/O error`, or user credit starts showing dates | **Disk full** — the free quota is 512 MB and SQLite corrupts when it cannot commit. Since 2026-09-12 the system prunes + checkpoints every 6 h and stops writing below 25 MB free. To recover space now: delete stale files in your home dir (`db_rescue*`, old `*.corrupt.bak`), then run `python -c "import maintenance; maintenance.run(force_backup=True)"` and Reload |
| Admin console shows players whose credit is a date / usernames that are just numbers | Corrupted player rows from the leak incident | Auto-cleaned since 2026-09-12: `maintenance.py` removes them on boot and every 6 h, logging each removal to `activity_log`. On a running Prod DB run `python -c "import maintenance; maintenance.run(force_backup=True)"` once, then Reload |

## Your existing players & balance?

The cloud starts with a fresh empty database. To bring your current
`bingo_bot.db` along: upload it from your PC into `/home/<username>/nicebingo/`
(via the dashboard **Files** tab) so it replaces `bingo_bot.db`, then Reload.
