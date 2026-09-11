"""
Automated housekeeping for the Bingo database (windows into db_size).

Runs on boot (from wsgi.py) and on a repeating scheduler interval:

  1. low-disk guard        — never WRITE when free space is below
                            MAINTENANCE_MIN_FREE_MB (writing on a full disk is
                            exactly what corrupted the production DB in Sep 2026)
  2. integrity probe       — abandoned + damage marker if the file is damaged
  3. daily backup snapshot — kept to DB_BACKUP_KEEP copies
  4. corrupt player rows   — cleans the garbage rows whose credit showed a
                            timestamp / username showed a random number
  5. stale-room purge      — drops game_state rows for rooms not in ROOM_BETS
  6. history pruning       — old games / game_history / activity_log / balls
  7. WAL checkpoint        — TRUNCATE so trimmed rows actually free disk space

The whole pass is defensive: every step is guarded so one failing table never
stops the rest, and a damaged DB is never written to.

update-in-every-change: yes
"""
import os
from datetime import datetime

import config


def run(db=None, reason="boot", force_backup: bool = False, log=True) -> dict:
    """One full maintenance pass. Safe to call from ANY thread/process —
    creates its own Database connection when none is given so the running
    server's connection is never shared. Returns a summary dict."""
    if db is None:
        from database import Database
        db = Database(config.DB_PATH)
    summary: dict = {"reason": reason}
    try:
        free_mb = db.available_disk_mb()
        summary["disk_free_mb"] = round(free_mb, 1)
        if free_mb < float(getattr(config, "MAINTENANCE_MIN_FREE_MB", 25.0)):
            msg = (f"aborted: only {free_mb:.0f} MB free on the DB volume "
                   f"(min {config.MAINTENANCE_MIN_FREE_MB:g} MB) — not touching "
                   f"the database to avoid corruption")
            print(f"[maintenance] ABORT — {msg}", flush=True)
            if log:
                db.log_activity("maintenance", details=msg)
            summary["aborted"] = True
            return summary

        ok, integrity_msg = db.check_integrity()
        summary["integrity"] = integrity_msg
        marker = config.DB_PATH + ".damaged"
        if not ok:
            with open(marker, "w", encoding="utf-8") as fh:
                fh.write(f"{datetime.now().isoformat()} {integrity_msg}")
            print(f"[maintenance] CRITICAL — integrity check: {integrity_msg}. "
                  f"App runs degraded until a backup is restored.", flush=True)
            try:
                db.log_activity("maintenance",
                                details=f"integrity FAILED: {integrity_msg} — damage "
                                        f"marker written, pruning skipped; restore "
                                        f"from the newest backup in "
                                        f"{config.DB_BACKUP_DIR}")
            except Exception:
                pass
            summary["damaged"] = True
            return summary
        if os.path.exists(marker):
            os.remove(marker)

        # Daily backup snapshot (one per day, old ones pruned by keep-count).
        last = db.get_setting("last_backup_at", "") or ""
        today = datetime.now().strftime("%Y-%m-%d")
        if force_backup or last != today:
            saved = db.backup_database(reason)
            if saved:
                db.set_setting("last_backup_at", today)
                summary["backup"] = saved
            else:
                summary["backup"] = "FAILED"

        # Fix the visible garbage rows (credit=timestamp, numeric usernames).
        summary["corrupt_rows_cleaned"] = db.clean_corrupt_player_rows()

        # Drop game_state rows for rooms deleted from ROOM_BETS.
        summary["rooms_purged"] = db.purge_unconfigured_rooms()

        # Prune old history so the file stops growing forever.
        summary["pruned"] = db.prune_history()

        # Return trimmed pages to the disk (tiny free-tier quota).
        summary["wal_checkpoint"] = db.wal_checkpoint()

        db.set_setting("last_maintenance_at", datetime.now().isoformat())
        print(f"[maintenance] ok({reason}) {summary}", flush=True)
    except Exception as exc:
        print(f"[maintenance] FAILED: {exc}", flush=True)
        summary["error"] = str(exc)
        try:
            if log:
                db.log_activity("maintenance", details=f"maintenance FAILED: {exc}")
        except Exception:
            pass
    return summary


def schedule(scheduler) -> bool:
    """Attach the repeating maintenance job to the running game loop scheduler.
    Returns True if the job was (re)scheduled."""
    try:
        scheduler.add_job(
            run,
            "interval",
            minutes=getattr(config, "MAINTENANCE_INTERVAL_MIN", 360),
            id="maintenance",
            max_instances=1,
            coalesce=True,
            kwargs={"reason": "interval"},
        )
        return True
    except Exception as exc:
        print(f"[maintenance] interval job not scheduled: {exc}", flush=True)
        return False