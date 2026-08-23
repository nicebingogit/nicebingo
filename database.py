"""
SQLite storage layer for the Bingo system (bot + local web server).

Design notes:
  * One persistent connection per process, serialized by a threading lock —
    opening a fresh connection per operation is ~100x slower on Windows
    (WAL checkpoint cost on close).  Every method is atomic under the lock.
  * WAL journal mode is enabled so the bot (announcer) and the Flask server
    (game loop) can safely share the same database file.
  * Existing databases are migrated automatically (missing columns/tables
    are added), so upgrading never loses player data.
"""
import json
import sqlite3
import threading
from contextlib import contextmanager
from datetime import datetime, timedelta
from typing import Dict, Iterator, List, Optional

import config

_GAME_STATE_COLUMNS = {
    "phase", "preparation_end_time", "current_call", "winner_user_id",
    "winning_pattern", "prize_pool", "total_bets", "ball_order",
    "round_number", "current_game_id", "bots_enabled", "next_call_time",
    "reset_time", "paused",
}


class Database:

    def __init__(self, db_path: str = "bingo_bot.db"):
        self.db_path = db_path
        self._conn: Optional[sqlite3.Connection] = None
        self._lock = threading.RLock()
        self.init_db()

    # ------------------------------------------------------------------ low level
    # One persistent connection per process, serialized by a lock.  Opening
    # a fresh sqlite connection per operation is ~100x slower on Windows
    # (WAL checkpoint cost on close), which made bot-filling crawl.
    def _connect(self) -> sqlite3.Connection:
        with self._lock:
            if self._conn is None:
                conn = sqlite3.connect(self.db_path, timeout=30,
                                       check_same_thread=False)
                conn.row_factory = sqlite3.Row
                try:
                    conn.execute("PRAGMA busy_timeout=10000")
                    conn.execute("PRAGMA synchronous=NORMAL")
                except sqlite3.Error:
                    pass
                self._conn = conn
            return self._conn

    @contextmanager
    def _session(self) -> Iterator[sqlite3.Connection]:
        conn = self._connect()
        with self._lock:
            try:
                yield conn
                conn.commit()
            except Exception:
                conn.rollback()
                raise

    # -------------------------------------------------------------------- schema
    def init_db(self) -> None:
        conn = self._connect()
        try:
            conn.execute("PRAGMA journal_mode=WAL")  # one-time, enables concurrent readers
        except sqlite3.Error:
            pass
        with self._session() as conn:
            conn.executescript(
                """
                CREATE TABLE IF NOT EXISTS players (
                    user_id       INTEGER PRIMARY KEY,
                    username      TEXT,
                    full_name     TEXT,
                    phone         TEXT,
                    is_registered INTEGER NOT NULL DEFAULT 1,
                    credit        INTEGER NOT NULL DEFAULT 1000,
                    is_admin      INTEGER NOT NULL DEFAULT 0,
                    created_at    TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                );
                -- one row per ROOM (keyed by its fixed bet: 30 / 50 / 100).
                -- Each room is its own game with its own phase, ball order,
                -- pool and timer, so low and high rollers never mix.
                CREATE TABLE IF NOT EXISTS game_state (
                    room INTEGER PRIMARY KEY,
                    phase TEXT DEFAULT 'preparation',
                    preparation_end_time TEXT,
                    current_call TEXT,
                    winner_user_id INTEGER,
                    winning_pattern TEXT,
                    prize_pool INTEGER DEFAULT 0,
                    total_bets INTEGER DEFAULT 0,
                    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                );
                CREATE TABLE IF NOT EXISTS cards (
                    id      TEXT PRIMARY KEY,
                    numbers TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS card_selections (
                    id         INTEGER PRIMARY KEY AUTOINCREMENT,
                    user_id    INTEGER NOT NULL,
                    card_id    TEXT NOT NULL,
                    room       INTEGER NOT NULL DEFAULT 30,
                    bet_amount INTEGER DEFAULT 30,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    UNIQUE(user_id, card_id)
                );
                -- one row per (room, number): the SAME ball can be drawn in
                -- several rooms, so uniqueness must be per room — a global
                -- UNIQUE(number) would silently drop the second room's call
                -- and its calling board would never highlight that ball.
                CREATE TABLE IF NOT EXISTS called_numbers (
                    id        INTEGER PRIMARY KEY AUTOINCREMENT,
                    room      INTEGER NOT NULL DEFAULT 30,
                    number    TEXT NOT NULL,
                    called_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    UNIQUE(room, number)
                );
                CREATE TABLE IF NOT EXISTS games (
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
                CREATE TABLE IF NOT EXISTS game_history (
                    id           INTEGER PRIMARY KEY AUTOINCREMENT,
                    game_id      INTEGER,
                    user_id      INTEGER,
                    card_ids     TEXT,
                    total_bet    INTEGER,
                    winnings     INTEGER,
                    credit_after INTEGER,
                    status       TEXT,
                    played_at    TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                );
                -- persistent bot accounts (negative user ids)
                CREATE TABLE IF NOT EXISTS bots (
                    user_id    INTEGER PRIMARY KEY,
                    username   TEXT,
                    cards      INTEGER DEFAULT 0,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                );
                -- deposit / withdraw requests (wallet) reviewed by the admin.
                -- The payment account details are stored as a SNAPSHOT on each
                -- row (provider / account_number / account_holder) so that
                -- editing or deleting an account later never corrupts the
                -- historical transaction record. user_name snapshots who paid.
                CREATE TABLE IF NOT EXISTS transactions (
                    id                 INTEGER PRIMARY KEY AUTOINCREMENT,
                    user_id            INTEGER NOT NULL,
                    type               TEXT NOT NULL,
                    amount             INTEGER NOT NULL,
                    tx_id              TEXT,
                    phone              TEXT,
                    user_name          TEXT,
                    payment_account_id INTEGER,
                    provider           TEXT,
                    account_number     TEXT,
                    account_holder     TEXT,
                    status             TEXT DEFAULT 'pending',
                    admin_note         TEXT,
                    reviewed_by        INTEGER,
                    created_at         TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    reviewed_at        TIMESTAMP
                );
                -- payment accounts (TeleBirr / CBE / CBB / bank ...) that
                -- players send deposits to. Managed by the admin; a user picks
                -- one active account when submitting a deposit.
                CREATE TABLE IF NOT EXISTS payment_accounts (
                    id             INTEGER PRIMARY KEY AUTOINCREMENT,
                    provider       TEXT NOT NULL,
                    account_name   TEXT NOT NULL,
                    account_number TEXT NOT NULL,
                    is_active      INTEGER NOT NULL DEFAULT 1,
                    created_at     TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    updated_at     TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                );
                -- round eliminations (false BINGO). Scoped by game_id so a
                -- player is only out for the CURRENT round and automatically
                -- becomes eligible again when the next round starts. Persisted
                -- so a server restart mid-round cannot revive the player.
                CREATE TABLE IF NOT EXISTS round_eliminations (
                    id            INTEGER PRIMARY KEY AUTOINCREMENT,
                    game_id       INTEGER NOT NULL,
                    user_id       INTEGER NOT NULL,
                    reason        TEXT DEFAULT 'false_bingo',
                    eliminated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                );
                -- simple key/value settings (legacy admin wallet account kept
                -- for backward compatibility; payment_accounts is authoritative)
                CREATE TABLE IF NOT EXISTS settings (
                    key   TEXT PRIMARY KEY,
                    value TEXT
                );
                -- wallet appeals: a user who sent a deposit but the admin never
                -- approved it can appeal; the SUPER ADMIN resolves these.
                CREATE TABLE IF NOT EXISTS appeals (
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
                -- cross-process bot message queue: server.py (Flask) enqueues
                -- admin/user alerts here; the bot's announcer tick drains the
                -- queue and sends them over Telegram. Works in BOTH polling
                -- and webhook modes (server and bot may be separate processes).
                CREATE TABLE IF NOT EXISTS bot_notifications (
                    id         INTEGER PRIMARY KEY AUTOINCREMENT,
                    chat_id    INTEGER NOT NULL,
                    text       TEXT NOT NULL,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    sent_at    TIMESTAMP
                );
                -- activity log: every critical action for the super admin
                -- console. Records who did what, when, and key details.
                CREATE TABLE IF NOT EXISTS activity_log (
                    id         INTEGER PRIMARY KEY AUTOINCREMENT,
                    user_id    INTEGER,
                    action     TEXT NOT NULL,
                    details    TEXT,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                );
                """
            )
            # ----------------------------------------------------------
            # migrate the legacy SINGLETON game_state (id=1) to per-ROOM
            # rows keyed by the fixed bet. Existing data moves to room 30.
            # ----------------------------------------------------------
            cols = {r[1] for r in conn.execute("PRAGMA table_info(game_state)").fetchall()}
            if "room" not in cols:
                legacy_cols = [r[1] for r in
                               conn.execute("PRAGMA table_info(game_state)").fetchall()]
                common = [c for c in legacy_cols if c != "id"]
                conn.execute("ALTER TABLE game_state RENAME TO game_state_legacy")
                conn.execute(
                    """
                    CREATE TABLE game_state (
                        room INTEGER PRIMARY KEY,
                        phase TEXT DEFAULT 'preparation',
                        preparation_end_time TEXT,
                        current_call TEXT,
                        winner_user_id INTEGER,
                        winning_pattern TEXT,
                        prize_pool INTEGER DEFAULT 0,
                        total_bets INTEGER DEFAULT 0,
                        updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                        ball_order TEXT,
                        round_number INTEGER DEFAULT 0,
                        current_game_id INTEGER,
                        bots_enabled INTEGER DEFAULT 1,
                        next_call_time TEXT,
                        reset_time TEXT
                    )
                    """
                )
                col_list = ", ".join(common)
                conn.execute(
                    f"INSERT INTO game_state (room, {col_list}) "
                    f"SELECT 30, {col_list} FROM game_state_legacy"
                )
                conn.execute("DROP TABLE game_state_legacy")

            # migrations for pre-existing databases
            self._ensure_column(conn, "game_state", "ball_order", "TEXT")
            self._ensure_column(conn, "game_state", "round_number", "INTEGER DEFAULT 0")
            self._ensure_column(conn, "game_state", "current_game_id", "INTEGER")
            self._ensure_column(conn, "game_state", "bots_enabled", "INTEGER DEFAULT 1")
            self._ensure_column(conn, "game_state", "next_call_time", "TEXT")
            self._ensure_column(conn, "game_state", "reset_time", "TEXT")
            self._ensure_column(conn, "game_state", "paused", "INTEGER DEFAULT 0")
            # rooms: existing rows join the default room (30) until a player
            # picks a room from the listbox
            self._ensure_column(conn, "card_selections", "room", "INTEGER NOT NULL DEFAULT 30")
            self._ensure_column(conn, "called_numbers", "room", "INTEGER NOT NULL DEFAULT 30")
            # called_numbers uniqueness must be PER-ROOM (room, number). Legacy
            # databases created with a global UNIQUE(number) silently drop the
            # same ball drawn in a second room, so its board never highlights
            # it — detect the legacy autoindex and rebuild the table.
            legacy_global_unique = False
            idx_rows = conn.execute(
                "SELECT name FROM sqlite_master WHERE type = 'index' "
                "AND tbl_name = 'called_numbers' AND name LIKE 'sqlite_autoindex%'"
            ).fetchall()
            for (idx_name,) in idx_rows:
                cols = [r[2] for r in
                        conn.execute(f"PRAGMA index_info('{idx_name}')").fetchall()]
                if cols == ["number"]:
                    legacy_global_unique = True
                    break
            if legacy_global_unique:
                conn.execute("ALTER TABLE called_numbers RENAME TO called_numbers_legacy")
                conn.execute(
                    """
                    CREATE TABLE called_numbers (
                        id        INTEGER PRIMARY KEY AUTOINCREMENT,
                        room      INTEGER NOT NULL DEFAULT 30,
                        number    TEXT NOT NULL,
                        called_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                        UNIQUE(room, number)
                    )
                    """
                )
                conn.execute(
                    "INSERT INTO called_numbers (room, number, called_at) "
                    "SELECT room, number, called_at FROM called_numbers_legacy"
                )
                conn.execute("DROP TABLE called_numbers_legacy")
            self._ensure_column(conn, "games", "room", "INTEGER NOT NULL DEFAULT 30")
            self._ensure_column(conn, "game_history", "game_id", "INTEGER")
            # wallet / registration migrations
            self._ensure_column(conn, "players", "full_name", "TEXT")
            self._ensure_column(conn, "players", "phone", "TEXT")
            self._ensure_column(conn, "players", "is_registered", "INTEGER NOT NULL DEFAULT 1")
            # admin-credit system: every admin has their own credit (the float
            # the super admin sells them). Deposits approved on an admin's
            # account deduct ADMIN_APPROVAL_RATE of the amount from that
            # admin's credit; withdrawals approved add it back to the reviewer.
            self._ensure_column(conn, "players", "admin_credit", "INTEGER NOT NULL DEFAULT 0")
            # last_seen (ISO timestamp): an admin is "online" when they have
            # made an API call / bot command recently. Only ONLINE admins'
            # payment accounts are shown to users for deposits.
            self._ensure_column(conn, "players", "last_seen", "TEXT")
            # payment accounts now belong to an admin (admin_id = owner). Only
            # the owner's account is charged when a deposit into it is approved.
            self._ensure_column(conn, "payment_accounts", "admin_id", "INTEGER")
            # legacy accounts created before admin ownership existed are
            # assigned to the FIRST admin so they keep working (the super admin
            # can re-assign them later in the Super Admin panel).
            if config.ADMIN_IDS:
                conn.execute(
                    "UPDATE payment_accounts SET admin_id = ? "
                    "WHERE admin_id IS NULL", (config.ADMIN_IDS[0],)
                )
            # wallet transaction snapshot columns (safe for old databases)
            self._ensure_column(conn, "transactions", "user_name", "TEXT")
            self._ensure_column(conn, "transactions", "payment_account_id", "INTEGER")
            self._ensure_column(conn, "transactions", "provider", "TEXT")
            self._ensure_column(conn, "transactions", "account_number", "TEXT")
            self._ensure_column(conn, "transactions", "account_holder", "TEXT")
            self._ensure_column(conn, "transactions", "reviewed_by", "INTEGER")
            # migrate the legacy single wallet account (settings.admin_account /
            # admin_account_name) into payment_accounts exactly once — existing
            # installations keep their account instead of silently losing it.
            count = conn.execute("SELECT COUNT(*) FROM payment_accounts").fetchone()[0]
            if count == 0:
                acc = conn.execute(
                    "SELECT value FROM settings WHERE key = 'admin_account'").fetchone()
                if acc and acc[0]:
                    name = conn.execute(
                        "SELECT value FROM settings WHERE key = 'admin_account_name'").fetchone()
                    label = (name[0] if name and name[0] else "Wallet")
                    conn.execute(
                        "INSERT INTO payment_accounts (provider, account_name, "
                        "account_number, is_active) VALUES (?, ?, ?, 1)",
                        (label, label, acc[0]),
                    )
            # read-only profiles view over players + aggregate history stats
            conn.execute(
                """
                CREATE VIEW IF NOT EXISTS profiles AS
                SELECT p.user_id, p.username, p.credit, p.is_admin, p.created_at,
                       COALESCE(s.rounds, 0)        AS rounds,
                       COALESCE(s.wins, 0)          AS wins,
                       COALESCE(s.winnings, 0)      AS total_winnings
                FROM players p
                LEFT JOIN (
                    SELECT user_id, COUNT(*) AS rounds,
                           SUM(CASE WHEN winnings > 0 THEN 1 ELSE 0 END) AS wins,
                           SUM(winnings) AS winnings
                    FROM game_history GROUP BY user_id
                ) s ON s.user_id = p.user_id
                """
            )
            # one game_state row per room, all sitting in a fresh preparation
            # phase (rooms created later start on their own countdown)
            for room in config.ROOM_BETS:
                row = conn.execute(
                    "SELECT COUNT(*) FROM game_state WHERE room = ?", (room,)
                ).fetchone()
                if row[0] == 0:
                    conn.execute(
                        "INSERT INTO game_state (room, phase, preparation_end_time) "
                        "VALUES (?, 'preparation', ?)",
                        (room, (datetime.now() +
                                timedelta(seconds=config.PREPARATION_SECONDS)).isoformat()),
                    )

    @staticmethod
    def _ensure_column(conn: sqlite3.Connection, table: str, column: str, ddl: str) -> None:
        cols = {r[1] for r in conn.execute(f"PRAGMA table_info({table})").fetchall()}
        if column not in cols:
            conn.execute(f"ALTER TABLE {table} ADD COLUMN {column} {ddl}")

    # ------------------------------------------------------------------- players
    def create_player(self, user_id: int, username: Optional[str] = None,
                      credit: Optional[int] = None) -> None:
        with self._session() as conn:
            conn.execute(
                "INSERT OR IGNORE INTO players (user_id, username, credit) VALUES (?, ?, ?)",
                (user_id, username, config.NEW_PLAYER_CREDIT if credit is None else credit),
            )

    def update_username(self, user_id: int, username: Optional[str]) -> None:
        with self._session() as conn:
            conn.execute("UPDATE players SET username = ? WHERE user_id = ?", (username, user_id))

    def update_profile(self, user_id: int, full_name: Optional[str] = None,
                       phone: Optional[str] = None, registered: Optional[bool] = None) -> None:
        """Update registration fields (full name / phone / is_registered)."""
        sets, vals = [], []
        if full_name is not None:
            sets.append("full_name = ?")
            vals.append(full_name)
        if phone is not None:
            sets.append("phone = ?")
            vals.append(phone)
        if registered is not None:
            sets.append("is_registered = ?")
            vals.append(1 if registered else 0)
        if not sets:
            return
        vals.append(user_id)
        with self._session() as conn:
            conn.execute(f"UPDATE players SET {', '.join(sets)} WHERE user_id = ?", vals)

    def get_player_by_phone(self, phone: str) -> Optional[Dict]:
        """Find a *registered* player holding this phone number (duplicate check)."""
        with self._session() as conn:
            row = conn.execute(
                "SELECT * FROM players WHERE phone = ? AND is_registered = 1 LIMIT 1",
                (phone,),
            ).fetchone()
            return dict(row) if row else None

    def delete_player(self, user_id: int) -> None:
        """Permanently remove a player account and everything owned by it.

        Called when the user blocks/deletes the bot, deletes the account from
        Settings, or re-registers with different credentials.
        """
        with self._session() as conn:
            conn.execute("DELETE FROM card_selections WHERE user_id = ?", (user_id,))
            conn.execute("DELETE FROM transactions WHERE user_id = ?", (user_id,))
            conn.execute("DELETE FROM players WHERE user_id = ?", (user_id,))

    def get_all_players(self, limit: int = 500) -> List[Dict]:
        """All real (non-bot) players with wallet + history aggregates (admin UI)."""
        with self._session() as conn:
            rows = conn.execute(
                """
                SELECT p.user_id, p.username, p.full_name, p.phone, p.credit,
                       p.admin_credit, p.is_admin, p.last_seen,
                       p.is_registered, p.created_at,
                       COALESCE(s.rounds, 0)   AS rounds,
                       COALESCE(s.wins, 0)     AS wins,
                       COALESCE(s.winnings, 0) AS total_winnings
                FROM players p
                LEFT JOIN (
                    SELECT user_id, COUNT(*) AS rounds,
                           SUM(CASE WHEN winnings > 0 THEN 1 ELSE 0 END) AS wins,
                           SUM(winnings) AS winnings
                    FROM game_history GROUP BY user_id
                ) s ON s.user_id = p.user_id
                WHERE p.user_id > 0
                ORDER BY p.created_at DESC, p.user_id
                LIMIT ?
                """,
                (limit,),
            ).fetchall()
            return [dict(r) for r in rows]

    def get_player(self, user_id: int) -> Optional[Dict]:
        with self._session() as conn:
            row = conn.execute("SELECT * FROM players WHERE user_id = ?", (user_id,)).fetchone()
            return dict(row) if row else None

    def get_credit(self, user_id: int) -> int:
        with self._session() as conn:
            row = conn.execute("SELECT credit FROM players WHERE user_id = ?", (user_id,)).fetchone()
            return int(row[0]) if row else 0

    def set_credit(self, user_id: int, amount: int) -> None:
        with self._session() as conn:
            conn.execute("UPDATE players SET credit = ? WHERE user_id = ?", (max(0, amount), user_id))

    def update_credit(self, user_id: int, delta: int) -> None:
        """Add `delta` credits; the balance can never go below 0."""
        with self._session() as conn:
            conn.execute(
                "UPDATE players SET credit = MAX(credit + ?, 0) WHERE user_id = ?",
                (delta, user_id),
            )

    # ----------------------------------------------------------------- admins
    def is_admin(self, user_id: int) -> bool:
        """An admin is either in config.ADMIN_IDS (env / core admins) OR was
        promoted to admin by the SUPER ADMIN (players.is_admin = 1)."""
        if user_id in config.ADMIN_IDS:
            return True
        with self._session() as conn:
            row = conn.execute(
                "SELECT is_admin FROM players WHERE user_id = ?", (user_id,)
            ).fetchone()
            return bool(row and row[0])

    def get_admin_ids(self) -> List[int]:
        """Every admin user id: core admins (config.ADMIN_IDS) + super-admin-
        promoted admins (players.is_admin = 1). Used for notifications and
        online tracking."""
        ids = set(config.ADMIN_IDS)
        with self._session() as conn:
            rows = conn.execute(
                "SELECT user_id FROM players WHERE is_admin = 1").fetchall()
            ids.update(r[0] for r in rows)
        return sorted(ids)

    def set_admin(self, user_id: int, is_admin: bool) -> None:
        """Promote/demote a user in the DB (super admin only).

        Two-step upsert that works on every SQLite version: try UPDATE
        first; if no row exists yet, INSERT a fresh one.
        """
        val = 1 if is_admin else 0
        with self._session() as conn:
            cur = conn.execute(
                "UPDATE players SET is_admin = ? WHERE user_id = ?",
                (val, user_id),
            )
            if cur.rowcount == 0:
                conn.execute(
                    "INSERT INTO players (user_id, username, credit, is_admin) "
                    "VALUES (?, ?, 0, ?)",
                    (user_id, f"Player_{user_id}", val),
                )

    # --------------------------------------------------------- admin credit
    def get_admin_credit(self, user_id: int) -> int:
        """An admin's own credit float (set by the super admin)."""
        with self._session() as conn:
            row = conn.execute(
                "SELECT admin_credit FROM players WHERE user_id = ?", (user_id,)
            ).fetchone()
            return int(row[0]) if row else 0

    def set_admin_credit(self, user_id: int, amount: int) -> None:
        """Set an admin's credit to an absolute value (never negative)."""
        with self._session() as conn:
            conn.execute(
                "UPDATE players SET admin_credit = ? WHERE user_id = ?",
                (max(0, int(amount)), user_id),
            )

    def update_admin_credit(self, user_id: int, delta: int) -> None:
        """Add `delta` to an admin's credit; the balance can never go below 0."""
        with self._session() as conn:
            conn.execute(
                "UPDATE players SET admin_credit = MAX(admin_credit + ?, 0) "
                "WHERE user_id = ?",
                (delta, user_id),
            )

    # ----------------------------------------------------------- online status
    def touch_admin(self, user_id: int) -> None:
        """Record that an admin is active RIGHT NOW (last_seen = now).

        Also ensures the admin has a players row (an admin may only ever call
        the admin API without ever registering as a player — their row must
        exist for online lookups and the deposit-account join)."""
        with self._session() as conn:
            conn.execute(
                "INSERT OR IGNORE INTO players (user_id, username, credit) "
                "VALUES (?, ?, 0)", (user_id, f"Player_{user_id}"),
            )
            conn.execute(
                "UPDATE players SET last_seen = ? WHERE user_id = ?",
                (datetime.now().isoformat(), user_id),
            )

    def get_last_seen(self, user_id: int) -> Optional[str]:
        with self._session() as conn:
            row = conn.execute(
                "SELECT last_seen FROM players WHERE user_id = ?", (user_id,)
            ).fetchone()
            return row[0] if row else None

    def is_admin_online(self, user_id: int,
                        minutes: Optional[int] = None) -> bool:
        """True when the admin has been active within the online window."""
        if not self.is_admin(user_id):
            return False
        last = self.get_last_seen(user_id)
        if not last:
            return False
        try:
            seen = datetime.fromisoformat(last)
        except (ValueError, TypeError):
            return False
        window = (minutes if minutes is not None
                  else config.ADMIN_ONLINE_MINUTES)
        return (datetime.now() - seen).total_seconds() <= window * 60

    def delete_bot_players(self) -> None:
        """Remove leftover bot accounts (negative ids)."""
        with self._session() as conn:
            conn.execute("DELETE FROM players WHERE user_id < 0")
            conn.execute("DELETE FROM bots")

    def get_all_player_ids(self) -> List[int]:
        """All real (non-bot) user ids, used for broadcasts."""
        with self._session() as conn:
            rows = conn.execute("SELECT user_id FROM players WHERE user_id > 0").fetchall()
            return [r[0] for r in rows]

    def top_players(self, limit: int = 10) -> List[Dict]:
        with self._session() as conn:
            rows = conn.execute(
                "SELECT user_id, username, full_name, credit FROM players "
                "WHERE user_id > 0 ORDER BY credit DESC LIMIT ?",
                (limit,),
            ).fetchall()
            return [dict(r) for r in rows]

    # --------------------------------------------------------------------- cards
    def insert_card(self, card_id: str, numbers: Dict) -> None:
        with self._session() as conn:
            conn.execute(
                "INSERT OR IGNORE INTO cards (id, numbers) VALUES (?, ?)",
                (card_id, json.dumps(numbers)),
            )

    def get_card(self, card_id: str) -> Optional[Dict]:
        """Return the numbers dict of a card (or None)."""
        with self._session() as conn:
            row = conn.execute("SELECT numbers FROM cards WHERE id = ?", (card_id,)).fetchone()
            return json.loads(row[0]) if row else None

    def get_all_cards(self) -> List[Dict]:
        with self._session() as conn:
            rows = conn.execute("SELECT id, numbers FROM cards").fetchall()
            return [{"id": r[0], "numbers": json.loads(r[1])} for r in rows]

    def get_all_card_ids(self) -> List[str]:
        """Just the card ids, in stable order — the light query the Mini App's
        card picker needs (numbers are only sent for the player's own cards)."""
        with self._session() as conn:
            rows = conn.execute("SELECT id FROM cards ORDER BY rowid").fetchall()
            return [r[0] for r in rows]

    def count_cards(self) -> int:
        with self._session() as conn:
            return int(conn.execute("SELECT COUNT(*) FROM cards").fetchone()[0])

    def get_cards_map(self) -> Dict[str, Dict]:
        """All cards as {card_id: numbers} in a single query (winner checks)."""
        with self._session() as conn:
            rows = conn.execute("SELECT id, numbers FROM cards").fetchall()
            return {r["id"]: json.loads(r["numbers"]) for r in rows}

    # --------------------------------------------------------------- game state
    def get_game_state(self, room: int = 30) -> Dict:
        with self._session() as conn:
            row = conn.execute(
                "SELECT * FROM game_state WHERE room = ?", (room,)
            ).fetchone()
            return dict(row) if row else {}

    def update_game_state(self, room: int = 30, **kwargs) -> None:
        unknown = set(kwargs) - _GAME_STATE_COLUMNS
        if unknown:
            raise ValueError(f"Unknown game_state columns: {unknown}")
        if not kwargs:
            return
        sets = ", ".join(f"{k} = ?" for k in kwargs)
        values = list(kwargs.values()) + [datetime.now().isoformat(), room]
        with self._session() as conn:
            conn.execute(
                f"UPDATE game_state SET {sets}, updated_at = ? WHERE room = ?", values
            )

    def get_bots_enabled(self, room: int = 30) -> bool:
        return bool(self.get_game_state(room).get("bots_enabled", 1))

    def set_bots_enabled(self, enabled: bool) -> None:
        """Toggle bots for EVERY room (a global switch, stored per room row)."""
        with self._session() as conn:
            for room in config.ROOM_BETS:
                conn.execute(
                    "UPDATE game_state SET bots_enabled = ? WHERE room = ?",
                    (1 if enabled else 0, room),
                )

    # --------------------------------------------------------------------- bots
    def record_bot(self, user_id: int, username: str, cards: int) -> None:
        with self._session() as conn:
            conn.execute(
                "INSERT OR IGNORE INTO bots (user_id, username, cards) VALUES (?, ?, ?)",
                (user_id, username, cards),
            )

    def bot_count(self) -> int:
        with self._session() as conn:
            return int(conn.execute("SELECT COUNT(*) FROM bots").fetchone()[0])

    # ---------------------------------------------------------------- selections
    def select_card(self, user_id: int, card_id: str, bet_amount: int = 30,
                    room: int = 30) -> bool:
        """Insert a selection. Returns True only if a new row was created
        (so a concurrent double-pick can never be charged twice)."""
        with self._session() as conn:
            cur = conn.execute(
                "INSERT OR IGNORE INTO card_selections (user_id, card_id, room, bet_amount) "
                "VALUES (?, ?, ?, ?)",
                (user_id, card_id, room, bet_amount),
            )
            return cur.rowcount > 0

    def deselect_card(self, user_id: int, card_id: str) -> None:
        with self._session() as conn:
            conn.execute(
                "DELETE FROM card_selections WHERE user_id = ? AND card_id = ?",
                (user_id, card_id),
            )

    def get_user_selections(self, user_id: int, room: int = 30) -> List[Dict]:
        with self._session() as conn:
            rows = conn.execute(
                "SELECT * FROM card_selections WHERE user_id = ? AND room = ?",
                (user_id, room),
            ).fetchall()
            return [dict(r) for r in rows]

    def get_all_selections(self, room: int = 30) -> List[Dict]:
        with self._session() as conn:
            rows = conn.execute(
                "SELECT * FROM card_selections WHERE room = ?", (room,)
            ).fetchall()
            return [dict(r) for r in rows]

    def is_card_taken(self, card_id: str, room: int = 30) -> bool:
        with self._session() as conn:
            row = conn.execute(
                "SELECT user_id FROM card_selections WHERE card_id = ? AND room = ?",
                (card_id, room),
            ).fetchone()
            return row is not None

    def clear_selections(self, room: int = 30) -> None:
        with self._session() as conn:
            conn.execute("DELETE FROM card_selections WHERE room = ?", (room,))

    # ------------------------------------------------------------- called numbers
    def call_number(self, room: int, number: str) -> None:
        """Record one called ball (per-room unique)."""
        with self._session() as conn:
            conn.execute(
                "INSERT OR IGNORE INTO called_numbers (room, number) VALUES (?, ?)",
                (room, number),
            )

    def record_call(self, room: int, number: str, order: List[str]) -> None:
        """Record a called ball ATOMICALLY: new ball order + called_numbers row
        + current_call in a single transaction. Concurrent readers (the Mini
        App's /api/game-state) can never observe a called number with a stale
        or missing current_call (or vice versa) — the calling board always
        highlights the freshly drawn ball."""
        with self._session() as conn:
            conn.execute(
                "UPDATE game_state SET ball_order = ?, current_call = ?, "
                "updated_at = ? WHERE room = ?",
                (json.dumps(order), number, datetime.now().isoformat(), room),
            )
            conn.execute(
                "INSERT OR IGNORE INTO called_numbers (room, number) VALUES (?, ?)",
                (room, number),
            )

    def get_called_numbers(self, room: int = 30) -> List[str]:
        with self._session() as conn:
            rows = conn.execute(
                "SELECT number FROM called_numbers WHERE room = ? "
                "ORDER BY called_at, id", (room,)
            ).fetchall()
            return [r[0] for r in rows]

    def clear_called_numbers(self, room: int = 30) -> None:
        with self._session() as conn:
            conn.execute("DELETE FROM called_numbers WHERE room = ?", (room,))

    # --------------------------------------------------------------- ball machine
    def set_ball_order(self, room: int, order: List[str]) -> None:
        with self._session() as conn:
            conn.execute(
                "UPDATE game_state SET ball_order = ?, updated_at = ? WHERE room = ?",
                (json.dumps(order), datetime.now().isoformat(), room),
            )

    def get_ball_order(self, room: int = 30) -> List[str]:
        with self._session() as conn:
            row = conn.execute(
                "SELECT ball_order FROM game_state WHERE room = ?", (room,)
            ).fetchone()
            if not row or not row[0]:
                return []
            try:
                return json.loads(row[0])
            except (ValueError, TypeError):
                return []

    # --------------------------------------------------------------------- games
    def create_game(self, round_number: int, room: int = 30) -> int:
        with self._session() as conn:
            cur = conn.execute(
                "INSERT INTO games (room, round_number) VALUES (?, ?)", (room, round_number)
            )
            return int(cur.lastrowid)

    def finish_game(self, game_id: Optional[int], winner_user_id, winner_name,
                    winning_pattern, total_bets, prize_paid, house_kept, status) -> None:
        if game_id is None:
            return
        with self._session() as conn:
            conn.execute(
                "UPDATE games SET ended_at = ?, winner_user_id = ?, winner_name = ?, "
                "winning_pattern = ?, total_bets = ?, prize_paid = ?, house_kept = ?, status = ? "
                "WHERE id = ?",
                (datetime.now().isoformat(), winner_user_id, winner_name, winning_pattern,
                 total_bets, prize_paid, house_kept, status, game_id),
            )

    def game_stats(self) -> Dict:
        with self._session() as conn:
            row = conn.execute(
                "SELECT COUNT(*), COALESCE(SUM(total_bets),0), COALESCE(SUM(prize_paid),0), "
                "COALESCE(SUM(house_kept),0) FROM games WHERE status != 'running'"
            ).fetchone()
            real_winners = conn.execute(
                "SELECT COUNT(*) FROM games WHERE status = 'finished' AND winner_user_id > 0"
            ).fetchone()[0]
            return {
                "rounds": int(row[0]),
                "total_bets": int(row[1]),
                "prize_paid": int(row[2]),
                "house_kept": int(row[3]),
                "real_winners": int(real_winners),
            }

    def recent_games(self, limit: int = 10) -> List[Dict]:
        with self._session() as conn:
            rows = conn.execute(
                "SELECT * FROM games ORDER BY id DESC LIMIT ?", (limit,)
            ).fetchall()
            return [dict(r) for r in rows]

    # ------------------------------------------------------------------- history
    def add_history(self, game_id: Optional[int], user_id: int, card_ids: List[str],
                    total_bet: int, winnings: int, credit_after: int, status: str) -> None:
        with self._session() as conn:
            conn.execute(
                "INSERT INTO game_history (game_id, user_id, card_ids, total_bet, winnings, "
                "credit_after, status) VALUES (?, ?, ?, ?, ?, ?, ?)",
                (game_id, user_id, json.dumps(card_ids), total_bet, winnings,
                 credit_after, status),
            )

    def get_user_history(self, user_id: int, limit: int = 10) -> List[Dict]:
        with self._session() as conn:
            rows = conn.execute(
                "SELECT * FROM game_history WHERE user_id = ? ORDER BY id DESC LIMIT ?",
                (user_id, limit),
            ).fetchall()
            return [dict(r) for r in rows]

    def profile(self, user_id: int) -> Optional[Dict]:
        with self._session() as conn:
            row = conn.execute("SELECT * FROM profiles WHERE user_id = ?", (user_id,)).fetchone()
            return dict(row) if row else None

    # ------------------------------------------------------------------ wallet
    def add_transaction(self, user_id: int, type_: str, amount: int,
                        tx_id: Optional[str] = None, phone: Optional[str] = None,
                        user_name: Optional[str] = None,
                        account_id: Optional[int] = None,
                        provider: Optional[str] = None,
                        account_number: Optional[str] = None,
                        account_holder: Optional[str] = None) -> int:
        """Insert a deposit/withdraw request.

        The payment account info (provider / account_number / account_holder)
        and the user's full name are stored as SNAPSHOTS on the row, so later
        account edits never corrupt this transaction's history.
        """
        with self._session() as conn:
            cur = conn.execute(
                "INSERT INTO transactions (user_id, type, amount, tx_id, phone, "
                "user_name, payment_account_id, provider, account_number, "
                "account_holder) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (user_id, type_, amount, tx_id, phone, user_name, account_id,
                 provider, account_number, account_holder),
            )
            return int(cur.lastrowid)

    def get_user_transactions(self, user_id: int, limit: int = 30) -> List[Dict]:
        with self._session() as conn:
            rows = conn.execute(
                "SELECT * FROM transactions WHERE user_id = ? "
                "ORDER BY id DESC LIMIT ?", (user_id, limit),
            ).fetchall()
            return [dict(r) for r in rows]

    def get_all_transactions(self, limit: int = 300) -> List[Dict]:
        with self._session() as conn:
            rows = conn.execute(
                "SELECT * FROM transactions ORDER BY id DESC LIMIT ?", (limit,)
            ).fetchall()
            return [dict(r) for r in rows]

    def get_transaction(self, tx_id: int) -> Optional[Dict]:
        with self._session() as conn:
            row = conn.execute("SELECT * FROM transactions WHERE id = ?", (tx_id,)).fetchone()
            return dict(row) if row else None

    def review_transaction(self, tx_id: int, status: str,
                           admin_note: Optional[str] = None,
                           reviewed_by: Optional[int] = None) -> Optional[Dict]:
        """Mark a pending transaction approved/rejected. Only pending rows change."""
        with self._session() as conn:
            cur = conn.execute(
                "UPDATE transactions SET status = ?, admin_note = ?, "
                "reviewed_by = ?, reviewed_at = ? "
                "WHERE id = ? AND status = 'pending'",
                (status, admin_note, reviewed_by, datetime.now().isoformat(), tx_id),
            )
            if cur.rowcount == 0:
                return None
            row = conn.execute("SELECT * FROM transactions WHERE id = ?", (tx_id,)).fetchone()
            return dict(row) if row else None

    def set_transaction_status(self, tx_id: int, status: str,
                               reviewed_by: Optional[int] = None,
                               admin_note: Optional[str] = None) -> Optional[Dict]:
        """Set a transaction's status REGARDLESS of the current status.

        Used by the super admin when resolving an appeal: a deposit the admin
        rejected can still be approved on appeal (the user did pay after all).
        """
        with self._session() as conn:
            conn.execute(
                "UPDATE transactions SET status = ?, admin_note = ?, "
                "reviewed_by = ?, reviewed_at = ? WHERE id = ?",
                (status, admin_note, reviewed_by, datetime.now().isoformat(), tx_id),
            )
            row = conn.execute("SELECT * FROM transactions WHERE id = ?", (tx_id,)).fetchone()
            return dict(row) if row else None

    # ----------------------------------------------------------------- appeals
    def add_appeal(self, user_id: int, transaction_id: int,
                   reason: Optional[str] = None) -> int:
        """File a wallet appeal (a deposit the admin never approved)."""
        with self._session() as conn:
            cur = conn.execute(
                "INSERT INTO appeals (user_id, transaction_id, reason) "
                "VALUES (?, ?, ?)",
                (user_id, transaction_id, reason),
            )
            return int(cur.lastrowid)

    def get_appeal(self, appeal_id: int) -> Optional[Dict]:
        with self._session() as conn:
            row = conn.execute(
                "SELECT * FROM appeals WHERE id = ?", (appeal_id,)
            ).fetchone()
            return dict(row) if row else None

    def get_user_appeals(self, user_id: int, limit: int = 30) -> List[Dict]:
        with self._session() as conn:
            rows = conn.execute(
                "SELECT * FROM appeals WHERE user_id = ? "
                "ORDER BY id DESC LIMIT ?", (user_id, limit),
            ).fetchall()
            return [dict(r) for r in rows]

    def get_all_appeals(self, limit: int = 300) -> List[Dict]:
        """Every appeal joined with the user + the transaction details (super
        admin console)."""
        with self._session() as conn:
            rows = conn.execute(
                """
                SELECT a.*, p.full_name AS user_name, p.phone AS user_phone,
                       t.type AS tx_type, t.amount AS tx_amount,
                       t.status AS tx_status, t.provider AS tx_provider,
                       t.tx_id AS tx_ref, t.created_at AS tx_created_at
                FROM appeals a
                LEFT JOIN players p ON p.user_id = a.user_id
                LEFT JOIN transactions t ON t.id = a.transaction_id
                ORDER BY a.id DESC LIMIT ?
                """,
                (limit,),
            ).fetchall()
            return [dict(r) for r in rows]

    def resolve_appeal(self, appeal_id: int, status: str,
                       resolution: Optional[str] = None,
                       resolved_by: Optional[int] = None) -> Optional[Dict]:
        """Mark an appeal approved/rejected. Only pending appeals change."""
        with self._session() as conn:
            cur = conn.execute(
                "UPDATE appeals SET status = ?, resolution = ?, "
                "resolved_by = ?, resolved_at = ? "
                "WHERE id = ? AND status = 'pending'",
                (status, resolution, resolved_by, datetime.now().isoformat(), appeal_id),
            )
            if cur.rowcount == 0:
                return None
            row = conn.execute("SELECT * FROM appeals WHERE id = ?", (appeal_id,)).fetchone()
            return dict(row) if row else None

    # --------------------------------------------------------- notifications
    def add_bot_notification(self, chat_id: int, text: str) -> int:
        """Enqueue a Telegram message for the bot's announcer to send."""
        with self._session() as conn:
            cur = conn.execute(
                "INSERT INTO bot_notifications (chat_id, text) VALUES (?, ?)",
                (chat_id, text),
            )
            return int(cur.lastrowid)

    def get_unsent_bot_notifications(self, limit: int = 50) -> List[Dict]:
        with self._session() as conn:
            rows = conn.execute(
                "SELECT * FROM bot_notifications WHERE sent_at IS NULL "
                "ORDER BY id LIMIT ?", (limit,),
            ).fetchall()
            return [dict(r) for r in rows]

    def mark_bot_notification_sent(self, notif_id: int) -> None:
        with self._session() as conn:
            conn.execute(
                "UPDATE bot_notifications SET sent_at = ? WHERE id = ?",
                (datetime.now().isoformat(), notif_id),
            )

    # --------------------------------------------------------- payment accounts
    def add_payment_account(self, provider: str, account_name: str,
                            account_number: str, is_active: int = 1,
                            admin_id: Optional[int] = None) -> int:
        """Add a payment account. `admin_id` is the admin who owns it — only
        ONLINE owners' accounts are shown to users for deposits, and the
        owner's admin credit is charged when a deposit into it is approved."""
        with self._session() as conn:
            cur = conn.execute(
                "INSERT INTO payment_accounts (provider, account_name, "
                "account_number, is_active, admin_id) VALUES (?, ?, ?, ?, ?)",
                (provider, account_name, account_number, 1 if is_active else 0,
                 admin_id),
            )
            return int(cur.lastrowid)

    def get_deposit_accounts(self) -> List[Dict]:
        """Active payment accounts whose OWNER admin is currently ONLINE
        and has sufficient credit to cover a deposit, joined with the owner's
        name + credit. Ordered by credit DESC so the richest ONLINE admin
        comes first for every provider — the caller picks the first row
        per provider and that is the ONE account shown to the user.

        Only admins with enough credit (>= room bet) are included, so
        players never see an account whose admin can't cover the approval."""
        cutoff = (datetime.now() -
                  timedelta(minutes=config.ADMIN_ONLINE_MINUTES)).isoformat()
        # minimum credit an admin needs to cover any room's deposit
        min_credit = min(config.ROOM_BETS) if config.ROOM_BETS else 10
        with self._session() as conn:
            rows = conn.execute(
                """
                SELECT pa.*, p.full_name AS admin_name, p.credit AS admin_credit,
                       p.last_seen
                FROM payment_accounts pa
                JOIN players p ON p.user_id = pa.admin_id
                WHERE pa.is_active = 1 AND pa.admin_id IS NOT NULL
                  AND p.last_seen IS NOT NULL AND p.last_seen >= ?
                  AND p.credit >= ?
                ORDER BY p.credit DESC, pa.id
                """,
                (cutoff, min_credit),
            ).fetchall()
            return [dict(r) for r in rows]

    def get_payment_account(self, account_id: int) -> Optional[Dict]:
        with self._session() as conn:
            row = conn.execute(
                "SELECT * FROM payment_accounts WHERE id = ?", (account_id,)
            ).fetchone()
            return dict(row) if row else None

    def get_payment_accounts(self, active_only: bool = False) -> List[Dict]:
        sql = "SELECT * FROM payment_accounts"
        args: tuple = ()
        if active_only:
            sql += " WHERE is_active = 1"
        sql += " ORDER BY is_active DESC, id"
        with self._session() as conn:
            rows = conn.execute(sql, args).fetchall()
            return [dict(r) for r in rows]

    def update_payment_account(self, account_id: int, provider: Optional[str] = None,
                               account_name: Optional[str] = None,
                               account_number: Optional[str] = None,
                               is_active: Optional[bool] = None,
                               admin_id: Optional[int] = None) -> None:
        sets, vals = [], []
        if provider is not None:
            sets.append("provider = ?")
            vals.append(provider)
        if account_name is not None:
            sets.append("account_name = ?")
            vals.append(account_name)
        if account_number is not None:
            sets.append("account_number = ?")
            vals.append(account_number)
        if is_active is not None:
            sets.append("is_active = ?")
            vals.append(1 if is_active else 0)
        if admin_id is not None:
            sets.append("admin_id = ?")
            vals.append(admin_id)
        if not sets:
            return
        sets.append("updated_at = ?")
        vals.append(datetime.now().isoformat())
        vals.append(account_id)
        with self._session() as conn:
            conn.execute(f"UPDATE payment_accounts SET {', '.join(sets)} "
                         f"WHERE id = ?", vals)

    def delete_payment_account(self, account_id: int) -> None:
        with self._session() as conn:
            conn.execute("DELETE FROM payment_accounts WHERE id = ?", (account_id,))

    # ------------------------------------------------------------ eliminations
    def add_elimination(self, game_id: Optional[int], user_id: int,
                        reason: str = "false_bingo") -> None:
        if game_id is None:
            return
        with self._session() as conn:
            conn.execute(
                "INSERT OR IGNORE INTO round_eliminations (game_id, user_id, reason) "
                "VALUES (?, ?, ?)",
                (game_id, user_id, reason),
            )

    def get_eliminated_user_ids(self, game_id: Optional[int]) -> List[int]:
        if game_id is None:
            return []
        with self._session() as conn:
            rows = conn.execute(
                "SELECT user_id FROM round_eliminations WHERE game_id = ?",
                (game_id,),
            ).fetchall()
            return [r[0] for r in rows]

    def clear_eliminations(self) -> None:
        """Drop all elimination markers (called at each new round)."""
        with self._session() as conn:
            conn.execute("DELETE FROM round_eliminations")

    # ----------------------------------------------------------------- settings
    def get_setting(self, key: str, default: Optional[str] = None) -> Optional[str]:
        with self._session() as conn:
            row = conn.execute("SELECT value FROM settings WHERE key = ?", (key,)).fetchone()
            return row[0] if row else default

    def set_setting(self, key: str, value: Optional[str]) -> None:
        with self._session() as conn:
            conn.execute(
                "INSERT INTO settings (key, value) VALUES (?, ?) "
                "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
                (key, value),
            )

    # ------------------------------------------------------------ activity log
    def log_activity(self, action: str, user_id: Optional[int] = None,
                     details: Optional[str] = None) -> None:
        """Record a critical activity for the super admin activity log."""
        with self._session() as conn:
            conn.execute(
                "INSERT INTO activity_log (user_id, action, details) VALUES (?, ?, ?)",
                (user_id, action, details),
            )

    def get_activity_log(self, limit: int = 100) -> List[Dict]:
        """Recent activity log entries for the super admin console."""
        with self._session() as conn:
            rows = conn.execute(
                """
                SELECT a.*, p.full_name AS user_name, p.username
                FROM activity_log a
                LEFT JOIN players p ON p.user_id = a.user_id
                ORDER BY a.id DESC LIMIT ?
                """,
                (limit,),
            ).fetchall()
            return [dict(r) for r in rows]
