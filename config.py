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
APP_URL = os.getenv("APP_URL", f"http://localhost:{SERVER_PORT}")

# ---------------------------------------------------------------------------
# Storage
# ---------------------------------------------------------------------------
DB_PATH = os.getenv("DB_PATH", "bingo_bot.db")

# ---------------------------------------------------------------------------
# Economy (ETB — Ethiopian Birr)
# ---------------------------------------------------------------------------
APP_CURRENCY = os.getenv("APP_CURRENCY", "ETB").strip()  # wallet currency symbol
# Rooms are separated by a FIXED bet per card: each room runs its own round
# with its own ball order, selections and prize pool. Players pick a room via
# a listbox in the Mini App; the bet input is gone.
ROOM_BETS = [int(x.strip()) for x in os.getenv("ROOM_BETS", "10,20,30").split(",") if x.strip()]
if not ROOM_BETS:
    ROOM_BETS = [10, 20, 30]
ROOM_DEFAULT = ROOM_BETS[0]                         # room used when none is specified
BET_PER_CARD = ROOM_DEFAULT                         # legacy alias: default room bet
BET_MIN_CARD = ROOM_DEFAULT                         # legacy alias: bet is fixed per room
MAX_CARDS_PER_PLAYER = _int("MAX_CARDS_PER_PLAYER", 3)  # max cards per player per round
NEW_PLAYER_CREDIT = _int("NEW_PLAYER_CREDIT", 50)  # welcome coins
MIN_WITHDRAWAL = _int("MIN_WITHDRAWAL", 100)      # minimum withdraw request (ETB)
PRIZE_PERCENT = _float("PRIZE_PERCENT", 0.8)        # 80% of the pool goes to the winner
BOTS_CONTRIBUTE_TO_POOL = True                      # bot bets also feed the pool


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

# ---------------------------------------------------------------------------
# Players / bots
# ---------------------------------------------------------------------------
MIN_TOTAL_PLAYERS = _int("MIN_TOTAL_PLAYERS", 18)   # minimum total players (real + bots) per room
MAX_TOTAL_PLAYERS = _int("MAX_TOTAL_PLAYERS", 90)   # maximum total players (real + bots) per room
NUM_CARDS = _int("NUM_CARDS", 400)                  # pre-generated card pool

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
