"""
PythonAnywhere WSGI entry point
"""
import os
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

import migrate_db
import server  # noqa: E402

migrate_db.main()
server.loop.start()

if os.getenv("BOT_WEBHOOK", "0").strip().lower() in ("1", "true", "yes"):
    try:
        import bot  # noqa: E402
        bot.start_webhook()
    except Exception as _bot_exc:
        import logging as _log
        _log.getLogger("wsgi").error("Bot webhook startup failed: %s", _bot_exc)

from server import app as application  # noqa: E402
