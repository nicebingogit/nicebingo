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
    "round_eliminations", "settings", "profiles(view)",
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

    # 3) make sure EVERY room sits in a fresh preparation phase
    now = datetime.now()
    for room in config.ROOM_BETS:
        state = db.get_game_state(room)
        if state.get("phase") != "preparation" or not state.get("preparation_end_time"):
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
            print(f"[3/3] {config.room_label(room)} reset → preparation phase")
        else:
            print(f"[3/3] {config.room_label(room)} already in preparation — leaving it as-is")

    print("─" * 56)
    print("✅ Migration complete.")


if __name__ == "__main__":
    main()
