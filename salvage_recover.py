"""Salvage + autoclean + verify for the 2026-09 corruption incident.

Reads ONLY from the live DB `SRC` (attached read-only), writes a fresh compact
`OUT` database containing every still-readable data table. The two tables that
were malformed and are 100% regenerable (`bots`, `card_selections`) are skipped
— their schema is recreated by migrate_db on the next boot. Corrupted player
rows (credit holding a timestamp, is_registered outside 0/1, negative-number
username on a positive id) are dropped and listed. Verifies OUT with
integrity_check and prints a human + transaction + history census.

Safe to run while the game is playing (read-only on SRC). Does NOT touch SRC.
Change SRC/OUT at the top (or set SALVAGE_SRC / SALVAGE_OUT) if your layout
differs. Run:
    python3 salvage_recover.py
"""
import datetime
import json
import os
import sys

SRC = os.getenv("SALVAGE_SRC", "/home/nicebingo/bingo_bot.db")
OUT = os.getenv("SALVAGE_OUT", "/home/nicebingo/db_rescue2/recovered.db")

import sqlite3

SKIP_TABLES = {"bots", "card_selections", "sqlite_sequence"}

PLAYER_JUNK_SQL = (
    "typeof(credit) != 'integer' "
    "OR is_registered NOT IN (0,1) "
    "OR (username IS NOT NULL AND CAST(username AS TEXT) GLOB '-[0-9]*')"
)


def main() -> int:
    os.makedirs(os.path.dirname(OUT) or ".", exist_ok=True)
    if os.path.exists(OUT):
        os.remove(OUT)

    dst = sqlite3.connect(OUT, timeout=30, uri=True)
    report = {"source": SRC, "date": datetime.datetime.now().isoformat(),
              "tables": {}, "junk_players_removed": [], "errors": []}
    try:
        dst.execute(f"ATTACH DATABASE 'file:{SRC.replace(chr(92), '/')}?mode=ro' AS sf")
        tables = [r[0] for r in dst.execute(
            "SELECT name FROM sf.sqlite_master WHERE type='table' "
            "AND name NOT LIKE 'sqlite_stat%' ORDER BY name")]

        for t in tables:
            if t in SKIP_TABLES:
                report["tables"][t] = "skipped (regenerable, was malformed)"
                continue
            try:
                row = dst.execute(
                    "SELECT sql FROM sf.sqlite_master WHERE name=? AND type='table'",
                    (t,)).fetchone()
                ddl = row[0] if row else None
                if ddl:
                    dst.execute(ddl)
                else:
                    cols = [r[1] for r in dst.execute(f"PRAGMA table_info(\"{t}\")")]
                    dst.execute("CREATE TABLE \"" + t + "\" (" +
                                ", ".join('"%s"' % c for c in cols) + ")")
                if t == "players":
                    doomed = dst.execute(
                        "SELECT user_id, username, full_name, credit, is_registered "
                        f"FROM sf.\"{t}\" WHERE user_id > 0 AND ({PLAYER_JUNK_SQL})"
                    ).fetchall()
                    report["junk_players_removed"] = [tuple(r) + () for r in doomed]
                    cur = dst.execute(
                        f"INSERT INTO \"{t}\" SELECT * FROM sf.\"{t}\" "
                        f"WHERE NOT ({PLAYER_JUNK_SQL})")
                    report["tables"][t] = cur.rowcount
                else:
                    cur = dst.execute(f"INSERT INTO \"{t}\" SELECT * FROM sf.\"{t}\"")
                    report["tables"][t] = cur.rowcount
            except (sqlite3.OperationalError, sqlite3.DatabaseError) as exc:
                report["errors"].append(f"{t}: {exc}")
                report["tables"][t] = f"UNREADABLE: {exc}"

        dst.commit()
        dst.execute("DETACH DATABASE sf")
        try:
            dst.execute(
                "INSERT INTO settings (key, value) VALUES ('salvage_note', ?) "
                "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
                (json.dumps({"date": datetime.datetime.now().isoformat(),
                             "source": os.path.basename(SRC)}),))
        except sqlite3.Error:
            pass  # settings unreadable in source — migrate_db recreates it on boot
        dst.commit()
        dst.execute("PRAGMA wal_checkpoint(TRUNCATE)")
        dst.execute("VACUUM")
        dst.commit()

        ok = dst.execute("PRAGMA integrity_check").fetchone()[0]
        report["integrity"] = ok

        report["census"] = {}
        for label, q in (
            ("players", "SELECT COUNT(*) FROM players"),
            ("humans", "SELECT COUNT(*) FROM players WHERE user_id > 0"),
            ("games", "SELECT COUNT(*) FROM games"),
            ("game_history", "SELECT COUNT(*) FROM game_history"),
            ("activity_log", "SELECT COUNT(*) FROM activity_log"),
            ("transactions", "SELECT COUNT(*) FROM transactions"),
            ("transactions_humans",
             "SELECT COUNT(DISTINCT user_id) FROM transactions WHERE user_id > 0"),
            ("announcements", "SELECT COUNT(*) FROM announcements"),
        ):
            try:
                report["census"][label] = dst.execute(q).fetchone()[0]
            except sqlite3.Error as exc:
                report["census"][label] = f"ERR {exc}"
        humans = dst.execute(
            "SELECT user_id, username, full_name, credit, is_registered "
            "FROM players WHERE user_id > 0 ORDER BY user_id").fetchall()
        report["humans"] = [dict(zip(
            ("user_id", "username", "full_name", "credit", "is_registered"), r))
            for r in humans]
    finally:
        dst.close()

    print(json.dumps(report, indent=1, default=str))
    size = os.path.getsize(OUT) if os.path.exists(OUT) else 0
    print(f"\nrecovered.db size: {size:,} bytes")
    verified = report.get("integrity") == "ok"
    humans_n = report.get("census", {}).get("humans", 0)
    print("RESULT:",
          "VERIFIED - safe to swap in" if verified else "NOT OK - do NOT swap",
          f"(integrity={report.get('integrity')}, humans={humans_n})")
    return 0 if verified else 1


if __name__ == "__main__":
    sys.exit(main())