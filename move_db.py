"""Move the live database OUT of the code folder (one-time, safe).

Why: if the database sits next to the code, a deploy that copies the project
(zip upload, folder copy, or pulling a repo that tracks a *.db) silently
replaces the live database — and every real account with it.  A database in a
folder outside the project can never be overwritten that way.

This script COPIES the database (plus its -wal/-shm files) to a data folder
beside the project, verifies the copy row-by-row counts, and then prints the
exact line to add to .env.  It never deletes your original file.

    python move_db.py                        # default: ../bingo_data
    python move_db.py /home/you/bingo_data   # explicit target folder

Stop the server and the bot before running it, then restart after updating
.env.
"""
import os
import shutil
import sqlite3
import sys

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

import config


def _counts(path: str):
    """(total, humans, bots) for the players table, or None when unreadable."""
    if not os.path.exists(path):
        return None
    try:
        conn = sqlite3.connect(path)
        try:
            total = conn.execute("SELECT COUNT(*) FROM players").fetchone()[0]
            humans = conn.execute(
                "SELECT COUNT(*) FROM players WHERE user_id > 0").fetchone()[0]
            return total, humans, total - humans
        finally:
            conn.close()
    except sqlite3.Error:
        return None


def main() -> int:
    src = os.path.abspath(config.DB_PATH)
    project_dir = os.path.dirname(os.path.abspath(__file__))
    dest_dir = (os.path.abspath(sys.argv[1]) if len(sys.argv) > 1
                else os.path.join(os.path.dirname(project_dir), "bingo_data"))
    dest = os.path.join(dest_dir, os.path.basename(src))

    print("─" * 62)
    print("  Move the database out of the code folder")
    print("─" * 62)
    print(f"source      : {src}")
    print(f"destination : {dest}")

    if not os.path.exists(src):
        print("\n❌ Source database not found — nothing to move.")
        return 1
    if not src.startswith(project_dir + os.sep):
        print("\n✅ The database is already OUTSIDE the code folder — nothing to do.")
        print("   (Keep DB_PATH absolute in .env so it stays there.)")
        return 0

    print("\n⚠️  Stop the server AND the bot before continuing, so nothing is\n"
          "   writing while the file is copied.  Press Ctrl+C to abort; the\n"
          "   original file is never deleted by this script.\n")

    src_counts = _counts(src)
    if src_counts is None:
        print("❌ Could not read the source database — is it corrupted? "
              "Do not continue; keep a copy first.")
        return 1
    print(f"source players: total {src_counts[0]} | humans {src_counts[1]} "
          f"| bots {src_counts[2]}")

    if not src_counts[1]:
        print("\n⚠️  The source has 0 human accounts. If that is unexpected, "
              "restore a backup FIRST —\n   moving the file will not bring "
              "those accounts back.")

    if os.path.exists(dest):
        dest_counts = _counts(dest)
        if dest_counts and dest_counts[1] > src_counts[1]:
            print(f"\n❌ {dest} already holds {dest_counts[1]} human account(s), "
                  f"more than the source's {src_counts[1]}.")
            print("   Refusing to overwrite it. Pick another folder or handle "
                  "it manually.")
            return 1

    try:
        os.makedirs(dest_dir, exist_ok=True)
    except OSError as exc:
        print(f"\n❌ Could not create {dest_dir}: {exc}")
        return 1

    copied = []
    for suffix in ("", "-wal", "-shm"):
        s = src + suffix
        if not os.path.exists(s):
            continue
        d = dest + suffix
        try:
            shutil.copy2(s, d)
            copied.append((os.path.basename(s), os.path.getsize(s)))
        except OSError as exc:
            print(f"\n❌ Copying {s} failed: {exc}")
            return 1

    print("\nCopied:")
    for name, size in copied:
        print(f"  {name}  ({size} bytes)")

    dest_counts = _counts(dest)
    if dest_counts is None:
        print("\n❌ The copied database is unreadable — NOT safe to switch over.")
        print("   Your original file is untouched. Keep the copy for inspection.")
        return 1
    if dest_counts != src_counts:
        print(f"\n❌ Copy verification failed: source {src_counts} vs "
              f"copy {dest_counts}.")
        print("   Your original file is untouched. Keep the copy for inspection.")
        return 1
    print(f"verified copy: total {dest_counts[0]} | humans {dest_counts[1]} "
          f"| bots {dest_counts[2]}  ✅")

    data_dir = os.path.dirname(dest)
    print("\n" + "─" * 62)
    print("Next steps")
    print("─" * 62)
    print(f"1) Add this line to .env (create it if needed):\n")
    print(f"     DB_PATH={dest}\n")
    print(f"2) Restart the server and the bot, then open the panels and confirm")
    print(f"   the accounts and balances are all there.")
    print(f"3) ONLY after step 2 looks correct, delete the old copy next to the")
    print(f"   code:\n")
    print(f"     {src}")
    print(f"     {src}-wal   (if present)")
    print(f"     {src}-shm   (if present)\n")
    print(f"   Keep a copy of the database somewhere else too (e.g. in")
    print(f"   {os.path.join(project_dir, 'db_rescue')}).")
    print("─" * 62)
    return 0


if __name__ == "__main__":
    sys.exit(main())
