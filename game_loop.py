"""
Server-side game loop (APScheduler).

The Flask server is the single source of truth for the game.  Every tick it
reads the persisted game_state row and advances the game accordingly, so the
loop survives restarts and neither the bot nor the Mini App can race it.

Lifecycle:  preparation -> playing (a ball every CALL_INTERVAL_SECONDS)
            -> ended (winner / 75th ball) -> preparation -> ...
"""
import json
import logging
import random
import threading
from datetime import datetime, timedelta

from apscheduler.schedulers.background import BackgroundScheduler

import config
from database import Database
from game_logic import GameLogic, bot_name

logger = logging.getLogger("game_loop")


def _iso(seconds: float) -> str:
    return (datetime.now() + timedelta(seconds=seconds)).isoformat()


def _parse(value) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(str(value))
    except (ValueError, TypeError):
        return None


class GameLoop:
    def __init__(self, db: Database, logic: GameLogic):
        self.db = db
        self.logic = logic
        self.scheduler = BackgroundScheduler()
        self._lock = threading.RLock()
        # bots press BINGO like humans — once a bot's card completes a pattern
        # it "notices" after a short random delay (1-4 balls) and claims, so
        # other players genuinely win rounds. shape: {room: {bot_id: call_index}}
        self._bot_claim_at: dict[int, dict[int, int]] = {}

    # ------------------------------------------------------------------ boot
    def start(self) -> None:
        """Repair/restore state for EVERY room and start the ticker.

        Idempotent — safe to call again after a WSGI reload or a second
        import of the app (the APScheduler cannot be started twice).
        """
        if self.scheduler.running:
            return
        with self._lock:
            for room in config.ROOM_BETS:
                state = self.db.get_game_state(room)
                if not state.get("phase"):
                    self.db.update_game_state(room, phase="preparation")
                    state = self.db.get_game_state(room)
                now = datetime.now()
                if state["phase"] == "preparation" and not _parse(state.get("preparation_end_time")):
                    self.db.update_game_state(room, preparation_end_time=_iso(config.PREPARATION_SECONDS))
                elif state["phase"] == "playing":
                    # resume mid-round: make sure a call is scheduled soon
                    if not _parse(state.get("next_call_time")):
                        self.db.update_game_state(room, next_call_time=_iso(0.5))
                elif state["phase"] == "ended" and not _parse(state.get("reset_time")):
                    self.db.update_game_state(room, reset_time=_iso(config.POST_GAME_RESET_SECONDS))
        self.scheduler.add_job(self.tick, "interval",
                               seconds=config.TICK_INTERVAL, id="game_tick",
                               max_instances=1, coalesce=True)
        self.scheduler.start()
        logger.info("Game loop started · rooms=%s", config.ROOM_BETS)

    def stop(self) -> None:
        try:
            self.scheduler.shutdown(wait=False)
        except Exception:
            pass

    # ------------------------------------------------------------------ tick
    def tick(self) -> None:
        """Advance every room's game independently."""
        with self._lock:
            now = datetime.now()
            for room in config.ROOM_BETS:
                state = self.db.get_game_state(room)
                phase = state.get("phase")
                if phase == "preparation":
                    # keep the room looking alive: top up bots during the
                    # countdown too, so the player sees other players BEFORE
                    # the round starts (idempotent — stops at the cap)
                    if self.db.get_bots_enabled(room):
                        # add ONE bot per tick so players see them joining
                        # gradually (feels like humans picking cards)
                        breakdown = self.logic.player_breakdown(room)
                        if breakdown["real"] + breakdown["bots"] < config.MAX_TOTAL_PLAYERS:
                            self.logic.add_bot_player(room)
                    end = _parse(state.get("preparation_end_time"))
                    if end and now >= end:
                        self.start_round(room)
                elif phase == "playing":
                    nxt = _parse(state.get("next_call_time"))
                    if nxt and now >= nxt:
                        self.call_step(room)
                elif phase == "ended":
                    rst = _parse(state.get("reset_time"))
                    if rst and now >= rst:
                        self.reset_round(room)

    # ------------------------------------------------------------ lifecycle
    def start_round(self, room: int = 30) -> bool:
        """preparation -> playing. Returns True on success."""
        with self._lock:
            state = self.db.get_game_state(room)
            if state.get("phase") != "preparation":
                return False

            bots_enabled = self.db.get_bots_enabled(room)
            if bots_enabled:
                self.logic.ensure_minimum_players(room)
                # persist bot accounts (negative ids) for the /api/admin/bots view
                for sel in self.db.get_all_selections(room):
                    if sel["user_id"] < 0:
                        name = bot_name(sel["user_id"])
                        self.db.record_bot(sel["user_id"], name, 1)
                        self.db.update_username(sel["user_id"], name)
            # fresh round -> fresh bot-claim schedule
            self._bot_claim_at[room] = {}

            round_number = int(state.get("round_number") or 0) + 1
            # a fresh round means a fresh eligibility window: any false-BINGO
            # eliminations from the previous round no longer apply
            self.db.clear_eliminations()
            self.db.set_ball_order(room, self.logic.new_ball_order())
            pool = self.logic.calculate_prize_pool(room)
            game_id = self.db.create_game(round_number, room)
            self.db.update_game_state(
                room,
                phase="playing",
                round_number=round_number,
                current_game_id=game_id,
                current_call=None,
                winner_user_id=None,
                winning_pattern=None,
                preparation_end_time=None,
                next_call_time=_iso(config.CALL_INTERVAL_SECONDS),
                reset_time=None,
                prize_pool=pool["prize_pool"],
                total_bets=pool["total_bets"],
            )
            logger.info("%s round %s started · pool=%s · players=%s",
                        config.room_label(room), round_number,
                        pool["prize_pool"], pool["real_players"])
            return True

    def call_step(self, room: int = 30) -> dict | None:
        """Call the next ball.

        A winner is ONLY declared when a player presses the BINGO button
        (claim_bingo) — the loop never auto-announces a winner, even when a
        card already has a winning pattern. If all 75 balls are called before
        anyone claims, the round ends without a winner.
        """
        with self._lock:
            state = self.db.get_game_state(room)
            if state.get("phase") != "playing":
                return None
            number = self.logic.call_next_number(room)
            if number is None:
                # all 75 balls have been called -> round ends without winner
                self.end_round_no_winner(room)
                return None
            called = self.db.get_called_numbers(room)
            # bots can claim this ball — the first bot whose delay elapsed
            # presses BINGO and may END the round right here
            winner = self._bot_claim_pass(room)
            if self.db.get_game_state(room).get("phase") == "playing":
                self.db.update_game_state(room, next_call_time=_iso(config.CALL_INTERVAL_SECONDS))
            return {"number": number, "called": len(called), "winner": winner}

    def handle_winner(self, room: int, winner: dict) -> None:
        """Declare the round ended, pay the winner immediately, log history."""
        with self._lock:
            state = self.db.get_game_state(room)
            prize = int(winner.get("prize") or 0)
            self.db.update_credit(winner["user_id"], prize)
            payload = {
                "pattern": winner.get("pattern", "BINGO"),
                "patterns": winner.get("patterns", []),
                "prize": prize,
                "card_id": winner.get("card_id"),
                # the exact cells that made the pattern — lets the Mini App
                # draw the winning pattern visually for every player
                "winning_cells": winner.get("winning_cells", []),
            }
            self.db.update_game_state(
                room,
                phase="ended",
                winner_user_id=winner["user_id"],
                winning_pattern=json.dumps(payload),
                next_call_time=None,
                reset_time=_iso(config.POST_GAME_RESET_SECONDS),
            )
            self._write_history(state, winner["user_id"], prize, room)
            game_id = state.get("current_game_id")
            winner_name = self._name_of(winner["user_id"])
            pool = self.logic.calculate_prize_pool(room)
            self.db.finish_game(game_id, winner["user_id"], winner_name,
                                payload["pattern"], pool["total_bets"], prize,
                                pool["total_bets"] - prize, "finished")
            self._distribute_referral_commissions(room, state)
            try:
                self.db.log_activity('round_winner', winner["user_id"],
                                     f'{winner_name} won {prize} '
                                     f'{config.APP_CURRENCY} ({payload["pattern"]})')
            except Exception:
                pass
            logger.info("%s winner: %s (%s) won %s",
                        config.room_label(room), winner_name, payload["pattern"], prize)

    def end_round_no_winner(self, room: int = 30) -> None:
        """75th ball called and nobody completed a pattern."""
        with self._lock:
            state = self.db.get_game_state(room)
            self.db.update_game_state(
                room,
                phase="ended",
                winner_user_id=None,
                winning_pattern=json.dumps({"pattern": None, "prize": 0}),
                next_call_time=None,
                reset_time=_iso(config.POST_GAME_RESET_SECONDS),
            )
            self._write_history(state, None, 0, room)
            game_id = state.get("current_game_id")
            pool = self.logic.calculate_prize_pool(room)
            self.db.finish_game(game_id, None, None, "none", pool["total_bets"], 0,
                                pool["total_bets"], "finished")
            self._distribute_referral_commissions(room, state)
            logger.info("%s round %s ended without a winner (75 balls)",
                        config.room_label(room), state.get("round_number"))

    def _distribute_referral_commissions(self, room: int, state: dict) -> None:
        """After a round ends, pay 5%% commission to the referring admin
        for every REAL player they referred. Commission is calculated from
        that player's total bet amount across all their cards in the round.

        Bots (negative user ids) never generate commissions.
        """
        rate = config.REFERRAL_COMMISSION_RATE
        if rate <= 0:
            return
        game_id = state.get("current_game_id")
        selections = self.db.get_all_selections(room)
        # group bets by user
        bets_by_user: dict[int, int] = {}
        for sel in selections:
            uid = sel["user_id"]
            if uid > 0:  # real players only
                bets_by_user.setdefault(uid, 0)
                bets_by_user[uid] += sel["bet_amount"]
        for uid, total_bet in bets_by_user.items():
            referrer_id = self.db.get_referred_by(uid)
            if referrer_id is None:
                continue
            commission = int(total_bet * rate)
            if commission <= 0:
                continue
            self.db.record_referral_commission(
                referrer_id, uid, game_id, room, total_bet, commission)
            self.db.apply_referral_commission(referrer_id, commission)
            try:
                referrer_name = self._name_of(referrer_id)
                referred_name = self._name_of(uid)
                # every commission is logged for the super admin's All Logs view
                self.db.log_activity(
                    'referral_commission', referrer_id,
                    f'+{commission} {config.APP_CURRENCY} from {referred_name}'
                    f'\'s bet of {total_bet} (rate {int(rate * 100)}%)')
            except Exception:
                pass
            try:
                from bot import notify_user
                referrer_name = self._name_of(referrer_id)
                referred_name = self._name_of(uid)
                notify_user(referrer_id, [
                    '💰 REFERRAL COMMISSION',
                    f'+{commission} {config.APP_CURRENCY} from {referred_name}\'s round',
                    f'Bet: {total_bet} ETB · Rate: {int(rate * 100)}%',
                    f'Your new balance: {self.db.get_credit(referrer_id)} ETB',
                ])
            except Exception:
                pass

    def reset_round(self, room: int = 30) -> None:
        """ended -> fresh preparation phase."""
        with self._lock:
            self._bot_claim_at[room] = {}
            self.db.clear_selections(room)
            self.db.clear_called_numbers(room)
            self.db.clear_eliminations()
            self.db.update_game_state(
                room,
                phase="preparation",
                preparation_end_time=_iso(config.PREPARATION_SECONDS),
                current_call=None,
                winner_user_id=None,
                winning_pattern=None,
                prize_pool=0,
                total_bets=0,
                next_call_time=None,
                reset_time=None,
            )
            logger.info("%s: new preparation round (%ss)",
                        config.room_label(room), config.PREPARATION_SECONDS)

    # ------------------------------------------------------------- bot claims
    # Difficulty levels: how many balls a bot waits before claiming.
    # 0=Easy (never claim), 1=Normal(5-8), 2=Medium(3-5),
    # 3=Hard(1-2), 4=VeryHard(0-1), 5=Impossible(0)
    _DIFFICULTY_DELAY = {
        0: None,         # never claim — bots are powerless
        1: (5, 8),       # very slow, humans always win
        2: (3, 5),       # default human-like delay
        3: (1, 2),       # fast, often beats humans
        4: (0, 1),       # near-instant
        5: (0, 0),       # instant — impossible to beat
    }

    def _bot_claim_pass(self, room: int = 30) -> dict | None:
        """Bots press BINGO like humans — only when a card actually has a
        complete pattern. The claim delay is controlled by bots_difficulty:
          0 (Easy)      — never claim, bots are powerless
          1 (Normal)    — 5-8 ball delay, rarely win
          2 (Medium)    — 3-5 ball delay, default
          3 (Hard)      — 1-2 ball delay, often win
          4 (Very Hard) — 0-1 ball delay, very powerful
          5 (Impossible)— instant claim, impossible to beat"""
        if not self.db.get_bots_enabled(room):
            return None
        state = self.db.get_game_state(room)
        if state.get("phase") != "playing" or state.get("winner_user_id"):
            return None
        called = set(self.db.get_called_numbers(room))
        cards = self.db.get_cards_map()
        index = len(called)
        difficulty = self.db.get_bots_difficulty(room)
        delay_range = self._DIFFICULTY_DELAY.get(difficulty, (3, 5))
        # difficulty 0 = bots never claim
        if delay_range is None:
            return None
        ready = self._bot_claim_at.setdefault(room, {})
        # discover bots with a winning card; schedule a delayed claim for them
        for sel in self.db.get_all_selections(room):
            if sel["user_id"] > 0:
                continue  # real players claim themselves
            card = cards.get(sel["card_id"])
            if not card:
                continue
            patterns, _ = self.logic.check_winning_patterns(card, called)
            if patterns and sel["user_id"] not in ready:
                lo, hi = delay_range
                ready[sel["user_id"]] = index + random.randint(lo, hi)
        # claim the first bot whose delay has elapsed — ONLY through cards that
        # actually have a complete pattern (a bot must never false-claim itself)
        claimants = sorted((bid, at) for bid, at in ready.items() if at <= index)
        for bid, _ in claimants:
            for s in self.db.get_user_selections(bid, room):
                card = cards.get(s["card_id"])
                if not card:
                    continue
                patterns, _ = self.logic.check_winning_patterns(card, called)
                if not patterns:
                    continue
                result = self.claim_bingo(bid, s["card_id"], room)
                if result.get("ok"):
                    ready.pop(bid, None)
                    return result["winner"]
            ready.pop(bid, None)
        return None

    # ------------------------------------------------------------- claim-bingo
    def claim_bingo(self, user_id: int, card_id: str | None = None,
                    room: int = 30) -> dict:
        """Player presses BINGO in the Mini App. Verify, then pay.

        This is the ONLY way a winner is declared — the ball loop never
        auto-announces a winner.

        Valid claim  -> the normal winner flow runs.
        False claim  -> the player is ELIMINATED for the current round:
        their cards stop participating (but their already-paid bet stays in
        the prize pool), they get no refund and cannot claim again. The
        elimination is persisted, so a server restart mid-round cannot
        revive them. They are eligible again next round.
        """
        with self._lock:
            state = self.db.get_game_state(room)
            if state.get("phase") != "playing":
                return {"ok": False, "message": "The game is not in progress right now."}
            if state.get("winner_user_id"):
                return {"ok": False, "message": "This round already has a winner."}
            game_id = state.get("current_game_id")
            if user_id in self.db.get_eliminated_user_ids(game_id):
                return {"ok": False, "eliminated": True,
                        "message": "You have already been eliminated from this round."}
            selections = self.db.get_user_selections(user_id, room)
            if card_id:
                selections = [s for s in selections if s["card_id"] == card_id]
            if not selections:
                return {"ok": False, "message": "You have no cards in this round."}
            called = set(self.db.get_called_numbers(room))
            for sel in selections:
                card_numbers = self.db.get_card(sel["card_id"])
                if not card_numbers:
                    continue
                patterns, cells = self.logic.check_winning_patterns(card_numbers, called)
                if patterns:
                    prize = self.logic.calculate_prize_pool(room)["prize_pool"]
                    winner = {
                        "user_id": user_id,
                        "card_id": sel["card_id"],
                        "pattern": patterns[0],
                        "patterns": patterns,
                        "winning_cells": cells,
                        "prize": prize,
                    }
                    self.handle_winner(room, winner)
                    return {"ok": True, "winner": winner}
            # no valid pattern -> FALSE BINGO -> eliminated for this round only
            self.db.add_elimination(game_id, user_id, "false_bingo")
            return {"ok": False, "eliminated": True,
                    "message": "False BINGO. You have been eliminated from this round."}

    # ------------------------------------------------------------------ admin
    def force_start(self, room: int = 30) -> dict:
        return {"ok": self.start_round(room)}

    def force_call(self, room: int = 30) -> dict:
        """Call one ball immediately; the regular cadence resumes afterwards."""
        with self._lock:
            result = self.call_step(room)
            if result is None:
                return {"ok": False, "message": "Game is not running."}
            # only reschedule the cadence if the round is still running
            if self.db.get_game_state(room).get("phase") == "playing":
                self.db.update_game_state(room, next_call_time=_iso(config.CALL_INTERVAL_SECONDS))
            return {"ok": True, "number": result["number"],
                    "winner": result["winner"]}

    def add_bots(self, room: int = 30) -> dict:
        with self._lock:
            added = self.logic.ensure_minimum_players(room)
            for sel in self.db.get_all_selections(room):
                if sel["user_id"] < 0:
                    name = bot_name(sel["user_id"])
                    self.db.record_bot(sel["user_id"], name, 1)
                    self.db.update_username(sel["user_id"], name)
            return {"ok": True, "added": added,
                    "total": self.logic.player_breakdown(room)["bots"]}

    def toggle_bots(self, enabled: bool | None = None) -> dict:
        with self._lock:
            current = self.db.get_bots_enabled()
            enabled = (not current) if enabled is None else enabled
            self.db.set_bots_enabled(enabled)
            return {"ok": True, "enabled": enabled}

    def set_bots_difficulty(self, level: int | None = None) -> dict:
        """Set bot difficulty (0-5). 0=Easy (powerless), 5=Impossible."""
        with self._lock:
            if level is None:
                level = self.db.get_bots_difficulty()
            level = max(0, min(5, int(level)))
            self.db.set_bots_difficulty(level)
            return {"ok": True, "difficulty": level}

    # ------------------------------------------------------------- utilities
    def _name_of(self, user_id: int) -> str:
        """Display identity — the stored full name is authoritative."""
        p = self.db.get_player(user_id)
        if p:
            if p.get("full_name"):
                return p["full_name"]
            if p.get("username"):
                return p["username"]
        return bot_name(user_id) if user_id < 0 else "Player"

    def _write_history(self, state: dict, winner_user_id, winner_prize: int,
                       room: int = 30) -> None:
        """Record a game_history row per real player."""
        game_id = state.get("current_game_id")
        eliminated = set(self.db.get_eliminated_user_ids(game_id))
        by_user: dict[int, list] = {}
        for sel in self.db.get_all_selections(room):
            if sel["user_id"] > 0:
                by_user.setdefault(sel["user_id"], []).append(sel)
        for uid, sels in by_user.items():
            total_bet = sum(s["bet_amount"] for s in sels)
            winnings = winner_prize if uid == winner_user_id else 0
            if winnings:
                status = "winner"
            elif uid in eliminated:
                status = "eliminated"
            else:
                status = "played"
            self.db.add_history(game_id, uid, [s["card_id"] for s in sels],
                                total_bet, winnings, self.db.get_credit(uid), status)
