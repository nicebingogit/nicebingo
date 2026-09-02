"""
Pure game rules: the ball machine, pattern detection, winner lookup,
bot players and the prize pool.
"""
import random
from typing import Dict, List, Optional, Set, Tuple

import config
from database import Database

COLUMNS = ["B", "I", "N", "G", "O"]
RANGES = {"B": (1, 15), "I": (16, 30), "N": (31, 45), "G": (46, 60), "O": (61, 75)}

# Human-looking display names for bot accounts (negative user ids). Bots are
# meant to feel like other people in the room, never like "Bot_12345".
#
# Every bot gets a male first name + surname (the requested default mix), so
# the room always looks like real Ethiopian men playing alongside the user.
BOT_MALE_FIRST_NAMES = [
    "Abel", "Abebe", "Amanuel", "Biruk", "Dagmawi", "Dawit", "Elias",
    "Ephrem", "Haile", "Henok", "Kalid", "Kebede", "Kidus", "Nahom",
    "Nathan", "Robel", "Samuel", "Solomon", "Yohannes", "Yonatan",
    "Abrham", "Addisu", "Alemayehu", "Ashenafi", "Berhanu", "Binyam",
    "Daniel", "Dereje", "Endale", "Ermias", "Eyob", "Fasil", "Fikadu",
    "Getachew", "Girma", "Habtamu", "Hailu", "Ismael", "Jemal", "Kaleab",
    "Kassahun", "Luel", "Mathewos", "Mekonnen", "Melaku", "Merid",
    "Mesfin", "Michael", "Mikias", "Muluken", "Natnael", "Nebiyu",
    "Sileshi", "Surafel", "Tadesse", "Tamrat", "Tekle", "Tesfaye",
    "Teshome", "Tewodros", "Wondwossen", "Yared", "Zekarias", "Betre",
    "Biniam", "Bruk", "Edom", "Feleke", "Gashaw", "Getnet", "Goitom",
    "Haftom", "Hagos", "Kiros", "Leul", "Mamo", "Mebrahtom", "Molla",
    "Mulugeta", "Negash", "Samson", "Seifu", "Senay", "Shimelis",
    "Sisay", "Taye", "Teka", "Tinsae", "Tsegaye", "Yitbarek",
]
BOT_FEMALE_FIRST_NAMES = [
    "Bethlehem", "Eden", "Eyerusalem", "Frehiwot", "Genet", "Hanna",
    "Hawi", "Helina", "Liya", "Mahlet", "Mekdes", "Meron", "Rediet",
    "Ruth", "Sara", "Selam", "Tigist", "Tsion", "Winta", "Abebech",
    "Alem", "Almaz", "Beza", "Birtukan", "Blen", "Bontu", "Emebet",
    "Fikirte", "Hiwot", "Kidist", "Konjit", "Lemlem", "Makeda",
    "Meseret", "Mihret", "Rahel", "Roman", "Saba", "Senait", "Aster",
    "Azeb", "Etenesh", "Fana", "Kalekidan", "Netsanet", "Nigist",
    "Serkalem", "Shewit", "Tadelech", "Tirhas", "Zinash",
]
BOT_NICKNAMES = [
    "Lucky", "Ace", "BigWin", "KingBingo", "LuckyStar", "Jackpot",
    "NightOwl", "FastFingers", "CardMaster", "GoldenBall", "SlyFox",
    "NumberNinja", "HotShot", "WildCard", "LuckySeven", "BallHawk",
    "DeepPocket", "SilverFox", "StarPlayer", "TopGun", "QuickShot",
    "KingPin", "HighRoller", "LuckyCharm", "MoneyMaker",
]
BOT_LAST_NAMES = [
    "Tadesse", "Alemu", "Bekele", "Tesfaye", "Girma", "Haile",
    "Mekonnen", "Desta", "Worku", "Shiferaw", "Assefa", "Kebede",
]


def bot_name(user_id: int) -> str:
    """Deterministic, human-like display name for a bot account.

    Stable across restarts (derived from the id, not random), so the same
    "player" keeps the same name round after round. Bots always get a human
    MALE first name + surname (e.g. "Abel Girma"), so the room feels full of
    real men playing alongside the user. The multipliers mix the id so that
    nearby ids get clearly different name combos.
    """
    idx = abs(int(user_id))
    first = BOT_MALE_FIRST_NAMES[(idx * 7 + 3) % len(BOT_MALE_FIRST_NAMES)]
    last = BOT_LAST_NAMES[(idx * 5 + idx // len(BOT_MALE_FIRST_NAMES)) % len(BOT_LAST_NAMES)]
    return f"{first} {last}"


class GameLogic:
    def __init__(self, db: Database):
        self.db = db

    # ------------------------------------------------------------ ball machine
    def new_ball_order(self) -> List[str]:
        """A fresh shuffled order of all 75 balls, e.g. 'B-7', 'N-44'..."""
        order = [
            f"{letter}-{n}"
            for letter, (lo, hi) in RANGES.items()
            for n in range(lo, hi + 1)
        ]
        random.shuffle(order)
        return order

    def call_next_number(self, room: int = 30) -> Optional[str]:
        """Pop the next ball from the persisted order and record it as called.

        The ball order, the called_numbers row and current_call are written in
        ONE atomic transaction (record_call), so a concurrent reader never sees
        a called number without its current_call highlight (or vice versa).
        """
        order = self.db.get_ball_order(room)
        if not order:
            return None
        number = order.pop(0)
        self.db.record_call(room, number, order)
        return number

    # ----------------------------------------------------------------- patterns
    @staticmethod
    def _is_hit(card_numbers: Dict, col: int, row: int, called: Set[str]) -> bool:
        letter = COLUMNS[col]
        value = card_numbers[letter][row]
        return value == "FREE" or f"{letter}-{value}" in called

    def check_winning_patterns(self, card_numbers: Dict, called: Set[str]) -> Tuple[List[str], List[Tuple[int, int]]]:
        """Return (achieved patterns, winning cells as (col, row) pairs)."""
        patterns: List[str] = []
        cells: Set[Tuple[int, int]] = set()

        # rows
        for r in range(5):
            if all(self._is_hit(card_numbers, c, r, called) for c in range(5)):
                patterns.append("Row")
                cells.update((c, r) for c in range(5))
        # columns
        for c in range(5):
            if all(self._is_hit(card_numbers, c, r, called) for r in range(5)):
                patterns.append("Column")
                cells.update((c, r) for r in range(5))
        # diagonals
        if all(self._is_hit(card_numbers, i, i, called) for i in range(5)):
            patterns.append("Diagonal")
            cells.update((i, i) for i in range(5))
        if all(self._is_hit(card_numbers, 4 - i, i, called) for i in range(5)):
            patterns.append("Anti-Diagonal")
            cells.update((4 - i, i) for i in range(5))
        # four corners
        corners = [(0, 0), (4, 0), (0, 4), (4, 4)]
        if all(self._is_hit(card_numbers, c, r, called) for c, r in corners):
            patterns.append("Four Corners")
            cells.update(corners)

        return patterns, sorted(cells)

    def is_one_away(self, card_numbers: Dict, called: Set[str]) -> bool:
        """True if the card is exactly ONE uncalled number away from completing
        any winning pattern (row, column, diagonal, anti-diagonal, four corners).
        The FREE cell always counts as marked.
        """
        # rows
        for r in range(5):
            hits = sum(1 for c in range(5) if self._is_hit(card_numbers, c, r, called))
            if hits == 4:
                return True
        # columns
        for c in range(5):
            hits = sum(1 for r in range(5) if self._is_hit(card_numbers, c, r, called))
            if hits == 4:
                return True
        # diagonals
        diag_hits = sum(1 for i in range(5) if self._is_hit(card_numbers, i, i, called))
        if diag_hits == 4:
            return True
        anti_hits = sum(1 for i in range(5) if self._is_hit(card_numbers, 4 - i, i, called))
        if anti_hits == 4:
            return True
        # four corners (4 cells, need 3)
        corners = [(0, 0), (4, 0), (0, 4), (4, 4)]
        corner_hits = sum(1 for c, r in corners if self._is_hit(card_numbers, c, r, called))
        if corner_hits == 3:
            return True
        return False

    # ------------------------------------------------------------------ winners
    def check_winner(self, room: int = 30) -> Optional[Dict]:
        """Return the first winning selection (shuffled for fairness), or None.

        Utility (admin/testing scenarios) — the live game loop does NOT call
        this: a winner is only declared when a player presses the BINGO button
        (game_loop.claim_bingo). Selections belonging to players eliminated
        this round (false BINGO) are skipped: their cards stop participating,
        although their already-paid bet stays in the prize pool.
        """
        selections = self.db.get_all_selections(room)
        random.shuffle(selections)  # fair when several players win on the same ball
        called = set(self.db.get_called_numbers(room))
        cards = self.db.get_cards_map()  # one query instead of one per card
        state = self.db.get_game_state(room)
        eliminated = set(self.db.get_eliminated_user_ids(state.get("current_game_id")))
        for sel in selections:
            if sel["user_id"] in eliminated:
                continue
            card_numbers = cards.get(sel["card_id"])
            if not card_numbers:
                continue
            patterns, cells = self.check_winning_patterns(card_numbers, called)
            if patterns:
                prize = self.calculate_prize_pool(room)["prize_pool"]
                return {
                    "user_id": sel["user_id"],
                    "card_id": sel["card_id"],
                    "pattern": patterns[0],
                    "patterns": patterns,
                    "winning_cells": cells,
                    "prize": prize,
                }
        return None

    # -------------------------------------------------------------- prize pool
    def calculate_prize_pool(self, room: int = 30) -> Dict:
        """Return {'total_bets', 'prize_pool', 'house_fee', 'real_players'}.

        All bets (real and bot) are counted once. Bot bets contribute to the
        pool just like real bets, so the prize is always a fair percentage of
        the actual money collected.
        """
        real_bets = 0
        bot_bets = 0
        real_ids: Set[int] = set()
        for sel in self.db.get_all_selections(room):
            if sel["user_id"] > 0:
                real_ids.add(sel["user_id"])
                real_bets += sel["bet_amount"]
            elif config.BOTS_CONTRIBUTE_TO_POOL:
                bot_bets += sel["bet_amount"]
        # bot bets are counted once, same as real bets
        total_bets = real_bets + bot_bets
        prize_pool = int(total_bets * config.PRIZE_PERCENT)
        return {
            "total_bets": total_bets,
            "prize_pool": prize_pool,
            "house_fee": total_bets - prize_pool,
            "real_players": len(real_ids),
        }

    # -------------------------------------------------------------------- bots

    def add_bot_player(self, room: int = 30, num_cards: int = 2) -> Optional[Dict]:
        """Create one bot player with a specified number of cards.

        The number of cards is determined by the target player count:
          - 80-140 players → 1 card each
          - 40-79 players  → 2 cards each
          - 18-39 players  → 3 cards each

        Difficulty only controls how FAST bots claim (see game_loop._bot_claim_pass),
        not how many cards they get.
        """
        all_cards = self.db.get_all_cards()
        taken = {s["card_id"] for s in self.db.get_all_selections(room)}
        available = [c for c in all_cards if c["id"] not in taken]
        if not available:
            return None

        bot_id = None
        for _ in range(100):
            candidate = -random.randint(1000, 999_999)
            if not self.db.get_player(candidate):
                bot_id = candidate
                break
        if bot_id is None:
            return None

        self.db.create_player(bot_id, bot_name(bot_id), credit=0)
        num_cards = min(num_cards, len(available))
        if num_cards <= 0:
            return None
        chosen = random.sample(available, num_cards)
        for card in chosen:
            self.db.select_card(bot_id, card["id"], room, room)
        return {"bot_id": bot_id, "cards": num_cards}

    def count_unique_players(self, room: int = 30) -> int:
        """Count unique players (real + bots) that currently hold cards."""
        players: set[int] = set()
        for sel in self.db.get_all_selections(room):
            players.add(sel["user_id"])
        return len(players)

    @staticmethod
    def cards_per_player(total_players: int) -> int:
        """Determine cards per player based on the target player count.

          - 80-140 players → 1 card each
          - 40-79 players  → 2 cards each
          - 18-39 players  → 3 cards each
        """
        if total_players >= 80:
            return 1
        elif total_players >= 40:
            return 2
        else:
            return 3

    def ensure_minimum_players(self, room: int = 30,
                                   min_total: int | None = None,
                                   max_total: int | None = None) -> int:
        """Add bots until a random target of total PLAYERS is reached.

        The target player count is randomized each round:
          - 80-140 players → 1 card each
          - 40-79 players  → 2 cards each
          - 18-39 players  → 3 cards each

        Returns how many bots were added.
        """
        if min_total is None:
            min_total = config.MIN_TOTAL_PLAYERS
        if max_total is None:
            max_total = config.MAX_TOTAL_PLAYERS
        target = random.randint(min_total, max_total)
        # always fill to at least the target — if real players already exceed
        # the random pick, use the actual count + a small cushion so bots
        # still join (players like seeing opponents enter the room).
        current_players = self.count_unique_players(room)
        target = max(target, current_players + random.randint(2, 5))
        target = min(target, max_total)
        # cards per player is determined by the target player count
        cpp = self.cards_per_player(target)
        added = 0
        while self.count_unique_players(room) < target:
            bot = self.add_bot_player(room, num_cards=cpp)
            if not bot:
                break
            added += 1
        return added

    def player_breakdown(self, room: int = 30) -> Dict:
        """Return {'real': n, 'bots': n} of players that currently hold cards."""
        real = set()
        bots = set()
        for sel in self.db.get_all_selections(room):
            if sel["user_id"] > 0:
                real.add(sel["user_id"])
            else:
                bots.add(sel["user_id"])
        return {"real": len(real), "bots": len(bots)}
