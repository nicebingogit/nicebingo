# 🎰 Bingo Royale — Immersive Telegram Mini App Edition

A professional, fully immersive Bingo system. The Telegram bot is the launcher:
tapping **Play Mini App** opens a full-screen interactive game inside Telegram
(same look & feel as the web version) — live board, your cards, sound effects,
global win pool, winner celebrations, admin controls. **No Supabase, no
Vercel, no external services** — and it runs either **on your Windows desktop**
or **24/7 in the free cloud with no PC needed** (see
[☁️ Run 24/7 in the cloud](#-run-247-in-the-cloud-free)).

```
┌─────────────────────┐      ┌──────────────────────────────────────────┐
│  Telegram app       │      │  YOUR WINDOWS PC                         │
│                     │      │                                          │
│  Bot chat message   │─────▶│  bot.py (python-telegram-bot)            │
│  [🎮 Play Mini App] │      │   • Web App button → opens the Mini App  │
│                     │      │   • announcer (watches the database)     │
│  Mini App (React)   │◀────▶│  server.py (Flask on :5000)              │
│  opens full screen  │      │   • serves the React app (frontend/dist) │
│                     │      │   • JSON API for the Mini App            │
│                     │      │   • APScheduler game loop (the ref!)     │
│                     │      │   • SQLite database (bingo_bot.db)       │
└─────────────────────┘      └──────────────────────────────────────────┘
```

Everything (game state, database, logic) lives wherever you run it. The **same
bot token and admin ids** from your existing `.env` are used — nothing changes
on the Telegram side.

---

## ☁️ Run 24/7 in the cloud (free)

Want the game to run around the clock **without leaving your PC on**? Two free
routes, depending on whether you can provide a card:

* **Have a Visa/Mastercard?** The repo ships a ready-made `Dockerfile` +
  `run_prod.py` supervisor that run the server and bot together in one
  container with a persistent SQLite volume. Deploy it to Northflank's free
  **Sandbox** plan — always-on (no sleeping), free HTTPS on a stable
  `…code.run` URL, no credit card *charges* (a card is required for
  verification only), auto-redeploys on every `git push`. Guide:
  **[`DEPLOY.md`](DEPLOY.md)** (≈ 15 minutes).
* **No card at all?** Deploy to **PythonAnywhere**'s free tier — always-on
  web app, free HTTPS on `…pythonanywhere.com`, no credit card ever. The bot
  runs in **webhook mode** (this repo supports it via `BOT_WEBHOOK=1`).
  Guide: **[`PYTHONANYWHERE.md`](PYTHONANYWHERE.md)** (≈ 30 minutes).

---

## ✨ What you get

| Feature | Details |
|---|---|
| 🎮 **Telegram Mini App** | Full-screen interactive Bingo arena inside Telegram, opened with one button |
| ⏱️ **60 s countdown** | Preparation countdown, then the round auto-starts |
| 🔢 **Auto-calling** | A ball every **4 seconds**, driven by a server-side APScheduler loop |
| 💰 **Global win pool** | Pool = sum of **all** purchased cards (bots included); winner takes **80 %**, credited instantly |
| 🃏 **Up to 4 cards** | Bet per card, **min 2 ETB, default 30 ETB** (per-card bet editor in the app) |
| 🤖 **18 bot players** | Auto-fill the room, toggleable by admins, bets feed the pool |
| 🔁 **Auto-reset** | New 60 s round automatically after a winner or the 75th ball |
| 🔔 **Real-time sync** | The app polls the local API every 2.5 s — called numbers, sold cards, phase, pool |
| 🔊 **Sound effects** | Synthesized via Web Audio (no files needed) with Classic / Retro / Digital / Mute packs |
| 🏆 **Winner celebration** | Confetti modal with the winning pattern + instant payout |
| 🛠 **Admin controls** | Force start / force call / reset / add bots / toggle bots / **user list with inline credit editing** / **wallet request review** / **wallet account number** (in-app panel *and* bot `/admin`) |
| 📝 **In-app registration** | First time you press Play, the Mini App asks your **full name** and **phone number** (shared automatically) — no chat setup needed |
| 💰 **Wallet** | Your phone number is your wallet. Send deposits to the admin's account (TeleBirr / CBB) and submit the **transaction number**; request withdrawals to your phone — all reviewed in the admin panel |
| ⚙️ **Settings & Help** | Deposit/withdraw wallet (withdrawals need destination account details), editable name **and phone (wallet)** profile, and full help & guide including the **winning patterns** |
| 🗄️ **Persistence** | SQLite — the game even resumes mid-round after a restart |

---

## ✅ Requirements

- **Windows 10/11** with Python **3.11+** ([python.org](https://www.python.org/downloads/) —
  tick *"Add python.exe to PATH"*)
- **Node.js 18+** — only if you want to *rebuild* the React app
  (a ready-built copy already ships in `frontend/dist/`, so usually not needed)
- Telegram Desktop / phone, and internet (to talk to Telegram)

---

## 🚀 Setup (under 15 minutes)

### 1. One-time install

Double-click **`setup.bat`** — it creates the `venv`, installs the Python
dependencies (Flask, python-telegram-bot, APScheduler, Pillow, …) and creates
`.env` from the template if missing.

> Your existing `.env` is **left untouched** — your `BOT_TOKEN` and `ADMIN_IDS`
> keep working exactly as before. If you don't have `.env` yet, copy
> `.env.example` to `.env` and paste the token/ids.

### 2. Start the system

Double-click **`run_all.bat`** — it opens three windows and wires everything
together (server → HTTPS tunnel → bot):

```
Window 1 (server):  migrate DB → Flask server on http://localhost:5000
Window 2 (tunnel):  cloudflared HTTPS tunnel → writes the fresh https URL
Window 3 (bot):     Telegram bot polling (starts as soon as the URL is ready)
```

> The **tunnel is required** — Telegram only allows `https://` addresses on the
> Mini App button (see [HTTPS tunnel](#-https-tunnel-required-for-telegram)).
> `run_all.bat` handles it automatically. To stop everything, run
> `stop_all.bat`.

### 3. Play!

1. In Telegram, message your bot `/start`, then **`/play`**.
2. Tap **🎮 OPEN BINGO ARENA** — the full-screen Mini App opens inside Telegram.
3. **First time:** enter your **full name** and tap **📱 Share** — Telegram
   shares your phone number automatically (your wallet account).
4. During the 60 s countdown pick up to **4 cards** (set your bet per card,
   2–999 ETB) or hit **⚡ Quick Play**.
4. Balls are called every 4 seconds — find each number on your card and
   **tap it to mark it** (paper-bingo style). Complete a **row, column,
   diagonal or four corners** and press **🔔 BINGO!** (the server verifies your
   card — a wrong claim kicks you out of the round).
5. Winner takes **80 % of the whole pool** — paid instantly, confetti included.
6. A new round starts by itself. Keep playing, or chat with the bot anytime.

**Wallet:** ⚙️ Settings → Wallet shows the admin's account — send money there
with TeleBirr/CBB, then submit a deposit with the amount **and the transaction
number** from your wallet app. The admin approves it and your balance updates.
To cash out, request a withdrawal and enter the **account name**, **holder's
name** and **account number** you want the money sent to. Deleting the bot or
your account removes it here too — you can register again anytime.

> **Testing without Telegram:** open `http://localhost:5000/?user_id=12345&username=Tester`
> in Chrome — the app runs in any browser and uses that id.

---

## 🔒 HTTPS tunnel (required for Telegram)

Telegram **requires `https://` on every Web App button** — even on the same
machine, `http://localhost:5000` is rejected with `only https links are
allowed`. That's why the system ships a free **Cloudflare Quick Tunnel**
(no account, no registration, no card) that gives your local server a public
HTTPS address:

1. **One-time:** double-click **`setup_tunnel.bat`** — it downloads
   `cloudflared.exe` into `tools\` (~50 MB, Cloudflare's official tunnel
   client). It's already bundled in this project, so the script will just
   say *already downloaded* and you can skip to step 2.
2. **Every session:** `run_all.bat` starts the tunnel automatically and writes
   the fresh URL into `.env` (`APP_URL=…`) before launching the bot. Running
   **`run_tunnel.bat`** alone does the same if you prefer separate windows.

The tunnel URL is **new every time** (it's a free throwaway address) — that's
fine, `run_all.bat` re-captures it for you. Keep the tunnel window open while
playing.

**Alternative — ngrok** (requires a free account):

```
ngrok http 5000
```

then set in `.env`: `APP_URL=https://xxxx.ngrok-free.app` and restart the bot.

> Browser testing without Telegram still works over plain http:
> `http://localhost:5000/?user_id=12345&username=Tester` — the HTTPS rule only
> applies to Telegram's button.

---

## 🎮 Game commands (bot)

| Command | Who | What it does |
|---|---|---|
| `/start` | all | Register + welcome + Mini App button |
| `/play` | all | Sends the **Play Mini App** button |
| `/status` | all | Live round status (phase, pool, countdown) |
| `/balance` | all | Your ETB balance |
| `/cards` | all | Your cards this round (text preview) |
| `/history` | all | Your last rounds |
| `/top` | all | Leaderboard |
| `/give <id> <amount>` | admin | Add ETB to a user |
| `/take <id> <amount>` | admin | Remove ETB from a user |
| `/admin` | admin | Admin panel (buttons → server API) |

Admins also get the **🛠 Admin** tab inside the Mini App itself.

---

## 🔧 Configuration (`.env`)

Everything is optional except `BOT_TOKEN` / `ADMIN_IDS` (already in your file):

```ini
BOT_TOKEN=your-bot-token-here           # from @BotFather
ADMIN_IDS=your-telegram-id-here        # find yours via @userinfobot

# SERVER_HOST=127.0.0.1
# SERVER_PORT=5000
# APP_URL=http://localhost:5000        # run_tunnel.bat sets your https URL automatically
# ROOM_BETS=30,50,100                 # rooms = FIXED bet per card (comma separated)
# MAX_CARDS_PER_PLAYER=4               # max cards per player per round
# NEW_PLAYER_CREDIT=1000               # welcome coins
# PRIZE_PERCENT=0.8                    # winner's share of the pool
# PREPARATION_SECONDS=60               # countdown between rounds
# CALL_INTERVAL_SECONDS=4              # seconds between balls
# POST_GAME_RESET_SECONDS=15           # winner screen length
# MAX_TOTAL_PLAYERS=18                 # real players + bots
# NUM_CARDS=400                        # card pool size
# ANNOUNCE_NUMBERS=True                # also announce every ball in chat
```

---

## 🗄️ Database

`bingo_bot.db` (SQLite) holds everything — players (name, phone,
registration status), credits, cards, selections, called numbers, round
history, bot accounts, wallet transactions, settings.

- **Migrate / seed / repair:** `python migrate_db.py` (idempotent, runs
  automatically when the server starts). Creates all tables +
  `profiles` view + `bots` table and seeds the 400 unique cards.
- Your existing players/credits/history are **preserved** (migrations only add).
- Backup: copy `bingo_bot.db` while the system is stopped.

---

## 🛠 Rebuilding the React app (optional)

A built copy already ships in `frontend/dist/` and is served by Flask. Only do
this if you edit the app:

```bat
build_frontend.bat     :: npm install + npm run build  → frontend/dist
```

For live development: `cd frontend && npm run dev` (Vite on :5173 proxies
`/api` to the Flask server on :5000).

---

## 📁 Project structure

```
bot.py              Telegram bot: /play Web App button, announcer, /admin
server.py           Flask server: API + serves frontend/dist + starts game loop
game_loop.py        APScheduler game loop (tick, rounds, winners, payouts)
game_logic.py       Pure rules: ball machine, patterns, bots, prize pool
database.py         SQLite layer (WAL, auto-migrations, profiles/bots tables)
cards_data.py       Generates the 400 unique cards
card_generator.py   Pillow card-image renderer (chat previews)
config.py           All settings (overridable via .env)
migrate_db.py       Schema migration + card seed (idempotent)
api_smoke.py        Offline API test suite (no Telegram needed)
smoke_test.py       Full offline smoke test (API + image rendering)
frontend/           React Mini App source (Vite)
frontend/dist/      Built Mini App — served by Flask
run_all.bat         Starts server + HTTPS tunnel + bot together
run_server.bat      Starts just the Flask server
run_tunnel.bat      Starts the HTTPS tunnel (cloudflared) + updates .env
setup_tunnel.bat    One-time download of cloudflared.exe (tools\)
stop_all.bat        Closes the three Bingo windows
run_bot.bat         Starts just the Telegram bot
tunnel.py           Tunnel helper: captures the URL, writes APP_URL to .env
build_frontend.bat  Rebuilds frontend/dist
```

---

## ✅ Verifying everything (no Telegram needed)

```bat
venv\Scripts\python.exe smoke_test.py
```

This plays full rounds offline through the real Flask API — registration,
card sales, bots, winner detection, exact 80 % payout, claim-bingo, admin
controls — and renders sample card images into `sample_cards/`. A green
`SMOKE TEST PASSED` means the core is healthy.

---

## 🔍 Troubleshooting

| Symptom | Fix |
|---|---|
| `No module named flask` | Run `setup.bat` again (installs the new deps), or `venv\Scripts\python.exe -m pip install -r requirements.txt` |
| Mini App shows *"Frontend not built yet"* | Run `build_frontend.bat` |
| Bot says *"Game server is offline"* | Start `run_server.bat` first — the bot needs the server |
| `BadRequest: … only https links are allowed` | Telegram needs HTTPS on the Mini App button — run `setup_tunnel.bat` once, then `run_tunnel.bat` (see “HTTPS tunnel”) |
| `409 Conflict: terminated by other getUpdates` | Another bot instance is running — close extra windows |
| Bot replies Unauthorized to `/admin` | Your id isn't in `ADMIN_IDS` (numeric — check with @userinfobot) |
| Game stuck / no countdown | Run `migrate_db.py` (resets a stale round to preparation) |
| Windows Firewall prompt when the tunnel starts | Click **Allow** — cloudflared needs outbound access to create the tunnel |
| Port 5000 already in use | Close the other server, or set `SERVER_PORT` in `.env` |

---

Enjoy — and good luck! 🍀
#   n i c e b i n g o  
 