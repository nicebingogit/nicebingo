"""
PythonAnywhere WSGI entry point

This file is the entry point for PythonAnywhere's WSGI server. It:
  1. Loads environment variables from .env
  2. Runs database migration + card seeding (idempotent)
  3. Starts the game loop (APScheduler)
  4. Starts the Telegram bot in webhook mode
  5. Exposes the Flask app as `application`

IMPORTANT: Every time the codebase changes, this file must be updated to
match. PythonAnywhere caches WSGI modules — press Reload after every deploy.

update-in-every-change: yes
"""
import os
import sys
import logging
from pathlib import Path

from dotenv import load_dotenv

_HERE = Path(__file__).resolve().parent
load_dotenv(_HERE / ".env")

# --- Environment variables (defaults for PythonAnywhere) ---
os.environ.setdefault('BOT_TOKEN', '8813404978:AAHupEGJSdvEuaPmP9GRnZ7BOeOs0oZN4ac')
os.environ.setdefault('APP_URL', 'https://nicebingo.pythonanywhere.com')
os.environ.setdefault('BOT_WEBHOOK', '1')
os.environ.setdefault('SERVER_HOST', '0.0.0.0')
os.environ.setdefault('SERVER_PORT', '5000')
os.environ.setdefault('ADMIN_IDS', '')
os.environ.setdefault('SUPER_ADMIN_IDS', '5747372427,391347553,502672318,903313112,420938946,1512842545')

logger = logging.getLogger("wsgi")

# --- Step 1: Database migration + card seed ---
try:
    import migrate_db
    migrate_db.main()
except Exception as exc:
    logger.error("Migration failed: %s", exc)
    # Even if migration fails, try to seed cards directly as a fallback
    try:
        import config
        import cards_data
        from database import Database
        db = Database(config.DB_PATH)
        before = db.count_cards()
        if before < config.NUM_CARDS:
            for card in cards_data.ALL_CARDS:
                db.insert_card(card["id"], card["numbers"])
            logger.info("Fallback card seed: %d -> %d", before, db.count_cards())
    except Exception as fallback_exc:
        logger.error("Fallback card seed also failed: %s", fallback_exc)

# --- Step 2: Start the game loop ---
try:
    import server  # noqa: E402
    server.loop.start()
    logger.info("Game loop started from wsgi.py")
except Exception as exc:
    logger.error("Game loop start failed: %s", exc)

# --- Step 3: Start the Telegram bot (webhook mode) ---
if os.getenv("BOT_WEBHOOK", "0").strip().lower() in ("1", "true", "yes"):
    try:
        import bot  # noqa: E402
        bot.start_webhook()
    except Exception as _bot_exc:
        logger.error("Bot webhook startup failed: %s", _bot_exc)

# --- Step 4: Expose the Flask app ---
from server import app as application  # noqa: E402
