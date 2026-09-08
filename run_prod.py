#!/usr/bin/env python3
"""
Production supervisor for the cloud image (see Dockerfile).

Runs the Flask game server (server.py) and the Telegram bot (bot.py) in the
same container. They share one SQLite file (config.DB_PATH), so they must run
on the same machine / volume — never in separate containers.

Behaviour:
  * runs migrate_db.py first (idempotent migration + card seed)
  * starts both processes and streams their logs with a [server]/[bot] prefix
  * restarts a crashed process with exponential backoff (1s, 2s, 4s, ... capped
    at 30s) so a temporary error never causes a tight restart loop
  * gives up on a process that crashes 5 times in a row within ~30s and keeps
    the other one running (e.g. a missing BOT_TOKEN stops only the bot)
  * forwards SIGTERM/SIGINT to both children and exits cleanly (platforms such
    as Northflank send SIGTERM on redeploys / restarts)

Run:  python run_prod.py
"""
import logging
import os
import signal
import subprocess
import sys
import threading
import time

logging.basicConfig(
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    level=logging.INFO,
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger("supervisor")

PY = sys.executable or "python"

# Children inherit our environment, but always run unbuffered so their logs
# stream into ours in real time (Docker sets this too, this is belt & braces).
CHILD_ENV = {**os.environ, "PYTHONUNBUFFERED": "1"}

# (name, command) — both processes, in this order
PROCESSES = [
    ("server", [PY, "server.py"]),
    ("bot", [PY, "bot.py"]),
]

MAX_CONSECUTIVE_FAILURES = 5   # give up on a process after this many quick crashes
QUICK_FAIL_WINDOW = 30.0       # a crash within this uptime counts as a "quick" failure
BACKOFF_MAX = 30.0             # cap the restart delay (seconds)

children = {}   # name -> {"proc": Popen, "failed": int, "uptime": float}
streams = {}    # name -> pump thread


def _start(name: str, cmd: list) -> subprocess.Popen:
    logger.info("starting %s: %s", name, " ".join(cmd))
    return subprocess.Popen(
        cmd,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        bufsize=1,
        env=CHILD_ENV,
    )


def _stream(name: str, proc: subprocess.Popen) -> threading.Thread:
    """Copy the child's stdout into our own log with a [name] prefix."""

    def pump():
        try:
            for line in proc.stdout:
                line = line.rstrip("\n")
                if line:
                    print(f"[{name}] {line}", flush=True)
        except Exception:
            pass

    t = threading.Thread(target=pump, daemon=True)
    t.start()
    return t


def _cmd_for(name: str) -> list:
    return dict(PROCESSES)[name]


def main() -> int:
    logger.info("running migrate_db.py (idempotent migration + card seed)")
    subprocess.run([PY, "migrate_db.py"], check=False, env=CHILD_ENV)

    for name, _cmd in PROCESSES:
        proc = _start(name, _cmd)
        children[name] = {"proc": proc, "failed": 0, "uptime": time.time()}
        streams[name] = _stream(name, proc)

    stopping = {"flag": False}

    def _stop(signum=None, _frame=None):
        if stopping["flag"]:
            return
        stopping["flag"] = True
        if signum is not None:
            logger.info("received %s — stopping children", signal.Signals(signum).name)
        else:
            logger.info("stopping children")
        for name, info in children.items():
            proc = info["proc"]
            if proc.poll() is None:
                logger.info("sending SIGTERM to %s", name)
                proc.terminate()
        deadline = time.time() + 10
        for name, info in children.items():
            proc = info["proc"]
            if proc.poll() is None:
                remaining = max(0.1, deadline - time.time())
                try:
                    proc.wait(timeout=remaining)
                except subprocess.TimeoutExpired:
                    logger.warning("[%s] did not stop in time — killing", name)
                    proc.kill()
        logger.info("supervisor exiting")

    signal.signal(signal.SIGTERM, _stop)
    signal.signal(signal.SIGINT, _stop)

    while not stopping["flag"]:
        time.sleep(2)
        for name, info in list(children.items()):
            proc = info["proc"]
            code = proc.poll()
            if code is None:
                continue
            uptime = time.time() - info["uptime"]
            if uptime < QUICK_FAIL_WINDOW:
                info["failed"] += 1
            else:
                info["failed"] = 0  # ran fine for a while → reset the counter
            logger.warning(
                "[%s] exited with code %s (uptime %.1fs, failures %d/%d)",
                name, code, uptime, info["failed"], MAX_CONSECUTIVE_FAILURES,
            )
            if info["failed"] >= MAX_CONSECUTIVE_FAILURES:
                logger.error(
                    "[%s] crashed %d times quickly — giving up on it; "
                    "the other processes keep running",
                    name, MAX_CONSECUTIVE_FAILURES,
                )
                del children[name]
                continue
            delay = min(BACKOFF_MAX, 2 ** (info["failed"] - 1))
            logger.info("[%s] restarting in %.0fs", name, delay)
            time.sleep(delay)
            if stopping["flag"]:
                break
            new_proc = _start(name, _cmd_for(name))
            children[name] = {"proc": new_proc, "failed": info["failed"],
                              "uptime": time.time()}
            streams[name] = _stream(name, new_proc)

    for t in streams.values():
        t.join(timeout=1)
    return 0


if __name__ == "__main__":
    sys.exit(main())
