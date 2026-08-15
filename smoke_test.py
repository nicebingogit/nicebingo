"""
Offline smoke test — verifies the whole new system WITHOUT Telegram.

  1. the full Flask API suite (api_smoke.py): registration, selection,
     rounds, bots, winner + 80% payout, claim-bingo, admin, reset
  2. card image rendering into sample_cards/

Run:  venv\\Scripts\\python.exe smoke_test.py
"""
import os
import sys

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

import api_smoke  # noqa: E402  (runs its own isolated test database)

from cards_data import generate_card  # noqa: E402
from card_generator import PremiumCardGenerator  # noqa: E402


def main() -> None:
    print("=" * 58)
    print("  SMOKE TEST — part 1: full API suite")
    print("=" * 58)
    api_smoke.main()

    print()
    print("=" * 58)
    print("  SMOKE TEST — part 2: card image rendering")
    print("=" * 58)
    os.makedirs("sample_cards", exist_ok=True)
    gen = PremiumCardGenerator(output_dir="sample_cards")
    card = generate_card(1)
    called = ["B-1", "I-19", "N-37", "G-56", "O-61", "B-7"]
    gen.generate_card_image("1", card["numbers"], called, "Tester").save(
        "sample_cards/card_in_progress.png")
    gen.generate_card_image("1", card["numbers"], called, "Tester",
                            highlight_cells=[[0, 0], [1, 0], [2, 0], [3, 0], [4, 0]],
                            is_winner=True, frame=3).save(
        "sample_cards/card_winner.png")
    sizes = [os.path.getsize(f"sample_cards/{f}")
             for f in os.listdir("sample_cards") if f.endswith(".png")]
    assert all(s > 10_000 for s in sizes), sizes
    print(f"[2] Card images rendered OK -> sample_cards/ ({sizes})")

    print()
    print("SMOKE TEST PASSED ✅")


if __name__ == "__main__":
    try:
        main()
    finally:
        for f in ("api_smoke.db", "api_smoke.db-wal", "api_smoke.db-shm"):
            if os.path.exists(f):
                try:
                    os.remove(f)
                except OSError:
                    pass
