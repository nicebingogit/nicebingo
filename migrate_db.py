"""
Database migration + card seed for the Bingo system.

Safe to run any number of times:
  * creates every table/view the system needs (players, game_state, cards,
    card_selections, called_numbers, games, game_history, profiles, bots)
  * seeds the 400 unique cards (INSERT OR IGNORE — existing data untouched)
  * resets a stuck game to a fresh preparation phase

Run:  python migrate_db.py
"""
import os
import sys
from datetime import datetime, timedelta

from dotenv import load_dotenv

load_dotenv()

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

import config
import cards_data
from database import Database

SCHEMA_TABLES = [
    "players", "game_state", "cards", "card_selections", "called_numbers",
    "games", "game_history", "bots", "transactions", "payment_accounts",
    "round_eliminations", "appeals", "bot_notifications", "settings",
    "profiles(view)",
]


def main() -> None:
    print("─" * 56)
    print("  Bingo Mini App — database migration & seed")
    print("─" * 56)

    db = Database(config.DB_PATH)

    # 1) tables (Database.init_db already CREATEs everything idempotently)
    print(f"[1/3] Schema ready  ({', '.join(SCHEMA_TABLES)})")

    # 2) seed the card pool
    before = db.count_cards()
    for card in cards_data.ALL_CARDS:
        db.insert_card(card["id"], card["numbers"])
    after = db.count_cards()
    print(f"[2/3] Cards seeded  {before} → {after} in pool (target {config.NUM_CARDS})")

    # 3) make sure EVERY room sits in a fresh preparation phase and
    #    old card selections are cleared so bot-fill doesn't see stale data
    now = datetime.now()
    for room in config.ROOM_BETS:
        state = db.get_game_state(room)
        if state.get("phase") != "preparation" or not state.get("preparation_end_time"):
            db.clear_selections(room)
            db.update_game_state(
                room,
                phase="preparation",
                preparation_end_time=(now + timedelta(seconds=config.PREPARATION_SECONDS)).isoformat(),
                current_call=None,
                winner_user_id=None,
                winning_pattern=None,
                prize_pool=0,
                total_bets=0,
                next_call_time=None,
                reset_time=None,
            )
            print(f"[3/3] {config.room_label(room)} reset → preparation (selections cleared)")
        else:
            print(f"[3/3] {config.room_label(room)} already in preparation — leaving it as-is")

    # 4) one-time: the default bot difficulty is now 5 (Impossible). Databases
    # created before this change hold the OLD default (2 = Medium) in every
    # room. That is indistinguishable from an explicit Medium choice, so the
    # migration runs exactly ONCE — afterwards the admin's difficulty selection
    # is never overridden again.
    flag = "bots_default_difficulty_5_applied"
    if db.get_setting(flag) is None:
        changed = db.upgrade_bots_difficulty_to_impossible()
        db.set_setting(flag, "1")
        print(f"[4/4] Default difficulty → 5 (Impossible) updated {changed} room(s)")
    else:
        print("[4/4] Default difficulty already migrated — leaving it as-is")

    # 5) purge stale bot players (negative user_ids) that no longer hold any
    #    card selections.  Over many rounds the players table accumulates
    #    hundreds of thousands of bot rows which exhaust the random bot_id
    #    range (-1M to -999M).  Keeping only bots with active selections
    #    frees IDs for future rounds.
    with db._session() as conn:
        before = conn.execute(
            "SELECT COUNT(*) FROM players WHERE user_id < 0"
        ).fetchone()[0]
        conn.execute(
            "DELETE FROM players WHERE user_id < 0 "
            "AND user_id NOT IN (SELECT DISTINCT user_id FROM card_selections "
            "WHERE user_id < 0)"
        )
        after = conn.execute(
            "SELECT COUNT(*) FROM players WHERE user_id < 0"
        ).fetchone()[0]
    if before != after:
        print(f"[5/5] Purged {before - after} stale bot players ({before} → {after})")
    else:
        print(f"[5/5] No stale bots to purge ({before} active)")

    print("─" * 56)
    print("✅ Migration complete.")


if __name__ == "__main__":
    main()
