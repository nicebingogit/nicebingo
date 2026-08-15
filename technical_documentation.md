# 🎰 Bingo Royale — Technical Documentation

This document describes the current system. It is kept up to date with every
change so that any developer or AI can refer to it at any time.

> **Latest update:** **bots play & win too** — bots are included in every room
> by default (all **human male names**), they fill the room during
> preparation, and they **press BINGO like humans** (with a short random
> delay), so other players genuinely win rounds; the winner modal now **draws
> the winning pattern on the winner's card** (glowing gold cells) for **all**
> players; 3-card play gets slightly bigger cards that never overflow the
> screen; the winning moment always vibrates. Built on top of claim-driven
> winners, hidden win pool, manual play, compact single-card layout, the
> per-room called-numbers fix, withdrawals with destination details, the
> editable wallet phone, the 400-card pool and three rooms (30 / 50 / 100 ETB).

---

## 1. Architecture Overview

```
Telegram (user chat)                    Local machine
┌─────────────────────┐      ┌──────────────────────────────────────────────┐
│ bot.py (python-     │─────▶│ server.py (Flask)  ·  game_loop.py           │
│ telegram-bot)       │      │   - hosts the Mini App (frontend/dist)       │
│  - /start name      │      │   - JSON API (game, wallet, admin)           │
│  - /play button     │      │   - APScheduler game loop (source of truth)  │
│  - announcer        │      └──────────────┬───────────────────────────────┘
└─────────────────────┘                     │
     ▲ Telegram Mini App (frontend/src → dist, built by Vite/React)
     │     └────────────────────────────────┘
                    SQLite (bingo_bot.db — WAL)
```

* The **Flask server** owns the game loop and every authoritative decision
  (bets, winners, eliminations, credit, wallet).
* The **bot** only talks to the user in chat (collects the full name once),
  opens the Mini App, and announces rounds. It never runs the game.
* The **Mini App** is the main UI. The **Telegram user ID** (verified through
  `initData` signature) is the authoritative identity; the server never trusts
  the frontend for authorization or financial operations.

---

## 2. Onboarding & Identity

### 2.1 The bot collects the full name once (chat)

When a brand-new user sends `/start`, `bot.py`:

1. Creates a placeholder account (credit 0, `is_registered = 0`) if needed.
2. If the user has **no stored full name**, the bot asks:

   > 🎰 **Welcome to Bingo Royale!** Before you continue, please enter your **full name**.

3. The bot waits for the next text message (`text_handler`, gated by
   `context.user_data["awaiting_full_name"]`).
4. On a valid reply the full name is stored (`players.full_name`) and becomes
   the **display identity** everywhere:
   * winner announcements
   * admin Users list
   * player identification (`_name_of` in the game loop)
   * wallet deposit requests / transaction records (snapshot)
   * game history (`games.winner_name`)
   * leaderboard

Rules:
* Empty / whitespace-only names are rejected ("it can't be empty").
* Names longer than 60 characters are rejected.
* Names are **Markdown-escaped** (`_md()` in bot.py) before being inserted into
  Telegram messages — this is the fix for the classic "Something went wrong".
* The welcome bonus (`NEW_PLAYER_CREDIT`) is granted **exactly once**, when the
  full name is first stored. `/start` alone never grants credit, and existing
  users are never asked again.
* The name is **not** re-collected on later `/start`s. It can be changed
  explicitly by the user in **Settings → Profile → Change your name**
  (`POST /api/profile`), never automatically.

### 2.2 The Mini App only adds the phone

The Mini App never asks for the full name again:

* Account not registered + **has** a stored name → Registration screen with a
  read-only name line and a **phone number** field (native Telegram
  `requestContact` share button with manual fallback, works worldwide).
* Account not registered + **no** stored name → the Mini App shows a gate:
  "open the bot chat, send /start, type your full name" and a retry button.
  The backend also enforces this: `POST /api/register` returns 400 unless a
  full name is already stored. The Mini App cannot bypass name onboarding.

### 2.3 Registration contract

| Field        | Collector        | When                                   |
|--------------|------------------|----------------------------------------|
| full name    | bot chat (`/start`) | first `/start` (once per account)    |
| phone        | Mini App          | Registration screen (share or manual) |
| welcome bonus| bot chat          | when the full name is first stored    |

`POST /api/register` (phone only):
* 400 if the caller has no stored full name (name gate).
* 409 if the phone is already registered to another account.
* Same phone again → just updates the profile (no bonus).
* **Different** phone → the old account is wiped and recreated with the same
  identity name and a fresh welcome bonus (re-registration with new
  credentials). Historical transactions of the old account are removed with it.

`POST /api/profile` — the user edits their own profile from **Settings →
Profile**. Both fields are optional but at least one must be present:
* `full_name` — the display identity (validated, max 60).
* `phone` — the **wallet account number**, editable by the user. Same
  duplicate rule as registration (409 if another *registered* user owns it),
  but **no account wipe and no bonus** — it's a plain profile update, unlike
  re-registering with a new phone via `/api/register`.

### 2.4 Account lifecycle

* Blocking / deleting the bot (`my_chat_member` → `kicked`/`left` in a private
  chat) or deleting the account in **Settings → Profile** wipes the account
  (`delete_player`), so the same person can register again with new credentials.
* Broadcasting catches `Forbidden` (blocked user) and auto-deletes the account.

---

## 3. Gameplay (server-authoritative)

### 3.1 Round lifecycle

`preparation → playing (ball every CALL_INTERVAL_SECONDS) → ended → preparation`

Persisted in `game_state`; the loop survives restarts.

### 3.2 Manual play — the player daubs their own card

During `playing`, numbers are **NOT auto-marked** anymore. The calling board
(`CalledBoard`) shows which balls were drawn; the player must find each called
number on their own card and **tap it to mark it** (paper-bingo style).
Daubing a number **auto-daubs it on the player's other cards** when the same
number appears there — one tap marks it everywhere it exists.

**Layout (fits one screen — nothing ever overflows):**
* A single card is rendered **compact** (the `small` variant, capped at
  `max-width: 210px`, centered) so the card, daub hint and BINGO button all
  stay visible without scrolling.
* Playing **3 cards** uses a slightly **bigger variant** (`triple`: larger
  cells/font for readability) while the play column stays height-capped and
  compact (tightened gaps, slim calling board and current-ball bar), so even
  3 bigger cards + the called strip + BINGO button fit on one screen.
* Playing **2–3 cards** shows a horizontally scrollable **called strip** right
  above the cards — every called ball as a letter-coloured chip. Tapping a
  chip daubs that number on **all** of the player's cards at once (tap again
  to unmark everywhere); tapping numbers directly on each card still works.

**Called-ball highlighting:** the ball machine writes the ball order, the
`called_numbers` row and `current_call` in **one atomic transaction**
(`Database.record_call`), and `called_numbers` is unique **per room**
(`UNIQUE(room, number)` — a legacy global `UNIQUE(number)` silently dropped
the same ball drawn in a second room, so its board never highlighted it). The
board also derives its "last ball" highlight from the end of the called list
instead of the possibly-stale `current_call`.

* The daubs live in client-side state only (`marked` in `App.jsx`, keyed by
  card → set of `"B-7"`-style keys). They are cleared on a new round and when
  switching rooms.
* The **win pool is hidden during preparation** (card selection window) — it
  is only displayed once the round is actually running (`state.phase ==
  'playing'`), so players never see a partial/final winning amount before the
  game starts.
* The FREE centre cell always counts as marked (standard bingo).
* Client-side pattern detection (`bingo.js`) runs over the player's **own
  daubs** — it only highlights cards and drives the "Press now!" pulse/hint,
  and it **never disables the button**.
* The **BINGO button stays active for every player with cards** who has not
  been eliminated and where no winner is declared yet — pressing it at any
  moment is allowed, because the **server is the sole judge** of a claim
  (it verifies the card against the *real* called numbers). A player who
  daubs a number that was never called, or misses one, simply has no valid
  pattern → false BINGO (below).

### 3.3 Claim validation & false BINGO elimination

**A winner is ONLY declared when a player presses the BINGO button.** The ball
loop (`call_step`) never auto-announces a winner — even when a card already
holds a winning pattern, the round keeps running until somebody claims it (or
all 75 balls are called, ending the round without a winner). This keeps the
"first to press wins" excitement and makes the BINGO button the sole trigger.

**Bots press BINGO too** — see §3.8, so a real player is never alone and other
players genuinely win rounds.

When a winner IS declared, **every player sees the winner's name AND winning
pattern** — and the winner modal **draws the pattern on the winner's card**:
the game state carries the winner's card numbers + the exact `winning_cells`,
and the modal renders a mini card where the winning cells glow gold (radial
shine animation) while the rest stay dimmed, labelled with the pattern name
(Winner modal for all + the ended summary screen).

`POST /api/claim-bingo` → `game_loop.claim_bingo`:

* **Valid pattern** → normal winner flow: round ends, prize credited.
* **No pattern** → the player is **eliminated for the current round**:
  1. elimination is persisted in `round_eliminations(game_id, user_id,
     reason='false_bingo', eliminated_at)` — survives a server restart;
  2. their cards stop participating — `claim_bingo` rejects the eliminated
     player before any pattern check, so they can never win the round (their
     already-paid **bet stays in the prize pool** — no refund);
  3. they cannot claim again during the same round;
  4. other players/bots continue;
  5. the next round clears all eliminations → the player is eligible again.

API response for a false claim: HTTP 409 with
`{"ok": false, "eliminated": true, "message": "False BINGO. ..."}` — the Mini
App shows a FALSE BINGO modal/banner. The eliminated player's cards stay
**visible but read-only** (no daubing, no claiming) until the next round; the
game state also reports `user.eliminated` for the current round.

### 3.4 Rooms — fixed bets, separate games

There is no bet input anymore. The Mini App shows a **room listbox** in the
card picker with three options: **Room by 30 · Room by 50 · Room by 100**
(`config.ROOM_BETS = [30, 50, 100]`, overridable via the `ROOM_BETS` env var).

Each room is its **own game**: its own `game_state` row (phase, countdown,
ball order, pool, round number), its own `card_selections`, `called_numbers`
and `games` rows. The game loop ticks every room independently, so a round
can be live in one room while another is still preparing. The wallet is
shared — one credit balance across all rooms. A player may hold cards in
several rooms at once (max `MAX_CARDS_PER_PLAYER` per room).

API calls carry the room (`room` in the JSON body or query string); old
clients/tests that omit it default to `config.ROOM_DEFAULT` (30). The bet per
card is always the room's value — any `bet_amount` sent by a client is
ignored (the server is the authority). Bot players in a room wager the room's
fixed amount too.

### 3.5 Dynamic prize pool

Per room: `total_bets = SUM(card_selections.bet_amount)` for the room's round
(actual bets, all equal to the room's fixed bet), `winner_prize =
int(total_bets × PRIZE_PERCENT)` (80% default), `house_kept = total_bets −
winner_prize`. Eliminated players' bets still count toward the pool.

### 3.6 Announcements — no round numbers

User-facing Telegram messages never expose the round number:

* Round start: "🎰 **A new Bingo round has started!** …" (pool + players only).
* Preparation: "🔄 **A new round is preparing** — Xs to pick your cards!"
* Winner: "🎉 **BINGO!** 🎉 🏆 Winner: **full name** …" (no round number).
* The Mini App UI likewise shows "Next round · Preparation" / "Round finished".

`round_number` remains in the database/game engine for technical tracking and
history (`games.round_number`) — it is only hidden from presentation.

### 3.7 Sounds & haptics

All effects are synthesized with the Web Audio API (no audio files). The
sound packs (Classic / Retro / Digital / Mute) pick the oscillator waveform;
every effect layers a fundamental with a quieter octave harmonic for a fuller,
more satisfying sound: a letter-pitched ball "bling", a daub "pop" on every
mark, a round-start fanfare, a triumphant win fanfare and a gentle "so close"
descent. On critical moments the phone vibrates via
`Telegram.WebApp.HapticFeedback` (`telegram.js` → `haptic()`): light on ball
calls/daubs, medium on the BINGO press and round start, **success on a win
(also fired when the winner modal opens)**, warning on a loss (also on the
modal for non-winners), error on a false-BINGO elimination (also when the
elimination modal opens). Outside Telegram it falls back to `navigator.vibrate`.

### 3.8 Bots — they play, and they win

Bots are **enabled by default** (`game_state.bots_enabled` defaults to 1; the
admin can toggle them via `/api/admin/bots/toggle`). They are **topped up
during the preparation countdown** (so the room already looks full before the
round starts) and again at `start_round` (`ensure_minimum_players`), up to
`MAX_TOTAL_PLAYERS` (default 18) players per room. Each bot holds 1–3 random
cards at the room's fixed bet and **contributes to the prize pool**
(`BOTS_CONTRIBUTE_TO_POOL`). The prep hero shows the room as "X players · Y
bots · Z cards".

* **Names:** every bot gets a deterministic **human male** first name + surname
  (e.g. "Abel Girma") from `game_logic.bot_name` — no female names, no
  nicknames, no "Bot_12345".
* **They press BINGO:** after every called ball, `game_loop._bot_claim_pass`
  finds bots whose cards have a complete pattern and schedules their claim
  **1–4 balls later** (`_bot_claim_at` — a random, human-like delay, so a real
  player pressing quickly can still win first). When the delay elapses the bot
  claims through the normal `claim_bingo` path and can **win the round** like
  any player. Bots never false-claim (they only claim cards that genuinely
  have a pattern) and are never auto-announced as winners by the ball loop.

---

## 4. Wallet & Payment Accounts

### 4.1 Multiple admin payment accounts

The single-account `settings.admin_account` design is replaced by the
`payment_accounts` table. The admin can **add / edit / delete / activate /
deactivate** any number of accounts (TeleBirr, CBE, CBB, bank, …). Each
account has: `id`, `provider`, `account_name` (holder), `account_number`,
`is_active`, `created_at`, `updated_at`. Nothing is hard-coded.

**Migration (idempotent, safe):** on startup, if `payment_accounts` is empty
and the legacy `settings.admin_account` key has a value, it is inserted as one
account (label taken from `admin_account_name`), so existing installations keep
their account.

### 4.2 User deposit flow

Settings → Wallet shows all **active** accounts:

```
💳 Where can you pay?
◉ TeleBirr — ELCOTECH · 0911226070   [📋]
○ CBE — ELCOTECH · 1000XXXXXXXX      [📋]
```

A deposit requires: **selected payment account + amount + transaction number**.
The server validates all three (account must exist and be active, amount > 0
and ≤ 1,000,000, tx number non-empty and ≤ 100 chars).

### 4.3 User withdraw flow

A withdraw requires the **destination account details**: **account name**
(provider, e.g. TeleBirr / CBE / CBB), **account holder's name**, **amount**
and **account number**. The server validates all of them (non-empty, ≤ 60
chars each, amount > 0 and ≤ balance). They are snapshotted onto the same
`provider` / `account_holder` / `account_number` columns used for deposits, so
the admin Wallet panel shows exactly where to pay out and the record never
changes later. A withdraw without these details is rejected (400).

### 4.4 Transaction snapshots

Each `transactions` row stores a **snapshot** at creation time:

`user_name` (full name), `payment_account_id`, `provider`, `account_number`,
`account_holder`, plus `user_id`, `type`, `amount`, `tx_id`, `phone`, `status`,
`admin_note`, `reviewed_by`, `created_at`, `reviewed_at`.

* **Deposit** rows snapshot the admin payment account the user paid into.
* **Withdraw** rows snapshot the destination account the user provided.

Editing or deleting a payment account later **never corrupts** historical
transactions (the snapshot stays). Admin approval:
* deposit → user credit +amount;
* withdraw → user credit −amount (rejected if the balance can't cover it);
  the admin pays the money out to the snapshotted destination details.

The admin Wallet panel shows: user full name, phone, payment method, selected
account (provider/holder/number), amount, transaction number, status, date,
and review info.

---

## 5. Admin Panel (Mini App)

Tabs: **Overview · Users · Wallet · Accounts**.

### 5.1 Users → click to edit credit (target-only)

Clicking a user row opens a **detail modal** with: full name, Telegram
username, Telegram ID, phone, current credit, registration status, rounds
played, wins, total winnings, account creation date.

The modal's credit editor provides: current credit display, an amount input,
**＋ Add** and **− Subtract** actions, and feedback after each change. The
server (`POST /api/admin/credit` with explicit `user_id`) is the authority —
**only the selected user's credit changes**; the logged-in admin's balance is
never touched unless they open their own account. After an update the modal
and the Users list refresh.

### 5.2 Wallet

Pending requests are highlighted; each row shows the full snapshot columns and
✓ Approve / ✕ Reject buttons. Approving moves money; the user list refreshes.
Deposits show the admin account paid into; **withdrawals show the destination
account (provider / holder / number) the user provided**, so the admin knows
exactly where to pay out.

### 5.3 Accounts

List (provider, holder, number, active badge), Add form (provider datalist +
holder + number + active checkbox), inline Edit, Activate/Deactivate toggle,
Delete with inline two-step confirm (no `window.confirm` — WebViews block it).

---

## 6. Database Schema

Tables: `players`, `game_state`, `cards`, `card_selections`, `called_numbers`,
`games`, `game_history`, `bots`, `transactions`, `payment_accounts`,
`round_eliminations`, `settings`, plus the read-only `profiles` view.

Rooms: `game_state` is keyed by **`room`** (the fixed bet, 30/50/100) — one
row per room, each with its own phase, countdown, ball order, pool and round
number. `card_selections`, `called_numbers` and `games` carry a `room` column
(legacy rows migrate to room 30 automatically).

Key columns:

```sql
players(user_id, username, full_name, phone, is_registered, credit,
        is_admin, created_at)

card_selections(user_id, card_id, room, bet_amount, UNIQUE(user_id, card_id))
called_numbers(room, number, UNIQUE(room, number))  -- per-room: the same ball
                                                        can be drawn in many rooms
games(room, round_number, ...)

transactions(id, user_id, type, amount, tx_id, phone, user_name,
             payment_account_id, provider, account_number, account_holder,
             status, admin_note, reviewed_by, created_at, reviewed_at)

payment_accounts(id, provider, account_name, account_number, is_active,
                 created_at, updated_at)

round_eliminations(id, game_id, user_id, reason, eliminated_at)
```

All migrations are idempotent (`CREATE TABLE IF NOT EXISTS` +
`_ensure_column`); existing `bingo_bot.db` files upgrade without data loss.

---

## 7. API Reference

| Endpoint | Method | Purpose |
|---|---|---|
| `/api/init` | GET | Resolve identity, create placeholder, state + user |
| `/api/register` | POST | Store phone (requires stored full name) |
| `/api/profile` | POST | Edit own profile: `full_name` and/or `phone` (wallet; duplicate phone → 409) |
| `/api/delete-account` | POST | Self-service account deletion |
| `/api/game-state` | GET | State + user (incl. `eliminated`) for a room |
| `/api/cards` | GET | Card pool (taken status per room) |
| `/api/select-card` / `/api/deselect-card` / `/api/quick-play` | POST | Card betting at the room's FIXED bet (no `bet_amount`) |
| `/api/claim-bingo` | POST | Valid claim → winner; false claim → `eliminated:true` |

Room-aware: every gameplay endpoint accepts `room` (body/query, default
`config.ROOM_DEFAULT` = 30). The state payload exposes `config.rooms`
(`[30, 50, 100]`) so the Mini App can build the room listbox.
| `/api/history` / `/api/leaderboard` | GET | Stats |
| `/api/transactions` | GET/POST | Own wallet requests (POST: deposit = amount + tx number + payment account; withdraw = amount + account name / holder / number) |
| `/api/admin/*` | — | All guarded by `ADMIN_IDS` (server-side) |

Admin endpoints: `stats`, `bots`, `force-start`, `force-call`, `reset`,
`bots/add`, `bots/toggle`, `credit` (target-only), `users`, `users/delete`,
`transactions`, `transactions/review`, `accounts` (GET/POST),
`accounts/update`, `accounts/delete`.

`_require_admin()` resolves `admin_id` from JSON body or query params and
rejects anything not in `config.ADMIN_IDS`.

---

## 8. Security Notes

* Telegram `initData` HMAC verification is preserved; the Telegram user ID is
  the authoritative ID.
* The frontend is never trusted for authorization or money movement — the
  server re-validates everything.
* Admin credit changes target an explicit `user_id`, never the caller.
* User-supplied names are Markdown-escaped before any Telegram message.
* Deposit transaction numbers are validated; withdraws check the balance.

---

## 8.5 Performance & scale

* **Instant reopen** — the Mini App caches the last session (sessionStorage,
  stale-while-revalidate): reopening paints immediately from cache and
  refreshes in the background, so the splash screen is only ever seen on the
  very first open. The chosen room is remembered too.
* **Lightweight card list** — `/api/cards` sends only `id` + taken status
  (the numbers of the player's OWN cards come from the user payload), so the
  400-card pool is a ~21 KB payload instead of hundreds of KB. The taken map
  is computed in one pass over the room's selections (no O(cards×players)
  loop).
* **Adaptive polling** — polls every **2 s** during a live round and every
  **4 s** during preparation/ended, so hundreds of players don't hammer the
  server while nothing is changing.
* **Paginated card grid** — the picker renders the pool in chunks of 100
  ("Show more"), keeping the DOM light and scrolling smooth on mobile
  WebViews.
* **Concurrency** — Flask runs threaded, SQLite uses WAL (concurrent readers
  with a single writer) and each room already runs independently, so many
  players can sit in the same room at once (bots only top the room up to
  `MAX_TOTAL_PLAYERS`; real players are never capped).

## 9. Tests

`venv\Scripts\python.exe api_smoke.py` (offline, isolated `api_smoke.db`):

1. registration contract: unregistered start, name-gate 400, phone completes
   profile without a double bonus, duplicate phone 409, phone change wipes +
   fresh bonus, display identity; 400-card pool with a lightweight `/api/cards`
   payload (no numbers); rooms: fixed bet per room (30 vs 50), `bet_amount`
   ignored, per-room refund;
2. bot onboarding via real handlers with fake updates: `/start` asks for the
   name, name saved + escaped + bonus once, repeated `/start` never re-asks,
   empty name rejected;
3. card select / deselect refund / quick-play;
4. non-admin rejected;
5–6. force start, auto calling — **no winner is ever auto-announced**: the
    board advances while the round stays running;
7. exact 80% payout from a 30 ETB card (24 ETB) + dynamic payout (two room-30
   cards: 30+30 = 60 pool → 48 prize) — **both won via a BINGO claim** (the
   winning pattern is present before the claim and NOT announced);
8. bots toggle, admin credit affects only the target, stats;
9. payment accounts CRUD + activation, deposit requires an account, snapshot
   correctness (account edited after deposit → history unchanged), approve
   deposit/withdraw, **withdraw requires account details (rejected without,
   snapshotted with)**, **profile phone edit (Settings) incl. duplicate-phone
   409 and no-account-wipe**, admin wallet panel fields, active accounts
   exposed to users;
10. account lifecycle: delete → gate → re-register after bot onboarding;
11. false BINGO: elimination, no refund, no re-claim, cards can't win,
    elimination persisted across a fresh DB connection (restart), eligible
    again next round;
12. round announcement carries no round number; `_name_of` uses full name;
13. reset → preparation;
14. called numbers are **per-room**: the same ball drawn in two rooms appears
    on BOTH calling boards (regression test for the legacy global-unique bug);
15. **bots win rounds**: all bot names are human male names; a force-started
    round includes bots holding cards; forcing the first bot's row to complete
    ends the round with a **bot winner** (the ball loop never auto-announced
    it — the bot claimed); the winner payload carries `winning_cells` + the
    winner's card numbers for the visual pattern.

`venv\Scripts\python.exe smoke_test.py` runs the API suite + card image
rendering. `build_frontend.bat` rebuilds `frontend/dist`. `run_all.bat` starts
server + tunnel + bot.

---

## 10. Files

| File | Role |
|---|---|
| `bot.py` | chat onboarding (full name), announcements, auto-delete on block |
| `server.py` | Flask API + admin + payment accounts + registration contracts |
| `database.py` | schema, migrations, wallet/elimination/accounts storage |
| `game_loop.py` | round lifecycle, claim validation + elimination |
| `game_logic.py` | patterns, winner lookup (skips eliminated), prize pool, bot names (100% human male names) |
| `config.py` | `APP_CURRENCY`, rooms (`ROOM_BETS`), timing, `ADMIN_IDS` |
| `migrate_db.py` | idempotent schema/seed helper |
| `api_smoke.py` / `smoke_test.py` | offline test suites |
| `frontend/src/…` | React Mini App (Registration, Settings, AdminPanel, App) |
