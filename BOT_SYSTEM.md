# Bot Player System — Complete Documentation

> **Every change to the bot system must be reflected in this document.**  
> **→ Next programmer or AI: after ANY change, update all docs in the same change.**  
> update-in-every-change: yes

---

## Table of Contents

1. [Overview](#1-overview)
2. [Algorithm](#2-algorithm)
3. [Implementation Files](#3-implementation-files)
4. [Bot Naming](#4-bot-naming)
5. [Card Allocation](#5-card-allocation)
6. [Gradual Bot Filling](#6-gradual-bot-filling)
7. [Difficulty Levels](#7-difficulty-levels)
8. [Impossible Mode (Difficulty 5)](#8-impossible-mode-difficulty-5)
9. [Database Schema](#9-database-schema)
10. [API Endpoints](#10-api-endpoints)
11. [Frontend Display](#11-frontend-display)
12. [Deployment Notes](#12-deployment-notes)
13. [Troubleshooting](#13-troubleshooting)
14. [Recreating the Bot System](#14-recreating-the-bot-system)

---

## 1. Overview

The bot system fills every game room with AI-controlled "players" that behave identically to human players. Bots:

- Have **human-like names** — 20% Oromo / 20% Amhara / 10% Tigray / 30% general Ethiopian male / 5% Ethiopian female / 10% East African / 5% international nicknames (e.g., "Guyo Tadesse", "Lemma Girma", "Merhawi Haile", "Abel Girma", "Hiwot Girma", "Baraka", "HotShot")
- Hold **1–3 cards** per bot (varies by difficulty option)
- **Buy cards** just like humans (bets feed the prize pool)
- **Press BINGO** when their card completes a winning pattern (delay varies by difficulty)
- Are **completely invisible** to human players — stored as ordinary `players` rows with negative user IDs
- Only the **super admin** can see them via `/api/admin/bots` and the `bots` table

**The room must NEVER show 0 players.** Even with 0 humans, bots fill the room and play a full round.

---

## 2. Algorithm

### Player Count Selection

Both the number of bots and the cards each bot holds are re-rolled **every round** and locked for that round (the stored plan survives restarts mid-round; the next round draws a fresh one). The bot count is determined by the number of **human** players currently in the room:

| Option | Human Players | Bots Added | Cards per Bot |
|--------|---------------|------------|---------------|
| **1** | 0–1 humans | 80–140 bots | 1–3 cards each |
| **2** | 2–5 humans | 40–79 bots | 1–3 cards each |
| **3** | 6+ humans | 18–39 bots | 1–3 cards each |

**Example (Option 2):**
- 2 human players → 42 bots chosen randomly from 40–79
- Each bot gets a random 1–3 cards → e.g. 42 bots hold ~94 cards total
- The total is clamped to the card pool (400), so the deck is never exhausted

### Card Randomization

Every bot gets a **random** card count inside the option's 1–3 range
(`game_logic.py:bot_card_plan()`, clamped so the sum never exceeds the pool
and every bot keeps at least one card). Because the plan is rolled once per
round and locked, a game's size (players and cards) differs every round —
the count never creeps to the same ceiling each game.

### Implementation in Code

**`config.py`:**
```python
BOT_OPTIONS = (
    (1, 80, 140, 1, 3),   # humans <= 1 -> 80-140 bots, 1-3 cards each
    (5, 40, 79, 1, 3),    # 2 <= humans <= 5 -> 40-79 bots, 1-3 cards each
    (None, 18, 39, 1, 3), # humans >= 6 -> 18-39 bots, 1-3 cards each
)
# Each tuple: (max_humans, min_bots, max_bots, min_cards, max_cards)
```

**`game_logic.py:bot_option_for_humans()`:**
```python
def bot_option_for_humans(self, humans: int) -> Tuple[int, int, int, int]:
    for max_humans, min_bots, max_bots, min_cards, max_cards in config.BOT_OPTIONS:
        if max_humans is None or humans <= max_humans:
            return (min_bots, max_bots, min_cards, max_cards)
    return (18, 39, 1, 3)
```

**`game_logic.py:pick_bot_target()`:**
```python
def pick_bot_target(self, humans: int | None = None) -> int:
    lo, hi, _, _ = self.bot_option_for_humans(humans if humans is not None else 0)
    return random.randint(lo, hi)
```

**`game_loop.py` — the per-round lock (`_bot_plan`, `_load_plan`, `_clear_plan`):**
```python
def _bot_plan(self, room: int = 30) -> Tuple[int, int, int, list]:
    stored = self._load_plan(room)      # persisted in the settings table
    if stored is not None:              # SAME plan for the whole round
        return (stored["bots"], stored["min_cards"],
                stored["max_cards"], stored["counts"])
    ...  # roll a fresh random plan once, persist it, fill toward it
```

---

## 3. Implementation Files

| File | Role |
|------|------|
| `config.py` | Bot option ranges (bots + cards 1-3), pool contribution flag |
| `game_logic.py` | Bot naming, card plans, player creation, pattern detection |
| `game_loop.py` | Gradual filling, claim delays, impossible guard, round management |
| `database.py` | `bots` table, `card_selections` for bot accounts, migrations |
| `server.py` | API responses (hides bot info from non-super-admins) |
| `wsgi.py` | PythonAnywhere entry point (ensures cards seeded + bots filled) |
| `migrate_db.py` | Database migration + card seeding on deploy |

---

## 4. Bot Naming

Bot names are **deterministic** based on the negative user ID, so the same bot
keeps the same name across restarts. Every 100 consecutive IDs produce exactly
the same mix: **20% Oromo / 20% Amhara / 10% Tigray / 30% general Ethiopian
male / 5% Ethiopian female / 10% East African nickname / 5% international
nickname**.

**`game_logic.py:bot_name()`:**
```python
def bot_name(user_id: int) -> str:
    idx = abs(int(user_id))
    mix = (idx * 31 + 17) % 100
    if mix < 20:  # 20% Oromo male
        return _ethiopian_full_name(BOT_OROMO_FIRST_NAMES, idx)
    if mix < 40:  # 20% Amhara male
        return _ethiopian_full_name(BOT_AMHARA_FIRST_NAMES, idx)
    if mix < 50:  # 10% Tigray male
        return _ethiopian_full_name(BOT_TIGRAY_FIRST_NAMES, idx)
    if mix < 80:  # 30% Ethiopian male — all regions
        return _ethiopian_full_name(BOT_MALE_FIRST_NAMES, idx)
    if mix < 85:  # 5% Ethiopian female
        return _ethiopian_full_name(BOT_FEMALE_FIRST_NAMES, idx)
    if mix < 95:  # 10% East African nickname
        return BOT_EAST_AFRICAN_NICKNAMES[(idx * 13 + 7) % len(BOT_EAST_AFRICAN_NICKNAMES)]
    return BOT_NICKNAMES[(idx * 13 + 7) % len(BOT_NICKNAMES)]  # 5% international
```

`_ethiopian_full_name(pool, idx)` draws the first name from the given pool and
the surname `BOT_LAST_NAMES[(idx * 5 + idx // len(pool)) % len(BOT_LAST_NAMES)]`
— both derived from the ID, so the full name is stable across restarts.

**Name pools (disjoint first-name pools → each bot's group is unambiguous):**
- `BOT_OROMO_FIRST_NAMES`: 32 Oromo male first names (Addise, Bayisa, Boru, Chala, Guyo, Kumsa, Tolu, ...)
- `BOT_AMHARA_FIRST_NAMES`: 32 Amhara male first names (Admasu, Ayele, Bekele, Lemma, Mulat, Zewdu, ...)
- `BOT_TIGRAY_FIRST_NAMES`: 32 Tigray male first names (Abera, Berhe, Girmay, Hadush, Merhawi, Tesfay, ...)
- `BOT_MALE_FIRST_NAMES`: 90+ Ethiopian male first names, ALL regions (Abel, Abebe, Amanuel, Biruk, ...)
- `BOT_FEMALE_FIRST_NAMES`: ~30 Ethiopian female first names
- `BOT_EAST_AFRICAN_NICKNAMES`: 22 East African (Swahili-flavoured) nicknames (Baraka, Zuri, Simba, Nuru, ...)
- `BOT_NICKNAMES`: 30 international nicknames (BigShot, RoyalFlush, MoneyMaster, NumberNinja, ...)
- `BOT_LAST_NAMES`: 12 Ethiopian surnames (Tadesse, Alemu, Bekele, Tesfaye, ...)

**Examples:** "Guyo Tadesse", "Lemma Girma", "Merhawi Haile", "Abel Girma",
"Hiwot Girma", "Baraka", "HotShot"

---

## 5. Card Allocation

Each bot's card count comes from the round's **card plan** (`game_logic.py:bot_card_plan()`):

```python
def bot_card_plan(self, bot_count: int, min_cards: int | None = None,
                  max_cards: int | None = None, card_cap: int = 400) -> List[int]:
    # Returns a list of per-bot card counts, rolled fresh each round
    # Each bot gets random.randint(min_cards, max_cards) cards
    # The sum is clamped to card_cap; every bot keeps at least min_cards (>=1)
```

**Example (Option 2, 42 bots, 1-3 cards each, cap 400):**
```
each = random.randint(1, 3)         # e.g., 42 bots, random 1..3 cards each
total = sum(plan)                   # e.g., ~90 bot cards in the room
# clamped so the deck (400 cards) is never exhausted
```

**Card assignment** happens in `game_logic.py:add_bot_player()`:
```python
def add_bot_player(self, room: int = 30, cards_per_bot: int | None = None) -> Optional[Dict]:
    all_cards = self.db.get_all_cards()
    taken = {s["card_id"] for s in self.db.get_all_selections(room)}
    available = [c for c in all_cards if c["id"] not in taken]
    # ... pick random cards from available pool
    # Returns {"bot_id": -NNN, "cards": N} or None if no cards available
```

---

## 6. Gradual Bot Filling

Bots are **never added all at once**. They join gradually during the preparation countdown:

### Filling Timeline

```
Reset Round → Seed batch (up to 8 bots)
     ↓
Preparation tick (every 1s) → Add up to 8 bots/tick
     ↓
Start Round → Final top-up to plan target (last fill — the
     ↓         roster is then FROZEN for the whole round)
Playing tick (every 1s) → Call balls only — NO bot fill (player
                         count and prize pool are locked mid-round)
```

### Code Flow

1. **`reset_round()`** → `_ensure_bot_players(room, cap=8)` — immediate seed
2. **`tick()` (preparation)** → `_add_prep_bots(room)` → `_ensure_bot_players(room, cap=8)`
3. **`start_round()`** → `_bot_plan(room)` → `_ensure_bot_players(room)` — full fill
4. **`tick()` (playing)** → calls balls only — **no** `_ensure_bot_players` (roster frozen)

### Self-Healing

The fill is **self-healing up through `start_round()`** — even a reloaded/headless
room tops-up during preparation until the round starts. Once the round is
**playing** the roster is FROZEN: `start()`, `_post_boot_fill()` and the ticker
all skip `playing` rooms, so the player count and prize pool never change
mid-round. The full fill always happens one final time in `start_round()` while
the room is still in preparation.

### Post-Boot Fill

On PythonAnywhere, the WSGI module may load before the database is fully ready. A **post-boot fill job** runs every 5 seconds for the first ~30 seconds after boot, retrying bot fills for any room with 0 bots:

```python
def _post_boot_fill(self) -> None:
    # Retries bot fill for rooms with 0 bots
    # Stops itself when all rooms have at least 1 bot
```

---

## 7. Difficulty Levels

Bot **filling** is identical on all difficulty levels — the same 18–140 bots join with 1–3 cards each. The **only difference** is how bots claim BINGO:

| Level | Name | Claim Delay | Behavior |
|-------|------|-------------|----------|
| 0 | Easy | Never | Bots never claim — humans always win if they claim |
| 1 | Normal | 5–8 balls | Very slow, rarely win |
| 2 | Medium | 3–5 balls | Balanced, human-like delay |
| 3 | Hard | 1–2 balls | Fast, often beats humans |
| 4 | Very Hard | 0–1 balls | Near-instant |
| 5 | **Impossible** | 0 balls | Instant — **default**; humans can NEVER win |

**Default difficulty: 5 (Impossible)**

The delay is the number of balls to wait **after** the pattern is completed before claiming. This gives other players a chance to claim first on lower difficulties.

### Implementation

**`game_loop.py:_bot_claim_pass()`:**
```python
_DIFFICULTY_DELAY = {
    0: None,         # never claim
    1: (5, 8),       # very slow
    2: (3, 5),       # default human-like
    3: (1, 2),       # fast
    4: (0, 1),       # near-instant
    5: (0, 0),       # instant — impossible to beat
}
```

---

## 8. Impossible Mode (Difficulty 5)

On Impossible difficulty, **no human can ever win**. This is enforced by multiple mechanisms:

### Pre-Call Guard (`_impossible_guard`)

Before each ball is called, the system checks if drawing that ball would complete a **human** card. If so, the ball machine is reordered so the next ball completes a **bot** card instead:

```python
def _impossible_guard(self, room: int = 30) -> list | None:
    # 1. Check if next ball completes a human pattern
    # 2. If yes, find a ball that completes a bot pattern
    # 3. Bring that ball to the front of the queue
    # 4. If no safe ball exists, end the round winless
```

### Human Claim Interception

When a human presses BINGO on Impossible, the win is handed to a ready bot instead:

```python
def claim_bingo(self, user_id, card_id, room):
    human_impossible = self.db.get_bots_difficulty(room) == 5 and user_id > 0
    if human_impossible:
        _number, winner = self._force_bot_win(room)
        if winner is not None:
            return {"ok": True, "winner": winner, "human": False}
```

### 75/75 Backstop

When all 75 balls have been called on Impossible, a ready bot is declared the winner:

```python
if not self.db.get_ball_order(room):
    if self.db.get_bots_difficulty(room) == 5:
        winner = self._bot_win_claim(room)
        if winner is not None:
            return {"winner": winner}
    self.end_round_no_winner(room)
```

### Standard Bingo on Other Difficulties

On difficulties 0–4, the game plays like **standard bingo**:
- Winner only declared when a player presses BINGO
- Round ends winless after all 75 balls if nobody claims
- **Minimum 10 balls**: no valid BINGO (human OR bot) is accepted before
  `MIN_CALLS_BEFORE_WIN` (default 10) balls are called — `claim_bingo()` returns
  a `too_soon` refusal (no elimination) and `_bot_claim_pass()` re-schedules the
  bot to claim on a later ball instead of dropping it
- Game duration is **never shortened** to make a bot win
- Normal pacing preserved

---

## 9. Database Schema

### `bots` Table (Persistent Bot Accounts)

```sql
CREATE TABLE IF NOT EXISTS bots (
    user_id    INTEGER PRIMARY KEY,   -- Negative integer (e.g., -12345)
    username   TEXT,                  -- human-like bot name (20/20/10/30/5/10/5 mix — see §4)
    cards      INTEGER DEFAULT 0,    -- Card count
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
```

### `players` Table (Bot Accounts)

Bots are stored as regular players with **negative user IDs**:

```sql
-- Bot: user_id = -12345, username = "Abel Girma", credit = 0
INSERT INTO players (user_id, username, credit) VALUES (-12345, 'Abel Girma', 0);
```

### `card_selections` Table (Bot Cards)

Bot card selections are identical to human selections:

```sql
-- Bot -12345 holds card "C042" in room 10
INSERT INTO card_selections (user_id, card_id, room, bet_amount)
VALUES (-12345, 'C042', 10, 10);
```

---

## 10. API Endpoints

### Super Admin Only

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/api/admin/bots` | GET | Bot status and breakdown |
| `/api/admin/bots/add` | POST | Manually add bots to room |
| `/api/admin/bots/toggle` | POST | Toggle bots on/off |
| `/api/superadmin/game/add-bots` | POST | Add bots (super admin) |
| `/api/superadmin/game/bots-difficulty` | POST | Set difficulty (0–5) |
| `/api/superadmin/game/bots-toggle` | POST | Toggle bots on/off |

### Game State (Hidden from Non-Super-Admins)

The `/api/game-state` response hides bot details from regular players:

```python
# Only included for super admins:
if user_id in config.SUPER_ADMIN_IDS:
    payload["bots_players"] = logic.player_breakdown(room)["bots"]
    payload["bots_enabled"] = bool(state.get("bots_enabled", 1))
    payload["bots_difficulty"] = int(state.get("bots_difficulty", 5))
```

Regular players see `total_players` (humans + bots combined) — they never learn about bots.

---

## 11. Frontend Display

The Mini App shows:
- **"Players"**: `total_players` (humans + bots combined) — never shows 0
- **"Cards in play"**: Total selections (human + bot cards)
- **Player names**: human-like bot names (20% Oromo / 20% Amhara / 10% Tigray / 30% general Ethiopian male / 5% Ethiopian female / 10% East African / 5% international nicknames), real names for humans
- **No bot indicators**: Bots are indistinguishable from humans

The **Super Admin Panel** has:
- Add Bots button
- Bot toggle (on/off)
- Difficulty selector (0–5)
- Bot count display (separate from human count)

---

## 12. Deployment Notes

### PythonAnywhere

1. **WSGI entry point**: `wsgi.py` runs `migrate_db.main()` → `server.loop.start()` → bot webhook → `maintenance.run()` + interval job
2. **Card seeding + cleanup**: `migrate_db.main()` seeds 400 cards and clears stale `card_selections` when resetting rooms
3. **Bot filling**: `GameLoop.start()` fills every room with bots immediately
4. **Post-boot fill**: Retries every 5 seconds for rooms with 0 bots
5. **Database corruption**: `_repair_schema()` auto-heals corrupted DB (with double-probe to avoid false positives); `_create_tables_individually()` as fallback
6. **Auto housekeeping (`maintenance.py`)**: on boot + every `MAINTENANCE_INTERVAL_MIN` (6 h) — low-disk write-guard, integrity probe, **daily backup snapshot**, cleanup of corrupted player rows (the "credit shows a date / users are just numbers" garbage), purge of stuck rooms no longer in `ROOM_BETS`, pruning of old games/activity/called balls (`PRUNE_HISTORY_DAYS`), and a WAL TRUNCATE checkpoint so trimmed space returns to the disk. `/health` also shows `game_loop_heartbeat` so you can see the loop is alive.

### After `git pull`

```bash
cd ~/nicebingo
git pull
# Press Reload on PythonAnywhere web app page
```

The WSGI module is reloaded, which re-runs `migrate_db.main()` and `server.loop.start()`.

### Environment Variables

```
BOT_WEBHOOK=1          # Required for PythonAnywhere
SERVER_HOST=0.0.0.0    # Required for PythonAnywhere
APP_URL=https://<username>.pythonanywhere.com
SUPER_ADMIN_IDS=...    # Required — no hardcoded super-admins since 2026-09-12
DB_BACKUP_DIR=/home/<username>/bingo_backups   # daily backups outside the code folder
```

---

## 13. Troubleshooting

| Symptom | Cause | Fix |
|---------|-------|-----|
| 0 Players, 0 Cards | Database corrupted or cards not seeded | Check Error log; delete `bingo_bot.db` and Reload |
| 0 Players, Cards exist | Bot fill failed (card pool exhausted or DB error) | Check logs for "bot fill" messages; ensure `NUM_CARDS=400` |
| Bots not claiming | Difficulty set to 0 (Easy) | Set difficulty to 5 via super admin panel |
| Humans winning on Impossible | Impossible guard not active | Ensure `bots_difficulty=5` in game_state table |
| WSGI module stale | PythonAnywhere cached old code | Press Reload; verify with `/health` endpoint |
| `NameError: added` | Old code without the fix | Pull latest code and Reload |

### Health Check

Visit `https://<username>.pythonanywhere.com/health`:
```json
{
  "status": "ok",
  "game_loop": true,
  "database": true,
  "bot": {"webhook_mode": true, "webhook_registered": true}
}
```

---

## 14. Recreating the Bot System

To recreate the entire bot system from scratch:

### Step 1: Database Tables

```sql
-- bots table (persistent bot accounts)
CREATE TABLE bots (
    user_id INTEGER PRIMARY KEY,
    username TEXT,
    cards INTEGER DEFAULT 0,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- players table (bots use negative IDs)
-- No special schema needed — bots are regular players with negative user_id

-- card_selections table (bots select cards like humans)
-- No special schema needed — same table as human selections
```

### Step 2: Config (`config.py`)

```python
BOT_OPTIONS = (
    (1, 80, 140, 1, 3),   # humans <= 1 -> 80-140 bots, 1-3 cards each
    (5, 40, 79, 1, 3),    # 2 <= humans <= 5 -> 40-79 bots, 1-3 cards each
    (None, 18, 39, 1, 3), # humans >= 6 -> 18-39 bots, 1-3 cards each
)
# Each tuple: (max_humans, min_bots, max_bots, min_cards, max_cards)
BOTS_CONTRIBUTE_TO_POOL = True
```

### Step 3: Bot Naming (`game_logic.py`)

```python
# Seven disjoint pools: regional male, general male, female, and nicknames
BOT_OROMO_FIRST_NAMES = ["Addise", "Bayisa", "Boru", "Chala", ...]   # 32 names
BOT_AMHARA_FIRST_NAMES = ["Admasu", "Ayele", "Bekele", "Lemma", ...] # 32 names
BOT_TIGRAY_FIRST_NAMES = ["Abera", "Berhe", "Girmay", "Hadush", ...] # 32 names
BOT_MALE_FIRST_NAMES = ["Abel", "Abebe", "Amanuel", ...]             # 90+ names
BOT_LAST_NAMES = ["Tadesse", "Alemu", "Bekele", ...]                 # 12 names

def bot_name(user_id: int) -> str:
    idx = abs(int(user_id))
    mix = (idx * 31 + 17) % 100
    if mix < 20:  return _ethiopian_full_name(BOT_OROMO_FIRST_NAMES, idx)
    if mix < 40:  return _ethiopian_full_name(BOT_AMHARA_FIRST_NAMES, idx)
    if mix < 50:  return _ethiopian_full_name(BOT_TIGRAY_FIRST_NAMES, idx)
    if mix < 80:  return _ethiopian_full_name(BOT_MALE_FIRST_NAMES, idx)
    if mix < 85:  return _ethiopian_full_name(BOT_FEMALE_FIRST_NAMES, idx)
    if mix < 95:  return BOT_EAST_AFRICAN_NICKNAMES[(idx * 13 + 7) % len(BOT_EAST_AFRICAN_NICKNAMES)]
    return BOT_NICKNAMES[(idx * 13 + 7) % len(BOT_NICKNAMES)]        # international
```

### Step 4: Bot Creation (`game_logic.py`)

```python
def add_bot_player(self, room, cards_per_bot=None):
    # 1. Get available cards (not taken by anyone in this room)
    # 2. Generate a unique negative user_id
    # 3. Create player record with human-like bot name (see Section 4)
    # 4. Select random cards from available pool
    # 5. Return {"bot_id": -NNN, "cards": N}
```

### Step 5: Bot Filling (`game_loop.py`)

```python
def _ensure_bot_players(self, room, cap=None):
    # 1. Check if cards exist (defer if 0 cards)
    # 2. Load the round's LOCKED plan (bot count + per-bot cards), rolling
    #    and persisting it once per round if not present
    # 3. Add bots one by one until the locked target is reached
    # 5. Persist bot accounts for super admin view
```

### Step 6: Gradual Filling

```python
def tick(self):
    if phase == "preparation":
        self._add_prep_bots(room, state)  # cap=8 per tick
    elif phase == "playing":
        pass  # roster FROZEN — no bot fill mid-round
```

### Step 7: Difficulty / Claim System (`game_loop.py`)

```python
_DIFFICULTY_DELAY = {
    0: None,         # never claim
    1: (5, 8),       # very slow
    2: (3, 5),       # balanced
    3: (1, 2),       # fast
    4: (0, 1),       # near-instant
    5: (0, 0),       # instant (impossible)
}

def _bot_claim_pass(self, room):
    # 1. Find bots with winning cards
    # 2. Schedule delayed claim based on difficulty
    # 3. Claim when delay elapsed
```

### Step 8: Impossible Guard (`game_loop.py`)

```python
def _impossible_guard(self, room):
    # 1. Check if next ball completes human pattern
    # 2. If yes, reorder so bot completes first
    # 3. If no safe ball, end round winless

def _force_bot_win(self, room):
    # When human claims on Impossible:
    # 1. Find a bot with a winning card
    # 2. Declare that bot the winner
    # 3. Human never knows about bots
```

### Step 9: Frontend Integration (`server.py`)

```python
def _state_payload(user_id, room):
    # total_players = humans + bots (shown to everyone)
    # bots_players, bots_enabled, bots_difficulty (super admin only)
```

## Data Retention (run-forever storage)

Only **human** history is recorded, and BOT rows are automatically cleaned up
so the database never grows without bound:

- **`game_history` is human-only by design** (`game_loop._write_history`
  filters `user_id > 0`) — bots never get a history row.
- **`transactions` are human-only** — deposits/withdrawals/reviews; bot bets
  only feed the in-game prize pool and are never written as transactions.
- **Bot accounts are retired automatically** (`Database.prune_bot_history`):
  every round invents ~80–140 brand-new random negative-id accounts plus one
  `bots` roster row each. After `BOT_HISTORY_KEEP_GAMES` (default 10, 5–20
  recommended) finished games, rows older than the newest N games are deleted:
  bot account rows (only when not actively holding a card), their orphaned
  roster rows, any stray negative-id `game_history`, and bot
  `round_eliminations` outside the last N games.
- Runs **after every finished round** and **on every maintenance pass**
  (`maintenance.py`), then a `wal_checkpoint(TRUNCATE)` returns the freed
  space to the disk — so the file stays small and the game can run forever.
- Human accounts, human `game_history`, `transactions`, `referrals` and
  commissions are **never touched** by this cleanup.

---

## Summary of Key Principles

1. **Room never shows 0 players** — bots fill immediately on boot, gradually during prep, and the final top-up happens in `start_round()` (the roster is then frozen until the next countdown)
2. **Bots are invisible** — stored as regular players with human-like names (20% Oromo / 20% Amhara / 10% Tigray / 30% general Ethiopian male / 5% Ethiopian female / 10% East African / 5% international nicknames), negative IDs hidden from frontend
3. **Option-based filling** — 0–1 humans → 80–140 bots; 2–5 → 40–79; 6+ → 18–39
4. **Random card spread** — each bot draws a random 1–3 cards every round, capped to the pool; no fixed "cards each" tiers
5. **Minimum 10 balls before any win** — `MIN_CALLS_BEFORE_WIN` (default 10): an early valid claim (human or bot) is gently deferred, never a punishment; false BINGO still eliminates at any count; the Impossible bot-win backtrack respects the minimum too
6. **Normal game duration** — no shortened rounds to make bots win (except Impossible)
7. **Impossible mode** — humans can NEVER win; ball machine reordered to prevent human completion
8. **Standard bingo on other difficulties** — normal pacing, winner only on valid BINGO claim
9. **All difficulty levels use the same bot fill** — only claiming behavior differs

---

*This document must be updated with every change to the bot system.*  
update-in-every-change: yes
