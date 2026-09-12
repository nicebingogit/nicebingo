"""Restore/merge REAL human accounts back into the app's database.

Never deletes anything. Reads every real (user_id > 0) account from the SOURCE
database and INSERT OR IGNOREs it into the TARGET database (the one the app
actually uses). Skips the corrupted "credit shows a date" rows. Idempotent —
safe to run any number of times, while the app is running.

Use when the admin/super-admin panels show fewer accounts than expected after
the app was pointed at the wrong/empty DB (the panels list every user_id > 0;
a fresh DB only contains accounts created after it started).

    python .\restore_players.py                          # SRC default + TARGET = the app's DB_PATH
    python .\restore_players.py /x/source.db             # explicit source file
    python .\restore_players.py /x/source.db /y/target.db

Change SRC/TARGET at the top (or SALVAGE_SRC / SALVAGE_OUT env vars) if your
layout differs.
"""
import datetime
import json
import os
import sqlite3
import sys

SRC = os.getenv("RESTORE_SRC", "/home/nicebingo/bingo_bot.db")
TARGET = os.getenv("RESTORE_TARGET", "")

import config


def _cols(conn, table):
    return {r[1] for r in conn.execute(f"PRAGMA table_info({table})")}


def _players_ddl(conn):
    row = conn.execute(
        "SELECT sql FROM sqlite_master WHERE type='table' AND name='players'"
    ).fetchone()
    return row[0] if row else None


def main() -> int:
    tgt = os.path.abspath(TARGET if TARGET else config.DB_PATH)

    print("-" * 62)
    print("Restore real accounts (idempotent merge)")
    print("-" * 62)
    print(f"source : {SRC}")
    print(f"target : {tgt}")
    if not os.path.exists(SRC):
        print(f"\n!! Source database not found: {SRC}")
        return 1
    if not os.path.exists(tgt):
        print(f"\n!! Target database not found: {tgt}")
        return 1

    s = sqlite3.connect(f"file:{SRC.replace(os.sep, '/')}?mode=ro", uri=True)
    s.row_factory = sqlite3.Row
    d = sqlite3.connect(tgt, timeout=30)
    report = {
        "source": SRC, "target": tgt,
        "date": datetime.datetime.now().isoformat(),
        "scanned": 0, "inserted": 0, "already_present": 0,
    }

    try:
        # guarantee target schema exists even if it is a freshly-seeded DB
        ddl = _players_ddl(s)
        if ddl and not d.execute(
                "SELECT 1 FROM sqlite_master WHERE type='table' AND name='players'"
        ).fetchone():
            d.execute(ddl)
        s_cols = _cols(s, "players")
        d_cols = _cols(d, "players")
        insert_cols = [c for c in s_cols if c in d_cols and c != "user_id"]

        humans = s.execute(
            "SELECT * FROM players WHERE user_id > 0 AND ("
            "  typeof(credit) = 'integer' "
            "  AND is_registered IN (0, 1) "
            "  AND (username IS NULL OR CAST(username AS TEXT) NOT GLOB '-[0-9]*')"
            ") ORDER BY user_id"
        ).fetchall()
        report["scanned"] = len(humans)

        q = "INSERT OR IGNORE INTO players (user_id, " + ", ".join(insert_cols) + \
            ") VALUES (?, " + ", ".join("?" for _ in insert_cols) + ")"
        for row in humans:
            uid = row["user_id"]
            present = d.execute(
                "SELECT 1 FROM players WHERE user_id=?", (uid,)
            ).fetchone()
            d.execute(q, [uid] + [row[c] for c in insert_cols])
            if present:
                report["already_present"] += 1
            else:
                report["inserted"] += 1

        # sync the same humans' transactions so wallet history is preserved
        stx = [c for c in _cols(s, "transactions")
               if c in _cols(d, "transactions") and c != "id"]
        if stx:
            ddl_tx = s.execute(
                "SELECT sql FROM sqlite_master WHERE type='table' AND name='transactions'"
            ).fetchone()
            if ddl_tx and not d.execute(
                    "SELECT 1 FROM sqlite_master WHERE type='table' AND name='transactions'"
            ).fetchone():
                d.execute(ddl_tx[0])
            cols = ("user_id", *stx)
            colsel = ", ".join(cols)
            match_sql = " AND ".join(f"{c}=?" for c in cols)
            placeholders = ", ".join("?" for _ in cols)
            restored = 0
            human_ids = [r["user_id"] for r in humans]
            marks = ", ".join("?" for _ in human_ids)
            for row in s.execute(
                    f"SELECT {colsel} FROM transactions "
                    f"WHERE user_id IN ({marks})", human_ids
            ).fetchall():
                vals = [row[c] for c in cols]
                exists = d.execute(
                    f"SELECT 1 FROM transactions WHERE {match_sql} LIMIT 1", vals
                ).fetchone()
                if not exists:
                    d.execute(
                        f"INSERT INTO transactions ({colsel}) VALUES ({placeholders})", vals)
                    restored += 1
            report["transactions_restored"] = restored

        d.commit()
        pr = "PRAGMA integrity_check"
        report["target_integrity"] = d.execute(pr).fetchone()[0]

        report["target_humans"] = d.execute(
            "SELECT COUNT(*) FROM players WHERE user_id > 0").fetchone()[0]
    except (sqlite3.DatabaseError, OSError) as exc:
        print(f"!! restore failed: {exc}", flush=True)
        return 1
    finally:
        s.close()
        d.close()

    print(json.dumps(report, indent=1, default=str))
    print("\nRESULT:",
          "OK - accounts merged, verify in the super-admin panel"
          if report["target_integrity"] == "ok" else
          "DANGER - target DB is damaged, do NOT proceed")
    return 0 if report["target_integrity"] == "ok" else 1


if __name__ == "__main__":
    sys.exit(main())