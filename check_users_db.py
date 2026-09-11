"""Read-only diagnostic for the players table.

Use this when the admin / super-admin panels show WRONG values for users
(for example a "credit" that looks like a date, or a username that is just
numbers) or when the number of accounts suddenly dropped.

It NEVER writes to the database — it only prints what is really stored, so we
can tell apart:
  * a damaged / misaligned table (values shifted between columns)
  * a different database file being used than the one you expect
  * bots being counted as human players (bots have NEGATIVE user_id)

Run it where the live database is:

    python check_users_db.py                     # uses config.DB_PATH
    python check_users_db.py /data/bingo_bot.db  # explicit file
"""
import os
import re
import sqlite3
import sys

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

_TS_RE = re.compile(r"^\d{4}-\d{2}-\d{2}[ T]\d{2}:\d{2}")


def _looks_like_timestamp(value) -> bool:
    return isinstance(value, str) and bool(_TS_RE.match(value.strip()))


def main() -> None:
    if len(sys.argv) > 1:
        db_path = sys.argv[1]
    else:
        try:
            import config
            db_path = config.DB_PATH
        except Exception:
            db_path = "bingo_bot.db"

    print("─" * 60)
    print("  Users / credit database check")
    print("─" * 60)
    print(f"DB_PATH (as configured) : {db_path}")
    print(f"absolute path           : {os.path.abspath(db_path)}")
    print(f"exists / size           : "
          f"{os.path.exists(db_path)} / "
          f"{os.path.getsize(db_path) if os.path.exists(db_path) else 0} bytes")

    for suffix in ("-wal", "-shm", ".corrupt.bak", ".repair.tmp"):
        p = db_path + suffix
        if os.path.exists(p):
            print(f"companion file          : {p} ({os.path.getsize(p)} bytes)")

    if not os.path.exists(db_path):
        print("\n❌ File not found — the app may be running from another folder "
              "and created a different bingo_bot.db there.")
        return

    try:
        conn = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
        conn.row_factory = sqlite3.Row
    except sqlite3.Error as exc:
        print(f"\n❌ Cannot open database: {exc}")
        return

    try:
        integrity = conn.execute("PRAGMA integrity_check").fetchone()[0]
        print(f"integrity_check         : {integrity}")
    except sqlite3.Error as exc:
        print(f"integrity_check         : ERROR {exc} "
              "(malformed schema — this is the corruption case)")

    try:
        cols = [r[1] for r in conn.execute("PRAGMA table_info(players)")]
    except sqlite3.Error as exc:
        print(f"\n❌ players table unreadable: {exc}")
        return

    print(f"\nplayers columns ({len(cols)})      : {cols}")
    expected = ["user_id", "username", "full_name", "phone", "is_registered",
                "credit", "is_admin", "created_at", "admin_credit", "last_seen"]
    missing = [c for c in expected if c not in cols]
    if missing:
        print(f"⚠️  missing expected columns : {missing} (old/partial schema)")

    for label, where in (("total rows", ""),
                         ("humans (user_id > 0)", "WHERE user_id > 0"),
                         ("bots  (user_id < 0)", "WHERE user_id < 0")):
        try:
            n = conn.execute(f"SELECT COUNT(*) FROM players {where}").fetchone()[0]
            print(f"{label:<24}: {n}")
        except sqlite3.Error as exc:
            print(f"{label:<24}: ERROR {exc}")

    # rows whose credit is NOT an integer, or contains a date-like string
    print("\n── suspicious rows (credit is not a plain number) ──")
    try:
        rows = conn.execute(
            "SELECT user_id, username, full_name, credit, created_at "
            "FROM players WHERE user_id > 0 "
            "AND (typeof(credit) != 'integer' OR credit IS NULL)"
        ).fetchall()
        if not rows:
            print("none ✅")
        for r in rows:
            print(f"  id={r['user_id']} username={r['username']!r} "
                  f"full_name={r['full_name']!r} credit={r['credit']!r} "
                  f"created_at={r['created_at']!r}")
    except sqlite3.Error as exc:
        print(f"  query failed: {exc}")

    # rows where a text column holds a timestamp (sign of shifted columns)
    print("\n── rows where username/full_name holds a date, or credit holds text ──")
    try:
        rows = conn.execute(
            "SELECT user_id, username, full_name, credit, created_at "
            "FROM players WHERE user_id > 0 ORDER BY created_at DESC LIMIT 500"
        ).fetchall()
        bad = 0
        for r in rows:
            if _looks_like_timestamp(r["username"]) or _looks_like_timestamp(r["full_name"]):
                bad += 1
                print(f"  SHIFTED? id={r['user_id']} username={r['username']!r} "
                      f"full_name={r['full_name']!r} credit={r['credit']!r}")
        if not bad:
            print("none ✅")
    except sqlite3.Error as exc:
        print(f"  query failed: {exc}")

    # raw dump so the real values are visible
    print("\n── first 40 human accounts (raw) ──")
    print("  id | username | full_name | phone | credit | reg | created_at")
    try:
        for r in conn.execute(
            "SELECT user_id, username, full_name, phone, credit, is_registered, "
            "created_at FROM players WHERE user_id > 0 "
            "ORDER BY created_at DESC LIMIT 40"
        ):
            print(f"  {r['user_id']} | {r['username']!r} | {r['full_name']!r} | "
                  f"{r['phone']!r} | {r['credit']!r} | {r['is_registered']!r} | "
                  f"{r['created_at']!r}")
    except sqlite3.Error as exc:
        print(f"  query failed: {exc}")

    conn.close()
    print("\nDone — nothing was changed.")


if __name__ == "__main__":
    main()
