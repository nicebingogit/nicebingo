# Bot Player System — Complete Documentation

> **Every change to the bot system must be reflected in this document.**  
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

- Have **Ethiopian male names** (e.g., "Abel Girma", "Biruk Tesfaye")
- Hold **1–3 cards** per bot (varies by difficulty option)
- **Buy cards** just like humans (bets feed the prize pool)
- **Press BINGO** when their card completes a winning pattern (delay varies by difficulty)
- Are **completely invisible** to human players — stored as ordinary `players` rows with negative user IDs
- Only the **super admin** can see them via `/api/admin/bots` and the `bots` table

**The room must NEVER show 0 players.** Even with 0 humans, bots fill the room and play a full round.

---

## 2. Algorithm

### Player Count Selection

The number of bots added to a game is determined by the number of **human** players currently in the room:

| Option | Human Players | Bots Added | Cards per Bot |
|--------|---------------|------------|---------------|
| **1** | 0–1 humans | 80–140 bots | 1 card each |
| **2** | 2–5 humans | 40–79 bots | 2 cards each |
| **3** | 6+ humans | 18–39 bots | 3 cards each |

**Example (Option 2):**
- 2 human players → 42 bots chosen randomly from 40–79
- Each bot gets 2 cards → 42 × 2 = 84 cards
- Random deduction of 5–15 cards → e.g., 9 deducted → 75 total bot cards
- Game starts with 42 bots holding 75 cards total

### Card Deduction

Every game randomly deducts **5–15 cards** from the total bot-card count. This is implemented in `game_logic.py:bot_card_plan()`:

```python
# Most bots keep cards_each cards, but a few keep one fewer.
# A bot never holds fewer than 1 card.
```

The deduction is capped so no bot drops below 1 card. For Option 1 (1 card each), no deduction applies.

### Implementation in Code

**`config.py`:**
```python
BOT_OPTIONS = (
    (1, 80, 140, 1),      # humans <= 1 → 80-140 bots, 1 card
    (5, 40, 79, 2),        # 2 <= humans <= 5 → 40-79 bots, 2 cards
    (None, 18, 39, 3),     # humans >= 6 → 18-39 bots, 3 cards
)
BOT_CARD_DEDUCTION = (5, 15)  # random deduction range
```

**`game_logic.py:bot_option_for_humans()`:**
```python
def bot_option_for_humans(self, humans: int) -> Tuple[int, int, int]:
    for max_humans, min_bots, max_bots, cards_each in config.BOT_OPTIONS:
        if max_humans is None or humans <= max_humans:
            return (min_bots, max_bots, cards_each)
    return (18, 39, 3)
```

**`game_logic.py:pick_bot_target()`:**
```python
def pick_bot_target(self, humans: int | None = None) -> int:
    lo, hi, _ = self.bot_option_for_humans(humans if humans is not None else 0)
    return random.randint(lo, hi)
```

---

## 3. Implementation Files

| File | Role |
|------|------|
| `config.py` | Bot option ranges, card deduction, pool contribution flag |
| `game_logic.py` | Bot naming, card plans, player creation, pattern detection |
| `game_loop.py` | Gradual filling, claim delays, impossible guard, round management |
| `database.py` | `bots` table, `card_selections` for bot accounts, migrations |
| `server.py` | API responses (hides bot info from non-super-admins) |
| `wsgi.py` | PythonAnywhere entry point (ensures cards seeded + bots filled) |
| `migrate_db.py` | Database migration + card seeding on deploy |

---

## 4. Bot Naming

Bot names are **deterministic** based on the negative user ID, so the same bot keeps the same name across restarts.

**`game_logic.py:bot_name()`:**
```python
def bot_name(user_id: int) -> str:
    idx = abs(int(user_id))
    first = BOT_MALE_FIRST_NAMES[(idx * 7 + 3) % len(BOT_MALE_FIRST_NAMES)]
    last = BOT_LAST_NAMES[(idx * 5 + idx // len(BOT_MALE_FIRST_NAMES)) % len(BOT_LAST_NAMES)]
    return f"{first} {last}"
```

**Name pools:**
- `BOT_MALE_FIRST_NAMES`: 90+ Ethiopian male first names (Abel, Abebe, Amanuel, Biruk, ...)
- `BOT_LAST_NAMES`: 12 Ethiopian surnames (Tadesse, Alemu, Bekele, Tesfaye, ...)

**Examples:** "Abel Girma", "Biruk Tesfaye", "Ermias Worku", "Kirubel Haile"

---

## 5. Card Allocation

Each bot's card count comes from the round's **card plan** (`game_logic.py:bot_card_plan()`):

```python
def bot_card_plan(self, bot_count: int, cards_each: int | None = None) -> List[int]:
    # Returns a list of per-bot card counts
    # Most bots get cards_each, some get one fewer
    # Total = bot_count * cards_each - random_deduction(5-15)
    # Every bot keeps at least 1 card
```

**Example (Option 2, 42 bots):**
```
cards_each = 2
deduction = random.randint(5, 15)  # e.g., 9
total = 42 * 2 - 9 = 75 cards
Plan: 33 bots × 2 cards + 9 bots × 1 card = 75
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
Start Round → Final top-up to plan target
     ↓
Playing tick (every 1s) → Self-healing fill (up to 8/tick)
```

### Code Flow

1. **`reset_round()`** → `_ensure_bot_players(room, cap=8)` — immediate seed
2. **`tick()` (preparation)** → `_add_prep_bots(room)` → `_ensure_bot_players(room, cap=8)`
3. **`start_round()`** → `_bot_plan(room)` → `_ensure_bot_players(room)` — full fill
4. **`tick()` (playing)** → `_ensure_bot_players(room, cap=8)` — self-healing

### Self-Healing

Even if a round entered play without bots (e.g., stale DB, WSGI reload), the ticker adds up to 8 bots per tick during the playing phase. The room **never** stays empty.

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
- Game duration is **never shortened** to make a bot win
- Normal pacing preserved

---

## 9. Database Schema

### `bots` Table (Persistent Bot Accounts)

```sql
CREATE TABLE IF NOT EXISTS bots (
    user_id    INTEGER PRIMARY KEY,   -- Negative integer (e.g., -12345)
    username   TEXT,                  -- Ethiopian male name
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
- **Player names**: Ethiopian male names for bots, real names for humans
- **No bot indicators**: Bots are indistinguishable from humans

The **Super Admin Panel** has:
- Add Bots button
- Bot toggle (on/off)
- Difficulty selector (0–5)
- Bot count display (separate from human count)

---

## 12. Deployment Notes

### PythonAnywhere

1. **WSGI entry point**: `wsgi.py` runs `migrate_db.main()` → `server.loop.start()` → bot webhook
2. **Card seeding**: `migrate_db.main()` seeds 400 cards from `cards_data.py`
3. **Bot filling**: `GameLoop.start()` fills every room with bots immediately
4. **Post-boot fill**: Retries every 5 seconds for rooms with 0 bots
5. **Database corruption**: `_repair_schema()` auto-heals corrupted DB; `_create_tables_individually()` as fallback

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
    (1, 80, 140, 1),      # humans <= 1 → 80-140 bots, 1 card
    (5, 40, 79, 2),        # 2 <= humans <= 5 → 40-79 bots, 2 cards
    (None, 18, 39, 3),     # humans >= 6 → 18-39 bots, 3 cards
)
BOT_CARD_DEDUCTION = (5, 15)
BOT_CARDS_BY_COUNT = ((80, 1), (40, 2), (18, 3))
BOTS_CONTRIBUTE_TO_POOL = True
```

### Step 3: Bot Naming (`game_logic.py`)

```python
BOT_MALE_FIRST_NAMES = ["Abel", "Abebe", "Amanuel", ...]  # 90+ names
BOT_LAST_NAMES = ["Tadesse", "Alemu", "Bekele", ...]       # 12 names

def bot_name(user_id: int) -> str:
    idx = abs(int(user_id))
    first = BOT_MALE_FIRST_NAMES[(idx * 7 + 3) % len(BOT_MALE_FIRST_NAMES)]
    last = BOT_LAST_NAMES[(idx * 5 + idx // len(BOT_MALE_FIRST_NAMES)) % len(BOT_LAST_NAMES)]
    return f"{first} {last}"
```

### Step 4: Bot Creation (`game_logic.py`)

```python
def add_bot_player(self, room, cards_per_bot=None):
    # 1. Get available cards (not taken by anyone in this room)
    # 2. Generate a unique negative user_id
    # 3. Create player record with Ethiopian male name
    # 4. Select random cards from available pool
    # 5. Return {"bot_id": -NNN, "cards": N}
```

### Step 5: Bot Filling (`game_loop.py`)

```python
def _ensure_bot_players(self, room, cap=None):
    # 1. Check if cards exist (defer if 0 cards)
    # 2. Compute target from human count (Option 1/2/3)
    # 3. Build card plan (cards per bot with deduction)
    # 4. Add bots one by one until target reached
    # 5. Persist bot accounts for super admin view
```

### Step 6: Gradual Filling

```python
def tick(self):
    if phase == "preparation":
        self._add_prep_bots(room, state)  # cap=8 per tick
    elif phase == "playing":
        self._ensure_bot_players(room, cap=8)  # self-healing
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

---

## Summary of Key Principles

1. **Room never shows 0 players** — bots fill immediately on boot, gradually during prep, and self-heal during play
2. **Bots are invisible** — stored as regular players with Ethiopian male names, negative IDs hidden from frontend
3. **Option-based filling** — 0–1 humans → 80–140 bots × 1 card; 2–5 → 40–79 × 2; 6+ → 18–39 × 3
4. **Card deduction** — 5–15 cards randomly removed from total bot cards each round
5. **Normal game duration** — no shortened rounds to make bots win (except Impossible)
6. **Impossible mode** — humans can NEVER win; ball machine reordered to prevent human completion
7. **Standard bingo on other difficulties** — normal pacing, winner only on valid BINGO claim
8. **All difficulty levels use the same bot fill** — only claiming behavior differs

---

*This document must be updated with every change to the bot system.*  
update-in-every-change: yes
