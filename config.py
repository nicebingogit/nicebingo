"""
Central configuration for the Telegram Bingo system (bot + local web server).

Every value can be overridden through environment variables (see .env.example),
so you never need to touch this file to run the system.
"""
import hashlib
import os
 

def _int(name: str, default: int) -> int:
    try:
        return int(os.getenv(name, str(default)))
    except ValueError:
        return default
 

def _float(name: str, default: float) -> float:
    try:
        return float(os.getenv(name, str(default)))
    except ValueError:
        return default


def _bool(name: str, default: bool) -> bool:
    return os.getenv(name, str(default)).strip().lower() in ("1", "true", "yes", "on")


# ---------------------------------------------------------------------------
# Telegram   
# ---------------------------------------------------------------------------
BOT_TOKEN = os.getenv("BOT_TOKEN", "").strip()
# BOT_WEBHOOK=1 switches the bot from polling to webhook mode. Used on always-on
# hosts (e.g. PythonAnywhere) whose free tier cannot run background processes:
# Telegram POSTs updates to APP_URL/webhook/<secret>, which the Flask server
# forwards to the in-process bot. Local/desktop usage keeps polling (default).
BOT_WEBHOOK = _bool("BOT_WEBHOOK", False)
# Secret path segment for the webhook endpoint. Derived from the bot token so
# nobody can guess it; override with BOT_WEBHOOK_SECRET if you want your own.
WEBHOOK_SECRET = os.getenv("BOT_WEBHOOK_SECRET", "").strip()
if not WEBHOOK_SECRET:
    WEBHOOK_SECRET = hashlib.sha256(BOT_TOKEN.encode()).hexdigest()[:24] if BOT_TOKEN else "dev-secret"
# ADMIN_IDS: comma separated numeric ids, inline "# comments" are allowed.
ADMIN_IDS: list[int] = []
for part in os.getenv("ADMIN_IDS", "").split(","):
    part = part.split("#")[0].strip() 
    if part:
        try:
            ADMIN_IDS.append(int(part))
        except ValueError:
            pass

# SUPER_ADMIN_IDS: comma-separated list of Telegram user IDs that have full
# super-admin privileges — every account (admin or user), every transaction
# log, admin credits (selling credit to admins), and wallet appeals.
# No hardcoded fallbacks — set SUPER_ADMIN_IDS or SUPER_ADMIN_ID in .env
SUPER_ADMIN_IDS: list[int] = []
for part in os.getenv("SUPER_ADMIN_IDS", "").split(","):
    part = part.split("#")[0].strip()
    if part:
        try:
            SUPER_ADMIN_IDS.append(int(part))
        except ValueError:
            pass
if not SUPER_ADMIN_IDS:
    # fallback: single SUPER_ADMIN_ID env var (legacy)
    single = _int("SUPER_ADMIN_ID", 0)
    if single:
        SUPER_ADMIN_IDS = [single]
if not SUPER_ADMIN_IDS:
    print("[config] WARNING: no SUPER_ADMIN_IDS configured — set them in .env "
          "(comma-separated Telegram numeric ids). Without one there is no "
          "super administrator.", flush=True)
# backward compat: code that uses SUPER_ADMIN_ID still works
SUPER_ADMIN_ID = SUPER_ADMIN_IDS[0] if SUPER_ADMIN_IDS else 0
# ADMIN_APPROVAL_RATE: the share of a DEPOSIT amount that is deducted from the
# account-owner admin's credit when the deposit is approved (0.9 = 90%). The
# same rate is credited BACK to the reviewing admin when a WITHDRAW is
# approved (the admin pays the money out for real).
ADMIN_APPROVAL_RATE = _float("ADMIN_APPROVAL_RATE", 0.9)
# ADMIN_ONLINE_MINUTES: how many minutes of recent activity keep an admin
# "online". Only ONLINE admins' payment accounts are shown to users for
# deposits, and the system picks the online admin with the MOST admin credit
# per bank/provider.
ADMIN_ONLINE_MINUTES = _int("ADMIN_ONLINE_MINUTES", 5)
# REFERRAL_COMMISSION_RATE: share of a referred player's total bet that
# the referring admin earns as commission each round (0.05 = 5%).
REFERRAL_COMMISSION_RATE = _float("REFERRAL_COMMISSION_RATE", 0.05)

# ---------------------------------------------------------------------------
# Local web server (Flask) that hosts the Mini App + API
# ---------------------------------------------------------------------------
SERVER_HOST = os.getenv("SERVER_HOST", "127.0.0.1")
SERVER_PORT = _int("SERVER_PORT", 5000)
# Public URL of the Mini App. localhost works in Telegram for testing on the
# same machine; use an ngrok / Cloudflare tunnel HTTPS url for your phone.
APP_URL = os.getenv("APP_URL", f"http://localhost:{SERVER_PORT}")# ---------------------------------------------------------------------------
# Storage
# ---------------------------------------------------------------------------
# The database MUST live outside the code folder.  A deploy that copies the
# project (zip / folder copy — which carries the gitignored *.db files that sit
# next to the code) silently replaces the live database, and every real account
# with it.  Set an absolute path outside the project in .env:
#     DB_PATH=/home/youruser/bingo_data/bingo_bot.db
# A relative value is still accepted for backward compatibility, but it is
# resolved against the PROJECT folder (not the current working directory), so
# the same database is used no matter where the app is launched from.
_PROJECT_DIR = os.path.dirname(os.path.abspath(__file__))
DB_PATH = (os.getenv("DB_PATH", "") or "bingo_bot.db").strip() or "bingo_bot.db"
if not os.path.isabs(DB_PATH):
    DB_PATH = os.path.join(_PROJECT_DIR, DB_PATH)
DB_PATH = os.path.abspath(DB_PATH)
# True while the database still sits inside the code folder — warned about at
# startup because a project-copy deploy would overwrite it (see move_db.py).
DB_PATH_INSIDE_PROJECT = DB_PATH.startswith(_PROJECT_DIR + os.sep)

# ---------------------------------------------------------------------------
# Economy (ETB — Ethiopian Birr)
# ---------------------------------------------------------------------------
APP_CURRENCY = os.getenv("APP_CURRENCY", "ETB").strip()  # wallet currency symbol
# Rooms are separated by a FIXED bet per card: each room runs its own round
# with its own ball order, selections and prize pool. The production game runs
# exactly ONE room — "Room by 10" (10 ETB per card). Set ROOM_BETS in .env to
# change it, e.g. ROOM_BETS=50 for a single 50 ETB room.
ROOM_BETS = [int(x.strip()) for x in os.getenv("ROOM_BETS", "10").split(",") if x.strip()]
if not ROOM_BETS:
    ROOM_BETS = [10]
ROOM_DEFAULT = ROOM_BETS[0]                         # room used when none is specified
BET_PER_CARD = ROOM_DEFAULT                         # legacy alias: default room bet
BET_MIN_CARD = ROOM_DEFAULT                         # legacy alias: bet is fixed per room
MAX_CARDS_PER_PLAYER = _int("MAX_CARDS_PER_PLAYER", 3)  # max cards per player per round
NEW_PLAYER_CREDIT = _int("NEW_PLAYER_CREDIT", 15)  # welcome coins
MIN_WITHDRAWAL = _int("MIN_WITHDRAWAL", 100)      # minimum withdraw request (ETB)
PRIZE_PERCENT = _float("PRIZE_PERCENT", 0.8)        # 80% of the pool goes to the winner
BOTS_CONTRIBUTE_TO_POOL = True                      # bot bets also feed the pool


# ---------------------------------------------------------------------------
# Maintenance & reliability (auto housekeeping so the DB never fills the disk)
# ---------------------------------------------------------------------------
# The database prunes old games / activity / called balls after this many days
# (smaller = smaller file = less risk of the disk-full corruption of Sep 2026).
# A fixed number of the newest rows is ALWAYS kept for live display, and
# running rounds are never touched.
PRUNE_HISTORY_DAYS = _int("PRUNE_HISTORY_DAYS", 30)
# Closed rounds kept for display regardless of age (recent-games lists).
PRUNE_KEEP_LATEST_ROWS = _int("PRUNE_KEEP_LATEST_ROWS", 500)
# Daily sqlite3.online backup snapshot of the whole database is written here
# (absolute path recommended) and only the newest DB_BACKUP_KEEP copies kept.
DB_BACKUP_DIR = os.getenv("DB_BACKUP_DIR", "").strip() or os.path.join(_PROJECT_DIR, "backups")
DB_BACKUP_KEEP = _int("DB_BACKUP_KEEP", 14)
# How often the scheduled maintenance job runs (minutes), plus the interval
# job id used by wsgi.py / game_loop.py.
MAINTENANCE_INTERVAL_MIN = _int("MAINTENANCE_INTERVAL_MIN", 360)
# Maintenance forbids writing once fewer than this many MB are free — writing
# on a full disk is exactly what corrupts SQLite, so it stops instead.
MAINTENANCE_MIN_FREE_MB = _float("MAINTENANCE_MIN_FREE_MB", 25.0)


def room_label(room: int) -> str:
    """User-facing name for a room, e.g. 30 -> 'Room by 30'."""
    return f"Room by {room}"

# ---------------------------------------------------------------------------
# Game timing (seconds)
# ---------------------------------------------------------------------------
PREPARATION_SECONDS = _int("PREPARATION_SECONDS", 40)      # between rounds
CALL_INTERVAL_SECONDS = _int("CALL_INTERVAL_SECONDS", 4)   # between called numbers
# How often the server-side game loop wakes up. 1 = real-time (local / Docker).
# On throttled free hosts (PythonAnywhere) set TICK_INTERVAL=3 to cut CPU ~3x;
# ball calls still land on their CALL_INTERVAL_SECONDS schedule, just with a
# tick of extra jitter. Also lower MAX_TOTAL_PLAYERS (fewer bots) there.
TICK_INTERVAL = _int("TICK_INTERVAL", 1)
POST_GAME_RESET_SECONDS = _int("POST_GAME_RESET_SECONDS", 15)  # winner screen
END_GAME_RESET_SECONDS = _int("END_GAME_RESET_SECONDS", 10)     # forced stop
TOTAL_NUMBERS = 75                                          # a bingo set
# Minimum number of balls that must be called before a round can END. A valid
# BINGO pattern claimed before this is kindly refused (never a punishment) and
# the round keeps running; false BINGO (no pattern) still eliminates regardless,
# so nobody can cheat the game to end early. 10 = one complete row (5) plus 5
# more balls, which keeps every round long enough to be a real game.
MIN_CALLS_BEFORE_WIN = _int("MIN_CALLS_BEFORE_WIN", 10)

# ---------------------------------------------------------------------------
# Players / bots
# ---------------------------------------------------------------------------
# Legacy total-player aliases (informational only — the live fill logic below
# sums real + bot players per room, so these just describe the overall range).
MIN_TOTAL_PLAYERS = _int("MIN_TOTAL_PLAYERS", 18)   # minimum total players (real + bots)
MAX_TOTAL_PLAYERS = _int("MAX_TOTAL_PLAYERS", 140)  # maximum total players (real + bots)
# How many bot players AND how many cards each bot holds are RE-ROLLED EVERY
# ROUND. The bot-player count is chosen by the NUMBER OF HUMAN players in the
# room, then randomized inside that option's range:
#   humans <= 1        -> Option 1: 80-140 bots, 1-3 cards each
#   2 <= humans <= 5   -> Option 2: 40-79  bots, 1-3 cards each
#   humans >= 6        -> Option 3: 18-39  bots, 1-3 cards each
# Each tuple: (max_humans, min_bots, max_bots, min_cards, max_cards).
# max_humans None means the option catches every larger human count. Pure
# constants (not env-driven) so a deployed environment can never distort the
# required ranges. Per-bot cards are randomized inside (min_cards, max_cards),
# and the TOTAL is clamped to the card pool so the deck is never exhausted.
BOT_OPTIONS = (
    (1, 80, 140, 1, 3),
    (5, 40, 79, 1, 3),
    (None, 18, 39, 1, 3),
)
# LEGACY — no longer used by the game loop. Rounds are NOT shortened to make
# a bot win: every difficulty other than Impossible plays a standard bingo
# game (winner only on a valid BINGO claim; the round ends winless after all
# 75 balls if nobody claims). Only Impossible (difficulty 5) hands a win to a
# bot — and it never shortens the game either. Kept for config compatibility.
BOT_GUARANTEED_WIN_AFTER = _int("BOT_GUARANTEED_WIN_AFTER", 64)
NUM_CARDS = _int("NUM_CARDS", 400)                  # pre-generated card pool
# BOT-HISTORY RETENTION — how many FINISHED games of bot-created rows to keep.
# Every round invents ~80-140 brand-new random bot accounts (players rows with
# negative ids) plus one `bots` roster row each; without cleanup those
# accumulate forever and the DB file grows without bound. This knobs how many
# finished games' worth of BOT rows survive before the next prune (5-20
# recommended). HUMAN history (game_history, transactions, accounts) is NEVER
# touched — bots are recognised by negative user ids only.
BOT_HISTORY_KEEP_GAMES = _int("BOT_HISTORY_KEEP_GAMES", 10)

# ---------------------------------------------------------------------------
# Telegram bot notifications (the bot only announces; the server runs the game)
# ---------------------------------------------------------------------------
ANNOUNCE_NUMBERS = _bool("ANNOUNCE_NUMBERS", False)  # announce every ball in chat (OFF = quiet; the Mini App is the main UI)
ANNOUNCE_ROUNDS = _bool("ANNOUNCE_ROUNDS", True)     # announce round start / winner in chat
ANNOUNCER_INTERVAL = 1.5                            # seconds between state polls

# ---------------------------------------------------------------------------
# Card image theme (used by card_generator.py)
# ---------------------------------------------------------------------------
CARD_THEME = {
    "background_top": (13, 15, 34),
    "background_bottom": (24, 27, 55),
    "cell_idle": (32, 35, 66),
    "cell_idle_border": (66, 71, 122),
    "cell_called": (56, 28, 40),
    "cell_called_border": (122, 62, 72),
    "cell_free": (50, 46, 98),
    "cell_free_border": (125, 114, 205),
    "text_idle": (240, 242, 255),
    "accent_gold": (255, 213, 79),
    "called_glow": (255, 82, 96),
    "win_glow": (255, 215, 96),
    "footer_text": (150, 155, 190),
    "footer_brand": (112, 118, 156),
    "header_colors": {
        "B": (255, 82, 105),
        "I": (105, 240, 174),
        "N": (255, 213, 79),
        "G": (64, 196, 255),
        "O": (224, 64, 251),
    },
}
