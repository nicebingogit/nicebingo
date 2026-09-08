# Nice Bingo — Technical Documentation

> Complete technical reference for recreating, modifying, or deploying the Nice Bingo system from scratch.

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
17. [Troubleshooting](#17-troubleshooting)

---

## 1. Project Overview

Nice Bingo is a real-time multiplayer Bingo game built as a **Telegram Mini App**. The Telegram bot serves as a launcher — tapping "Play" opens a full-screen interactive Bingo arena inside Telegram (or any browser). Players buy cards, watch balls being called, mark numbers, and claim BINGO when they complete a winning pattern. The winner takes 80% of the prize pool instantly.

### Key Features
- **Multi-room system**: Players choose between rooms with fixed bets (default: 10 / 20 / 30 ETB per card)
- **Real-time gameplay**: Balls called every 4 seconds via a server-side game loop
- **Bot players**: AI players fill rooms to 18-90 total cards, each holding 2-3 cards
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
│   │       ├── SuperAdminPanel.jsx  # Super admin controls
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
| `SUPER_ADMIN_IDS` | *(none)* | Comma-separated super admin IDs |
| `BOT_WEBHOOK` | `False` | Use webhook mode instead of polling |
| `SERVER_HOST` | `127.0.0.1` | Flask bind address |
| `SERVER_PORT` | `5000` | Flask bind port |
| `APP_URL` | `http://localhost:5000` | Public URL for the Mini App |
| `DB_PATH` | `bingo_bot.db` | SQLite database file path |
| `APP_CURRENCY` | `ETB` | Currency symbol |
| `ROOM_BETS` | `10,20,30` | Room bet amounts (comma-separated) |
| `MAX_CARDS_PER_PLAYER` | `3` | Max cards per player per round |
| `NEW_PLAYER_CREDIT` | `50` | Welcome bonus |
| `MIN_WITHDRAWAL` | `100` | Minimum withdrawal amount |
| `PRIZE_PERCENT` | `0.8` | Winner's share (80%) |
| `BOTS_CONTRIBUTE_TO_POOL` | `True` | Bot bets feed the prize pool |
| `PREPARATION_SECONDS` | `40` | Countdown between rounds |
| `CALL_INTERVAL_SECONDS` | `4` | Seconds between ball calls |
| `POST_GAME_RESET_SECONDS` | `15` | Winner screen duration |
| `TICK_INTERVAL` | `1` | Game loop tick interval (seconds) |
| `MIN_TOTAL_PLAYERS` | `18` | Minimum total cards in play |
| `MAX_TOTAL_PLAYERS` | `90` | Maximum total cards in play |
| `NUM_CARDS` | `400` | Pre-generated card pool size |
| `ANNOUNCE_NUMBERS` | `False` | Announce every ball in chat |
| `ANNOUNCE_ROUNDS` | `True` | Announce round start/winner in chat |
| `ADMIN_APPROVAL_RATE` | `0.9` | Share of deposit deducted from admin |
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
    room INTEGER PRIMARY KEY,            -- Room bet amount (10/20/30)
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
    bots_difficulty INTEGER DEFAULT 2,  -- 0=Easy, 5=Impossible
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
- **Preparation phase**: Adds bots gradually (1 per tick) if cards < MAX_TOTAL_PLAYERS
- **Playing phase**: Calls next ball when `next_call_time` arrives
- **Ended phase**: Resets round when `reset_time` arrives

**`start_round()` method:**
- Calls `ensure_minimum_players()` to fill the room with bots
- Creates a new `games` row
- Sets ball order (shuffled 75 balls)
- Transitions to "playing" phase

**`call_step()` method:**
- Pops the next ball from the persisted order
- Runs `_bot_claim_pass()` — bots may auto-claim BINGO
- Schedules the next ball call

**`claim_bingo()` method:**
- Verifies the player's card actually has a winning pattern
- If valid: pays the prize, ends the round
- If invalid: eliminates the player for this round (false BINGO)

**`handle_winner()` method:**
- Credits the prize to the winner
- Writes game history
- Distributes referral commissions
- Logs activity

**Bot claim system:**
- Bots claim based on difficulty level (0=Easy/never, 5=Impossible/instant)
- Each difficulty has a delay range (number of balls to wait after completing a pattern)
- Bots genuinely check their cards — they never false-claim

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
- `add_bot_player()` — Creates a bot with a human name, gives it 2-3 random cards
- `ensure_minimum_players()` — Fills the room to a random target of 18-90 total cards
- `player_breakdown()` — Returns counts of real vs bot players

**Bot naming:**
- Deterministic from user ID (stable across restarts)
- Ethiopian male first names + surnames
- Example: "Abel Girma", "Biruk Tesfaye"

### 9.5 `database.py` — SQLite Layer

**Key design decisions:**
- **One persistent connection per process** (serialized by RLock) — ~100x faster than opening per-operation on Windows
- **WAL journal mode** — allows concurrent readers (bot + server)
- **Auto-migration** — missing columns/tables are added on startup
- **INSERT OR IGNORE** — idempotent operations prevent double-charges

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

### 9.6 `config.py` — Configuration

All settings are read from environment variables with defaults. Helper functions:
- `_int(name, default)` — Parse integer from env
- `_float(name, default)` — Parse float from env
- `_bool(name, default)` — Parse boolean from env

---

## 10. Frontend Components

### 10.1 `App.jsx` — Main Component

The root component that manages:
- **Phase routing**: Shows `Registration` → `CardPicker` (preparation) → `BingoCard` + `CalledBoard` (playing) → `WinnerModal` (ended)
- **State polling**: Fetches `/api/game-state` every 2.5 seconds
- **User state**: Tracks selections, credit, registration status
- **Auto-play**: Toggles automatic daubing and BINGO claiming
- **Spectator mode**: Shows another player's card when no cards selected

### 10.2 `Header.jsx` — Top Bar

Shows brand name, room selector dropdown, credit chip, pool chip, settings button, admin/super-admin toggle buttons, and connection status dot.

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
3. Each card costs the room's fixed bet (10/20/30 ETB)
4. Bots gradually join (1 per tick), each taking 2-3 cards
5. When timer hits 0, `ensure_minimum_players()` fills to 18-90 total cards

### Playing Phase
1. Balls are called every 4 seconds from a shuffled pool of 75
2. Players' cards auto-daub matching numbers
3. Players can manually daub by tapping cells
4. Auto-play mode daubs and claims automatically
5. When a player completes a winning pattern, they press BINGO
6. Server verifies the card — valid claim pays the prize, false claim eliminates

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
- Bots are identified by **negative user IDs** (e.g., -12345)
- Each bot gets a **human-like Ethiopian name** (deterministic from ID)
- Each bot picks **2-3 random cards** from the available pool
- Bot bets feed the prize pool (controlled by `BOTS_CONTRIBUTE_TO_POOL`)

### Bot Filling Logic
1. During preparation, one bot is added per tick (every 1 second)
2. The tick checks if `cards_in_play < MAX_TOTAL_PLAYERS` (90)
3. When the round starts, `ensure_minimum_players()` fills to a random target of 18-90 cards
4. The target is always at least `current_cards + 2-5`, so bots always join

### Bot Claim System
Bots press BINGO like humans — only when a card actually has a complete pattern.

**Difficulty levels (0-5):**
| Level | Name | Delay Range | Behavior |
|-------|------|-------------|----------|
| 0 | Easy | Never | Bots never claim — humans always win |
| 1 | Normal | 5-8 balls | Very slow, rarely win |
| 2 | Medium | 3-5 balls | Default, human-like delay |
| 3 | Hard | 1-2 balls | Fast, often beats humans |
| 4 | Very Hard | 0-1 balls | Near-instant |
| 5 | Impossible | 0 balls | Instant — impossible to beat |

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

### Admin Credit System
- Admins use their **own player credit** (no separate admin balance)
- When a deposit is approved, the user gets the full amount
- The admin's credit is reduced by `ADMIN_APPROVAL_RATE` (90% of the deposit)
- When a withdrawal is approved, the admin's credit is increased by the same rate

### Payment Account Management
- Admins add payment accounts (bank name, account holder, account number)
- Only **online** admins' accounts are shown to users for deposits
- Super admin accounts are always available as fallback
- Admin is "online" while actively using the app (within `ADMIN_ONLINE_MINUTES`)

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
| POST | `/api/admin/bots/add` | Add bots to a room |
| POST | `/api/admin/bots/toggle` | Toggle bots on/off |
| GET | `/api/admin/bots` | Bot status and breakdown |
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
| Cards show equal to players | Bot cards = 1 per bot | Already fixed: bots now pick 2-3 cards each |
| Notifications not arriving | Webhook mode + job queue | Server drains `bot_notifications` table on each request |

### Logs
- **Server**: Console output from `server.py` or `[server]` prefix in `run_prod.py`
- **Bot**: Console output from `bot.py` or `[bot]` prefix in `run_prod.py`
- **Game loop**: `game_loop` logger (round starts, winners, ball calls)

### Database Operations
```bash
# Reset game state
python migrate_db.py

# Smoke test (no Telegram needed)
python smoke_test.py

# API-only tests
python api_smoke.py

# Full database reset (DELETES ALL DATA)
rm bingo_bot.db
python migrate_db.py
```
