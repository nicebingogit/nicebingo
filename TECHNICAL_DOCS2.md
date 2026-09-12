# Nice Bingo — Technical Documentation

> Complete technical reference for recreating, modifying, or deploying the Nice Bingo system from scratch.
>
> **⚠️ This documentation must be updated with every change to the codebase.** When you modify behavior,
> configuration, schema, or APIs, update the relevant sections here (and in `README.md`) in the **same change**.
> An out-of-date document is worse than no document.
> **→ Next programmer or AI: after ANY change, update all docs in the same change, and add a changelog row.**

---

## Table of Contents

1. [Project Overview](#1-project-overview)
2. [Architecture](#2-architecture)
3. [Tech Stack](#3-tech-stack)
4. [Directory Structure](#4-directory-structure)
5. [Prerequisites](#5-prerequisites)
6. [Setup & Installation](#6-setup--installation)
7. [Configuration (.env)](#7-configuration-env)
8. [Database Schema](#8-database-schema)
9. [Backend Components](#9-backend-components)
10. [Frontend Components](#10-frontend-components)
11. [Game Flow & Logic](#11-game-flow--logic)
12. [Bot System (AI Players)](#12-bot-system-ai-players)
13. [Wallet & Transactions](#13-wallet--transactions)
14. [Referral System](#14-referral-system)
15. [API Reference](#15-api-reference)
16. [Deployment](#16-deployment)
16b. [Changelog (update on EVERY change)](#16b-changelog-update-on-every-change)
17. [Troubleshooting](#17-troubleshooting)

---

## 1. Project Overview

Nice Bingo is a real-time multiplayer Bingo game built as a **Telegram Mini App**. The Telegram bot serves as a launcher — tapping "Play" opens a full-screen interactive Bingo arena inside Telegram (or any browser). Players buy cards, watch balls being called, mark numbers, and claim BINGO when they complete a winning pattern. The winner takes 80% of the prize pool instantly.

### Key Features
- **Single room (By 10)**: the game runs exactly ONE room — 10 ETB per card. `ROOM_BETS` in `.env` can change it (e.g. `ROOM_BETS=50`), but the production default is a single “By 10” room
- **Real-time gameplay**: Balls called every 4 seconds via a server-side game loop
- **Bot players**: AI players fill every room to 18-140 players (count chosen by how many **humans** are playing — see [Bot System](#12-bot-system-ai-players)). Bots look exactly like real players (human-like names — 20% Oromo / 20% Amhara / 10% Tigray / 30% general Ethiopian male / 5% Ethiopian female / 10% East African / 5% international nicknames, negative IDs — see §9.4) and are completely invisible to humans. The fill works on **every difficulty level**; the only difference is that on **Impossible** no human can win. With bots disabled the room keeps exactly **one other player** so nobody plays alone.
- **Auto-play mode**: Players can toggle auto-daub and auto-claim
- **Wallet system**: Deposit/withdraw via bank accounts (TeleBirr, CBE, CBB, etc.)
- **Referral program**: 5% commission on referred players' bets
- **Admin panel**: Full game control from both the Mini App and bot chat
- **Sound effects**: Synthesized via Web Audio (no external files)
- **Spectator mode**: Watch another player's card when not playing

---

## 2. Architecture

```
┌─────────────────────────┐      ┌──────────────────────────────────────────┐
│  Telegram App           │      │  Server (Python)                         │
│                         │      │                                          │
│  Bot chat               │─────▶│  bot.py (python-telegram-bot)            │
│  [🎮 Play Mini App]     │      │   • Web App button → opens Mini App      │
│                         │      │   • Announcer (watches DB)               │
│  Mini App (React/Vite)  │◀────▶│   • Notification queue drain             │
│  opens full screen      │      │                                          │
│                         │      │  server.py (Flask on :5000)              │
│                         │      │   • Serves frontend/dist as static files │
│                         │      │   • JSON REST API for the Mini App       │
│                         │      │   • APScheduler game loop (source of     │
│                         │      │     truth for game state)                │
│                         │      │   • SQLite database (bingo_bot.db)       │
│                         │      │   • Webhook dispatch for Telegram        │
└─────────────────────────┘      └──────────────────────────────────────────┘
```

### Communication Model
- **Bot ↔ Server**: The bot makes HTTP requests to the Flask server's API (`/api/*`). Both processes share a single SQLite database file.
- **Mini App ↔ Server**: The React app polls `/api/game-state` every 2.5 seconds. All game actions go through the REST API.
- **Server → Bot (notifications)**: The server writes to a `bot_notifications` table. The bot's announcer tick drains this queue and sends messages via Telegram API. This works in both polling and webhook modes.
- **Game loop**: APScheduler runs a tick every 1 second in `server.py`. It reads `game_state` from the DB and advances phases (preparation → playing → ended → preparation).

---

## 3. Tech Stack

### Backend (Python 3.11+)
| Package | Version | Purpose |
|---------|---------|---------|
| `flask` | 3.0.0 | HTTP server, REST API, static file hosting |
| `python-telegram-bot` | 20.7 | Telegram Bot API wrapper |
| `apscheduler` | 3.10.4 | Background game loop scheduler |
| `python-dotenv` | 1.0.0 | `.env` file loading |
| `pillow` | 10.1.0 | Card image generation |
| `imageio` | 2.31.0 | Image I/O for card rendering |
| `numpy` | 1.24.3 | Numerical operations for card generation |
| `requests` | 2.31.0 | HTTP client (bot → server API calls) |

### Frontend (React 18 + Vite 5)
| Package | Purpose |
|---------|---------|
| `react` 18.2.0 | UI framework |
| `react-dom` 18.2.0 | DOM rendering |
| `@vitejs/plugin-react` 4.2.1 | React Fast Refresh |
| `vite` 5.0.10 | Build tool, dev server, bundler |

### Storage
- **SQLite** with WAL journal mode — single file (`bingo_bot.db`), supports concurrent readers

---

## 4. Directory Structure

```
nicebingo/
├── bot.py                  # Telegram bot (commands, menus, announcer, wallet flows)
├── server.py               # Flask server (API, game loop, static hosting)
├── game_loop.py            # APScheduler game loop (tick, rounds, winners, payouts)
├── game_logic.py           # Pure game rules (ball machine, patterns, bots, prize pool)
├── database.py             # SQLite layer (WAL, auto-migrations, all tables)
├── config.py               # All settings (overridable via .env)
├── cards_data.py           # Pre-generated 400 unique Bingo cards
├── card_generator.py       # Pillow card-image renderer (chat previews)
├── migrate_db.py           # Schema migration + card seed (idempotent)
├── maintenance.py          # Auto housekeeping: disk guard, integrity, daily backup, prune, corrupt-row cleanup, WAL checkpoint
├── salvage_recover.py      # Incident-recovery tool: builds a verified recovered.db from a corrupt DB (read-only), drops garbage player rows
├── run_prod.py             # Production supervisor (runs server + bot in one container)
├── api_smoke.py            # Offline API test suite
├── smoke_test.py           # Full offline smoke test
├── requirements.txt        # Python dependencies (pinned versions)
├── Dockerfile              # Cloud deployment image
├── .env.example            # Environment variable template
├── .env                    # Active environment config (git-ignored)
├── bingo_bot.db            # SQLite database (created at runtime)
│
├── frontend/               # React Mini App
│   ├── index.html          # Entry HTML
│   ├── package.json        # Node dependencies
│   ├── vite.config.js      # Vite config (proxy /api to Flask in dev)
│   ├── src/
│   │   ├── main.jsx        # React entry point
│   │   ├── App.jsx         # Main application component
│   │   ├── api.js          # API client (fetch wrapper)
│   │   ├── bingo.js        # Bingo card rendering logic
│   │   ├── sound.js        # Web Audio sound effects
│   │   ├── telegram.js     # Telegram Web App SDK integration
│   │   ├── styles.css      # Global styles
│   │   └── components/
│   │       ├── Header.jsx           # Top bar (brand, room selector, chips)
│   │       ├── BingoCard.jsx        # Individual Bingo card renderer
│   │       ├── CalledBoard.jsx      # Ball calling board (B/I/N/G/O columns)
│   │       ├── CardPicker.jsx       # Card selection grid (preparation phase)
│   │       ├── AdminPanel.jsx       # Admin controls (inline in Mini App)
│   │       ├── SuperAdminPanel.jsx  # Super admin controls (game controls incl. Add Bots, bot toggle & difficulty)
│   │       ├── Settings.jsx         # Settings panel (wallet, profile, help)
│   │       ├── Registration.jsx     # First-time registration screen
│   │       ├── WinnerModal.jsx      # Winner celebration modal (confetti)
│   │       └── ReferralPanel.jsx    # Referral program UI
│   └── dist/               # Built Mini App (served by Flask)
│
├── cards/                  # Card image assets
├── sample_cards/           # Generated sample card images (from smoke test)
├── static/                 # Static assets
├── tools/                  # Tooling (cloudflared.exe for tunnels)
│
├── setup.bat               # One-time setup (venv, deps, .env)
├── run_all.bat             # Start server + tunnel + bot
├── run_server.bat          # Start Flask server only
├── run_bot.bat             # Start Telegram bot only
├── run_tunnel.bat          # Start HTTPS tunnel
├── setup_tunnel.bat        # Download cloudflared.exe
├── stop_all.bat            # Stop all processes
├── build_frontend.bat      # Rebuild frontend/dist
│
├── DEPLOY.md               # Cloud deployment guide (Northflank)
├── PYTHONANYWHERE.md       # PythonAnywhere deployment guide
├── README.md               # User-facing README
└── TECHNICAL_DOCS.md       # This file
```

---

## 5. Prerequisites

- **Python 3.11+** (add to PATH during installation)
- **Node.js 18+** (only needed if rebuilding the React app — a pre-built copy ships in `frontend/dist/`)
- **Telegram Bot Token** (from @BotFather)
- **Telegram User IDs** (from @userinfobot)
- **Internet connection** (for Telegram API)
- **HTTPS URL** (Telegram requires HTTPS for Mini App buttons — see Section 16)

---

## 6. Setup & Installation

### Quick Start (Windows)
1. Run `setup.bat` — creates a virtual environment, installs Python deps, copies `.env.example` to `.env`
2. Edit `.env` with your `BOT_TOKEN` and `ADMIN_IDS`
3. Run `run_all.bat` — starts server, HTTPS tunnel, and bot in three windows
4. In Telegram: send `/start` → enter your name → `/play` → tap "Open Nice Bingo"

### Manual Setup
```bash
# 1. Create virtual environment
python -m venv venv
venv\Scripts\activate  # Windows
# source venv/bin/activate  # Linux/Mac

# 2. Install dependencies
pip install -r requirements.txt

# 3. Configure environment
cp .env.example .env
# Edit .env with BOT_TOKEN and ADMIN_IDS

# 4. Start the server
python server.py  # Runs on http://localhost:5000

# 5. Start the bot (in another terminal)
python bot.py

# 6. For Telegram access, you need HTTPS:
#    - Install cloudflared: setup_tunnel.bat
#    - Start tunnel: run_tunnel.bat
#    - Or use ngrok: ngrok http 5000
```

### Frontend Development
```bash
cd frontend
npm install
npm run dev  # Vite dev server on :5173, proxies /api to Flask :5000
```

### Building Frontend for Production
```bash
build_frontend.bat
# or: cd frontend && npm run build
```

---

## 7. Configuration (.env)

All configuration lives in `.env` (or environment variables). Every value in `config.py` can be overridden.

| Variable | Default | Description |
|----------|---------|-------------|
| `BOT_TOKEN` | *(required)* | Telegram bot token from @BotFather |
| `ADMIN_IDS` | *(required)* | Comma-separated Telegram user IDs for admins |
| `SUPER_ADMIN_IDS` | *(none)* | Comma-separated telecom-number Telegram IDs with full privileges. **Required** — with no value (and no `SUPER_ADMIN_ID`) `config.py` warns loudly and there is NO super admin. No hardcoded fallbacks since 2026-09-12; `wsgi.py` provides PythonAnywhere defaults via `setdefault` so a reload without `.env` still works |
| `PRUNE_HISTORY_DAYS` | `30` | Finished games / old activity / old called balls older than this many days are auto-deleted by every maintenance pass (running rounds never touched; newest `PRUNE_KEEP_LATEST_ROWS` always kept). Bounds the `games` table so the DB never fills the disk again |
| `PRUNE_KEEP_LATEST_ROWS` | `500` | Newest finished games / activity rows always kept for display regardless of age |
| `DB_BACKUP_DIR` | `backups/` (project) | Folder for daily sqlite3 backup snapshots. **Use an absolute path OUTSIDE the code folder** (like `DB_PATH`) so copies/`git pull` never route around it |
| `DB_BACKUP_KEEP` | `14` | How many daily backups to keep (oldest deleted) |
| `MAINTENANCE_INTERVAL_MIN` | `360` | Minutes between automatic maintenance runs (6h) |
| `MAINTENANCE_MIN_FREE_MB` | `25` | Maintenance refuses to WRITE once fewer MB are free — writing on a full disk corrupts SQLite (the Sep 2026 production incident) |
| `BOT_WEBHOOK` | `False` | Use webhook mode instead of polling (needed on PythonAnywhere) |
| `WEBHOOK_SECRET` | *(auto)* | Secret path segment for `POST /webhook/<secret>`. Auto-derived as `sha256(BOT_TOKEN).hexdigest()[:24]` if not set; falls back to `"dev-secret"` with no token |
| `SERVER_HOST` | `127.0.0.1` | Flask bind address |
| `SERVER_PORT` | `5000` | Flask bind port |
| `APP_URL` | `http://localhost:5000` | Public URL for the Mini App |
| `DB_PATH` | `bingo_bot.db` | SQLite database file path |
| `APP_CURRENCY` | `ETB` | Currency symbol |
| `ROOM_BETS` | `10` | Single room's fixed bet per card (comma-separated if you ever run multiple) |
| `MAX_CARDS_PER_PLAYER` | `3` | Max cards per player per round |
| `NEW_PLAYER_CREDIT` | `15` | Welcome bonus |
| `MIN_WITHDRAWAL` | `100` | Minimum withdrawal amount |
| `PRIZE_PERCENT` | `0.8` | Winner's share (80%) |
| `BOTS_CONTRIBUTE_TO_POOL` | `True` | Bot bets feed the prize pool |
| `BOT_GUARANTEED_WIN_AFTER` | `64` | **Legacy — no longer used.** Rounds are never shortened to make a bot win; normal game duration and pacing are preserved |
| `PREPARATION_SECONDS` | `40` | Countdown between rounds |
| `CALL_INTERVAL_SECONDS` | `4` | Seconds between ball calls |
| `MIN_CALLS_BEFORE_WIN` | `10` | Minimum balls that must be called before a round can END. A valid pattern claimed earlier is refused with a “too soon” message (no elimination, round keeps running); false BINGO still eliminates. Bots wait for this minimum too (`_bot_claim_pass` reschedules a too-early read bot) |
| `POST_GAME_RESET_SECONDS` | `15` | Winner screen duration |
| `TICK_INTERVAL` | `1` | Game loop tick interval (seconds) |
| `MIN_TOTAL_PLAYERS` | `18` | Informational — lowest total players (real + bots) in play |
| `MAX_TOTAL_PLAYERS` | `140` | Informational — highest total players (real + bots) in play |
| `NUM_CARDS` | `400` | Pre-generated card pool size |
| `ANNOUNCE_NUMBERS` | `False` | Announce every ball in chat |
| `ANNOUNCE_ROUNDS` | `True` | Announce round start/winner in chat |
| `ADMIN_APPROVAL_RATE` | `0.9` | Legacy (unused) — admin credit is unified with player credit; kept for compatibility |
| `ADMIN_ONLINE_MINUTES` | `5` | How long admin stays "online" |
| `REFERRAL_COMMISSION_RATE` | `0.05` | 5% commission rate |

---

## 8. Database Schema

SQLite database (`bingo_bot.db`) with WAL journal mode. The schema auto-migrates on startup.

### Tables

#### `players`
```sql
CREATE TABLE players (
    user_id       INTEGER PRIMARY KEY,  -- Telegram user ID (positive = real, negative = bot)
    username      TEXT,                  -- Telegram @username
    full_name     TEXT,                  -- Display name (collected on registration)
    phone         TEXT,                  -- Wallet phone number
    is_registered INTEGER NOT NULL DEFAULT 1,
    credit        INTEGER NOT NULL DEFAULT 1000,  -- Balance in ETB
    is_admin      INTEGER NOT NULL DEFAULT 0,
    created_at    TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
```

#### `game_state` (one row per room)
```sql
CREATE TABLE game_state (
    room INTEGER PRIMARY KEY,            -- Room bet amount (10 by default)
    phase TEXT DEFAULT 'preparation',     -- preparation | playing | ended
    preparation_end_time TEXT,           -- ISO timestamp
    current_call TEXT,                   -- Current ball (e.g., "B-7")
    winner_user_id INTEGER,
    winning_pattern TEXT,                -- JSON with pattern, prize, card, cells
    prize_pool INTEGER DEFAULT 0,
    total_bets INTEGER DEFAULT 0,
    ball_order TEXT,                     -- JSON array of remaining balls
    round_number INTEGER DEFAULT 0,
    current_game_id INTEGER,
    bots_enabled INTEGER DEFAULT 1,
    bots_difficulty INTEGER DEFAULT 5,  -- 0=Easy, 5=Impossible (default)
    next_call_time TEXT,                -- ISO timestamp for next ball call
    reset_time TEXT,                    -- ISO timestamp for round reset
    paused INTEGER DEFAULT 0,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
```

#### `cards`
```sql
CREATE TABLE cards (
    id      TEXT PRIMARY KEY,   -- e.g., "C001"
    numbers TEXT NOT NULL        -- JSON: {"B": [1,12,4,8,15], "I": [22,...], ...}
);
```

#### `card_selections`
```sql
CREATE TABLE card_selections (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id    INTEGER NOT NULL,
    card_id    TEXT NOT NULL,
    room       INTEGER NOT NULL DEFAULT 30,
    bet_amount INTEGER DEFAULT 30,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(user_id, card_id)
);
```

#### `called_numbers`
```sql
CREATE TABLE called_numbers (
    id        INTEGER PRIMARY KEY AUTOINCREMENT,
    room      INTEGER NOT NULL DEFAULT 30,
    number    TEXT NOT NULL,            -- e.g., "B-7"
    called_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(room, number)
);
```

#### `games`
```sql
CREATE TABLE games (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    room            INTEGER NOT NULL DEFAULT 30,
    round_number    INTEGER,
    started_at      TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    ended_at        TIMESTAMP,
    winner_user_id  INTEGER,
    winner_name     TEXT,
    winning_pattern TEXT,
    total_bets      INTEGER DEFAULT 0,
    prize_paid      INTEGER DEFAULT 0,
    house_kept      INTEGER DEFAULT 0,
    status          TEXT DEFAULT 'running'
);
```

#### `game_history`
```sql
CREATE TABLE game_history (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    game_id      INTEGER,
    user_id      INTEGER,
    card_ids     TEXT,           -- JSON array of card IDs
    total_bet    INTEGER,
    winnings     INTEGER,
    credit_after INTEGER,
    status       TEXT,           -- winner | eliminated | played
    played_at    TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
```

#### `bots`
```sql
CREATE TABLE bots (
    user_id    INTEGER PRIMARY KEY,   -- Negative integer
    username   TEXT,
    cards      INTEGER DEFAULT 0,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
```

#### `transactions`
```sql
CREATE TABLE transactions (
    id                 INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id            INTEGER NOT NULL,
    type               TEXT NOT NULL,        -- deposit | withdraw
    amount             INTEGER NOT NULL,
    tx_id              TEXT,                 -- Wallet transaction number
    phone              TEXT,
    user_name          TEXT,                 -- Snapshot of user's name
    payment_account_id INTEGER,              -- Which admin account was paid into
    provider           TEXT,                 -- Bank name snapshot
    account_number     TEXT,                 -- Account number snapshot
    account_holder     TEXT,                 -- Account holder name snapshot
    status             TEXT DEFAULT 'pending',  -- pending | approved | rejected
    admin_note         TEXT,
    reviewed_by        INTEGER,
    created_at         TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    reviewed_at        TIMESTAMP
);
```

#### `payment_accounts`
```sql
CREATE TABLE payment_accounts (
    id             INTEGER PRIMARY KEY AUTOINCREMENT,
    admin_id       INTEGER,                  -- Owner admin's user_id
    provider       TEXT NOT NULL,            -- Bank name (TeleBirr, CBE, CBB...)
    account_name   TEXT NOT NULL,            -- Account holder name
    account_number TEXT NOT NULL,            -- Account number
    is_active      INTEGER NOT NULL DEFAULT 1,
    created_at     TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at     TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
```

#### `round_eliminations`
```sql
CREATE TABLE round_eliminations (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    game_id       INTEGER NOT NULL,
    user_id       INTEGER NOT NULL,
    reason        TEXT DEFAULT 'false_bingo',
    eliminated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
```

#### `appeals`
```sql
CREATE TABLE appeals (
    id             INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id        INTEGER NOT NULL,
    transaction_id INTEGER NOT NULL,
    reason         TEXT,
    status         TEXT DEFAULT 'pending',
    resolution     TEXT,
    resolved_by    INTEGER,
    created_at     TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    resolved_at    TIMESTAMP
);
```

#### `bot_notifications`
```sql
CREATE TABLE bot_notifications (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    chat_id    INTEGER NOT NULL,    -- Telegram chat ID
    text       TEXT NOT NULL,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    sent_at    TIMESTAMP           -- NULL until sent
);
```

#### `activity_log`
```sql
CREATE TABLE activity_log (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id    INTEGER,
    action     TEXT NOT NULL,
    details    TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
```

#### `referrals`
```sql
CREATE TABLE referrals (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    referrer_id INTEGER NOT NULL,
    referred_id INTEGER NOT NULL UNIQUE,
    created_at  TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
```

#### `referral_commissions`
```sql
CREATE TABLE referral_commissions (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    referrer_id   INTEGER NOT NULL,
    referred_id   INTEGER NOT NULL,
    game_id       INTEGER,
    room          INTEGER DEFAULT 30,
    total_bet     INTEGER NOT NULL DEFAULT 0,
    commission    INTEGER NOT NULL DEFAULT 0,
    created_at    TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
```

#### `settings` (key-value)
```sql
CREATE TABLE settings (
    key   TEXT PRIMARY KEY,
    value TEXT
);
```

---

## 9. Backend Components

### 9.1 `server.py` — Flask Server

The central hub. Runs on port 5000 (configurable).

**Responsibilities:**
- Serves the built React app from `frontend/dist/`
- Exposes the JSON REST API consumed by the Mini App
- Initializes and runs the APScheduler game loop
- Seeds the card pool on startup
- Handles Telegram webhook dispatch (in webhook mode)
- Drains the notification queue on every incoming request

**Key initialization flow:**
```
server.py starts → Database(config.DB_PATH) → GameLogic(db) → GameLoop(db, logic)
→ seed_cards() → loop.start() → app.run()
```

**Key API endpoints:** See Section 15.

### 9.2 `bot.py` — Telegram Bot

A `PremiumBingoBot` class handles all bot interactions.

**Responsibilities:**
- `/start` — Registration flow (collects full name, processes referral deep-links)
- `/play` — Sends the "Open Nice Bingo" Web App button
- `/status`, `/balance`, `/cards`, `/history`, `/top` — Game info
  - `/balance` shows **only the credit** — the card-count line was removed so
    no user screen (bot or Mini App) reveals how many cards anyone holds
- `/admin` — Admin control panel
- `/help` — How to play guide (support link via bot menu button)
- Wallet chat flows (deposit/withdraw via inline conversation)
- Appeal submission
- **Announcer tick** — Polls `game_state` every 1.5s, sends round announcements
- **Notification queue drain** — Reads `bot_notifications` table and sends messages

**Announcer behavior:**
- Tracks per-room state (`phase`, `ball_count`, `round_number`)
- On preparation start: sends countdown message
- On round start: sends "Round started" with pool info
- On winner: sends winner announcement with prize
- Daily promotional message: sends once per day to all players

**Notification queue:**
- Server writes to `bot_notifications` table
- Bot reads unsent rows, sends via Telegram API, marks as sent
- Works in both polling and webhook mode

### 9.3 `game_loop.py` — Game Loop (APScheduler)

The single source of truth for game state. Runs inside `server.py`.

**Lifecycle per room:**
```
preparation (40s countdown) → playing (ball every 4s) → ended (15s) → preparation → ...
```

**`tick()` method (every 1 second):**
- **Preparation phase**: Adds up to 8 bots/tick gradually toward the current plan (chosen by human count)
- **Playing phase**: Calls next ball when `next_call_time` arrives. The roster is **FROZEN** once the round starts — no bots join mid-round (`tick()`, the boot fill in `start()`, and `_post_boot_fill()` all skip rooms that are already `playing`), so the player count and prize pool are locked for the whole round and can only change in the next preparation phase. The full fill happens one final time in `start_round()` while still in preparation.
- **Ended phase**: Resets round when `reset_time` arrives
- **Failure isolation**: every room is processed in its own `try/except` inside
  `tick()` (delegated to `_tick_room()`), so a transient DB error in one room
  can never stall the others — the room simply retries the next tick
- **Stale timestamps self-heal**: a room whose `preparation_end_time` /
  `next_call_time` / `reset_time` is in the past **or missing** is
  force-advanced to the next logical phase (`start_round` / `call_step` /
  `reset_round`) instead of hanging forever. If a tick still fails, a second
  `_heal_stale_room()` pass force-advances the stuck room (playing → ends
  winless via `end_round_no_winner`, preparation → starts, ended → resets)
- **Heartbeat + watchdog**: every ~15s `tick()` writes the `game_loop_heartbeat`
  setting (throttled — never one write per tick) so `/health` can prove the
  loop is alive; if the APScheduler is ever found stopped, `tick()` restarts
  it via `start()` (idempotent)

**Self-healing bot fill — a room with bots on NEVER sits at 0 players:**
- `start()` (game-loop boot, also run on every WSGI reload) fills every room with
  bots enabled **immediately to the plan target, before the first tick**
- `reset_round()` seeds an instant first batch (up to 8) so a fresh countdown
  never shows an empty table; prep ticks + `start_round()` top up the rest
- `start_round()` fills the remainder slot-by-slot with the plan's card counts
- The ticker tops up during **preparation only** (≤8 per tick). Once a room is
  **playing**, the roster is FROZEN — no bots join (`_tick_room`, the boot
  fill and `_post_boot_fill()` all skip `playing` rooms) so player count and
  prize pool stay fixed for the whole round. A reload mid-round keeps the
  existing roster as-is (the full fill happened in `start_round()`)
- **Presence is unconditional:** bot JOINING is never blocked while the toggle
  is on — the super-admin **"bots off" toggle only silences their
  auto-claims/auto-wins**; the room keeps exactly **one other player** so
  nobody plays alone, and no full bot fill happens until it is back on
- `add_bots()` (super-admin button) force-enables the toggle if it is off and
  fills straight to the plan target

**`start_round()` method:**
- Rebuilds the bot plan from the **final human count** and tops up the room slot-by-slot (each bot gets the plan's card count)
- Persists bot accounts (negative IDs) for the super-admin `/api/admin/bots` view
- Creates a new `games` row
- Sets ball order (shuffled 75 balls)
- Transitions to "playing" phase

**`call_step()` method:**
- Pops the next ball from the persisted order
- Runs `_bot_claim_pass()` — bots may auto-claim BINGO (per difficulty delay)
- **Normal game duration is preserved — no forced wins.** Every difficulty
  other than Impossible plays like a **standard bingo game**: a winner is
  declared ONLY when a player presses BINGO, and the round is never shortened
  to make a bot win
- **75/75 ALWAYS stops the round**: `call_step` checks the EMPTY BALL MACHINE
  FIRST — before any difficulty guard — so once every ball is called the round
  unconditionally ends. On every difficulty EXCEPT Impossible it ends
  **winless** after all 75 balls (standard bingo). ONLY on Impossible (5) a
  ready bot is declared the winner at that point so a human can still never
  win. No room can ever call past ball 75 or hang in `playing`
- Schedules the next ball call

**`claim_bingo()` method:**
- Verifies the player's card actually has a winning pattern
- **Minimum-ball rule (`MIN_CALLS_BEFORE_WIN`, default 10)**: a valid pattern
  claimed before enough balls are called is **refused with a friendly "too
  soon" message — never an elimination** and the round keeps running. The
  BINGO button stays **available throughout the whole game** exactly as
  before — pressing it early simply gets the friendly refusal and play
  continues. A false BINGO (no pattern at all) is still punished regardless of
  ball count, and the Impossible backtrack also respects the minimum (it fires
  only at ≥ the minimum balls)
- If valid (and at/after the minimum): pays the prize, ends the round
- If invalid: eliminates the player for this round (false BINGO)
- **Impossible (5)**: a human can never win — the win is handed to a bot
  player instead; the claim is NEVER refused with a "you can't win" warning
  and bots are never mentioned (the winner is simply a player with a
  human-like name)

**`handle_winner()` method:**
- Credits the prize to the winner
- Writes game history
- Distributes referral commissions
- Logs activity

**Bot claim system:**
- Bots claim based on difficulty level (0=Easy/never, 5=Impossible/instant)
- Each difficulty has a delay range (number of balls to wait after completing a pattern)
- Bots genuinely check their cards — they never false-claim
- **Minimum-ball respect**: a bot whose claim would end the round before
  `MIN_CALLS_BEFORE_WIN` is re-scheduled by `_bot_claim_pass()` (it claims on
  a later ball) instead of being dropped, so bots never win too early either

### 9.4 `game_logic.py` — Game Rules

Pure game logic, no I/O.

**Ball machine:**
- `new_ball_order()` — Shuffled array of all 75 balls (B-1 through O-75)
- `call_next_number()` — Pops the next ball, records it atomically

**Pattern detection:**
- `check_winning_patterns()` — Returns achieved patterns and winning cells
- Supported patterns: Row, Column, Diagonal, Anti-Diagonal, Four Corners
- FREE center cell counts as automatically hit

**Prize pool:**
- `calculate_prize_pool()` — Sums all bets (real + bot), applies `PRIZE_PERCENT`
- Returns: `total_bets`, `prize_pool` (80%), `house_fee` (20%), `real_players` count

**Bot system:**
- `add_bot_player()` — Creates a bot with a human name + the plan's card count (1-3 cards)
- `ensure_minimum_players()` — Fills the room to a plan chosen by the human count (see Bot System)
- `player_breakdown()` — Returns counts of real vs bot players

**Bot ID allocation (large negative window):**
- A new bot's `user_id` is `-random.randint(1_000_000, 999_999_999)` — a ~1
  **billion-value** window, probed against `players` for uniqueness
- Up to **200 random attempts** per bot; if all collide the call FAILS LOUDLY
  (`bot_id exhausted after 200 tries, available=N`) instead of reusing an ID
- Because bots accumulate in `players` over time, `migrate_db.py` **purges
  stale bot rows** (negative IDs with no current `card_selections`) on every
  deploy so the ID window never saturates — this is the fix for the old
  `bot_id exhausted after 100 tries, available=400` failure

**Bot naming:**
- Deterministic from user ID (stable across restarts) — `mix = (idx * 31 + 17) % 100`
- Seven groups, disjoint first-name pools, drawn from the ID:
  - **~20% Oromo male** first + surname (`mix < 20`, `BOT_OROMO_FIRST_NAMES`)
  - **~20% Amhara male** first + surname (`mix < 40`, `BOT_AMHARA_FIRST_NAMES`)
  - **~10% Tigray male** first + surname (`mix < 50`, `BOT_TIGRAY_FIRST_NAMES`)
  - **~30% Ethiopian male, all regions** first + surname (`mix < 80`, `BOT_MALE_FIRST_NAMES`)
  - **~5% Ethiopian female** first + surname (`mix < 85`, `BOT_FEMALE_FIRST_NAMES`)
  - **~10% East African nicknames** (`mix < 95`, `BOT_EAST_AFRICAN_NICKNAMES` — e.g. "Baraka", "Zuri")
  - **~5% international nicknames** (`mix ≥ 95`, `BOT_NICKNAMES` — e.g. "BigShot", "RoyalFlush")
- Shared surname pool `BOT_LAST_NAMES` (12 patronymic-style surnames) for every full name
- Example names: "Guyo Tadesse", "Lemma Girma", "Merhawi Haile", "Abel Girma", "Hiwot Girma", "Baraka", "HotShot"
- Over any 100 consecutive IDs every `mix` residue occurs exactly once (31 is coprime to 100), so the mix is exactly 20/20/10/30/5/10/5 (asserted by `api_smoke.py` step 15)

### 9.5 `database.py` — SQLite Layer

**Key design decisions:**
- **One persistent connection per process** (serialized by RLock) — ~100x faster than opening per-operation on Windows
- **WAL journal mode** — allows concurrent readers (bot + server)
- **Auto-migration** — missing columns/tables are added on startup
  (`_migrate_schema()` runs on **every** init, including a brand-new
  database, so the full `game_state` schema — `ball_order`, `round_number`,
  `current_game_id`, `bots_enabled`, `next_call_time`, `reset_time`, `paused`,
  `bots_difficulty` — plus a per-room `game_state` row always exist; fixed the
  fresh-DB bug where those columns were only created via the exception path)
- **INSERT OR IGNORE** — idempotent operations prevent double-charges
- **Connection self-heal** — `_session()` (the context manager every query runs
  through) closes the connection and drops `self._conn` on any
  `sqlite3.DatabaseError`, so the next call opens a fresh connection.
  A broken DB can never wedge the process permanently
- **Schema auto-repair** — `_repair_schema()` runs at startup. If the
  `sqlite_master` integrity probe fails twice (a second probe rules out a
  transient lock), it backs the file up as `<name>.corrupt.bak`, drops the
  schema rows with invalid `rootpage`, rebuilds the file via the SQLite backup
  API and recreates the lost tables (see Troubleshooting)

**Key methods:**
- `get_game_state(room)` — Returns the full game state row
- `update_game_state(room, **kwargs)` — Updates specific fields atomically
- `get_all_selections(room)` — All card selections for a room
- `get_user_selections(user_id, room)` — A user's cards in a room
- `select_card(user_id, card_id, bet, room)` — Buy a card (returns False if already taken)
- `get_called_numbers(room)` — All balls called so far
- `record_call(room, number, order)` — Atomic: append called number + update remaining order
- `update_credit(user_id, delta)` — Adjust balance
- `add_transaction(...)` — Create a wallet request
- `review_transaction(tx_id, status, reviewed_by)` — Approve/reject a wallet request
- `notify_user(chat_id, lines)` — Enqueue a notification for the bot to send

**Maintenance & self-defense (used by `maintenance.py`):**
- `check_integrity()` — `PRAGMA integrity_check` probe; returns `(ok, message)`
  and never raises on a damaged file
- `available_disk_mb()` / `db_size_bytes()` — free space + file size
- `backup_database(reason)` — consistent **online** snapshot via the sqlite3
  backup API into `DB_BACKUP_DIR`; keeps only the newest `DB_BACKUP_KEEP`
- `prune_history(keep_days)` — deletes finished games older than N days
  (newest `PRUNE_KEEP_LATEST_ROWS` always kept), orphaned `game_history`,
  old `activity_log` and old `called_numbers`; running rounds never touched
- `wal_checkpoint()` — `PRAGMA wal_checkpoint(TRUNCATE)` so trimmed rows
  actually return free space to the packed free-tier disk
- `clean_corrupt_player_rows()` — deletes the garbage rows whose `credit` is a
  timestamp string, `is_registered` is outside 0/1, or whose `username` is a
  negative (bot) number on a positive (human) `user_id`; every removal is
  logged to `activity_log` first; real accounts are never matched
- `purge_unconfigured_rooms()` — removes stuck `game_state` rows for rooms no
  longer listed in `ROOM_BETS`, only when the room has no pending selections

### 9.6 `config.py` — Configuration

All settings are read from environment variables with defaults. Helper functions:
- `_int(name, default)` — Parse integer from env
- `_float(name, default)` — Parse float from env
- `_bool(name, default)` — Parse boolean from env

The **maintenance / reliability group** (`PRUNE_HISTORY_DAYS`,
`PRUNE_KEEP_LATEST_ROWS`, `DB_BACKUP_DIR`, `DB_BACKUP_KEEP`,
`MAINTENANCE_INTERVAL_MIN`, `MAINTENANCE_MIN_FREE_MB`) is consumed by the new
`maintenance.py` module — see §9.5 and the 2026-09-12 changelog entry.

---

## 10. Frontend Components

### 10.1 `App.jsx` — Main Component

The root component that manages:
- **Phase routing**: Shows `Registration` → `CardPicker` (preparation) → `BingoCard` + `CalledBoard` (playing) → `WinnerModal` (ended)
- **State polling**: Fetches `/api/game-state` every 2.5 seconds
- **User state**: Tracks selections, credit, registration status
- **Auto-play**: Toggles automatic daubing and BINGO claiming
- **Spectator mode**: Shows another player's card when no cards selected
- **BINGO button always available**: the button stays present and clickable the
  whole game, exactly as originally — pressing it before the minimum
  (`cfg.min_calls_before_win`, server config) just gets the friendly "too
  soon" refusal from the server and play continues (auto-play still claims;
  the server simply refuses early claims)
- **Called strips (both sides)**: with 2–3 cards the recent called balls are
  rendered by the `CalledStrip` component above (`📣 Called`) and below
  (`🔔 Called`) the cards. Balls are shown **newest-first** — the newest ball
  sits next to the label — and a `useEffect` on `called_count` scrolls every
  strip back to `scrollLeft 0` as each new ball arrives, so it can never be
  hidden by older balls

### 10.2 `Header.jsx` — Top Bar

Shows brand name, the live **card count** (`🃏 N card(s)` while the round is
running), the room chip (a selector when multiple rooms exist, otherwise a
static “Room 10” label), credit chip, pool chip, settings button, admin/super-admin toggle buttons, and connection status dot. **The number of players is deliberately NOT shown** — only the card count (`cards_in_play`), so users see activity without being able to compare against a player count. The preparation hero in `App.jsx` shows `cards_in_play` instead of the player count too.

### 10.3 `CardPicker.jsx` — Card Selection (Preparation Phase)

Grid of 400 cards. Players tap to select/deselect. Shows:
- Available cards (dark tiles)
- Your selected cards (gold border)
- Taken cards by others (dimmed)
- Quick Play button (auto-fills up to MAX_CARDS_PER_PLAYER)

### 10.4 `BingoCard.jsx` — Bingo Card Renderer

Renders a 5×5 Bingo card with:
- Column headers (B/I/N/G/O)
- FREE center cell (always marked)
- Marked cells (called numbers highlighted in pink)
- Daubable cells (tap to mark during play)
- Winning pattern animation

### 10.5 `CalledBoard.jsx` — Ball Board

5-column board showing all 75 balls. Called numbers are highlighted. Current ball pulses with animation.

### 10.6 `WinnerModal.jsx` — Winner Celebration

Full-screen modal with:
- Confetti animation (CSS-based)
- NOTE: the super admin panel's Game Controls include an explicit **Add Bots**
  button (`POST /api/superadmin/game/add-bots`) that immediately fills the room
  with bot players up to the current round's locked plan target (chosen by
  human count: 1 human -> 80-140 bots, 2-5 -> 40-79, 6+ -> 18-39, each bot
  holding a random 1-3 cards, capped to the card pool). Bots also join
  automatically during every preparation countdown, so every game has players
  regardless of this button.
- Winner name and prize amount
- Winning card with pattern highlighted
- "Next round" countdown

### 10.7 `AdminPanel.jsx` — Admin Controls

In-app admin panel with:
- Force Start / Force Call / Reset Round
- Add Bots / Toggle Bots
- User list with inline credit editing
- Transaction review (approve/reject deposits and withdrawals)
- Payment account management

### 10.8 `Settings.jsx` — Settings Panel

Tabbed panel with:
- **Wallet**: Balance, deposit (bank selection + transaction number), withdrawal (account details)
- **Profile**: Edit full name and phone number
- **Referral**: Link, commissions, leaderboard
- **Sound**: Sound pack selection (Classic/Retro/Digital/Mute)
- **Help**: How to play guide

### 10.9 `sound.js` — Sound Effects

Synthesized via Web Audio API (no external files). Four packs:
- **Classic**: Traditional casino sounds
- **Retro**: 8-bit style
- **Digital**: Modern electronic
- **Mute**: No sounds

---

## 11. Game Flow & Logic

### Round Lifecycle

```
┌──────────────┐     ┌─────────────┐     ┌──────────────┐
│ PREPARATION  │────▶│   PLAYING   │────▶│    ENDED     │
│ (40 seconds) │     │ (ball/4sec) │     │  (15 seconds)│
└──────────────┘     └─────────────┘     └──────────────┘
       ▲                                        │
       └────────────────────────────────────────┘
```

### Preparation Phase
1. Timer starts at 40 seconds
2. Players select up to 3 cards from a pool of 400
3. Each card costs the single room's fixed bet (10 ETB by default)
4. Bots gradually join (up to 8 per tick) toward the round's **locked** plan
5. When timer hits 0, `start_round()` reads the same locked plan and tops up
   to the stored target (rolled once per round: 80-140 / 40-79 / 18-39 bots,
   each with a random 1-3 cards)

### Playing Phase
1. Balls are called every 4 seconds from a shuffled pool of 75
2. Players' cards auto-daub matching numbers
3. Players can manually daub by tapping cells
4. Auto-play mode daubs and claims automatically
5. When a player completes a winning pattern, they press BINGO
6. Server verifies the card — valid claim pays the prize, false claim eliminates
7. **75/75 always stops the game — standard bingo end**: the ball loop checks the empty ball machine FIRST (before the Impossible guard) and unconditionally ends the round at ball 75. On every difficulty EXCEPT Impossible the round simply ends **winless** if nobody claimed — exactly like a standard bingo game; the game duration is never shortened to make a bot win. ONLY on **Impossible** difficulty a ready bot is declared the winner at 75/75 (so a human can never win), and the ball machine is additionally reordered there so a bot completes and claims before a human ever can

### Winning Patterns
- **Row**: All 5 numbers in any horizontal row
- **Column**: All 5 numbers in any vertical column
- **Diagonal**: Top-left to bottom-right (5 numbers)
- **Anti-Diagonal**: Top-right to bottom-left (5 numbers)
- **Four Corners**: The 4 corner numbers (center FREE doesn't count)

### Prize Pool Calculation
```
total_bets = sum of all card bets (real + bot)
prize_pool = total_bets × PRIZE_PERCENT (80%)
house_fee = total_bets × (1 - PRIZE_PERCENT) (20%)
```

Bot bets contribute to the pool just like real bets, making the prize larger.

### False BINGO Rule
- If a player claims BINGO but their card doesn't actually have a winning pattern, they are **eliminated** for that round
- Their cards stop participating (bet stays in the pool)
- They are automatically eligible again in the next round
- Elimination is persisted (survives server restarts)

---

## 12. Bot System (AI Players)

### How Bots Work
- Bots are identified by **negative user IDs** drawn from a ~1-billion-value
  window (`-1,000,000` … `-999,999,999`, see §9.4) — never reused, never
  colliding with real Telegram IDs (which are always positive)
- Each bot gets a deterministic human-like name — **20% Oromo / 20% Amhara /
  10% Tigray / 30% general Ethiopian male**, **5% Ethiopian female**, **10%
  East African nicknames**, **5% international nicknames** (see §9.4) — e.g.
  "Guyo Tadesse", "Lemma Girma", "Merhawi Haile", "Abel Girma", "Hiwot Girma",
  "Baraka", "HotShot"
- Each bot picks **1-3 cards** from the pool, per the round's card plan
- Bot bets feed the prize pool (controlled by `BOTS_CONTRIBUTE_TO_POOL`)
- Bots are ordinary `players` rows to every player in the room — only the
  super admin can see them (`/api/admin/bots*` is super-admin only, and the
  game-state payload hides `bots_players`/`bots_enabled`/`bots_difficulty`
  from everyone except the super admin)
- **Every round includes bots — even a room with 0 humans still fills and
  plays a full round** (Option 1 below covers `0-1` humans)
- **Spectating**: a player with no card watches a random bot's card daub live
  (`/api/spectate` prefers bots) with that player's Ethiopian name shown

### Bot Filling Logic
1. During preparation, bots join gradually (up to 8 per tick) toward the
   round's **locked** plan — the room always looks alive before the round
   starts (bots are added **gradually throughout the countdown**, never all
   at once)
2. The plan is rolled **once per round** from the **current human-player
   count** and persisted, so the fill follows how many real players are in
   the room — and the SAME target is reused by every prep tick and the
   final top-up (the size never creeps up to the same ceiling every round;
   each round draws a different random size)
3. When the round starts, `_bot_plan()` returns the **stored** plan and
   `start_round()` tops up to the locked target slot-by-slot
4. Every round each bot gets a **random 1-3 cards** (`bot_card_plan()`); the
   total is clamped to the 400-card pool with every bot keeping at least one
   card — so bot-card totals differ every round
5. Bots work on **every difficulty level** — the fill is identical on all of
   them; the ONLY difference is that on **Impossible (5)** no human can win
6. **Bots disabled** (super-admin toggle): the room keeps exactly **ONE other
   player** holding a card — nobody should ever play alone — and no further
   players are added until the toggle is back on. The toggle only silences
   their auto-claims; the single companion is joined as a normal player

**Bot count is chosen by the number of HUMAN players** (`pick_bot_target()`):

| Option | Human players | Bots added | Cards per bot |
|--------|---------------|------------|---------------|
| 1 | `0-1` | 80-140 | 1-3 (random) |
| 2 | `2-5` (e.g. 2 players → 40-79) | 40-79 | 1-3 (random) |
| 3 | `6+` | 18-39 | 1-3 (random) |

Card plan example (Option 2, the famous case): 42 bot players each draw
`random.randint(1, 3)` cards → e.g. the room starts with **~90** bot cards,
capped so the deck is never exhausted. Every bot holds at least one card.

> Bots are completely **invisible to humans** — they are stored as ordinary
> players (negative IDs) with human-like names (20% Oromo / 20% Amhara / 10%
> Tigray / 30% general Ethiopian male / 5% Ethiopian female / 10% East
> African / 5% international nicknames — see §9.4), and their bets feed the
> prize pool. Only the **super admin** sees them via `/api/admin/bots` and the
> `bots` table.

### Bot Claim System
Bots press BINGO like humans — only when a card actually has a complete pattern.

**Difficulty levels (0-5). Default = 5 (Impossible). The bot FILL is identical
on every level (18-140 players by human count); only the claiming / win logic
differs — and every level other than Impossible behaves like a standard bingo
game with normal duration and pacing:**
| Level | Name | Delay Range | Behavior |
|-------|------|-------------|----------|
| 0 | Easy | Never | Bots never claim on their own — humans win whenever they claim; the round simply ends winless after all 75 balls if nobody claims (standard bingo) |
| 1 | Normal | 5-8 balls | Very slow, rarely win |
| 2 | Medium | 3-5 balls | Balanced, human-like delay |
| 3 | Hard | 1-2 balls | Fast, often beats humans |
| 4 | Very Hard | 0-1 balls | Near-instant |
| 5 | **Impossible** | 0 balls | Instant — **default**; a human can NEVER win (see below) |

**Impossible (5) is the default** and its mechanics are **strictly isolated**:
only difficulty 5 reorders the ball machine and blocks human wins (`_impossible_guard`
in `call_step`). A human's claim is never refused with a warning — the ball that
would complete a human's card is simply never drawn, and if a human ever holds a
ready pattern the win is handed to a bot player (via `_force_bot_win`) so the
claim silently "lands" on a player with an Ethiopian name instead. If the round
somehow reaches 75/75 without a winner on Impossible, a ready bot is declared
the winner so a human can still never win.

The delay is the number of balls to wait AFTER the pattern is completed before claiming. This gives other players a chance to claim first.

---

## 13. Wallet & Transactions

### Deposit Flow
1. User opens Settings → Wallet → Deposit
2. Selects a bank (TeleBirr, CBE, CBB, etc.)
3. System shows the admin's account number for that bank
4. User sends money via their wallet app
5. User enters the amount and transaction number
6. System creates a `transactions` row with status "pending"
7. Admin reviews in the admin panel → Approve or Reject
8. On approval: user's credit is increased by the deposit amount

### Withdrawal Flow
1. User opens Settings → Withdraw
2. Selects destination bank
3. Enters amount, account holder name, and account number
4. System creates a `transactions` row with status "pending"
5. Admin reviews → sends money to the user's account → Approve
6. On approval: user's credit is decreased by the withdrawal amount

### Admin Credit System (unified model)
- Every account — admin or user — has **ONE credit balance** (the `players.credit` field; the legacy `players.admin_credit` column is unused by the live flow)
- The super admin sells / buys back credit to admins via `POST /api/superadmin/credit` with `target=admin` — it writes the same unified balance
- Approving a **deposit** credits the user the full amount; approving a **withdrawal** debits the user the full amount
- The reviewing/owner admin's own balance is **never touched** — there is no separate admin_credit float. `ADMIN_APPROVAL_RATE` is retained in `config.py` for compatibility but is no longer applied anywhere

### Payment Account Management
- Admins add payment accounts (bank name, account holder, account number)
- The deposit picker shows **one account per bank/provider**: always the **online** admin with the most credit; if no admin is online for a provider, the **super admin's** account is the fallback; as a last resort an **offline** admin's account is shown clearly flagged `admin_online: false` so users always have somewhere to pay
- A deposit into an **offline** admin's account is rejected (`400 offline`)
- Admin is "online" while actively using the app (within `ADMIN_ONLINE_MINUTES`)

### Running the smoke tests
```bash
# .env only stores APP_URL here, so pass the test identities + rooms explicitly.
# (The test suite deliberately exercises 3 rooms (30/50/100) to cover the
# multi-room code paths; PRODUCTION runs a single “By 10” room.)
ADMIN_IDS=1 SUPER_ADMIN_IDS=2 ROOM_BETS=30,50,100 venv\Scripts\python.exe smoke_test.py
# or, for the API-only suite:  venv\Scripts\python.exe api_smoke.py
```
The suite plays full rounds offline (registration, card sales, gradual bot fill,
bot wins, **Impossible: a human can never win**, **standard-bingo 75-ball end
with no forced wins**, bots-disabled **one-companion-player rule**, exact 80%
payout, false-BINGO elimination, admin/super-admin controls)
and renders sample cards.

---

## 14. Referral System

### How It Works
1. Every user gets a unique referral link: `https://t.me/BotName?start=REF_<user_id>`
2. When someone clicks the link and registers, they are linked to the referrer
3. Every round the referred player plays, the referrer earns **5% commission**
4. Commission is calculated from the referred player's total bet across all their cards

### Commission Distribution
- Commissions are distributed at the end of each round (in `_distribute_referral_commissions`)
- Only real player bets generate commissions (bots don't)
- Commission is added to the referrer's balance immediately
- Each commission is logged in `referral_commissions` and `activity_log`

---

## 15. API Reference

### User API

| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | `/api/init` | Initialize user (create if new, return user + state) |
| POST | `/api/register` | Complete registration (set phone number) |
| POST | `/api/profile` | Update profile (name/phone) |
| POST | `/api/delete-account` | Delete own account |
| GET | `/api/game-state` | Get current game state + user data |
| GET | `/api/cards` | Get all cards with taken status |
| POST | `/api/select-card` | Buy a card |
| POST | `/api/deselect-card` | Return a card (refund) |
| POST | `/api/quick-play` | Auto-fill cards |
| POST | `/api/claim-bingo` | Claim BINGO |
| GET | `/api/history` | User's round history |
| GET | `/api/leaderboard` | Top 20 players |
| GET | `/api/spectate` | Random player's card for spectating |
| GET | `/api/transactions` | User's wallet requests |
| POST | `/api/transactions` | Submit deposit/withdraw request |
| GET | `/api/wallet/settings` | Public wallet settings (bank accounts) |

### Admin API

| Method | Endpoint | Description |
|--------|----------|-------------|
| POST | `/api/admin/credit` | Add/remove credit from a user |
| POST | `/api/admin/force-start` | Force start a round |
| POST | `/api/admin/force-call` | Force call next ball |
| POST | `/api/admin/reset` | Reset current round |
| POST | `/api/admin/bots/add` | Add bots to a room — **super admin only** |
| POST | `/api/admin/bots/toggle` | Toggle bots on/off — **super admin only** (off = bots still join the boards but never auto-claim/win) |
| GET | `/api/admin/bots` | Bot status and breakdown — **super admin only** |
| GET | `/api/admin/stats` | Game statistics |
| GET | `/api/admin/users` | All users with details |
| POST | `/api/admin/users/delete` | Delete a user |
| GET | `/api/admin/transactions` | Wallet requests (filtered by admin) |
| POST | `/api/admin/transactions/review` | Approve/reject wallet request |
| GET | `/api/admin/accounts` | Payment accounts |
| POST | `/api/admin/accounts` | Add payment account |
| PUT | `/api/admin/accounts` | Update payment account |
| DELETE | `/api/admin/accounts` | Delete payment account |

### Super Admin API

| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | `/api/superadmin/accounts` | All payment accounts |
| GET | `/api/superadmin/transactions` | All wallet requests |
| GET | `/api/superadmin/activity` | Activity log |
| GET | `/api/superadmin/appeals` | Wallet appeals |
| POST | `/api/superadmin/appeals/review` | Resolve appeal |
| POST | `/api/superadmin/game/add-bots` | Manually fill room with bots (up to current plan target) |
| POST | `/api/superadmin/game/bots-toggle` | Enable/disable bots (off = bots still join but never auto-claim/win) |
| POST | `/api/superadmin/game/bots-difficulty` | Set bot difficulty 0-5 (5=Impossible) |
| POST | `/api/superadmin/game/start` / `stop` / `pause` / `resume` | Game phase controls |

---

## 16. Deployment

### Option 1: Northflank (Free, requires credit card for verification)
- See `DEPLOY.md` for step-by-step guide
- Uses `Dockerfile` + `run_prod.py`
- Always-on (no sleeping), free HTTPS on `*.code.run`
- SQLite on persistent volume

### Option 2: PythonAnywhere (Free, no card needed)
- See `PYTHONANYWHERE.md` for step-by-step guide
- Bot runs in **webhook mode** (`BOT_WEBHOOK=1`)
- Free HTTPS on `*.pythonanywhere.com`

### Option 3: Docker (any host)
```bash
docker build -t nice-bingo .
docker run -p 5000:5000 \
  -e BOT_TOKEN=your-token \
  -e ADMIN_IDS=your-id \
  -e APP_URL=https://your-domain.com \
  -v bingo-data:/data \
  nice-bingo
```

### Option 4: Local Development
```bash
python server.py  # Terminal 1
python bot.py     # Terminal 2
# For HTTPS: run_tunnel.bat or ngrok http 5000
```

---

## 16b. Changelog (update on EVERY change)

> **⚠️ This changelog — and the whole document — must be updated with every
> change to the codebase, every time.** Anyone must be able to recreate the
> entire system just by reading this documentation.

### 2026-09-12 — Disk-full self-defense · auto-pruning · corrupt-row cleanup · no hardcoded secrets
- **NEW `maintenance.py`** — automatic housekeeping run on boot (`wsgi.py`)
  and every `MAINTENANCE_INTERVAL_MIN` minutes via the game-loop scheduler:
  (1) **low-disk guard** — never writes to the DB when free space <
  `MAINTENANCE_MIN_FREE_MB` (writing on a full disk is what corrupted production
  in Sep 2026); (2) **integrity probe** (`PRAGMA integrity_check`) — a damaged
  DB is left untouched and a `<db>.damaged` marker + activity-log entry is
  written instead of pruning; (3) **daily backup snapshot** via the sqlite3
  backup API into `DB_BACKUP_DIR`, keeping only the newest `DB_BACKUP_KEEP`;
  (4) **corrupt player-row cleanup**; (5) **stale-room purge**; (6) **history
  pruning**; (7) **WAL checkpoint(TRUNCATE)** so trimmed pages free disk space
- **Auto-pruning** (`Database.prune_history`, `config.PRUNE_HISTORY_DAYS=30`,
  `PRUNE_KEEP_LATEST_ROWS=500`): finished games older than N days are deleted
  (the newest 500 finished rounds are always kept for display), plus orphaned
  `game_history`, old `activity_log` (>30 days, newest 500 kept) and old
  `called_numbers`. `games` is therefore bounded (~500 rows) instead of
  growing forever — the database stayed ~117 MB because it was never pruned.
  Running rounds are never touched
- **Corrupt user rows fixed** (`Database.clean_corrupt_player_rows`): rows
  whose `credit` holds a timestamp string, whose `is_registered` is outside
  0/1, or whose `username` is a negative (bot) number with a positive (human)
  `user_id` — the "credit shows a date / users are just numbers" garbage in
  the admin console — are removed and logged to `activity_log` first. Real
  accounts (positive id, integer credit, 0/1 registration, no leading-dash
  username) are never matched
- **Stale rooms purged** (`Database.purge_unconfigured_rooms`): `game_state`
  rows for rooms no longer in `ROOM_BETS` are deleted **only** when the room
  has no pending `card_selections` — the production rooms 20/30 that sat stuck
  in `playing` since 2026-09-09 are cleaned automatically
- **Game loop heartbeat + watchdog** (`game_loop.py`): `tick()` writes a
  throttled `game_loop_heartbeat` setting every ~15s so `/health` can prove the
  loop is alive, and restarts the APScheduler if it ever stops running
- **Hardcoded secrets removed** (`wsgi.py`): the committed `BOT_TOKEN` default
  is gone — the token is read ONLY from `.env` (an empty token makes the bot
  fail loudly). `SUPER_ADMIN_IDS` default is kept in `wsgi.py` so a reload
  without `.env` still works; `config.py` no longer injects the five hardcoded
  super-admin fallbacks and warns loudly when none is configured
- **Maintenance settings** added to `config.py` / `.env.example`:
  `PRUNE_HISTORY_DAYS`, `PRUNE_KEEP_LATEST_ROWS`, `DB_BACKUP_DIR`,
  `DB_BACKUP_KEEP`, `MAINTENANCE_INTERVAL_MIN`, `MAINTENANCE_MIN_FREE_MB`
- On PythonAnywhere, set `DB_BACKUP_DIR` to an absolute path **outside** the
  code folder (like `DB_PATH`) so daily snapshots survive project copies
- **Bot-name mix reworked** (`game_logic.py`): instead of 65/30/5 the names
  are now **20% Oromo / 20% Amhara / 10% Tigray / 30% general Ethiopian male /
  5% Ethiopian female / 10% East African nickname / 5% international
  nickname**. New disjoint pools `BOT_OROMO_FIRST_NAMES`,
  `BOT_AMHARA_FIRST_NAMES`, `BOT_TIGRAY_FIRST_NAMES`,
  `BOT_EAST_AFRICAN_NICKNAMES`; `BOT_NICKNAMES` now means “international”.
  Still deterministic from the ID (`mix = (idx * 31 + 17) % 100`); exactly
  20/20/10/30/5/10/5 over any 100 consecutive IDs. `api_smoke.py` step 15
  validates both the exact percentages and that each name comes from its
  group's pool
- **Minimum balls before a round can end** (`config.MIN_CALLS_BEFORE_WIN=10`):
  `claim_bingo()` refuses a valid-but-early claim with a `too_soon` result
  (no elimination, round keeps running — false BINGO still eliminates at any
  count, and the Impossible bot-win backtrack only fires at ≥ the minimum);
  `_bot_claim_pass()` re-schedules an early bot instead of dropping it, so
  bots claim as soon as the minimum is reached. In the Mini App the BINGO
  button stays available the whole game exactly as before — an early press
  simply gets the friendly refusal and play continues (the server exposes
  `min_calls_before_win` in the state config). `api_smoke.py` step 7
  now asserts the 10-ball refusal then wins after 10 calls
- **Called numbers flank the cards on BOTH sides** (`App.jsx` + `styles.css`):
  the called strip (shown with 2-3 cards) is now **newest-first** — the newest
  ball sits right next to the “Called” label and can never be hidden by older
  balls scrolling off; on each new call the strip auto-scrolls back to the
  newest; a mirrored strip (`🔔 Called`) is shown BELOW the cards too. The
  running highlight animation moved to `:first-child` (was `:last-child`)
- **Responsive / accessibility pass** (`styles.css`): `overflow-x: hidden` on
  `html,body` kills any device-wide horizontal scroll; `:focus-visible`
  outlines for keyboard users; safe-area (notched-screen) padding on `.app`;
  compact strip chips at ≤420px and short viewports
- **Frontend rebuilt** into `frontend/dist/` (assets `index-DPJPs7-9.js`,
  `index-CThgN6I1.css`)
- Passing from a fresh DB: `api_smoke.py` (all steps, 9.6s) and
  `smoke_test.py` (API + card image rendering)

### 2026-09-11 — Fresh-DB schema fix · roster/pool frozen mid-round · bot-name mix · card count shown
- **Fresh-DB schema bug fixed** (`database.py`): `init_db()` now runs
  `_migrate_schema()` on the happy path too (previously the `game_state`
  columns `ball_order`, `round_number`, `current_game_id`, `bots_enabled`,
  `next_call_time`, `reset_time`, `paused`, `bots_difficulty` plus the
  per-room `game_state` rows were only created through the exception-path
  migration) — a brand-new database now boots the full game immediately
- **Player count & prize pool are FROZEN once a round starts**: the gaming
  loop no longer fills bots during the `playing` phase (`_tick_room`), and
  both the boot fill (`start()`) and `_post_boot_fill()` skip rooms that are
  already `playing`; the final fill happens one last time in `start_round()`.
  `_state_payload` reports the **stored** `prize_pool`/`total_bets` while a
  round is `playing`/`ended` (live recomputation only during preparation), so
  the winning price shown never changes mid-round
- **Bot-name mix** (`game_logic.py`, deterministic from bot ID —
  `mix = (idx * 31 + 17) % 100`): **65% male Ethiopian** first+last name,
  **30% international nickname** (`BOT_NICKNAMES` widened to 30),
  **5% female Ethiopian** first+last name. `api_smoke.py` step 15 asserts
  exactly 65/30/5 per 100 sampled IDs. **Later replaced** — since 2026-09-11
  (2nd pass) the mix is the 7-way Oromo/Amhara/Tigray/general/female/East
  African/international distribution (see the new changelog entry above)
- **Card count shown, player count hidden** (`Header.jsx` + `App.jsx`): the
  header now displays `🃏 N card(s)` (`cards_in_play`) and the preparation
  hero shows the card count — **reversing** the 2026-09-10 "card counts
  hidden" pass; users see how many cards are in play, never a player count
- **api_smoke hardened**: hardcoded test cards are freed from any seeded bot
  (`free_card()`) before the human picks them, and the free picks are now
  asserted — the suite previously flaked when a `reset`-seeded bot happened to
  hold card 5/6/8/9 etc.; both `api_smoke.py` (all steps) and `smoke_test.py`
  pass from a fresh database
- Frontend rebuilt into `frontend/dist/` (assets `index-DS5ksLzo.js`,
  `index-DX-Jwy5g.css`)

### 2026-09-10 — Resilience pass · card count hidden from users · bot-ID saturation fix
- **Game loop never dies** (`game_loop.py`): `tick()` now wraps every room in
  its own `try/except` (`_tick_room`) so a transient DB error in one room
  can't stall the others; stale/missing timestamps are self-healed (a room
  stuck in `preparation` starts, `playing` force-calls or ends winless,
  `ended` resets) and a final `_heal_stale_room()` pass force-advances a room
  if a tick still fails — the game loop can no longer stop forever
- **Database self-heals** (`database.py`): `_session()` closes the connection
  and drops `self._conn` on any `sqlite3.DatabaseError` so the next call
  reconnects; `_repair_schema()` now probes twice (a transient lock can mimic
  corruption) before committing to the `.corrupt.bak` rebuild
- **Bot-ID saturation fixed** (`game_logic.py` + `migrate_db.py`): bot IDs are
  now `-random.randint(1_000_000, 999_999_999)` (~1 B values, up from
  ~1 M) with **200** attempts per slot and loud failure logs; every
  `migrate_db.py` run (incl. on deploy) **purges stale bot players** (negative
  IDs with no current `card_selections`) and clears stale `card_selections`
  when resetting a room — the old `bot_id exhausted after 100 tries,
  available=400` failure can no longer occur
- **Card count removed from all user screens**: the Mini App header (`Header.jsx`)
  and `App.jsx`'s paused banner; the bot's `/balance` no longer prints a cards
  line (bot.py). **Later reversed** — since 2026-09-11 the header shows the
  card count instead of the player count (see the 2026-09-11 changelog entry)
- Frontend rebuilt into `frontend/dist/` (assets `index-BZ9IxgGN.js`,
  `index-DX-Jwy5g.css`); commits `5340ff4` and `7b17c1b`

### 2026-09-10 — Standard-bingo rounds · bots-disabled companion rule
- **Removed the forced guaranteed bot win** (`BOT_GUARANTEED_WIN_AFTER`, legacy
  now): the game is **never shortened** to make a bot win — normal game
  duration and pacing are preserved on every difficulty
- **Standard bingo end**: after all 75 balls the round ends **winless** on
  every difficulty EXCEPT Impossible (5); only Impossible declares a ready bot
  the winner at 75/75 so a human can still never win
- **Bots disabled** (super-admin toggle): the room keeps exactly **ONE other
  player** holding a card — nobody plays alone — instead of the full 18-140
  fill; the toggle still only silences their auto-claims
- Bot fill unchanged otherwise: 18-140 players chosen by human count
  (Options 1/2/3, each bot holding a random 1-3 cards, capped to the pool),
  added gradually through the countdown toward the round's locked plan,
  male Ethiopian names, invisible to humans, super-admin-only review; fill
  identical on all difficulties
- Smoke tests updated (`api_smoke.py` sections 8 and 15c); `BOT_GUARANTEED_WIN_AFTER`
  kept in `config.py`/`.env.example` marked legacy for compatibility

---

## 17. Troubleshooting

| Symptom | Cause | Fix |
|---------|-------|-----|
| `No module named flask` | Dependencies not installed | Run `setup.bat` or `pip install -r requirements.txt` |
| Mini App shows "Frontend not built" | frontend/dist missing | Run `build_frontend.bat` |
| Bot says "Game server is offline" | server.py not running | Start `run_server.bat` first |
| `only https links are allowed` | Telegram requires HTTPS | Set up a tunnel (setup_tunnel.bat + run_tunnel.bat) |
| `409 Conflict: terminated by other getUpdates` | Two bot instances running | Close extra windows, run `stop_all.bat` |
| Bot replies Unauthorized to `/admin` | ID not in ADMIN_IDS | Check with @userinfobot, add to .env |
| Game stuck / no countdown | Stale game state | Run `python migrate_db.py` |
| Port 5000 already in use | Another process on port | Close it or set `SERVER_PORT` in .env |
| Cards show equal to players | Bot cards = 1 per bot | Already fixed: bots now hold cards from the round's plan (1-3 per bot) |
| Players and cards both show **0** everywhere | Corrupted DB — e.g. `malformed database schema (announcements) - invalid rootpage` makes EVERY query fail, so all counts collapse to 0 | AUTO-FIXED since this release: `Database._repair_schema()` detects the broken schema at startup, backs the file up as `<name>.corrupt.bak`, drops the invalid `sqlite_master` rows, rebuilds the file via the sqlite backup API and recreates the lost table. No manual action needed — just restart the server |
| Admin console shows users whose **credit is a date** / usernames that are just **numbers** | Player rows mangled by the Sep 2026 disk-full corruption — `credit` holds a timestamp string, `is_registered` is 10, or a bot's negative id leaked into a human row's username | AUTO-FIXED since 2026-09-12: `maintenance.py` (and `Database.clean_corrupt_player_rows`) deletes those rows on boot and every 6h, logging each removal to `activity_log`. Real accounts are never matched. If already loaded in your Prod DB, run one full pass: `python -c "import maintenance; maintenance.run(force_backup=True)"` |
| `Disk quota exceeded` / `cp: failed to close` / `SQL error: disk I/O error` (or the DB silently corrupts) | **Disk FULL** — the free tier has ~512 MB and the DB never pruned (grew to 117 MB); SQLite cannot commit on a full disk, which is what corrupted it | PROTECTED since 2026-09-12: auto-pruning (`PRUNE_HISTORY_DAYS`), daily backups and the `MAINTENANCE_MIN_FREE_MB` write-guard. To free space now: delete stale files (`db_rescue*`, old `.corrupt.bak`) and run `python -c "import maintenance; maintenance.run(force_backup=True)"` to prune + `wal_checkpoint` |
| Notifications not arriving | Webhook mode + job queue | Server drains `bot_notifications` table on each request |
| Bot fill logs `bot_id exhausted after 200 tries` | Players table accumulated stale bot rows over many rounds | Fixed in current release: bot-ID window widened to ~1 B values (200 attempts) AND `migrate_db.py` purges negative-ID players with no card selections on every startup/deploy |
| Room seems stuck (no balls / no countdown) | A stale or missing timestamp in `game_state` | Auto-fixed since this release: `tick()` is per-room `try/except`-wrapped and a `_heal_stale_room()` pass force-advances any room stuck with an invalid timestamp (playing → ends winless, preparation → starts, ended → resets) |
| Rooms outside `ROOM_BETS` sit frozen in `playing` forever | They are never ticked | Since 2026-09-12 `maintenance.py` purges `game_state` rows for unconfigured rooms (only when they hold no card selections) |

### Logs
- **Server**: Console output from `server.py` or `[server]` prefix in `run_prod.py`
- **Bot**: Console output from `bot.py` or `[bot]` prefix in `run_prod.py`
- **Game loop**: `game_loop` logger (round starts, winners, ball calls)

### Database Operations
```bash
# Run one full maintenance pass now: disk guard -> integrity -> daily backup
# -> corrupt-row cleanup -> stale-room purge -> prune -> WAL checkpoint.
python -c "import maintenance; maintenance.run(force_backup=True)"

# RECOVER a corrupted database (Sep 2026 incident playbook): builds
# db_rescue2/recovered.db from the live DB read-only, drops the garbage player
# rows (credit=timestamp / numeric usernames), verifies integrity and prints a
# human census. Swap it in ONLY when it says "VERIFIED":
#   python3 salvage_recover.py
#   cp bingo_bot.db bingo_bot.db.live-pre-swap        # keep the original
#   rm -f bingo_bot.db-wal bingo_bot.db-shm
#   cp db_rescue2/recovered.db bingo_bot.db
#   # press Reload (PythonAnywhere) / restart. Then delete the old files &
#   # bingo_bot.db.corrupt.bak to free space.

# Reset game state (also: clears stale card_selections, purges stale bot
# players so the bot-ID window stays free, applies the one-time difficulty→5
# migration). Idempotent — safe to run any time.
python migrate_db.py

# Smoke test (no Telegram needed)
python smoke_test.py

# API-only tests
python api_smoke.py

# Full database reset (DELETES ALL DATA)
rm bingo_bot.db
python migrate_db.py
```
