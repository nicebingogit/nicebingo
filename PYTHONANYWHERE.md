# ☁️ Run Bingo Royale 24/7 on PythonAnywhere — free, no PC, no credit card

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

---

## What changed in the repo (for this host)

| File | Change |
|---|---|
| `bot.py` | Webhook mode: `start_webhook()` / `dispatch_webhook()`; polling stays the default |
| `config.py` | `BOT_WEBHOOK` + `WEBHOOK_SECRET` settings |
| `server.py` | `POST /webhook/<secret>` endpoint that feeds updates to the bot |
| `game_loop.py` | `start()` made idempotent (safe across WSGI reloads) |
| `wsgi.py` | **New** — the WSGI entry PythonAnywhere serves (migrate → loop → bot) |

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
curl -L https://codeload.github.com/elcotech/2xbingo/zip/refs/heads/main -o bingo.zip
unzip bingo.zip && mv 2xbingo-main 2xbingo && rm bingo.zip
cd ~/2xbingo
# the built Mini App is already in frontend/dist — no npm build needed.
# Remove junk that was committed by accident (Windows-only, not used here):
rm -rf frontend/node_modules tools
```

> If you prefer git: `git clone --depth 1 https://github.com/elcotech/2xbingo.git`
> then the same `rm -rf frontend/node_modules tools`.

### 4. Python environment (use 3.11 so every pinned wheel exists)
```bash
cd ~/2xbingo
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
  `/home/<username>/2xbingo/wsgi.py`
- **Virtualenv**: `/home/<username>/2xbingo/venv`
- **Security → Force HTTPS**: tick it (Telegram needs https on the button)

### 7. Environment variables
On the same page, **Environment variables → Add**:

```
BOT_TOKEN     = <your token>
ADMIN_IDS     = <your ids, comma separated>
APP_URL       = https://<username>.pythonanywhere.com
BOT_WEBHOOK   = 1
SERVER_HOST   = 0.0.0.0
```
(`DB_PATH` is optional — the database stays at `~/2xbingo/bingo_bot.db`,
which is persistent. `WEBHOOK_SECRET` is auto-derived from the bot token.)

### 8. Reload and check the logs
Click the green **Reload** button. Then open **Web → Error log** and
**Server log**. You should see:

```
[1/3] Schema ready ...
[3/3] Room by 30 reset → preparation phase
Game loop started · rooms=[30, 50, 100]
🎰 Bingo bot running in WEBHOOK mode
🎰 Bingo bot webhook registered → https://<username>.pythonanywhere.com/webhook/<secret>
```

### 9. Verify end-to-end
1. Open `https://<username>.pythonanywhere.com` in a browser → the arena loads.
2. In Telegram send the bot `/play` → tap **🎮 OPEN BINGO ARENA** → the Mini
   App opens on the cloud URL.
3. `/status` answers; rounds run automatically; bots fill the room. Your PC
   can stay off. 🎉

---

## Keeping it running

- The free web app **never sleeps** — the game loop ticks 24/7.
- **Updating the game:** SSH or Bash console →
  `cd ~/2xbingo && curl -L https://codeload.github.com/elcotech/2xbingo/zip/refs/heads/main -o b.zip && unzip -o b.zip && rm b.zip` (or `git pull`),
  then press **Reload** on the web app page.
- **Backups:** download `~/2xbingo/bingo_bot.db` regularly (while the app is
  reloaded, or just copy the file — SQLite handles it).

---

## Free-tier limits (fine for this game)

- **512 MB disk** — keep the repo lean (that's why we removed
  `frontend/node_modules` and `tools/`; the venv is the big chunk and fits).
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
| Error log shows a `setWebhook` / connection failure to `api.telegram.org` | Free accounts can normally reach Telegram; if the bank of the account blocks it, contact PythonAnywhere support and ask them to whitelist `api.telegram.org` |

## Your existing players & balance?

The cloud starts with a fresh empty database. To bring your current
`bingo_bot.db` along: upload it from your PC into `/home/<username>/2xbingo/`
(via the dashboard **Files** tab) so it replaces `bingo_bot.db`, then Reload.
