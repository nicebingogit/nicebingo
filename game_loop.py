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
from typing import Tuple

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
        # NO cached bot target: the plan is recomputed every time from the
        # CURRENT human-player count (fewer humans -> more bots, 80-140; more
        # humans -> fewer bots, 18-39) plus a per-bot card plan with a random
        # 5-15 card deduction. Prep ticks fill toward a provisional plan and
        # start_round() rebuilds it with the final human count and tops up.

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
            # GUARANTEED bot fill at boot: fill every room with bots enabled
            # straight to its plan target BEFORE the first tick runs — even a
            # fresh room (or one reloaded mid-round with 0 players) never
            # shows an empty table. The ticker keeps topping up from here.
            for room in config.ROOM_BETS:
                self._ensure_bot_players(room)
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
                # paused rooms are frozen — the game loop does nothing until
                # the super admin explicitly resumes
                if state.get("paused", 0):
                    continue
                phase = state.get("phase")
                if phase == "preparation":
                    # keep the room looking alive: top up bot players during
                    # the countdown too, so the player sees other players
                    # BEFORE the round starts. Bots join gradually (up to 8
                    # per tick) toward the current plan (chosen by human
                    # count) — never all at once. Bots disabled keeps just
                    # ONE other player (nobody plays alone).
                    self._add_prep_bots(room, state)
                    end = _parse(state.get("preparation_end_time"))
                    if end and now >= end:
                        self.start_round(room)
                elif phase == "playing":
                    # self-healing fill: even if a round entered play before
                    # bots were added (e.g. stale DB / reload mid-round), bot
                    # players join like any player (up to 8 per tick) instead
                    # of the room staying empty all round
                    self._ensure_bot_players(room, cap=8)
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

            # final bot plan, based on the CURRENT human count: prep ticks
            # seeded part of it, so top the rest up slot-by-slot right now —
            # a round NEVER starts with 0 players. With bots disabled this
            # keeps exactly ONE other player in the room (nobody plays alone;
            # the toggle only silences their auto-claims).
            target, cards_each, plan = self._bot_plan(room)
            self._ensure_bot_players(room)
            logger.info("%s: round starts with %s bot players · %s cards each",
                        config.room_label(room), target, cards_each)
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
        (claim_bingo) — the loop never auto-announces a winner mid-round, even
        when a card already has a winning pattern. 75/75 ALWAYS stops the
        round, exactly like a standard bingo game: on every difficulty other
        than Impossible the round simply ends winless when the machine is
        empty (no forced bot win, no shortened game — normal duration and
        pacing are preserved). ONLY on Impossible (difficulty 5) the last
        ball is handed to a bot so a human can still never win.
        """
        with self._lock:
            state = self.db.get_game_state(room)
            if state.get("phase") != "playing":
                return None
            # 75/75 FIRST — the round MUST stop once every ball has been
            # called, BEFORE any difficulty guard can look at the (now empty)
            # ball machine. Standard-bingo end: with no winner after all 75
            # balls the round ends winless on every difficulty EXCEPT
            # Impossible (5), where a ready bot is declared the winner so a
            # human can never win — normal game duration is never shortened.
            if not self.db.get_ball_order(room):
                if self.db.get_bots_difficulty(room) == 5:
                    winner = self._bot_win_claim(room)
                    if winner is not None:
                        return {"number": None,
                                "called": len(self.db.get_called_numbers(room)),
                                "winner": winner}
                self.end_round_no_winner(room)
                return None
            # IMPOSSIBLE (difficulty 5): the next ball is never allowed to
            # complete a HUMAN pattern — if it would, reorder the ball machine
            # so the next ball completes a bot card instead (bots claim
            # instantly on this difficulty and win first). Runs only while
            # balls remain (checked above).
            if self.db.get_bots_difficulty(room) == 5:
                order = self._impossible_guard(room)
                if order is None:
                    return None  # round already ended winless — nothing to call
                if order != self.db.get_ball_order(room):
                    self.db.set_ball_order(room, order)
            number = self.logic.call_next_number(room)
            if number is None:
                # Defensive duplicate of the 75/75 stop above — the machine
                # emptied between the order check and the pop.
                if self.db.get_bots_difficulty(room) == 5:
                    winner = self._bot_win_claim(room)
                    if winner is not None:
                        return {"number": None,
                                "called": len(self.db.get_called_numbers(room)),
                                "winner": winner}
                self.end_round_no_winner(room)
                return None
            called = self.db.get_called_numbers(room)
            # bots can claim this ball — the first bot whose delay elapsed
            # presses BINGO and may END the round right here (95%+ of rounds
            # with bots ON are decided well before ball 75)
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
            # bot plan is recomputed from the current human count every tick —
            # nothing to drop between rounds
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
            # never let the fresh countdown stare at an empty room: seed a
            # first batch of bot players immediately; prep ticks + start_round()
            # top the rest up gradually toward the plan target.
            self._ensure_bot_players(room, cap=8)
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

    # ------------------------------------------------------------- bot filling
    def _bot_plan(self, room: int = 30) -> Tuple[int, int, list]:
        """Build this instant's bot-fill plan for the room.

        Returns (target, cards_each, per_bot_card_counts). Recomputed every
        call so it always follows the CURRENT human count — fewer humans get
        the fullest option (80-140 bots), more humans get a lighter fill
        (18-39 bots). Prep ticks fill toward a provisional plan; start_round()
        rebuilds it with the final human count and tops up slot-by-slot.
        """
        humans = self.logic.human_player_count(room)
        target = self.logic.pick_bot_target(humans)
        cards_each = self.logic.bot_cards_for_count(target)
        plan = self.logic.bot_card_plan(target, cards_each)
        return target, cards_each, plan

    def _ensure_bot_players(self, room: int = 30,
                            cap: int | None = None) -> int:
        """Guarantee bot "players" exist in the room (self-healing fill).

        Callers hold the loop lock. BOT PRESENCE IS UNCONDITIONAL — bots are
        involved in the game BY ANY CASE, no matter what. With bots ENABLED
        the room is filled toward the CURRENT plan — recomputed from today's
        human count — so it can NEVER sit at 0 players, no matter how it
        reached its phase:
          * start()        -> full fill at boot, before the first tick
          * reset_round()  -> seed batch, so a new countdown never shows 0
          * tick() (prep + playing) -> top-up of up to `cap` per tick
          * start_round() / add_bots() -> fill the rest to the plan target
        With bots DISABLED the room keeps exactly ONE other player holding a
        card — nobody should ever play alone — and no more are ever added
        while that one is present (the toggle only re-enables auto-claims;
        joining as a normal player is what keeps the room non-empty).
        `cap` limits how many join per call (ticker uses 8 for a natural
        pace); None fills straight to the plan target. Bot accounts are also
        persisted (bots table + usernames refreshed) for the super-admin
        /api/admin/bots view. Returns how many bots were added.
        """
        if not self.db.get_bots_enabled(room):
            # BOTS OFF — guarantee ONE other player so nobody plays alone.
            if self.logic.bot_player_count(room) >= 1:
                return 0
            try:
                # None = the historical human-like 2-3 random cards
                if not self.logic.add_bot_player(room, None):
                    return 0
            except Exception:
                logger.exception("%s: solo-companion bot fill failed",
                                 config.room_label(room))
                return 0
            for sel in self.db.get_all_selections(room):
                if sel["user_id"] < 0:
                    name = bot_name(sel["user_id"])
                    self.db.record_bot(sel["user_id"], name, 1)
                    self.db.update_username(sel["user_id"], name)
            return 1
        target, cards_each, plan = self._bot_plan(room)
        current = self.logic.bot_player_count(room)
        goal = target if cap is None else min(target, current + cap)
        added = 0
        while self.logic.bot_player_count(room) < goal:
            slot = self.logic.bot_player_count(room)
            cards = plan[slot] if slot < len(plan) else cards_each
            try:
                if not self.logic.add_bot_player(room, cards):
                    break
            except Exception:
                logger.exception("%s: bot fill skipped a bad bot",
                                 config.room_label(room))
                break
            added += 1
        if added:
            for sel in self.db.get_all_selections(room):
                if sel["user_id"] < 0:
                    name = bot_name(sel["user_id"])
                    self.db.record_bot(sel["user_id"], name, 1)
                    self.db.update_username(sel["user_id"], name)
        return added

    def _add_prep_bots(self, room: int = 30, state: dict | None = None) -> int:
        """During preparation, join bot players gradually toward the current
        plan's target instead of dumping them all at once (up to 8 per tick).
        The plan is recomputed from the CURRENT human count on every call; the
        initial seed happens immediately on reset, and start_round() does the
        final top-up. With bots disabled this keeps just ONE other player in
        the room (nobody plays alone)."""
        return self._ensure_bot_players(room, cap=8)

    # ------------------------------------------------- Difficulty 5 (Impossible)
    # Humans can NEVER win on Impossible: before each ball is called, if that
    # ball would complete a human's pattern, the ball machine is reordered so
    # the next ball completes a BOT card instead. Impossible bots claim
    # instantly (delay 0-0) through the regular _bot_claim_pass and win.
    def _human_completing_ball(self, room: int = 30, called: set | None = None) -> str | None:
        """Return the next ball if drawing it would complete a HUMAN pattern
        (or if a human already holds a complete pattern)."""
        order = self.db.get_ball_order(room) or []
        if not order:
            return None
        next_ball = order[0]
        if called is None:
            called = set(self.db.get_called_numbers(room))
        for sel in self.db.get_all_selections(room):
            if sel["user_id"] < 0:
                continue  # humans only
            card = self.db.get_card(sel["card_id"])
            if not card:
                continue
            if self.logic.check_winning_patterns(card, called)[0]:
                return next_ball  # human already complete
            if self.logic.check_winning_patterns(card, called | {next_ball})[0]:
                return next_ball
        return None

    def _bot_completing_ball(self, room: int = 30, called: set | None = None) -> str | None:
        """Return a remaining ball that would complete a BOT card, if any.
        With bots enabled this is guaranteed to exist whenever it's needed.
        """
        order = self.db.get_ball_order(room) or []
        if not order:
            return None
        if called is None:
            called = set(self.db.get_called_numbers(room))
        bots = []
        cards = self.db.get_cards_map()
        for sel in self.db.get_all_selections(room):
            if sel["user_id"] > 0:
                continue  # bots only
            card = cards.get(sel["card_id"])
            if not card:
                continue
            if self.logic.check_winning_patterns(card, called)[0]:
                return order[0]  # a bot already wins — keep the natural order
            bots.append(card)
        if not bots:
            return None
        for b in order:
            union = called | {b}
            for card in bots:
                if self.logic.check_winning_patterns(card, union)[0]:
                    return b
        return None

    def _impossible_guard(self, room: int = 30) -> list | None:
        """Difficulty-5 pre-call guard: never let the next ball complete a
        human card. Returns the (possibly reordered) remaining ball order, or
        None when the round was ended without a winner (nothing left to call).
        """
        order = self.db.get_ball_order(room) or []
        if not order:
            return None
        called = set(self.db.get_called_numbers(room))
        if not self.db.get_bots_enabled(room):
            # bots disabled -> hand the win to NOBODY; block every human
            # completing ball, ending the round winless if none remain safe
            if self._human_completing_ball(room, called) is not None:
                ordered = [b for b in order
                           if not self._human_would_win(room, called, b)]
                if ordered:
                    return ordered
                self.end_round_no_winner(room)
                return None
            return order
        # bots enabled -> hand the win to a BOT instead of the human
        if self._human_completing_ball(room, called) is not None:
            bot_ball = self._bot_completing_ball(room, called)
            if bot_ball is None:
                # no single remaining ball completes a bot card yet: DEFER every
                # human-completing ball to the end and keep calling safe balls
                # until a bot card completes (then the guard hands it the win).
                # The round ends winless only when EVERY remaining ball would
                # complete a human — nobody can win then.
                safe = [b for b in order
                        if not self._human_would_win(room, called, b)]
                if safe:
                    return safe + [b for b in order if b not in safe]
                self.end_round_no_winner(room)
                return None
            if bot_ball != order[0]:
                # bring the bot-completing ball forward: the very next call
                # completes that bot, which claims instantly and wins
                return [bot_ball] + [b for b in order if b != bot_ball]
        return order

    def _human_would_win(self, room: int = 30, called: set | None = None,
                         ball: str | None = None) -> bool:
        """True if a human card has a complete pattern with `called` plus
        `ball` (or with `called` alone when ball is None)."""
        if called is None:
            called = set(self.db.get_called_numbers(room))
        union = called if ball is None else called | {ball}
        for sel in self.db.get_all_selections(room):
            if sel["user_id"] < 0:
                continue
            card = self.db.get_card(sel["card_id"])
            if card and self.logic.check_winning_patterns(card, union)[0]:
                return True
        return False

    def _bot_winning_card(self, room: int = 30, called: set | None = None) -> dict | None:
        """Return a bot selection whose card has a complete pattern, or None."""
        if called is None:
            called = set(self.db.get_called_numbers(room))
        cards = self.db.get_cards_map()
        for sel in self.db.get_all_selections(room):
            if sel["user_id"] > 0:
                continue  # bots only
            card = cards.get(sel["card_id"])
            if card and self.logic.check_winning_patterns(card, called)[0]:
                return sel
        return None

    def _bot_win_claim(self, room: int = 30, sel: dict | None = None) -> dict | None:
        """Declare a ready bot the round winner (used by the Impossible
        backstop when a human tries to claim). Returns the winner dict."""
        if sel is None:
            sel = self._bot_winning_card(room)
        if sel is None:
            return None
        called = set(self.db.get_called_numbers(room))
        cards = self.db.get_cards_map()
        card = cards.get(sel["card_id"])
        if not card:
            return None
        patterns, cells = self.logic.check_winning_patterns(card, called)
        if not patterns:
            return None
        prize = self.logic.calculate_prize_pool(room)["prize_pool"]
        winner = {
            "user_id": sel["user_id"],
            "card_id": sel["card_id"],
            "pattern": patterns[0],
            "patterns": patterns,
            "winning_cells": cells,
            "prize": prize,
        }
        self.handle_winner(room, winner)
        return winner

    def _force_bot_win(self, room: int = 30) -> Tuple[str | None, dict | None]:
        """Declare a ready bot the round winner — the IMPOSSIBLE backstop.

        If a bot card already has a complete pattern it claims right away;
        otherwise the machine is reordered so the NEXT ball completes a bot
        card, which is then called and claimed. Used ONLY when a HUMAN tries
        to claim on Impossible (difficulty 5): a human can never win there,
        so the win lands on a bot "player" instead (just a player with an
        Ethiopian name — nobody is ever told about bots). The game duration
        is NEVER shortened by this — it only fires inside a human claim.
        Returns (number, winner), or (None, None) when no bot can win yet.
        """
        with self._lock:
            called = set(self.db.get_called_numbers(room))
            order = self.db.get_ball_order(room) or []
            sel = self._bot_winning_card(room, called)
            if sel is not None:
                self._bot_claim_at[room].pop(sel["user_id"], None)
                return None, self._bot_win_claim(room, sel)
            if not order:
                return None, None
            cards = self.db.get_cards_map()
            bots = [s for s in self.db.get_all_selections(room) if s["user_id"] < 0]
            for ball in order:
                union = called | {ball}
                for s in bots:
                    card = cards.get(s["card_id"])
                    if card and self.logic.check_winning_patterns(card, union)[0]:
                        self.db.set_ball_order(room, [ball] + [b for b in order if b != ball])
                        number = self.logic.call_next_number(room)
                        self._bot_claim_at[room].pop(s["user_id"], None)
                        return number, self._bot_win_claim(room, s)
            return None, None

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
            # IMPOSSIBLE (difficulty 5) — a HUMAN can never win. The pre-call
            # guard keeps the human's completing ball from ever being drawn,
            # so a claim here is normally a false claim handled by the normal
            # false-BINGO flow below. If a human somehow holds a valid pattern,
            # the win is handed to a bot player instead — the claim is NEVER
            # refused with a "you can't win" message, and regular players are
            # never told about bots: the winner is simply a player with an
            # Ethiopian name.
            human_impossible = self.db.get_bots_difficulty(room) == 5 and user_id > 0
            if human_impossible:
                _number, winner = self._force_bot_win(room)
                if winner is not None:
                    return {"ok": True, "winner": winner, "human": False}
            for sel in selections:
                card_numbers = self.db.get_card(sel["card_id"])
                if not card_numbers:
                    continue
                patterns, cells = self.logic.check_winning_patterns(card_numbers, called)
                if patterns:
                    if human_impossible:
                        # last-resort safety: only reachable when no bot could
                        # win (e.g. bots disabled) — end the round so a human
                        # can still never win on Impossible.
                        self.end_round_no_winner(room)
                        return {"ok": False, "message": "BINGO cannot be claimed right now."}
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
            # a super admin explicitly asking for bots is an affirmative
            # "bots ON" — re-enable auto-fill in case it was ever toggled off
            if not self.db.get_bots_enabled(room):
                self.db.set_bots_enabled(True)
            # consistent with the current human count's plan; also persists the
            # bot accounts so the super-admin /api/admin/bots view is current
            # (bots ENABLED -> full plan fill; DISABLED rooms keep 1 player)
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
