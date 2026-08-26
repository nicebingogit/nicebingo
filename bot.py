"""
Telegram bot — launcher for the immersive Bingo Mini App.

The bot itself does NOT run the game anymore.  The local Flask server
(server.py) owns the game loop; this bot:

  * opens the Mini App with a Web App button (/play)
  * announces round events to the chat by watching the shared SQLite DB
  * offers the classic text commands (status, balance, cards, …)
  * exposes the admin panel, which drives the server's admin API

Run:  python bot.py      (keep server.py running in another window)
"""
import asyncio
import json
import logging
import os
import threading
import urllib.parse
from datetime import datetime

import requests
from dotenv import load_dotenv
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram import ChatMember, ReplyKeyboardMarkup, KeyboardButton
from telegram.error import Forbidden
from telegram.ext import (
    Application, CommandHandler, CallbackQueryHandler, ChatMemberHandler,
    MessageHandler, ContextTypes, filters,
)

load_dotenv()
BOT_TOKEN = os.getenv("BOT_TOKEN", "").strip()

import config
from database import Database
from game_logic import GameLogic, bot_name

logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO,
)
logger = logging.getLogger(__name__)

HTTPS_HINT = (
    "🔒 **One more step:** Telegram only allows **HTTPS** addresses on the "
    "Mini App button, so `http://localhost` is rejected.\n\n"
    "👉 Double-click **`setup_tunnel.bat`** once (downloads a free tunnel tool), "
    "then **`run_tunnel.bat`** — it gives your PC a free `https://…trycloudflare.com` "
    "address and updates `.env` automatically. Then press **/play** again. 🎯"
)

db = Database(config.DB_PATH)
logic = GameLogic(db)


def _md(text) -> str:
    """Escape a user-supplied string for Telegram Markdown (parse_mode="Markdown").

    Usernames / first names / winner names can contain `_`, `*`, `[`, `` ` `` …
    which would break Markdown parsing and turn any message into the generic
    "Something went wrong" error — this is the #1 cause of that message.
    """
    return (str(text or "").replace("\\", "\\\\").replace("_", "\\_")
            .replace("*", "\\*").replace("[", "\\[").replace("`", "\\`"))


def _fresh_app_url() -> str:
    """The CURRENT Mini App URL, re-read from .env on every call.

    tunnel.py writes a brand-new https://…trycloudflare.com URL into .env every
    time it starts, so a long-running bot must not cache APP_URL at import —
    otherwise every command/button keeps pointing at the dead old tunnel and
    the bot only works again after a restart.
    """
    try:
        from dotenv import dotenv_values
        url = (dotenv_values() or {}).get("APP_URL") or config.APP_URL
    except Exception:
        url = config.APP_URL
    return (url or "").strip().rstrip("/")


class PremiumBingoBot:
    def __init__(self):
        self.application = None
        # the announcer tracks the last seen state PER ROOM (each room runs
        # its own round with its own ball order and pool)
        self._last = {room: {"phase": None, "count": -1, "round": None}
                      for room in config.ROOM_BETS}

    # ------------------------------------------------------------ rooms
    @staticmethod
    def _rooms_line() -> str:
        """One status line per room, e.g. '• Room by 30: PLAYING · pool 90 ETB'."""
        lines = []
        for room in config.ROOM_BETS:
            state = db.get_game_state(room)
            pool = logic.calculate_prize_pool(room)
            lines.append(f"• {config.room_label(room)}: **{state['phase'].upper()}** · "
                         f"pool **{pool['prize_pool']} ETB**")
        return "\n".join(lines)

    # ------------------------------------------------------------------ HTTP
    async def _post(self, path: str, payload: dict) -> dict:
        try:
            resp = await asyncio.to_thread(
                requests.post, f"{_fresh_app_url()}{path}", json=payload, timeout=8)
            return resp.json() if resp.status_code < 500 else {"error": "Server error"}
        except Exception:
            return {"error": "⚠️ Game server is offline — start server.py first."}

    async def _get(self, path: str, params: dict) -> dict:
        try:
            resp = await asyncio.to_thread(
                requests.get, f"{_fresh_app_url()}{path}", params=params, timeout=8)
            return resp.json()
        except Exception:
            return {"error": "⚠️ Game server is offline — start server.py first."}

    # ------------------------------------------------------------------ menus
    def _webapp_ok(self) -> bool:
        """Telegram only accepts https:// addresses on Web App buttons."""
        return _fresh_app_url().lower().startswith("https")

    def get_main_menu(self, user_id: int = 0):
        """Professional bot menu with clear sections and modern layout."""
        rows = []
        # ── PLAY ──────────────────────────────────────────
        if self._webapp_ok():
            rows.append([InlineKeyboardButton("🎮  Play Bingo",
                                              web_app={"url": _fresh_app_url()})])
        else:
            rows.append([InlineKeyboardButton("🔒  Mini App unavailable",
                                              callback_data="tunnel_help")])
        rows.append([])  # spacer
        # ── GAME ──────────────────────────────────────────
        rows.append([
            InlineKeyboardButton("📊  Status", callback_data="status"),
            InlineKeyboardButton("💰  Balance", callback_data="balance"),
        ])
        rows.append([
            InlineKeyboardButton("🎲  My Cards", callback_data="my_cards"),
            InlineKeyboardButton("🏆  Rankings", callback_data="leaderboard"),
        ])
        rows.append([])  # spacer
        # ── WALLET ────────────────────────────────────────
        rows.append([
            InlineKeyboardButton("⬇️  Deposit", callback_data="wallet_deposit"),
            InlineKeyboardButton("⬆️  Withdraw", callback_data="wallet_withdraw"),
        ])
        rows.append([
            InlineKeyboardButton("📋  My Requests", callback_data="requests"),
            InlineKeyboardButton("🚨  Appeal", callback_data="appeal_list"),
        ])
        rows.append([])  # spacer
        # ── MORE ──────────────────────────────────────────
        rows.append([
            InlineKeyboardButton("🔗  Referral", callback_data="referral"),
            InlineKeyboardButton("❓  Help", callback_data="help"),
        ])
        return InlineKeyboardMarkup(rows)

    def get_game_menu(self):
        return InlineKeyboardMarkup([
            [InlineKeyboardButton("📋 Status", callback_data="status"),
             InlineKeyboardButton("🔄 Refresh", callback_data="refresh")],
            [InlineKeyboardButton("➕ Select Card", callback_data="select"),
             InlineKeyboardButton("➖ Remove Card", callback_data="deselect")],
            [InlineKeyboardButton("🎯 Show Cards", callback_data="show_cards"),
             InlineKeyboardButton("🏠 Menu", callback_data="menu")],
        ])

    @staticmethod
    def get_reply_keyboard(user_id: int = 0) -> ReplyKeyboardMarkup:
        """Persistent reply keyboard shown above the text input.

        Two rows of quick-action emoji buttons so the user always has
        fast access to the most common actions without scrolling through
        the inline menu.
        """
        from database import Database
        import config as _cfg
        _db = Database(_cfg.DB_PATH)
        is_admin = _db.is_admin(user_id)
        row1 = [
            KeyboardButton("🎮 Play"),
            KeyboardButton("💰 Balance"),
            KeyboardButton("🎲 Cards"),
        ]
        row2 = [
            KeyboardButton("⬇️ Deposit"),
            KeyboardButton("⬆️ Withdraw"),
            KeyboardButton("🚨 Appeal"),
        ]
        if is_admin:
            row2.append(KeyboardButton("🔧 Admin"))
        return ReplyKeyboardMarkup(
            [row1, row2],
            resize_keyboard=True,
            one_time_keyboard=False,
        )

    def get_admin_menu(self):
        """Professional admin panel with grouped actions."""
        return InlineKeyboardMarkup([
            # ── Round Control ──
            [InlineKeyboardButton("▶️  Force Start", callback_data="admin_start"),
             InlineKeyboardButton("⏭  Call Next Ball", callback_data="admin_call")],
            [InlineKeyboardButton("🔄  Reset Round", callback_data="admin_reset")],
            # ── Players ──
            [InlineKeyboardButton("🤖  Add Bots", callback_data="admin_bots"),
             InlineKeyboardButton("🔀  Toggle Bots", callback_data="admin_bots_toggle")],
            # ── Stats ──
            [InlineKeyboardButton("📊  Game Stats", callback_data="admin_status"),
             InlineKeyboardButton("🔗  Referrals", callback_data="referral")],
            # ── Back ──
            [InlineKeyboardButton("🏠  Main Menu", callback_data="menu")],
        ])

    # --------------------------------------------------------------- commands
    async def start_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """/start — asks a NEW user for their full name (first-time onboarding).

        Handles referral deep-links: /start REF_<referrer_id>
        The name is collected ONCE here in the chat. Existing users who already
        have a stored full name go straight to the normal welcome — they are
        never asked again (and /start alone never grants the welcome bonus).
        """
        user = update.effective_user
        # --- referral deep-link: /start REF_<referrer_id> ---
        referrer_id = None
        if context.args:
            raw = context.args[0].strip()
            if raw.startswith("REF_"):
                try:
                    referrer_id = int(raw[4:])
                except ValueError:
                    referrer_id = None
        if db.get_player(user.id) is None:
            # placeholder account — identity registration happens below
            db.create_player(user.id, user.username or user.first_name, credit=0)
            db.update_profile(user.id, registered=False)
        # process referral if valid
        if referrer_id and referrer_id != user.id:
            existing_ref = db.get_referred_by(user.id)
            # ANY user can refer friends — the feature is not admin-only anymore
            if existing_ref is None:
                db.create_referral(referrer_id, user.id)
                try:
                    db.log_activity('referral_signup', user.id,
                                   f'Referred by {referrer_id}')
                except Exception:
                    pass
                # notify the referring user
                try:
                    from bot import notify_user
                    notify_user(referrer_id, [
                        '🎉 NEW REFERRAL!',
                        f'User: {user.first_name} (ID: {user.id})',
                        'You will earn 5% commission on every round they play!',
                    ])
                except Exception:
                    pass
        player = db.get_player(user.id)
        if not (player.get("full_name") or "").strip():
            # first-time onboarding: collect the full name in the chat
            context.user_data["awaiting_full_name"] = True
            await update.message.reply_text(
                "🎰 **Welcome to Nice Bingo!**\n\n"
                "Before you continue, please enter your **full name**.",
                parse_mode="Markdown",
            )
            return
        await self._send_welcome(update, context)

    async def _send_welcome(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Professional welcome card — clean, modern, how-to-play guide."""
        user = update.effective_user
        player = db.get_player(user.id) or {}
        name = (player.get("full_name") or "").strip() or user.first_name
        credit = db.get_credit(user.id)
        is_admin = db.is_admin(user.id)
        is_super = user.id in config.SUPER_ADMIN_IDS
        badge = " ⭐" if is_super else (" 👑" if is_admin else "")
        room_names = " / ".join(config.room_label(r) for r in config.ROOM_BETS)
        room_bets = " / ".join(f"{r} ETB" for r in config.ROOM_BETS)
        text = (
            f"🎰  *NICE BINGO*\n"
            f"━━━━━━━━━━━━━━━━━━━━\n"
            f"Welcome, *{_md(name)}*{badge}\n"
            f"💰  Balance: *{credit} {config.APP_CURRENCY}*\n"
            f"━━━━━━━━━━━━━━━━━━━━\n\n"
            f"❓  *How to Play*\n"
            f"━━━━━━━━━━━━━━━━━━━━\n\n"
            f"*1.* Tap *🎮 Play Bingo* to open the full-screen arena\n"
            f"*2.* Pick a room (*{room_names}*) — fixed bet per card "
            f"({room_bets})\n"
            f"*3.* During the *{config.PREPARATION_SECONDS}s countdown*, pick up to "
            f"*{config.MAX_CARDS_PER_PLAYER}* cards\n"
            f"*4.* A ball is called every *{config.CALL_INTERVAL_SECONDS}s* — "
            f"numbers are marked automatically\n"
            f"*5.* Complete a row, column, diagonal or four corners → *BINGO!*\n"
            f"*6.* Winner takes *80%* of the prize pool — paid instantly\n\n"
            f"━━━━━━━━━━━━━━━━━━━━\n"
            f"*💰 Wallet* — Deposit & Withdraw right in this chat\n"
            f"*🔗 Referral* — Earn 5% commission on every round your friends play\n\n"
            f"*Commands:*\n"
            f"`/start`  `/menu`  `/play`  `/status`  `/balance`\n"
            f"`/deposit`  `/withdraw`  `/referral`  `/help`",
        )
        await update.message.reply_text(
            text,
            reply_markup=self.get_main_menu(user.id),
            parse_mode="Markdown",
        )
        # Show the persistent reply keyboard (stays above the text input)
        await update.message.reply_text(
            "👇 *Quick actions* — tap any button below:",
            reply_markup=self.get_reply_keyboard(user.id),
            parse_mode="Markdown",
        )
        

    async def text_handler(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Captures the full name when the bot is waiting for it (after /start),
        or processes one step of the deposit/withdraw wallet chat flow."""
        user = update.effective_user
        raw = (update.message.text or "").strip()
        # --- reply keyboard quick actions ---
        _rk = {
            "🎮 Play": "play",
            "💰 Balance": "balance",
            "🎲 Cards": "my_cards",
            "⬇️ Deposit": "wallet_deposit",
            "⬆️ Withdraw": "wallet_withdraw",
            "🚨 Appeal": "appeal_list",
            "🔧 Admin": "admin_panel",
            "🏠 Menu": "menu",
            "📊 Status": "status",
            "🏆 Leaderboard": "leaderboard",
            "🔗 Referral": "referral",
            "❓ Help": "help",
        }
        if raw in _rk:
            cb = _rk[raw]
            if cb == "play":
                await self.play_command(update, context)
            elif cb == "admin_panel":
                await self.admin_command(update, context)
            elif cb == "menu":
                await self.menu_command(update, context)
            elif cb == "balance":
                await self.balance_command(update, context)
            elif cb == "my_cards":
                await self.my_cards_command(update, context)
            elif cb == "status":
                await self.status_command(update, context)
            elif cb == "leaderboard":
                await self.top_command(update, context)
            elif cb == "referral":
                await self._show_referral(update, context, user.id)
            elif cb == "help":
                await self.help_command(update, context)
            elif cb in ("wallet_deposit", "wallet_withdraw"):
                kind = "deposit" if cb == "wallet_deposit" else "withdraw"
                try:
                    await self._wallet_start_reply(update, context, kind)
                except Exception as exc:
                    logger.warning("wallet start from reply keyboard: %s", exc)
                    await update.message.reply_text(
                        "⚠️ Something went wrong — please try /" + kind + " instead.",
                        reply_markup=self.get_main_menu(user.id))
            elif cb == "appeal_list":
                try:
                    await self.appeal_list(update, context)
                except Exception as exc:
                    logger.warning("appeal list from reply keyboard: %s", exc)
                    await update.message.reply_text(
                        "⚠️ Something went wrong — please try /requests instead.",
                        reply_markup=self.get_main_menu(user.id))
            return
        # --- wallet chat flow takes priority over everything ---
        if context.user_data.get("wallet_flow"):
            if not raw:
                await update.message.reply_text("Please enter a value.")
                return
            try:
                await self._wallet_flow_text(update, context, raw)
            except Exception as exc:
                logger.warning("wallet flow error: %s", exc)
                context.user_data.pop("wallet_flow", None)
                await update.message.reply_text(
                    "⚠️ Something went wrong — please try again.",
                    reply_markup=self.get_main_menu(user.id))
            return
        # --- appeal chat flow ---
        if context.user_data.get("appeal_flow"):
            if not raw:
                await update.message.reply_text("Please enter a reason.")
                return
            try:
                await self._appeal_flow_text(update, context, raw)
            except Exception as exc:
                logger.warning("appeal flow error: %s", exc)
                context.user_data.pop("appeal_flow", None)
                await update.message.reply_text(
                    "⚠️ Something went wrong — please try again.",
                    reply_markup=self.get_main_menu(user.id))
            return
        player0 = db.get_player(user.id) or {}
        if (player0.get("full_name") or "").strip():
            # already registered — nothing to collect (state lives in the DB,
            # so onboarding survives bot restarts / web-app reloads)
            context.user_data.pop("awaiting_full_name", None)
            return
        if not raw:
            await update.message.reply_text(
                "Please enter your full name — it can't be empty.", parse_mode="Markdown")
            return
        if len(raw) > 60:
            await update.message.reply_text(
                "That name is too long — please use at most 60 characters.",
                parse_mode="Markdown")
            return
        if db.get_player(user.id) is None:
            db.create_player(user.id, user.username or user.first_name, credit=0)
        player = db.get_player(user.id)
        had_name = bool((player.get("full_name") or "").strip())
        # the full name becomes the display identity everywhere (winner
        # announcements, admin user list, transactions, leaderboard, ...)
        db.update_profile(user.id, full_name=raw)
        context.user_data.pop("awaiting_full_name", None)
        if not had_name:
            # welcome bonus — granted exactly once, when the identity is first
            # registered. Repeated /start never re-grants it.
            db.set_credit(user.id, config.NEW_PLAYER_CREDIT)
            await update.message.reply_text(
                f"✅ **Registration complete**, {_md(raw)}! 🎉\n"
                f"💰 You received **{config.NEW_PLAYER_CREDIT} "
                f"{config.APP_CURRENCY}** as your welcome bonus.",
                parse_mode="Markdown",
            )
        else:
            await update.message.reply_text(
                f"✅ Got it, {_md(raw)} — your name has been updated.",
                parse_mode="Markdown",
            )
        await self._send_welcome(update, context)

    async def play_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        user = update.effective_user
        if update.callback_query:
            await update.callback_query.answer()
            msg = update.callback_query.message
            # web_app buttons can't be edited in place — always send fresh
            chat_id = msg.chat_id
        else:
            chat_id = update.message.chat_id
        if self._webapp_ok():
            keyboard = InlineKeyboardMarkup([
                [InlineKeyboardButton("🎮 OPEN BINGO ARENA",
                                      web_app={"url": _fresh_app_url()})],
                [InlineKeyboardButton("🏠 Back to Menu", callback_data="menu")],
            ])
            closing = ("Pick your room, select cards and play! "
                       "Works best inside Telegram on your phone or desktop.")
        else:
            keyboard = InlineKeyboardMarkup([
                [InlineKeyboardButton("🔒 Fix Mini App URL", callback_data="tunnel_help")],
                [InlineKeyboardButton("🏠 Back to Menu", callback_data="menu")],
            ])
            closing = HTTPS_HINT
        credit = db.get_credit(user.id)
        await context.bot.send_message(
            chat_id=chat_id,
            text=(
                f"🎰 **Bingo Arena**\n\n"
                f"💰 Balance: **{credit} {config.APP_CURRENCY}**\n\n"
                f"{self._rooms_line()}\n\n"
                f"{closing}"
            ),
            reply_markup=keyboard,
            parse_mode="Markdown",
        )

    async def status_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        query = update.callback_query
        if query:
            await query.answer()
            msg = query.message
        else:
            msg = update.message
        text = f"🎲 **Game Status**\n\n"
        for room in config.ROOM_BETS:
            state = db.get_game_state(room)
            called = db.get_called_numbers(room)
            pool = logic.calculate_prize_pool(room)
            progress = len(called)
            bar = "█" * int(progress / config.TOTAL_NUMBERS * 20) + \
                  "░" * (20 - int(progress / config.TOTAL_NUMBERS * 20))
            text += f"\n**{config.room_label(room)}** · {state['phase'].upper()} · " \
                    f"players **{pool['real_players']}**\n"
            if progress:
                text += f"🔢 Called: {bar} {progress}/{config.TOTAL_NUMBERS}\n"
            if state["phase"] == "preparation" and state.get("preparation_end_time"):
                try:
                    end = datetime.fromisoformat(state["preparation_end_time"])
                    remaining = max(0, int((end - datetime.now()).total_seconds()))
                    text += f"⏳ Countdown: **{remaining}s**\n"
                except (ValueError, TypeError):
                    pass
            text += f"💰 Prize pool: **{pool['prize_pool']} ETB**\n"
            if state["phase"] == "ended" and state.get("winner_user_id"):
                info = json.loads(state["winning_pattern"] or "{}")
                text += f"🏆 Winner: **{info.get('pattern')}** — {info.get('prize', 0)} ETB\n"
        if query:
            # inline taps edit in place instead of spamming new messages
            try:
                await query.edit_message_text(text, reply_markup=self.get_game_menu(),
                                              parse_mode="Markdown")
                return
            except Exception:
                pass
        await msg.reply_text(text, reply_markup=self.get_game_menu(), parse_mode="Markdown")

    async def balance_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        query = update.callback_query
        if query:
            await query.answer()
            msg = query.message
        else:
            msg = update.message
        user_id = update.effective_user.id
        credit = db.get_credit(user_id)
        cards_line = " · ".join(
            f"{config.room_label(room)}: {len(db.get_user_selections(user_id, room))}"
            for room in config.ROOM_BETS
        )
        await msg.reply_text(
            f"💰 **Balance**\n\nCurrent: **{credit} ETB**\n"
            f"🃏 Cards: {cards_line}",
            reply_markup=self.get_main_menu(user_id),
            parse_mode="Markdown",
        )

    async def my_cards_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        query = update.callback_query
        if query:
            await query.answer()
            msg = query.message
        else:
            msg = update.message
        user_id = update.effective_user.id
        all_sels = []
        for room in config.ROOM_BETS:
            all_sels += [(room, s) for s in db.get_user_selections(user_id, room)]
        if not all_sels:
            await msg.reply_text("No cards selected this round.", reply_markup=self.get_game_menu())
            return
        await msg.reply_text(f"🎯 Your {len(all_sels)} card(s):", reply_markup=self.get_game_menu())
        for room, sel in all_sels:
            card = db.get_card(sel["card_id"])
            if not card:
                continue
            called = set(db.get_called_numbers(room))
            patterns, cells = logic.check_winning_patterns(card, called)
            caption = (f"🎯 {config.room_label(room)} · Card #{sel['card_id']} · "
                       f"Bet {sel['bet_amount']} ETB")
            if patterns:
                caption += f"\n🏆 BINGO! Pattern: {patterns[0]}"
            await msg.reply_text(
                f"{caption}\n```\n{self._card_ascii(card, called)}```",
                parse_mode="Markdown",
            )

    @staticmethod
    def _card_ascii(card: dict, called: set) -> str:
        letters = ["B", "I", "N", "G", "O"]
        lines = ["   " + " ".join(l.center(3) for l in letters)]
        for row in range(5):
            cells = []
            for col, letter in enumerate(letters):
                v = card[letter][row]
                if v == "FREE":
                    cells.append("★")
                elif f"{letter}-{v}" in called:
                    cells.append("X")
                else:
                    cells.append(str(v))
            lines.append("  " + " ".join(c.center(3) for c in cells))
        return "\n".join(lines)

    async def history_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        user_id = update.effective_user.id
        rows = db.get_user_history(user_id)
        if not rows:
            await update.message.reply_text("No history yet — play a round!")
            return
        text = "📜 **Your last rounds**\n\n"
        for r in rows[:8]:
            cards = json.loads(r["card_ids"])
            text += f"• {r['played_at'][:16]} · {len(cards)} card(s) · bet {r['total_bet']} · " \
                    f"{'🏆 +' + str(r['winnings']) if r['winnings'] else '—'}\n"
        await update.message.reply_text(text, parse_mode="Markdown")

    async def top_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        top = db.top_players(10)
        if not top:
            await update.message.reply_text("No players yet!")
            return
        text = "🏆 **Leaderboard**\n\n"
        medals = ["🥇", "🥈", "🥉"]
        for i, p in enumerate(top):
            medal = medals[i] if i < 3 else f"{i + 1}."
            # the stored full name is the display identity
            name = p.get("full_name") or p.get("username") or "Anonymous"
            text += f"{medal} {_md(name)}: " \
                    f"**{p['credit']} {config.APP_CURRENCY}**\n"
        await update.message.reply_text(text, reply_markup=self.get_main_menu(update.effective_user.id), parse_mode="Markdown")

    async def help_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        query = update.callback_query
        if query:
            await query.answer()
            msg = query.message
        else:
            msg = update.message
        room_names = " / ".join(config.room_label(r) for r in config.ROOM_BETS)
        room_bets = " / ".join(f"{r} ETB" for r in config.ROOM_BETS)
        uid = update.effective_user.id
        text = (
            f"❓  *How to Play*\n"
            f"━━━━━━━━━━━━━━━━━━━━\n\n"
            f"*1.* Tap *🎮 Play Bingo* to open the full-screen arena\n"
            f"*2.* Pick a room (*{room_names}*) — fixed bet per card "
            f"({room_bets})\n"
            f"*3.* During the *{config.PREPARATION_SECONDS}s countdown*, pick up to "
            f"*{config.MAX_CARDS_PER_PLAYER}* cards\n"
            f"*4.* A ball is called every *{config.CALL_INTERVAL_SECONDS}s* — "
            f"numbers are marked automatically\n"
            f"*5.* Complete a row, column, diagonal or four corners → *BINGO!*\n"
            f"*6.* Winner takes *80%* of the prize pool — paid instantly\n\n"
            f"━━━━━━━━━━━━━━━━━━━━\n"
            f"*💰 Wallet* — Deposit & Withdraw right in this chat\n"
            f"*🔗 Referral* — Earn 5% commission on every round your friends play\n\n"
            f"*Commands:*\n"
            f"`/start`  `/menu`  `/play`  `/status`  `/balance`\n"
            f"`/deposit`  `/withdraw`  `/referral`  `/help`",
        )
        await msg.reply_text(
            text,
            reply_markup=self.get_main_menu(uid),
            parse_mode="Markdown",
        )

    # ----------------------------------------------------------- card pick flow
    async def select_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        query = update.callback_query
        await query.answer()
        user_id = update.effective_user.id
        room = config.ROOM_DEFAULT  # the chat flow picks cards in the default room
        state = db.get_game_state(room)
        if state["phase"] != "preparation":
            await query.edit_message_text("❌ Selection closed — round already started.",
                                          reply_markup=self.get_main_menu())
            return
        selections = db.get_user_selections(user_id, room)
        taken = {s["card_id"] for s in db.get_all_selections(room)
                 if s["user_id"] != user_id}
        available = [c for c in db.get_all_cards() if c["id"] not in taken]
        keyboard = []
        for card in available[:20]:
            keyboard.append([InlineKeyboardButton(f"🎯 Card #{card['id']}",
                                                  callback_data=f"select_{card['id']}")])
        keyboard.append([InlineKeyboardButton("🏠 Menu", callback_data="menu")])
        await query.edit_message_text(
            f"🎯 **Select a card** — {config.room_label(room)}, {room} ETB each "
            f"({len(selections)}/{config.MAX_CARDS_PER_PLAYER}):",
            reply_markup=InlineKeyboardMarkup(keyboard), parse_mode="Markdown")

    async def deselect_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        query = update.callback_query
        await query.answer()
        user_id = update.effective_user.id
        selections = db.get_user_selections(user_id, config.ROOM_DEFAULT)
        if not selections:
            await query.edit_message_text("No cards selected.", reply_markup=self.get_main_menu(user_id))
            return
        keyboard = [[InlineKeyboardButton(f"❌ Card #{s['card_id']}",
                                          callback_data=f"deselect_{s['card_id']}")]
                    for s in selections]
        keyboard.append([InlineKeyboardButton("🏠 Menu", callback_data="menu")])
        await query.edit_message_text("Remove a card (full refund):",
                                      reply_markup=InlineKeyboardMarkup(keyboard))

    # --------------------------------------------------------------- callbacks
    async def callback_handler(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        query = update.callback_query
        await query.answer()
        user_id = update.effective_user.id
        data = query.data

        if data == "menu":
            player = db.get_player(user_id) or {}
            credit = db.get_credit(user_id)
            name = (player.get("full_name") or "").strip() or "Player"
            is_admin = db.is_admin(user_id)
            is_super = user_id in config.SUPER_ADMIN_IDS
            badge = " ⭐" if is_super else (" 👑" if is_admin else "")
            room_names = " / ".join(config.room_label(r) for r in config.ROOM_BETS)
            room_bets = " / ".join(f"{r} ETB" for r in config.ROOM_BETS)
            text = (
                f"🎰  *NICE BINGO*\n"
                f"━━━━━━━━━━━━━━━━━━\n"
                f"Hi, *{_md(name)}*{badge}\n"
                f"💰  Balance: *{credit} {config.APP_CURRENCY}*\n"
                f"━━━━━━━━━━━━━━━━━━\n\n"
                f"❓  *How to Play*\n"
                f"━━━━━━━━━━━━━━━━━━\n\n"
                f"*1.* Tap *🎮 Play Bingo* to open the full-screen arena\n"
                f"*2.* Pick a room (*{room_names}*) — fixed bet per card "
                f"({room_bets})\n"
                f"*3.* During the *{config.PREPARATION_SECONDS}s countdown*, pick up to "
                f"*{config.MAX_CARDS_PER_PLAYER}* cards\n"
                f"*4.* A ball is called every *{config.CALL_INTERVAL_SECONDS}s* — "
                f"numbers are marked automatically\n"
                f"*5.* Complete a row, column, diagonal or four corners → *BINGO!*\n"
                f"*6.* Winner takes *80%* of the prize pool — paid instantly\n\n"
                f"━━━━━━━━━━━━━━━━━━\n"
                f"*💰 Wallet* — Deposit & Withdraw right in this chat\n"
                f"*🔗 Referral* — Earn 5% commission on every round your friends play\n\n"
                f"*Commands:*\n"
                f"`/start`  `/menu`  `/play`  `/status`  `/balance`\n"
                f"`/deposit`  `/withdraw`  `/referral`  `/help`",
            )
            try:
                await query.edit_message_text(
                    text,
                    reply_markup=self.get_main_menu(user_id),
                    parse_mode="Markdown")
            except Exception:
                await query.message.reply_text(
                    text,
                    reply_markup=self.get_main_menu(user_id),
                    parse_mode="Markdown")
        elif data == "play":
            await self.play_command(update, context)
        elif data in ("status", "refresh"):
            await self.status_command(update, context)
        elif data == "balance":
            await self.balance_command(update, context)
        elif data in ("my_cards", "show_cards"):
            await self.my_cards_command(update, context)
        elif data == "leaderboard":
            await self.top_command(update, context)
        elif data == "quick_play":
            result = await self._post("/api/quick-play",
                                      {"user_id": user_id, "room": config.ROOM_DEFAULT})
            if "chosen" in result:
                await query.edit_message_text(
                    f"✅ Auto-selected {len(result['chosen'])} card(s)! "
                    f"Balance: {result['user']['credit']} ETB",
                    reply_markup=self.get_main_menu(user_id))
            else:
                await query.edit_message_text(f"❌ {result.get('error', 'Failed')}",
                                              reply_markup=self.get_main_menu(user_id))
        elif data == "help":
            await self.help_command(update, context)
        elif data == "tunnel_help":
            await query.edit_message_text(HTTPS_HINT, reply_markup=self.get_main_menu(user_id),
                                          parse_mode="Markdown")
        elif data == "select":
            await self.select_command(update, context)
        elif data == "deselect":
            await self.deselect_command(update, context)
        elif data.startswith("select_"):
            card_id = data.split("_", 1)[1]
            result = await self._post("/api/select-card",
                                      {"user_id": user_id, "card_id": card_id,
                                       "room": config.ROOM_DEFAULT})
            if result.get("ok"):
                await query.edit_message_text(
                    f"✅ Card #{card_id} selected · {result['user']['credit']} ETB left",
                    reply_markup=self.get_game_menu())
            else:
                await query.edit_message_text(f"❌ {result.get('error', 'Failed')}",
                                              reply_markup=self.get_main_menu(user_id))
        elif data.startswith("deselect_"):
            card_id = data.split("_", 1)[1]
            result = await self._post("/api/deselect-card",
                                      {"user_id": user_id, "card_id": card_id})
            if result.get("ok"):
                await query.edit_message_text(
                    f"✅ Card #{card_id} removed — {result['user']['credit']} ETB refunded",
                    reply_markup=self.get_main_menu(user_id))
            else:
                await query.edit_message_text(f"❌ {result.get('error', 'Failed')}",
                                              reply_markup=self.get_main_menu(user_id))
        elif data == "referral":
            await self._show_referral(update, context, user_id)
        elif data == "referral_copy":
            try:
                bot_username = (await context.bot.get_me()).username
            except Exception:
                bot_username = "YourBingoBot"
            ref_link = f"https://t.me/{bot_username}?start=REF_{user_id}"
            share_text = urllib.parse.quote(
                f"🎰 Join Nice Bingo and play with me! Use my referral link:\n{ref_link}")
            await query.answer(
                text=f"📋 Your link:\n\n{ref_link}\n\nTap Share Link below to send it!",
                show_alert=True)
            await query.edit_message_reply_markup(
                reply_markup=InlineKeyboardMarkup([
                    [InlineKeyboardButton("📤 Share Link",
                                          url=f"https://t.me/share/url?url={share_text}")],
                    [InlineKeyboardButton("🔙 Back", callback_data="referral")],
                    [InlineKeyboardButton("🏠 Menu", callback_data="menu")],
                ]))
        elif data == "referral_stats":
            await self._show_referral(update, context, user_id)
        elif data in ("wallet_deposit", "wallet_withdraw"):
            await self._wallet_start(update, context,
                                     "deposit" if data == "wallet_deposit" else "withdraw")
        elif data.startswith("wbank_"):
            await self._wallet_bank_pick(update, context)
        elif data == "wallet_cancel":
            context.user_data.pop("wallet_flow", None)
            await query.edit_message_text("❌ Request cancelled.",
                                          reply_markup=self.get_main_menu(user_id))
        elif data.startswith("admin_"):
            await self.admin_callback_handler(update, context)
        elif data == "requests":
            await self.requests_command(update, context)
        elif data == "appeal_list":
            await self.appeal_list(update, context)
        elif data.startswith("appeal_"):
            if data == "appeal_cancel":
                context.user_data.pop("appeal_flow", None)
                await query.edit_message_text("❌ Appeal cancelled.",
                                              reply_markup=self.get_main_menu(user_id))
            else:
                try:
                    tx_id = int(data.split("_", 1)[1])
                    await self._start_appeal(update, context, tx_id)
                except (ValueError, IndexError):
                    await query.edit_message_text("Unknown action.")
        else:
            await query.edit_message_text("Unknown action.")

    # ------------------------------------------------- wallet (bot chat)
    async def _wallet_start(self, update: Update, context: ContextTypes.DEFAULT_TYPE,
                            kind: str):
        """Start a deposit/withdraw conversation IN THE CHAT — available before
        the Mini App is ever opened.  Requires only a stored full name (the
        phone number is NOT needed for bot-chat wallet flows)."""
        query = update.callback_query
        await query.answer()
        user_id = update.effective_user.id
        player = db.get_player(user_id)
        if not player or not (player.get("full_name") or "").strip():
            await query.edit_message_text(
                "⛔ Please send **/start** and enter your full name first.",
                reply_markup=self.get_main_menu(user_id),
                parse_mode="Markdown")
            return
        # Bank selection comes FIRST — the user picks the bank, then the amount.
        settings = await self._get("/api/wallet/settings", {})
        providers = settings.get("providers") or []
        accounts = {d["provider"]: d["account"]
                    for d in settings.get("deposit_accounts") or []}
        if not providers:
            await query.edit_message_text(
                "⏳ No bank accounts are available right now — please try "
                "again later.", reply_markup=self.get_main_menu(user_id))
            return
        banks = {str(a["id"]): p for p, a in accounts.items()}
        accts = {str(a["id"]): a for p, a in accounts.items()}
        context.user_data["wallet_flow"] = {
            "kind": kind, "step": "bank",
            "banks": banks, "accounts": accts,
        }
        cancel_kb = InlineKeyboardMarkup(
            [[InlineKeyboardButton("❌ Cancel", callback_data="wallet_cancel")]])
        label = "DEPOSIT ⬇️" if kind == "deposit" else "WITHDRAW ⬆️"
        keyboard = [[InlineKeyboardButton(p, callback_data=f"wbank_{accounts[p]['id']}")]
                    for p in providers]
        keyboard.append([InlineKeyboardButton("❌ Cancel", callback_data="wallet_cancel")])
        await query.edit_message_text(
            f"💰 **New {label}**\n\n🏦 Choose the bank:" if kind == "deposit"
            else f"💰 **New {label}**\n\n🏦 Which bank should receive your money?",
            reply_markup=InlineKeyboardMarkup(keyboard), parse_mode="Markdown")

    async def _wallet_start_reply(self, update: Update, context: ContextTypes.DEFAULT_TYPE,
                                   kind: str):
        """Start wallet flow from the reply keyboard — sends new messages
        instead of editing (reply keyboard messages can't be edited)."""
        user_id = update.effective_user.id
        player = db.get_player(user_id)
        if not player or not (player.get("full_name") or "").strip():
            await update.message.reply_text(
                "⛔ Please send /start and enter your full name first.",
                reply_markup=self.get_main_menu(user_id))
            return
        settings = await self._get("/api/wallet/settings", {})
        providers = settings.get("providers") or []
        accounts = {d["provider"]: d["account"]
                    for d in settings.get("deposit_accounts") or []}
        if not providers:
            await update.message.reply_text(
                "⏳ No bank accounts are available right now — please try "
                "again later.", reply_markup=self.get_main_menu(user_id))
            return
        banks = {str(a["id"]): p for p, a in accounts.items()}
        accts = {str(a["id"]): a for p, a in accounts.items()}
        context.user_data["wallet_flow"] = {
            "kind": kind, "step": "bank",
            "banks": banks, "accounts": accts,
        }
        label = "DEPOSIT ⬇️" if kind == "deposit" else "WITHDRAW ⬆️"
        keyboard = [[InlineKeyboardButton(p, callback_data=f"wbank_{accounts[p]['id']}")]
                    for p in providers]
        keyboard.append([InlineKeyboardButton("❌ Cancel", callback_data="wallet_cancel")])
        await update.message.reply_text(
            f"💰 **New {label}**\n\n🏦 Choose the bank:" if kind == "deposit"
            else f"💰 **New {label}**\n\n🏦 Which bank should receive your money?",
            reply_markup=InlineKeyboardMarkup(keyboard), parse_mode="Markdown")

    async def _wallet_flow_text(self, update: Update,
                                context: ContextTypes.DEFAULT_TYPE, raw: str):
        """One text step of the deposit/withdraw chat flow."""
        user_id = update.effective_user.id
        flow = context.user_data.get("wallet_flow") or {}
        kind, step = flow.get("kind"), flow.get("step")
        cancel_kb = InlineKeyboardMarkup(
            [[InlineKeyboardButton("❌ Cancel", callback_data="wallet_cancel")]])
        if step == "amount":
            try:
                amount = int(raw.replace(",", "").strip())
            except ValueError:
                await update.message.reply_text(
                    "Please enter a plain number, e.g. 200", reply_markup=cancel_kb)
                return
            if amount <= 0:
                await update.message.reply_text("Amount must be positive.",
                                                reply_markup=cancel_kb)
                return
            if kind == "withdraw":
                if amount < config.MIN_WITHDRAWAL:
                    await update.message.reply_text(
                        f"Minimum withdrawal is {config.MIN_WITHDRAWAL} "
                        f"{config.APP_CURRENCY}.", reply_markup=cancel_kb)
                    return
                if db.get_credit(user_id) < amount:
                    await update.message.reply_text(
                        "Insufficient balance for this withdrawal.",
                        reply_markup=cancel_kb)
                    return
            flow["amount"] = amount
            # bank is already selected — move to the next step
            if kind == "deposit":
                flow["step"] = "tx"
                provider = flow.get("provider", "")
                acc = flow.get("_selected_acc") or {}
                await update.message.reply_text(
                    f"🏦 **{provider}**\n"
                    f"Holder: {_md(acc.get('account_name', '?'))}\n"
                    f"Number: `{acc.get('account_number', '?')}`\n\n"
                    "Send the money to this account with your wallet app, then type "
                    "the **transaction number** shown there:",
                    reply_markup=cancel_kb, parse_mode="Markdown")
            else:
                flow["step"] = "holder"
                await update.message.reply_text(
                    "👤 Enter the account **holder's name** (whose account "
                    "should receive the money):",
                    reply_markup=cancel_kb, parse_mode="Markdown")
        elif step == "tx":
            flow["tx_id"] = raw[:100]
            await self._wallet_submit(update, context, flow)
        elif step == "holder":
            if len(raw) > 60:
                await update.message.reply_text("Name is too long (max 60).",
                                                reply_markup=cancel_kb)
                return
            flow["account_holder"] = raw[:60]
            flow["step"] = "acct"
            await update.message.reply_text(
                "🔢 Enter YOUR account number where the money should be sent:",
                reply_markup=cancel_kb)
        elif step == "acct":
            if len(raw) > 60:
                await update.message.reply_text("Account number is too long (max 60).",
                                                reply_markup=cancel_kb)
                return
            flow["account_number"] = raw[:60]
            await self._wallet_submit(update, context, flow)
        else:
            context.user_data.pop("wallet_flow", None)
            await update.message.reply_text("Session expired — start again.",
                                            reply_markup=self.get_main_menu(user_id))
        if step in ("amount", "bank", "tx", "holder", "acct") \
                and not flow.get("_done"):
            context.user_data["wallet_flow"] = flow

    async def _wallet_bank_pick(self, update: Update,
                                context: ContextTypes.DEFAULT_TYPE):
        query = update.callback_query
        await query.answer()
        user_id = update.effective_user.id
        flow = context.user_data.get("wallet_flow") or {}
        acc_id = query.data.split("_", 1)[1]
        provider = (flow.get("banks") or {}).get(acc_id)
        if not flow or not provider:
            context.user_data.pop("wallet_flow", None)
            await query.edit_message_text("Session expired — start again.",
                                          reply_markup=self.get_main_menu(user_id))
            return
        acc = (flow.get("accounts") or {}).get(acc_id) or {}
        flow["account_id"] = int(acc_id)
        flow["provider"] = provider
        cancel_kb = InlineKeyboardMarkup(
            [[InlineKeyboardButton("❌ Cancel", callback_data="wallet_cancel")]])
        # Bank selected — now ask for the amount (bank-first flow)
        flow["_selected_acc"] = acc  # store for display later
        if flow.get("kind") == "deposit":
            flow["step"] = "amount"
            await query.edit_message_text(
                f"🏦 **{provider}**\n"
                f"Holder: {_md(acc.get('account_name', '?'))}\n"
                f"Number: `{acc.get('account_number', '?')}`\n\n"
                f"Now enter the amount in {config.APP_CURRENCY} you sent:",
                reply_markup=cancel_kb, parse_mode="Markdown")
        else:
            flow["step"] = "amount"
            await query.edit_message_text(
                f"🏦 **{provider}** selected.\n\n"
                f"Enter the amount in {config.APP_CURRENCY} you want to withdraw "
                f"(minimum {config.MIN_WITHDRAWAL}):",
                reply_markup=cancel_kb, parse_mode="Markdown")
        context.user_data["wallet_flow"] = flow

    async def _wallet_submit(self, update: Update,
                             context: ContextTypes.DEFAULT_TYPE, flow: dict):
        """POST the collected deposit/withdraw to the server API."""
        user_id = update.effective_user.id
        kind = flow.get("kind")
        payload = {
            "user_id": user_id,
            "type": kind,
            "amount": flow.get("amount"),
        }
        if kind == "deposit":
            payload["tx_id"] = flow.get("tx_id")
            payload["payment_account_id"] = flow.get("account_id")
        else:
            payload["account_name"] = flow.get("provider")
            payload["account_holder"] = flow.get("account_holder")
            payload["account_number"] = flow.get("account_number")
        result = await self._post("/api/transactions", payload)
        flow["_done"] = True  # prevents _wallet_flow_text from re-saving it
        context.user_data.pop("wallet_flow", None)
        if result.get("ok"):
            label = "Deposit" if kind == "deposit" else "Withdrawal"
            await update.message.reply_text(
                f"✅ **{label} request submitted!**\n\n"
                f"Amount: {flow.get('amount')} {config.APP_CURRENCY}\n"
                "The admin has been notified on Telegram and will review it "
                "shortly. Track it under 💰 Balance → recent requests.",
                reply_markup=self.get_main_menu(user_id), parse_mode="Markdown")
        else:
            await update.message.reply_text(
                f"❌ {result.get('error', 'Failed to submit — please try again.')}",
                reply_markup=self.get_main_menu(user_id))

    # ------------------------------------------------- requests / appeals
    async def requests_command(self, update: Update,
                               context: ContextTypes.DEFAULT_TYPE):
        """/requests — show recent wallet transactions with appeal buttons
        for pending deposits."""
        query = update.callback_query
        if query:
            await query.answer()
        user_id = update.effective_user.id
        txs = db.get_user_transactions(user_id, limit=10)
        if not txs:
            text = "📋 **Your Requests**\n\nNo transactions yet."
            kb = self.get_main_menu(user_id)
        else:
            lines = ["📋 **Your Requests**\n"]
            buttons = []
            for tx in txs:
                icon = "⬇️" if tx["type"] == "deposit" else "⬆️"
                status = tx["status"].upper()
                status_icon = {"PENDING": "🟡", "APPROVED": "🟢",
                               "REJECTED": "🔴"}.get(status, "⚪")
                lines.append(
                    f"{icon} **{tx['type'].title()}** — {tx['amount']} {config.APP_CURRENCY} "
                    f"{status_icon} {status}\n"
                    f"   ID: #{tx['id']} · {tx.get('created_at', '')[:16]}")
                if tx.get('admin_note'):
                    lines.append(f"   📝 {tx['admin_note']}")
                # add appeal button for pending/rejected deposits
                if (tx["type"] == "deposit"
                        and tx["status"] in ("pending", "rejected")):
                    # check if user already has a pending appeal for this tx
                    existing = [a for a in db.get_user_appeals(user_id)
                                if a["transaction_id"] == tx["id"]
                                and a["status"] == "pending"]
                    if not existing:
                        buttons.append([
                            InlineKeyboardButton(
                                f"🚨 Appeal #{tx['id']} ({tx['amount']} ETB)",
                                callback_data=f"appeal_{tx['id']}")
                        ])
            text = "\n\n".join(lines)
            kb_rows = buttons if buttons else []
            kb_rows.append([InlineKeyboardButton("🏠 Menu", callback_data="menu")])
            kb = InlineKeyboardMarkup(kb_rows)
        if query:
            try:
                await query.edit_message_text(text, reply_markup=kb,
                                              parse_mode="Markdown")
            except Exception:
                await query.message.reply_text(text, reply_markup=kb,
                                              parse_mode="Markdown")
        else:
            await update.message.reply_text(text, reply_markup=kb,
                                            parse_mode="Markdown")

    # --------------------------------------------------- dedicated appeal
    async def appeal_list(self, update: Update,
                          context: ContextTypes.DEFAULT_TYPE):
        """Show a clean appeal screen: only pending/rejected deposits that
        can be appealed, with a simple one-tap flow."""
        query = update.callback_query
        if query:
            await query.answer()
        user_id = update.effective_user.id
        txs = db.get_user_transactions(user_id, limit=20)
        appealable = []
        for tx in txs:
            if tx["type"] != "deposit":
                continue
            if tx["status"] not in ("pending", "rejected"):
                continue
            # skip if user already has a pending appeal for this tx
            existing = [a for a in db.get_user_appeals(user_id)
                        if a["transaction_id"] == tx["id"]
                        and a["status"] == "pending"]
            if existing:
                continue
            appealable.append(tx)
        if not appealable:
            text = (
                f"🚨  *Appeal Center*\n"
                f"━━━━━━━━━━━━━━━━━━\n\n"
                f"You have no deposits that need an appeal.\n\n"
                f"Appeals are available for *pending* or *rejected* deposits."
            )
            kb = InlineKeyboardMarkup(
                [[InlineKeyboardButton("🏠  Menu", callback_data="menu")]])
        else:
            lines = [
                f"🚨  *Appeal Center*",
                f"━━━━━━━━━━━━━━━━━━",
                f"",
                f"Select a deposit to appeal. The super admin will review it.",
                f"",
            ]
            buttons = []
            for tx in appealable[:5]:
                status_icon = "🟡" if tx["status"] == "pending" else "🔴"
                lines.append(
                    f"{status_icon} *Deposit #{tx['id']}* — {tx['amount']} {config.APP_CURRENCY}\n"
                    f"   Status: {tx['status'].upper()} · {tx.get('created_at', '')[:16]}")
                buttons.append([
                    InlineKeyboardButton(
                        f"🚨  Appeal #{tx['id']} — {tx['amount']} ETB",
                        callback_data=f"appeal_{tx['id']}")
                ])
            text = "\n".join(lines)
            buttons.append([InlineKeyboardButton("🏠  Menu", callback_data="menu")])
            kb = InlineKeyboardMarkup(buttons)
        if query:
            try:
                await query.edit_message_text(text, reply_markup=kb,
                                              parse_mode="Markdown")
            except Exception:
                await query.message.reply_text(text, reply_markup=kb,
                                              parse_mode="Markdown")
        else:
            await update.message.reply_text(text, reply_markup=kb,
                                            parse_mode="Markdown")

    async def _start_appeal(self, update: Update,
                            context: ContextTypes.DEFAULT_TYPE, tx_id: int):
        """Begin an appeal flow for a specific deposit transaction."""
        query = update.callback_query
        await query.answer()
        user_id = update.effective_user.id
        tx = db.get_transaction(tx_id)
        if not tx or tx["user_id"] != user_id:
            await query.edit_message_text("❌ Transaction not found.",
                                          reply_markup=self.get_main_menu(user_id))
            return
        if tx["type"] != "deposit":
            await query.edit_message_text("❌ Only deposits can be appealed.",
                                          reply_markup=self.get_main_menu(user_id))
            return
        if tx["status"] not in ("pending", "rejected"):
            await query.edit_message_text("❌ This transaction is already finished.",
                                          reply_markup=self.get_main_menu(user_id))
            return
        existing = [a for a in db.get_user_appeals(user_id)
                    if a["transaction_id"] == tx_id and a["status"] == "pending"]
        if existing:
            await query.edit_message_text(
                "❌ You already have a pending appeal for this deposit.",
                reply_markup=self.get_main_menu(user_id))
            return
        context.user_data["appeal_flow"] = {"tx_id": tx_id}
        cancel_kb = InlineKeyboardMarkup(
            [[InlineKeyboardButton("❌  Cancel", callback_data="appeal_cancel")],
             [InlineKeyboardButton("🏠  Menu", callback_data="menu")]])
        text = (
            f"🚨  *Appeal — Deposit #{tx_id}*\n"
            f"━━━━━━━━━━━━━━━━━━\n\n"
            f"💰  Amount: *{tx['amount']} {config.APP_CURRENCY}*\n"
            f"📋  Status: *{tx['status'].upper()}*\n\n"
            f"Please describe your issue:\n"
            f"• When did you pay?\n"
            f"• What happened?\n"
            f"• Any reference number?\n\n"
            f"Type your reason below:"
        )
        await query.edit_message_text(
            text,
            reply_markup=cancel_kb, parse_mode="Markdown")

    async def _appeal_flow_text(self, update: Update,
                                context: ContextTypes.DEFAULT_TYPE, reason: str):
        """Process the appeal reason text and submit it."""
        user_id = update.effective_user.id
        flow = context.user_data.get("appeal_flow") or {}
        tx_id = flow.get("tx_id")
        if not tx_id:
            context.user_data.pop("appeal_flow", None)
            await update.message.reply_text(
                "Session expired — start again.",
                reply_markup=self.get_main_menu(user_id))
        reason = reason[:500]
        result = await self._post("/api/appeals", {
            "user_id": user_id,
            "transaction_id": tx_id,
            "reason": reason,
        })
        context.user_data.pop("appeal_flow", None)
        if result.get("ok"):
            text = (
                f"✅  *Appeal Submitted!*\n"
                f"━━━━━━━━━━━━━━━━━━\n\n"
                f"📋  Deposit #{tx_id} — your issue has been sent to the "
                f"super admin for review.\n\n"
                f"You'll be notified when it's resolved."
            )
            await update.message.reply_text(
                text,
                reply_markup=self.get_main_menu(user_id),
                parse_mode="Markdown")
        else:
            await update.message.reply_text(
                f"❌ {result.get('error', 'Failed to submit appeal.')}",
                reply_markup=self.get_main_menu(user_id))

    # ---------------------------------------------------------------- referral
    async def _show_referral(self, update: Update, context: ContextTypes.DEFAULT_TYPE,
                             user_id: int):
        """Show the admin's referral link and stats."""
        query = update.callback_query
        if query:
            await query.answer()
        # build the referral link using the bot's username
        try:
            bot_username = (await context.bot.get_me()).username
        except Exception:
            bot_username = "YourBingoBot"
        ref_link = f"https://t.me/{bot_username}?start=REF_{user_id}"
        # fetch stats from DB
        stats = db.get_referral_stats(user_id)
        total_refs = stats["total_referrals"]
        total_comm = stats["total_commission"]
        active_refs = stats["active_referrals"]
        users = stats["referred_users"]
        text = (
            f"🔗 **Your Referral Program**\n\n"
            f"💰 Earn **5%% commission** on every round your referrals play!\n\n"
            f"📨 **Your referral link:**\n"
            f"`{ref_link}`\n\n"
            f"Tap **Share Link** below to send to friends!\n\n"
            f"📊 **Stats:**\n"
            f"👥 Total referrals: **{total_refs}**\n"
            f"🎮 Active players: **{active_refs}**\n"
            f"💰 Total earned: **{total_comm} {config.APP_CURRENCY}**"
        )
        if users:
            text += "\n\n👥 **Your Referrals:**\n"
            for u in users[:10]:
                name = u.get("full_name") or u.get("username") or f"#{u['referred_id']}"
                credit = u.get("credit", 0)
                text += f"  • {_md(name)} — {credit} {config.APP_CURRENCY}\n"
        # recent commissions
        commissions = db.get_referral_commissions(user_id, limit=5)
        if commissions:
            text += "\n\n💎 **Recent Commissions:**\n"
            for c in commissions:
                cname = c.get("referred_name") or c.get("referred_username") or f"#{c['referred_id']}"
                text += f"  • +{c['commission']} {config.APP_CURRENCY} from {_md(cname)} (bet {c['total_bet']} ETB)\n"
        share_text = urllib.parse.quote(
            f"🎰 Join Nice Bingo and play with me! Use my referral link:\n{ref_link}")
        keyboard = InlineKeyboardMarkup([
            [InlineKeyboardButton("📤 Share Link",
                                  url=f"https://t.me/share/url?url={share_text}")],
            [InlineKeyboardButton("📊 Full Stats", callback_data="referral_stats")],
            [InlineKeyboardButton("🏠 Menu", callback_data="menu")],
        ])
        if query:
            try:
                await query.edit_message_text(text, reply_markup=keyboard, parse_mode="Markdown")
            except Exception:
                await query.message.reply_text(text, reply_markup=keyboard, parse_mode="Markdown")
        else:
            await update.message.reply_text(text, reply_markup=keyboard, parse_mode="Markdown")

    # ------------------------------------------------------------------ admin
    async def admin_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        user_id = update.effective_user.id
        if not db.is_admin(user_id):
            await update.message.reply_text("⛔ Unauthorized!")
            return
        db.touch_admin(user_id)
        stats = await self._get("/api/admin/stats", {"admin_id": user_id})
        s = stats.get("stats", {})
        bots = await self._get("/api/admin/bots", {"admin_id": user_id})
        admin_credit = db.get_admin_credit(user_id)
        text = (
            f"🔧  *Admin Panel*\n"
            f"━━━━━━━━━━━━━━━━━━\n\n"
            f"💳  Admin credit: *{admin_credit} ETB*\n\n"
            f"📊  *Statistics*\n"
            f"  Rounds: *{s.get('rounds', '?')}*\n"
            f"  Total bets: *{s.get('total_bets', 0)} ETB*\n"
            f"  Paid out: *{s.get('prize_paid', 0)} ETB*\n"
            f"  House kept: *{s.get('house_kept', 0)} ETB*\n\n"
            f"🤖  Bots: *{'ON' if bots.get('enabled') else 'OFF'}* "
            f"({bots.get('count', 0)} accounts)\n"
            f"━━━━━━━━━━━━━━━━━━\n"
            f"👇 *Choose an action:*"
        )
        await update.message.reply_text(text, reply_markup=self.get_admin_menu(),
                                        parse_mode="Markdown")

    async def give_take_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE,
                                sign: int):
        user_id = update.effective_user.id
        if not db.is_admin(user_id):
            await update.message.reply_text("⛔ Unauthorized!")
            return
        db.touch_admin(user_id)
        args = context.args
        if len(args) < 2:
            await update.message.reply_text("Usage: /give <user_id> <amount>  ·  /take <user_id> <amount>")
            return
        try:
            target, amount = int(args[0]), int(args[1]) * sign
        except ValueError:
            await update.message.reply_text("Usage: /give <user_id> <amount>")
            return
        result = await self._post("/api/admin/credit",
                                  {"admin_id": user_id, "user_id": target, "amount": amount})
        if result.get("ok"):
            await update.message.reply_text(
                f"✅ User {target} now has **{result['credit']} ETB**")
        else:
            await update.message.reply_text(result.get("error", "Failed"))

    async def admin_callback_handler(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        query = update.callback_query
        user_id = update.effective_user.id
        if not db.is_admin(user_id):
            await query.edit_message_text("⛔ Unauthorized!")
            return
        data = query.data
        actions = {
            "admin_start": ("/api/admin/force-start", {}),
            "admin_call": ("/api/admin/force-call", {}),
            "admin_bots": ("/api/admin/bots/add", {}),
            "admin_reset": ("/api/admin/reset", {}),
            "admin_bots_toggle": ("/api/admin/bots/toggle", {}),
        }
        labels = {
            "admin_start": "✅ Round force-started!",
            "admin_call": "✅ Ball called!",
            "admin_bots": "✅ Bots filled the room!",
            "admin_reset": "✅ Round reset — new preparation phase.",
            "admin_bots_toggle": "✅ Bots toggled.",
        }
        if data in actions:
            path, _ = actions[data]
            result = await self._post(path, {"admin_id": user_id})
            msg = labels[data] if result.get("ok") else f"❌ {result.get('error', 'Failed')}"
            await query.edit_message_text(msg, reply_markup=self.get_admin_menu())
        elif data == "admin_status":
            stats = await self._get("/api/admin/stats", {"admin_id": user_id})
            s = stats.get("stats", {})
            await query.edit_message_text(
                f"📊 **Admin Stats**\n\nRounds: {s.get('rounds', '?')}\n"
                f"Total bets: {s.get('total_bets', 0)} ETB\nPaid out: {s.get('prize_paid', 0)} ETB\n"
                f"House kept: {s.get('house_kept', 0)} ETB\nReal winners: {s.get('real_winners', 0)}",
                reply_markup=self.get_admin_menu(), parse_mode="Markdown")

    # -------------------------------------------------------------- announcer
    async def _drain_notifications(self):
        """Send every queued bot_notification over Telegram (best effort).

        server.py enqueues deposit/withdraw/appeal alerts into the shared DB;
        the bot's announcer tick drains the queue and sends it so admins are
        notified by bot message as soon as something needs their attention —
        even when the bot runs in a different process (polling mode).
        """
        try:
            for n in db.get_unsent_bot_notifications(50):
                sent = False
                try:
                    if self.application is not None and self.application.bot:
                        await self.application.bot.send_message(
                            chat_id=n["chat_id"], text=n["text"])
                        sent = True
                except Forbidden:
                    # recipient blocked/deleted the bot — drop the message
                    logger.info("notification to %s dropped (Forbidden)", n["chat_id"])
                    sent = True  # no point retrying
                except Exception as exc:
                    logger.warning("notification to %s failed: %s", n["chat_id"], exc)
                    # do NOT mark as sent — the announcer will retry on the next tick
                if sent:
                    db.mark_bot_notification_sent(n["id"])
        except Exception as exc:
            logger.warning("notification drain error: %s", exc)

    async def _announcer_tick(self, context):
        """One polling pass — scheduled on the app's job queue.

        Watches every room independently (each has its own phase, balls and
        pool) and names the room in every announcement.
        """
        try:
            await self._drain_notifications()
            players = db.get_all_player_ids()
            if not players:
                return
            for room in config.ROOM_BETS:
                state = db.get_game_state(room)
                called = db.get_called_numbers(room)
                phase, count, round_no = (state["phase"], len(called),
                                          state.get("round_number"))
                last = self._last.setdefault(room, {"phase": None, "count": -1, "round": None})
                label = config.room_label(room)

                if phase == "preparation" and last["phase"] != "preparation" and config.ANNOUNCE_ROUNDS:
                    await self.broadcast(
                        players,
                        f"🔄 **{label}** is preparing — {config.PREPARATION_SECONDS}s to pick your cards!\n"
                        f"Tap **/play** to open the Mini App 🎰")
                elif phase == "playing" and last["phase"] != "playing" and config.ANNOUNCE_ROUNDS:
                    pool = logic.calculate_prize_pool(room)
                    # NOTE: no round number is ever announced to users
                    await self.broadcast(
                        players,
                        f"🎰 **{label}**: A new Bingo round has started!\n\n"
                        f"💰 Prize pool: **{pool['prize_pool']} ETB**\n"
                        f"👥 Players: **{pool['real_players']}**\n\nGood luck! 🍀")
                elif phase == "ended" and last["phase"] != "ended" and config.ANNOUNCE_ROUNDS:
                    if state.get("winner_user_id"):
                        info = json.loads(state["winning_pattern"] or "{}")
                        winner = db.get_player(state["winner_user_id"])
                        name = (winner or {}).get("full_name") or (winner or {}).get("username") or (
                            bot_name(state["winner_user_id"])
                            if state["winner_user_id"] < 0 else "Player")
                        card_id = info.get('card_id', '?')
                        await self.broadcast(
                            players,
                            f"🎉 **BINGO!** 🎉 ({label})\n\n🏆 Winner: **{_md(name)}**\n"
                            f"🃏 Winning Card: **#{card_id}**\n"
                            f"🎯 Pattern: **{info.get('pattern')}**\n"
                            f"💰 Prize: **{info.get('prize', 0)} {config.APP_CURRENCY}**")
                    else:
                        await self.broadcast(
                            players,
                            f"🛑 **{label}**: all 75 balls called — no winner. Next round soon!")

                if phase == "playing" and config.ANNOUNCE_NUMBERS and count > last["count"]:
                    for idx, n in enumerate(called[last["count"]:count],
                                            start=last["count"] + 1):
                        await self.broadcast(
                            players,
                            f"🎯 **{n}**  ·  {idx}/{config.TOTAL_NUMBERS} ({label})")

                last.update(phase=phase, count=count, round=round_no)
        except Exception as exc:
            logger.warning("announcer error: %s", exc)

    async def broadcast(self, player_ids, message: str):
        for uid in player_ids:
            try:
                await self.application.bot.send_message(chat_id=uid, text=message,
                                                        parse_mode="Markdown")
            except Forbidden:
                # user blocked/deleted the bot -> their account is removed
                # automatically (they can register again with new credentials)
                db.delete_player(uid)
                logger.info("User %s blocked the bot — account deleted", uid)
            except Exception:
                pass

    async def my_chat_member_handler(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Auto-delete the account when the user deletes/stops the bot.

        Telegram sends a my_chat_member update with status 'kicked' (user
        blocked the bot) or 'left' (user deleted the chat) — on either, the
        account is wiped so the same person can register again with fresh
        credentials the next time they add the bot.
        """
        try:
            cm = update.my_chat_member
            if not cm:
                return
            status = cm.new_chat_member.status
            # only the user's PRIVATE chat with the bot counts (blocking the
            # bot, deleting the chat). Being removed from a group by an admin
            # must NOT delete anyone's account.
            chat_type = getattr(cm.chat, "type", None)
            if status in (ChatMember.KICKED, ChatMember.LEFT) and cm.from_user \
                    and chat_type == "private":
                uid = cm.from_user.id
                if uid > 0:
                    db.delete_player(uid)
                    logger.info("User %s stopped the bot (%s) — account deleted", uid, status)
        except Exception as exc:
            logger.warning("my_chat_member handler error: %s", exc)

    async def error_handler(self, update, context):
        """Last-resort handler — turns crashes into friendly replies."""
        logger.error("Update %s caused error %s", update, context.error)
        if not (update and update.effective_user):
            return
        err = str(context.error or "")
        text = HTTPS_HINT if "web app url" in err.lower() else \
            "⚠️ Something went wrong — try again in a moment."
        try:
            await context.bot.send_message(chat_id=update.effective_user.id,
                                           text=text, parse_mode="Markdown")
        except Exception:
            pass

    # ------------------------------------------------------------------- main
    def build_application(self):
        """Create the PTB Application with every handler wired (not started)."""
        if not BOT_TOKEN:
            raise SystemExit("BOT_TOKEN is missing — check your .env file.")
        self.application = Application.builder().token(BOT_TOKEN).build()
        self.application.post_init = self._on_start
        self.setup_handlers()
        return self.application

    def setup_handlers(self):
        self.application.add_handler(CommandHandler("start", self.start_command))
        self.application.add_handler(CommandHandler("play", self.play_command))
        self.application.add_handler(CommandHandler("status", self.status_command))
        self.application.add_handler(CommandHandler("balance", self.balance_command))
        self.application.add_handler(CommandHandler("cards", self.my_cards_command))
        self.application.add_handler(CommandHandler("history", self.history_command))
        self.application.add_handler(CommandHandler("top", self.top_command))
        self.application.add_handler(CommandHandler("leaderboard", self.top_command))
        self.application.add_handler(CommandHandler("help", self.help_command))
        self.application.add_handler(CommandHandler("menu", self.menu_command))
        self.application.add_handler(CommandHandler("admin", self.admin_command))
        self.application.add_handler(CommandHandler("give", self._give))
        self.application.add_handler(CommandHandler("take", self._take))
        # wallet + referral are available BEFORE the Mini App opens (chat-only)
        self.application.add_handler(CommandHandler("referral", self.referral_command))
        self.application.add_handler(CommandHandler("deposit", self.deposit_command))
        self.application.add_handler(CommandHandler("withdraw", self.withdraw_command))
        self.application.add_handler(CommandHandler("requests", self.requests_command))
        # collects the full name during first-time onboarding (after /start)
        self.application.add_handler(MessageHandler(
            filters.TEXT & ~filters.COMMAND, self.text_handler))
        self.application.add_handler(CallbackQueryHandler(self.callback_handler))
        self.application.add_handler(ChatMemberHandler(
            self.my_chat_member_handler, ChatMemberHandler.MY_CHAT_MEMBER))
        self.application.add_error_handler(self.error_handler)

    async def _give(self, update, context):
        await self.give_take_command(update, context, +1)

    async def _take(self, update, context):
        await self.give_take_command(update, context, -1)

    async def menu_command(self, update: Update,
                           context: ContextTypes.DEFAULT_TYPE):
        """/menu — show the main menu (works before the Mini App is opened)."""
        uid = update.effective_user.id
        player = db.get_player(uid) or {}
        name = (player.get("full_name") or "").strip() or "Player"
        credit = db.get_credit(uid)
        is_admin = db.is_admin(uid)
        is_super = uid in config.SUPER_ADMIN_IDS
        badge = " ⭐" if is_super else (" 👑" if is_admin else "")
        room_names = " / ".join(config.room_label(r) for r in config.ROOM_BETS)
        room_bets = " / ".join(f"{r} ETB" for r in config.ROOM_BETS)
        text = (
            f"🎰  *NICE BINGO*\n"
            f"━━━━━━━━━━━━━━━━━━\n"
            f"Hi, *{_md(name)}*{badge}\n"
            f"💰  Balance: *{credit} {config.APP_CURRENCY}*\n"
            f"━━━━━━━━━━━━━━━━━━\n\n"
            f"❓  *How to Play*\n"
            f"━━━━━━━━━━━━━━━━━━\n\n"
            f"*1.* Tap *🎮 Play Bingo* to open the full-screen arena\n"
            f"*2.* Pick a room (*{room_names}*) — fixed bet per card "
            f"({room_bets})\n"
            f"*3.* During the *{config.PREPARATION_SECONDS}s countdown*, pick up to "
            f"*{config.MAX_CARDS_PER_PLAYER}* cards\n"
            f"*4.* A ball is called every *{config.CALL_INTERVAL_SECONDS}s* — "
            f"numbers are marked automatically\n"
            f"*5.* Complete a row, column, diagonal or four corners → *BINGO!*\n"
            f"*6.* Winner takes *80%* of the prize pool — paid instantly\n\n"
            f"━━━━━━━━━━━━━━━━━━\n"
            f"*💰 Wallet* — Deposit & Withdraw right in this chat\n"
            f"*🔗 Referral* — Earn 5% commission on every round your friends play\n\n"
            f"*Commands:*\n"
            f"`/start`  `/menu`  `/play`  `/status`  `/balance`\n"
            f"`/deposit`  `/withdraw`  `/referral`  `/help`",
        )
        await update.message.reply_text(
            text,
            reply_markup=self.get_main_menu(uid),
            parse_mode="Markdown")
        await update.message.reply_text(
            "👇 *Quick actions* — tap any button below:",
            reply_markup=self.get_reply_keyboard(uid),
            parse_mode="Markdown",
        )

    async def referral_command(self, update: Update,
                               context: ContextTypes.DEFAULT_TYPE):
        """/referral — show the caller's referral link & stats (everyone)."""
        await self._show_referral(update, context, update.effective_user.id)

    async def deposit_command(self, update: Update,
                              context: ContextTypes.DEFAULT_TYPE):
        """/deposit — start a deposit request right in the chat."""
        class _FakeQuery:
            """Minimal shim so _wallet_start can answer both commands and taps."""
            message = update.message

            async def answer(self):
                pass

            async def edit_message_text(self, text, reply_markup=None,
                                        parse_mode=None):
                await update.message.reply_text(text, reply_markup=reply_markup,
                                                parse_mode=parse_mode)

        update.callback_query = _FakeQuery()
        await self._wallet_start(update, context, "deposit")

    async def withdraw_command(self, update: Update,
                               context: ContextTypes.DEFAULT_TYPE):
        """/withdraw — start a withdrawal request right in the chat."""
        class _FakeQuery:
            message = update.message

            async def answer(self):
                pass

            async def edit_message_text(self, text, reply_markup=None,
                                        parse_mode=None):
                await update.message.reply_text(text, reply_markup=reply_markup,
                                                parse_mode=parse_mode)

        update.callback_query = _FakeQuery()
        await self._wallet_start(update, context, "withdraw")

    async def _on_start(self, application):
        # Register bot commands for Telegram's menu button and autocomplete
        try:
            from telegram import BotCommand
            commands = [
                BotCommand("start", "Start the bot & open main menu"),
                BotCommand("play", "Open the Bingo Arena"),
                BotCommand("menu", "Show the main menu"),
                BotCommand("status", "Check game status"),
                BotCommand("balance", "View your balance"),
                BotCommand("cards", "See your selected cards"),
                BotCommand("deposit", "Deposit funds"),
                BotCommand("withdraw", "Withdraw funds"),
                BotCommand("referral", "Referral program & earnings"),
                BotCommand("leaderboard", "Top players"),
                BotCommand("help", "How to play"),
            ]
            await application.bot.set_my_commands(commands)
        except Exception as exc:
            logger.warning("Failed to set bot commands: %s", exc)
        # baseline sync so the first tick doesn't announce a fake phase change
        try:
            self._last = {}
            for room in config.ROOM_BETS:
                state = db.get_game_state(room)
                self._last[room] = {
                    "phase": state["phase"],
                    "count": len(db.get_called_numbers(room)),
                    "round": state.get("round_number"),
                }
        except Exception:
            pass
        application.job_queue.run_repeating(self._announcer_tick,
                                            interval=config.ANNOUNCER_INTERVAL,
                                            first=3.0)

    def run(self):
        """Polling mode — the default (local PC / Docker / any host)."""
        if not BOT_TOKEN:
            raise SystemExit("BOT_TOKEN is missing — check your .env file.")
        if not self._webapp_ok():
            logger.warning(
                "APP_URL='%s' is not https — Telegram rejects http:// on Web App "
                "buttons, so the bot will show the setup hint instead. Run "
                "setup_tunnel.bat once + run_tunnel.bat, or set APP_URL to an "
                "https:// tunnel URL in .env, then restart.", _fresh_app_url())
        self.application = self.build_application()
        logger.info("🎰 Bingo bot starting — Mini App URL: %s", config.APP_URL)
        self.application.run_polling(allowed_updates=Update.ALL_TYPES)


# ------------------------------------------------------------------- webhook
# Webhook mode (BOT_WEBHOOK=1): the bot runs INSIDE the Flask web process on
# always-on hosts (PythonAnywhere) whose free tier cannot run background
# processes. Telegram pushes updates to APP_URL/webhook/<secret>; server.py
# forwards them to dispatch_webhook() here. The bot still sends messages and
# runs its announcer job queue exactly like in polling mode.
_webhook_loop = None
_webhook_app = None
_webhook_thread = None
_webhook_lock = threading.Lock()
_webhook_registered = False  # True after setWebhook succeeds
# Track the PID that started the bot. uWSGI forks workers AFTER loading
# wsgi.py, so the forked worker inherits stale globals (_webhook_app=None)
# while the master's thread sets them. We detect the fork by PID mismatch
# and force-restart the bot in the worker.
_webhook_pid = os.getpid()


def start_webhook() -> None:
    """Start the bot in webhook mode on a background event loop.

    Initializes the PTB application, registers the webhook URL with Telegram,
    and keeps the loop alive. Call from the WSGI entry point (wsgi.py) only
    when BOT_WEBHOOK=1 — never together with a polling instance (Telegram
    rejects a second connection with 409 Conflict).

    The background thread retries set_webhook up to 3 times with a short
    delay so transient network errors (common on PythonAnywhere free tier)
    don't kill the bot permanently.
    """
    if not BOT_TOKEN:
        raise SystemExit("BOT_TOKEN is missing — check your .env file.")

    instance = PremiumBingoBot()
    instance.application = instance.build_application()
    loop = asyncio.new_event_loop()

    async def _start():
        global _webhook_loop, _webhook_app, _webhook_registered
        logger.info("webhook: _start beginning")
        try:
            logger.info("webhook: calling application.initialize()...")
            await instance.application.initialize()
            logger.info("webhook: application.initialize() done")
        except Exception as exc:
            logger.error("webhook: application.initialize() FAILED: %s", exc)
            return
        try:
            logger.info("webhook: calling application.start()...")
            await instance.application.start()
            logger.info("webhook: application.start() done")
        except Exception as exc:
            logger.error("webhook: application.start() FAILED: %s", exc)
            return
        # Set dispatch globals IMMEDIATELY after app is running
        _webhook_loop = loop
        _webhook_app = instance.application
        logger.info("🎰 Bingo bot app ready — dispatch enabled")
        # retry setWebhook up to 3 times
        webhook_url = f"{_fresh_app_url()}/webhook/{config.WEBHOOK_SECRET}"
        for attempt in range(1, 4):
            try:
                logger.info("webhook: setWebhook attempt %d to %s", attempt, webhook_url)
                await instance.application.bot.set_webhook(
                    url=webhook_url, allowed_updates=Update.ALL_TYPES,
                    drop_pending_updates=False)
                _webhook_registered = True
                logger.info("🎰 Bingo bot webhook registered → %s (attempt %d)",
                            webhook_url, attempt)
                return
            except Exception as exc:
                logger.warning("webhook setWebhook attempt %d failed: %s", attempt, exc)
                if attempt < 3:
                    await asyncio.sleep(2)
        logger.error("🎰 webhook registration FAILED after 3 attempts")

    async def _runner():
        logger.info("webhook: _runner starting")
        try:
            await _start()
        except Exception as exc:
            logger.error("webhook runner _start FAILED: %s", exc, exc_info=True)
            return
        logger.info("🎰 Bingo bot webhook runner alive — loop running")
        while True:
            await asyncio.sleep(3600)

    global _webhook_thread
    _webhook_thread = threading.Thread(
        target=lambda: loop.run_until_complete(_runner()), daemon=True)
    _webhook_thread.start()
    logger.info("🎰 Bingo bot running in WEBHOOK mode")


def _ensure_webhook_running() -> bool:
    """(Re)start the webhook bot if its loop thread isn't alive.

    Hosts that fork workers after import (uWSGI on PythonAnywhere) can leave
    the module globals pointing at a loop whose pumping thread is gone. When
    that happens the next delivery restarts the bot and returns False, so
    Telegram retries a moment later against the fresh, alive loop.

    Also detects uWSGI fork: the master loads wsgi.py and starts the bot
    thread, then forks workers. The worker inherits a COPY of the module
    globals (still None/False) while the master's thread sets them. We
    detect this by comparing PIDs and force-restart in the worker.
    """
    global _webhook_pid
    current_pid = os.getpid()
    forked = (current_pid != _webhook_pid)
    if forked:
        logger.warning("webhook: PID changed %d -> %d (uWSGI fork detected)"
                       " — resetting globals", _webhook_pid, current_pid)
        _webhook_pid = current_pid
        _webhook_loop = None
        _webhook_app = None
        _webhook_thread = None
        _webhook_registered = False
    if not forked and _webhook_thread is not None and _webhook_thread.is_alive():
        return True
    with _webhook_lock:
        if not forked and _webhook_thread is not None and _webhook_thread.is_alive():
            return True
        logger.warning("webhook thread is dead or forked — restarting")
        try:
            start_webhook()
        except Exception as exc:
            logger.error("webhook restart failed: %s", exc)
            return False
        return True


def notify_admins(lines: list) -> None:
    """Queue a plain-text alert to EVERY admin (best effort, non-blocking).

    `lines` is a list of message lines, joined with newlines here. The message
    is written into the `bot_notifications` table and the bot's announcer tick
    picks it up and sends it over Telegram — this works in BOTH polling and
    webhook modes, even when the server and the bot run in separate processes.
    """
    text = chr(10).join(str(line) for line in lines)
    for admin_id in db.get_admin_ids():
        try:
            db.add_bot_notification(admin_id, text)
        except Exception as exc:
            logger.error("admin notify failed: %s", exc)


def notify_user(user_id: int, lines: list) -> None:
    """Queue a Telegram alert for ONE specific chat (e.g. the admin who owns
    the payment account a deposit was paid into, or a user whose appeal was
    resolved). Best effort — never raises."""
    text = chr(10).join(str(line) for line in lines)
    try:
        db.add_bot_notification(user_id, text)
    except Exception as exc:
        logger.error("user notify failed: %s", exc)


def dispatch_webhook(update_dict: dict) -> bool:
    """Hand an incoming Telegram update to the running webhook bot.

    Called by server.py's /webhook/<secret> route. Fire-and-forget: the update
    is scheduled on the bot's event loop and the HTTP request returns at once.
    Returns False only while the bot is still starting up (Telegram will
    retry the delivery).
    """
    if _webhook_app is None or _webhook_loop is None:
        # App not ready yet — try to (re)start the bot
        logger.warning("webhook dispatch: app not ready, attempting restart")
        if not _ensure_webhook_running():
            return False
        # give the thread a moment to initialize
        import time
        for _ in range(20):
            if _webhook_app is not None and _webhook_loop is not None:
                break
            time.sleep(0.5)
        if _webhook_app is None or _webhook_loop is None:
            return False
    try:
        update = Update.de_json(update_dict, _webhook_app.bot)
        if update is None:
            return True
        asyncio.run_coroutine_threadsafe(
            _webhook_app.process_update(update), _webhook_loop)
        return True
    except Exception as exc:
        logger.error("webhook dispatch error: %s", exc)
        return False


if __name__ == "__main__":
    bot = PremiumBingoBot()
    bot.run()
