# Bingo Royale — cloud image
#
# Runs the Flask game server (server.py) AND the Telegram bot (bot.py) inside
# ONE container. They share a single SQLite file (config.DB_PATH), so they must
# always run on the same machine / volume — never in separate containers.
#
# The pre-built Mini App is committed in frontend/dist, so no Node build step
# is needed. All Python deps are pinned with prebuilt wheels for Python 3.11,
# so no compiler is required either.
FROM python:3.11-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    TZ=Africa/Addis_Ababa \
    SERVER_HOST=0.0.0.0 \
    SERVER_PORT=5000 \
    DB_PATH=/data/bingo_bot.db

# tzdata so round timestamps use East Africa Time (UTC+3)
RUN apt-get update \
    && apt-get install -y --no-install-recommends tzdata \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# copy the rest of the repo (see .dockerignore for what is excluded:
# .env, *.db, venv, node_modules, tools/, seller_package/, ...)
COPY . .

EXPOSE 5000

# migrate/seed (idempotent) then run server + bot under the supervisor
CMD ["python", "run_prod.py"]
