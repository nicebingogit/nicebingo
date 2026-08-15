# ☁️ Run Bingo Royale 24/7 — free, no PC needed

This guide deploys your repo (already at `github.com/elcotech/2xbingo`) to a free
cloud host so the game runs **24/7 without your PC being on**. Total cost: **$0**.

| | |
|---|---|
| **Host** | Northflank — free **Sandbox** plan |
| **Always on?** | ✅ Yes — “always-on compute, no sleeping” (rounds never pause) |
| **Credit card?** | ❌ Not needed for the free plan |
| **Public HTTPS URL** | ✅ Yes — free TLS on a stable `https://…code.run` address (Telegram requires HTTPS on the Mini App button) |
| **Database** | SQLite on a persistent volume (survives restarts/redeploys) |
| **How it deploys** | From your GitHub repo — auto-redeploys on every `git push` |

---

## How the deployment is wired

- **One container runs everything** — the Flask server (`server.py`), the
  Telegram bot (`bot.py`) and the game loop. They share a single SQLite file
  (`config.DB_PATH`), so they *must* live together on the same volume. The
  `Dockerfile` + `run_prod.py` supervisor in this repo do exactly that:
  `run_prod.py` starts both processes, restarts a crashed one with backoff,
  and shuts both down cleanly on redeploys (SIGTERM).
- **No tunnel, no webhook** — the bot uses Telegram **polling** (outbound only),
  and the Mini App is served from the same https URL the API runs on.
- **`APP_URL`** = your cloud https address. It's what Telegram puts on the
  🎮 button and what the bot calls for admin actions.

---

## Before you start

1. **Stop the PC version** — run `stop_all.bat` on your Windows machine.
   Two bot instances on one token fight each other
   (`409 Conflict: terminated by other getUpdates`). The cloud becomes the
   only instance.
2. Have your `.env` values handy: `BOT_TOKEN` and `ADMIN_IDS`.

---

## Step-by-step (≈ 15 minutes)

### 1. Create a free Northflank account
Go to **https://app.northflank.com** → **Sign up** (email or GitHub). No card
needed on the free plan.

### 2. Connect GitHub
Top-right **profile menu → Git** → **Connect GitHub** → grant access to
`elcotech/2xbingo` (private or public, either works).

### 3. Import the repo
**New Project** → name it `bingo-royale`, pick a region close to your players
(e.g. Europe West) → **Add a combined service** → **Import from Git** → choose
`elcotech/2xbingo` → branch `main`.

### 4. Service settings
- **Build method:** `Dockerfile` — auto-detected from the new `Dockerfile` at
  the repo root.
- **Compute plan:** the free Sandbox one (~0.5 vCPU / 1 GB RAM) — plenty for
  this app and within the free allowance.
- **Ports:** `5000` → **public** → protocol `HTTP`. The `*.code.run` domain is
  enabled automatically.
- **Health check (optional):** HTTP `GET /` on port `5000` → expect `200`.

### 5. Add the persistent volume (this is where the database lives)
In the service → **Volumes** → **Add volume**:
- Name: `bingo-data`
- Access mode: **Single read/write** (default — exactly right for SQLite)
- Size: **512 MB** (the free allowance; the database is only a few MB)
- Mount path: `/data`

### 6. Environment variables
Service → **Configuration → Environment**:

**Variables** (plain values):
```
SERVER_HOST=0.0.0.0
SERVER_PORT=5000
DB_PATH=/data/bingo_bot.db
```

**Secrets** (hidden values — paste from your `.env`):
```
BOT_TOKEN=<your token>
ADMIN_IDS=<your ids, e.g. 1512842545,903313112>
```

> Do **not** set `APP_URL` yet — you'll set it after the first deploy (step 8).
> Optional extras: `ANNOUNCE_NUMBERS=True` / `ANNOUNCE_ROUNDS=True` if you want
> the bot to announce every ball / round results in chat.

### 7. Deploy
Click **Deploy** and watch the **build log** (first build installs the pinned
wheels — 2–5 minutes), then the **runtime log**. You should see:

```
[server] Mini App server → http://0.0.0.0:5000
[bot]    Bingo bot starting — Mini App URL: http://localhost:5000
```

The bot's URL still says `localhost` until you do step 8 — that's expected.

### 8. Set APP_URL to your cloud address
1. Copy the service's **public URL** from the top of the service page —
   it looks like `https://<project>-<service>.<region>.code.run`.
2. Add env var `APP_URL=https://<that-url>` and **redeploy / restart**.
3. The runtime log should now show:
   `[bot] Bingo bot starting — Mini App URL: https://<that-url>`

### 9. Verify end-to-end
1. Open the `https://…code.run` URL in a browser → the arena loads.
2. In Telegram, send the bot `/play` → tap **🎮 OPEN BINGO ARENA** → the
   Mini App opens (now on the cloud URL).
3. `/status` should answer. Play a round — bots fill the room, rounds run
   automatically, winners get paid. 🎉

---

## Keeping it alive

- The Sandbox plan **never sleeps** — rounds keep running 24/7.
- Every `git push` to `main` auto-builds and redeploys. The volume persists,
  so players/balances/round state survive redeploys.
- On redeploy/restart the supervisor shuts the bot + server down cleanly, and
  the game resumes exactly where it stopped (SQLite + persisted round state).

---

## Your existing players & balance?

The cloud starts with a **fresh, empty database**. Two choices:

- **Start fresh** — simplest, fine for a public relaunch.
- **Bring your current database** — upload your local `bingo_bot.db` into the
  volume at `/data/bingo_bot.db` (e.g. via a temporary one-off job or the
  service terminal). Ask me if you want help doing this safely.

---

## Troubleshooting

| Symptom | Fix |
|---|---|
| Build fails | Open the build log — deps are pinned wheels for Python 3.11; usually transient → click **Redeploy**. |
| Telegram: “only https links are allowed” | `APP_URL` is missing/wrong → set the exact `https://…code.run` URL and redeploy, then send `/play` again (old buttons keep the old URL). |
| Bot log: `409 Conflict: terminated by other getUpdates` | Your PC is still running the bot → run `stop_all.bat` locally. |
| Database resets after redeploy | Volume not attached or `DB_PATH` wrong → confirm the volume is mounted at `/data` and `DB_PATH=/data/bingo_bot.db`. |
| Service restarts in a loop | Open the **Logs** tab — lines are prefixed `[server]` / `[bot]`. A bad `BOT_TOKEN` stops only the bot (it gives up after 5 tries) while the game keeps running; fix the secret and redeploy. |
| Mini App opens but API errors | Make sure only port `5000` is public and the frontend loads from the same URL (no extra port). |

---

## Cost & limits

- **$0** on the Sandbox plan: 2 free services (we use 1), always-on, 0.5 GB
  volume (we use a few MB).
- If you ever outgrow it, the same `Dockerfile` + `run_prod.py` deploy
  unchanged to any Docker host — a paid Northflank plan, Railway, Fly.io, or a
  cheap VPS — no code changes needed.

## Alternative: Oracle Cloud Always Free

More powerful (up to 4 ARM cores / 24 GB RAM) and free forever, but requires a
credit card at signup, manual VM setup, and a domain for HTTPS (Caddy or
Cloudflare). Ask me if you want the Oracle deployment kit instead.
