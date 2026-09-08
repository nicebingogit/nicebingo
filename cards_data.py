"""
Pre-generated, guaranteed-unique Bingo cards.

A standard Bingo card has one column per letter:
    B: 1-15, I: 16-30, N: 31-45, G: 46-60, O: 61-75
with the centre cell of the N column marked FREE.
"""
import random
from typing import Dict, List

from config import NUM_CARDS

COLUMNS = ["B", "I", "N", "G", "O"]
RANGES = {"B": (1, 15), "I": (16, 30), "N": (31, 45), "G": (46, 60), "O": (61, 75)}


def _pick(lo: int, hi: int, count: int) -> List[int]:
    return sorted(random.sample(range(lo, hi + 1), count))


def generate_card(card_id) -> Dict:
    """Build one card: {'id': str, 'numbers': {'B': [...], ..., 'O': [...]}}."""
    numbers = {letter: _pick(*RANGES[letter], 5) for letter in COLUMNS}
    numbers["N"][2] = "FREE"  # free centre space
    return {"id": str(card_id), "numbers": numbers}


def generate_all_cards(count: int = NUM_CARDS) -> List[Dict]:
    """Generate `count` unique cards (retries until every card is distinct)."""
    cards: List[Dict] = []
    seen = set()
    attempts = 0
    while len(cards) < count and attempts < count * 200:
        attempts += 1
        card = generate_card(len(cards) + 1)
        key = tuple(tuple(v) for v in card["numbers"].values())
        if key in seen:
            continue
        seen.add(key)
        cards.append(card)
    return cards


ALL_CARDS = generate_all_cards()
