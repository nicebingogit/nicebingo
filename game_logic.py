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

    def bot_cards_for_count(self, bot_count: int) -> int:
        """Cards per bot based on the FINAL bot-player count for the game."""
        for lower, cards in config.BOT_CARDS_BY_COUNT:
            if bot_count >= lower:
                return cards
        return 1

    def human_player_count(self, room: int = 30) -> int:
        """Number of distinct REAL players (positive ids) holding cards."""
        return len({s["user_id"] for s in self.db.get_all_selections(room)
                    if s["user_id"] > 0})

    def bot_option_for_humans(self, humans: int) -> Tuple[int, int, int]:
        """(min_bots, max_bots, cards_each) for a given number of human players.

        The bot count for a game is decided by the NUMBER OF HUMAN players:
           humans <= 1      -> 80-140 bots, 1 card each (Option 1)
           2 <= humans <= 5 -> 40-79  bots, 2 cards each (Option 2)
           humans >= 6      -> 18-39  bots, 3 cards each (Option 3)
        """
        for max_humans, min_bots, max_bots, cards_each in config.BOT_OPTIONS:
            if max_humans is None or humans <= max_humans:
                return (min_bots, max_bots, cards_each)
        return (18, 39, 3)  # unreachable — the last option is unbounded

    def pick_bot_target(self, humans: int | None = None) -> int:
        """A random bot-player count for one game, chosen by the current
        number of HUMAN players (see bot_option_for_humans).

        When `humans` is omitted it defaults to 0 (so an empty room still gets
        the fullest option: a game must never start with 0 players).
        """
        lo, hi, _ = self.bot_option_for_humans(humans if humans is not None else 0)
        return random.randint(lo, hi)

    def bot_card_plan(self, bot_count: int,
                      cards_each: int | None = None) -> List[int]:
        """Per-bot card counts for a game of `bot_count` bots.

        Most bots keep `cards_each` cards, but a random 5-15 cards are
        DEDUCTED from the total (config.BOT_CARD_DEDUCTION): a few bots hold
        one fewer card, so the game starts with `bot_count * cards_each - d`
        cards in total. Every bot always keeps at least 1 card, so a 1-card
        option cannot be deducted (returned as all 1s).
        """
        if cards_each is None:
            cards_each = self.bot_cards_for_count(bot_count)
        if cards_each <= 1:
            return [1] * bot_count
        d_lo, d_hi = config.BOT_CARD_DEDUCTION
        deduction = min(random.randint(d_lo, d_hi), bot_count * (cards_each - 1))
        counts = [1] * bot_count
        # leftover cards above the guaranteed 1-per-bot (never below 1 each)
        bonus = bot_count * cards_each - deduction - bot_count
        for i in range(bot_count):
            add = min(cards_each - 1, bonus)
            counts[i] += add
            bonus -= add
            if bonus <= 0:
                break
        random.shuffle(counts)
        return counts

    def bot_player_count(self, room: int = 30) -> int:
        """Number of bot players that currently hold cards in the room.
        Bots hold several cards each, so DISTINCT negative user ids are
        counted, not selection rows."""
        return len({s["user_id"] for s in self.db.get_all_selections(room)
                    if s["user_id"] < 0})

    def add_bot_player(self, room: int = 30,
                       cards_per_bot: int | None = None) -> Optional[Dict]:
        """Create one bot player.

        cards_per_bot: how many cards this bot gets. When None the historical
        2-3 random cards are used (backward compatible default). New games pass
        the value from the round's card plan (bot_card_plan), which mirrors the
        option chosen for the current human-player count.
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
        if cards_per_bot is None:
            num_cards = random.randint(2, 3)
        else:
            num_cards = max(1, int(cards_per_bot))
        num_cards = min(num_cards, len(available))
        chosen = random.sample(available, num_cards)
        for card in chosen:
            self.db.select_card(bot_id, card["id"], room, room)
        return {"bot_id": bot_id, "cards": num_cards}

    def ensure_minimum_players(self, room: int = 30,
                               target: int | None = None) -> int:
        """Fill the room until it holds `target` BOT PLAYERS.

        When `target` is omitted it is chosen from the current HUMAN player
        count (see pick_bot_target / bot_option_for_humans). Bots are created
        slot-by-slot from the round's card plan (bot_card_plan), so the final
        game starts with the option's cards-per-bot minus the random 5-15 card
        deduction:
          humans <= 1      -> 80-140 players, ~1 card each
          2 <= humans <= 5 -> 40-79  players, ~2 cards each
          humans >= 6      -> 18-39  players, ~3 cards each
        Existing humans and their cards are never touched. Returns how many
        bots were added by this call.
        """
        if target is None:
            target = self.pick_bot_target(self.human_player_count(room))
        cards_each = self.bot_cards_for_count(target)
        plan = self.bot_card_plan(target, cards_each)
        added = 0
        while self.bot_player_count(room) < target:
            slot = self.bot_player_count(room)
            cards = plan[slot] if slot < len(plan) else cards_each
            bot = self.add_bot_player(room, cards)
            if not bot:
                break  # card pool exhausted — never loop forever
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
