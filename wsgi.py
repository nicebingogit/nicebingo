"""
PythonAnywhere (free) WSGI entry point — runs the whole system 24/7 with no PC.

How it works on always-on hosts whose free tier cannot run background
processes (PythonAnywhere):

  * This file is the WSGI application PythonAnywhere serves.
  * The Flask app (server.py) serves the Mini App + JSON API, and the game
    loop (APScheduler) runs INSIDE the same web process — always-on, never
    sleeping, exactly like `python server.py` on your PC.
  * With BOT_WEBHOOK=1 the Telegram bot runs in webhook mode in this same
    process: Telegram POSTs updates to APP_URL/webhook/<secret>, server.py
    forwards them to the bot, and the bot answers / announces normally.
  * SQLite (bingo_bot.db in the project home dir) persists everything.

PythonAnywhere web app configuration:
  * Code → WSGI configuration file → /home/<user>/2xbingo/wsgi.py
  * Virtualenv → /home/<user>/2xbingo/venv
  * Environment variables (Web tab):
      BOT_TOKEN=...              ADMIN_IDS=...
      APP_URL=https://<user>.pythonanywhere.com
      BOT_WEBHOOK=1              SERVER_HOST=0.0.0.0   (DB_PATH optional)

Run locally (testing):  python -c "import wsgi"
"""
import os
from pathlib import Path

from dotenv import load_dotenv

# Load .env from THIS file's directory. A bare load_dotenv() searches the
# process working directory, which on PythonAnywhere is /home/<user> (uWSGI
# is treated as "interactive" so dotenv falls back to os.getcwd()). It would
# silently miss 2xbingo/.env, BOT_WEBHOOK would stay unset, and the bot would
# never start — exactly the bug this explicit path fixes.
_HERE = Path(__file__).resolve().parent
load_dotenv(_HERE / ".env")

import migrate_db
import server  # noqa: E402  (defines app, db, game loop; reads .env above)

# idempotent migration + card seed (same as run_prod.py does before booting)
migrate_db.main()

# start the game loop (idempotent — safe across WSGI reloads)
server.loop.start()

# always-on hosts run the bot in webhook mode inside this same process
if os.getenv("BOT_WEBHOOK", "0").strip().lower() in ("1", "true", "yes"):
    import bot  # noqa: E402
    bot.start_webhook()

from server import app as application  # noqa: E402
