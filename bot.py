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
from game_loop import GameLoop

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
loop = GameLoop(db, logic)


def _md(text) -> str:
    """Escape a user-supplied string for Telegram Markdown (parse_mode="Markdown").

    Usernames / first names / winner names can contain `_`, `*`, `[`, `` ` `` …
    which would break Markdown parsing and turn any message into the generic
    "Something went wrong" error — this is the #1 cause of that message.
    """
    return (str(text or "").replace("\\", "\\\\").replace("_", "\\_")
            .replace("*", "\\*").replace("[", "\\[").replace("`", "\\`"))


def _html(text) -> str:
    """Escape a user-supplied string for Telegram HTML (parse_mode="HTML")."""
    return (str(text or "").replace("&", "&amp;")
            .replace("<", "&lt;").replace(">", "&gt;"))


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
        # Persist wallet flow state across updates (survives webhook context resets)
        self._wallet_flows: dict = {}  # user_id -> flow dict

    # ------------------------------------------------------------ rooms
    @staticmethod
    def _rooms_line() -> str:
        """One status line per room, e.g. '• Room by 30: PLAYING · pool 90 ETB'."""
        lines = []
        for room in config.ROOM_BETS:
            state = db.get_game_state(room)
            pool = logic.calculate_prize_pool(room)
            lines.append(f"• {config.room_label(room)}: <b>{state['phase'].upper()}</b> · "
                         f"pool <b>{pool['prize_pool']} ETB</b>")
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

    def get_persistent_menu(self) -> ReplyKeyboardMarkup:
        """Persistent bottom keyboard — single 📋 Menu button."""
        return ReplyKeyboardMarkup(
            [[KeyboardButton("📋 Menu")]],
            resize_keyboard=True,
            one_time_keyboard=False,
        )

    def get_main_menu(self, user_id: int = 0):
        """Simple menu: opens the Mini App directly."""
        if self._webapp_ok():
            return InlineKeyboardMarkup([
                [InlineKeyboardButton("🎮  Open Nice Bingo",
                                      web_app={"url": _fresh_app_url()})],
            ])
        return InlineKeyboardMarkup([
            [InlineKeyboardButton("🔒  Mini App unavailable",
                                  callback_data="tunnel_help")],
        ])

    def get_game_menu(self):
        """Game menu — redirects to Mini App."""
        return self.get_main_menu()

    def get_main_menu_inline(self, user_id: int = 0) -> InlineKeyboardMarkup:
        """Inline keyboard with all action buttons attached to bot message."""
        rows = [
            [InlineKeyboardButton("🎮 Play", callback_data="menu_play"),
             InlineKeyboardButton("⬇️ Deposit", callback_data="menu_deposit"),
             InlineKeyboardButton("⬆️ Withdraw", callback_data="menu_withdraw")],
            [InlineKeyboardButton("🚨 Appeal", callback_data="menu_appeal"),
             InlineKeyboardButton("🔗 Referral", callback_data="menu_referral"),
             InlineKeyboardButton("💬 Support", url="https://t.me/nicebingosupport")],
        ]
        if self._webapp_ok():
            rows.append([InlineKeyboardButton("🚀 Open Nice Bingo",
                                              web_app={"url": _fresh_app_url()})])
        return InlineKeyboardMarkup(rows)

    def get_admin_menu(self):
        """Admin panel — redirects to Mini App."""
        return self.get_main_menu()

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
        """Welcome card with promo image and inline action buttons."""
        user = update.effective_user
        player = db.get_player(user.id) or {}
        name = (player.get("full_name") or "").strip() or user.first_name
        credit = db.get_credit(user.id)
        is_admin = db.is_admin(user.id)
        is_super = user.id in config.SUPER_ADMIN_IDS
        badge = " ⭐" if is_super else (" 👑" if is_admin else "")
        # Send promo image first
        try:
            promo_img = os.path.join(os.path.dirname(os.path.abspath(__file__)), "1.jpg")
            if os.path.isfile(promo_img):
                with open(promo_img, "rb") as photo:
                    await update.message.reply_photo(
                        photo=photo,
                        caption="🎉 *SPECIAL PROMOTION* 🎉\n\n🔥 Play Nice Bingo and win BIG!\n💰 Deposit now and get bonus credit!",
                        parse_mode="Markdown",
                    )
        except Exception as exc:
            logger.warning("promo image send failed: %s", exc)
        text = (
            f"<b>✨ 🎰 NICE BINGO 🎰 ✨</b>\n"
            f"━━━━━━━━━━━━━━━━━━━━\n\n"
            f"Welcome, <b>{_html(name)}</b>{badge}\n"
            f"💰 Balance: <b>{credit} {config.APP_CURRENCY}</b>\n\n"
            f"Choose an action below:"
        )
        try:
            await update.message.reply_text(
                text,
                reply_markup=self.get_main_menu_inline(user.id),
                parse_mode="HTML",
            )
        except Exception as exc:
            logger.warning("_send_welcome inline menu failed: %s", exc)
        # Show persistent 📋 Menu button at the bottom
        try:
            await update.message.reply_text(
                "👇 Use the 📋 Menu button below to navigate:",
                reply_markup=self.get_persistent_menu(),
            )
        except Exception as exc:
            logger.warning("_send_welcome persistent menu failed: %s", exc)

    async def text_handler(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Captures the full name when the bot is waiting for it (after /start),
        or processes one step of the deposit/withdraw wallet chat flow."""
        user = update.effective_user
        raw = (update.message.text or "").strip()
        # --- 📋 Menu persistent button ---
        if raw == "📋 Menu":
            try:
                await self.menu_command(update, context)
            except Exception as exc:
                logger.warning("menu_command error: %s", exc)
                try:
                    await update.message.reply_text(
                        "⚠️ Something went wrong — please try /menu.",
                        reply_markup=self.get_main_menu(user.id))
                except Exception:
                    pass
            return
        # --- wallet chat flow takes priority over everything ---
        if self._wallet_flows.get(user.id):
            if not raw:
                await update.message.reply_text("Please enter a value.")
                return
            try:
                await self._wallet_flow_text(update, context, raw)
            except Exception as exc:
                logger.warning("wallet flow error: %s", exc)
                self._wallet_flows.pop(user.id, None)
                await update.message.reply_text(
                    "⚠️ Something went wrong — please try again.",
                    reply_markup=self.get_main_menu(user.id))
            return
        # --- appeal chat flow ---
        if context.user_data.get("appeal_flow") or self._wallet_flows.get(f"appeal_{user.id}"):
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
                [InlineKeyboardButton("🎮 OPEN NICE BINGO",
                                      web_app={"url": _fresh_app_url()})],
            ])
            closing = ("📖 How to Play Guide:\n"
                       "• Pick your room, select cards and play!\n"
                       "• Works best inside Telegram on your phone or desktop.")
        else:
            keyboard = InlineKeyboardMarkup([
                [InlineKeyboardButton("🔒 Fix Mini App URL", callback_data="tunnel_help")],
            ])
            closing = HTTPS_HINT
        credit = db.get_credit(user.id)
        await context.bot.send_message(
            chat_id=chat_id,
            text=(
                f"<b>✨ 🎰 NICE BINGO 🎰 ✨</b>\n\n"
                f"💰 Balance: <b>{credit} {config.APP_CURRENCY}</b>\n\n"
                f"{self._rooms_line()}\n\n"
                f"{closing}"
            ),
            reply_markup=keyboard,
            parse_mode="HTML",
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
        uid = update.effective_user.id
        text = (
            f"❓ *How to Play*\n"
            f"━━━━━━━━━━━━━━━━━━━━\n\n"
            f"Tap *🎮 Play* to open the Bingo Arena!\n"
            f"Everything is inside the Mini App:\n"
            f"• Wallet (Deposit & Withdraw)\n"
            f"• Profile settings\n"
            f"• Referral program\n"
            f"• Help & guide\n\n"
            f"*Commands:*\n"
            f"`/start`  `/menu`  `/play`  `/help`\n\n"

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

        try:
            await self._handle_callback(update, query, context, user_id, data)
        except Exception as exc:
            logger.warning("callback_handler error for '%s': %s", data, exc)
            try:
                await query.edit_message_text(
                    "⚠️ Something went wrong. Please try again.",
                    reply_markup=self.get_main_menu(user_id))
            except Exception:
                try:
                    await query.message.reply_text(
                        "⚠️ Something went wrong. Please try again.",
                        reply_markup=self.get_main_menu(user_id))
                except Exception:
                    pass

    async def _handle_callback(self, update, query, context, user_id, data):

        if data == "menu":
            # Redirect to the Mini App
            try:
                await query.edit_message_text(
                    "🎮 Tap the button below to open the Bingo Arena!",
                    reply_markup=self.get_main_menu(user_id))
            except Exception:
                await query.message.reply_text(
                    "🎮 Tap the button below to open the Bingo Arena!",
                    reply_markup=self.get_main_menu(user_id))
        elif data == "menu_play":
            try:
                await self.play_command(update, context)
            except Exception as exc:
                logger.warning("menu_play error: %s", exc)
                await self._safe_edit_or_reply(query, user_id,
                    "⚠️ Something went wrong — please try again.",
                    reply_markup=self.get_main_menu(user_id))
        elif data == "menu_deposit":
            try:
                await self._wallet_start(update, context, "deposit")
            except Exception as exc:
                logger.warning("wallet deposit from menu: %s", exc)
                try:
                    await query.edit_message_text(
                        "⚠️ Something went wrong — please try /deposit instead.",
                        reply_markup=self.get_main_menu(user_id))
                except Exception:
                    await query.message.reply_text(
                        "⚠️ Something went wrong — please try /deposit instead.",
                        reply_markup=self.get_main_menu(user_id))
        elif data == "menu_withdraw":
            try:
                await self._wallet_start(update, context, "withdraw")
            except Exception as exc:
                logger.warning("wallet withdraw from menu: %s", exc)
                try:
                    await query.edit_message_text(
                        "⚠️ Something went wrong — please try /withdraw instead.",
                        reply_markup=self.get_main_menu(user_id))
                except Exception:
                    await query.message.reply_text(
                        "⚠️ Something went wrong — please try /withdraw instead.",
                        reply_markup=self.get_main_menu(user_id))
        elif data == "menu_appeal":
            try:
                await self.appeal_list(update, context)
            except Exception as exc:
                logger.warning("menu_appeal error: %s", exc)
                await self._safe_edit_or_reply(query, user_id,
                    "⚠️ Something went wrong — please try again.",
                    reply_markup=self.get_main_menu(user_id))
        elif data == "menu_referral":
            try:
                await self._show_referral(update, context, user_id)
            except Exception as exc:
                logger.warning("menu_referral error: %s", exc)
                await self._safe_edit_or_reply(query, user_id,
                    "⚠️ Something went wrong — please try again.",
                    reply_markup=self.get_main_menu(user_id))
        elif data == "play":
            try:
                await self.play_command(update, context)
            except Exception as exc:
                logger.warning("play callback error: %s", exc)
                await self._safe_edit_or_reply(query, user_id,
                    "⚠️ Something went wrong — please try again.",
                    reply_markup=self.get_main_menu(user_id))
        elif data in ("status", "refresh"):
            try:
                await self.status_command(update, context)
            except Exception as exc:
                logger.warning("status callback error: %s", exc)
                await self._safe_edit_or_reply(query, user_id,
                    "⚠️ Something went wrong — please try again.",
                    reply_markup=self.get_main_menu(user_id))
        elif data == "balance":
            try:
                await self.balance_command(update, context)
            except Exception as exc:
                logger.warning("balance callback error: %s", exc)
                await self._safe_edit_or_reply(query, user_id,
                    "⚠️ Something went wrong — please try again.",
                    reply_markup=self.get_main_menu(user_id))
        elif data in ("my_cards", "show_cards"):
            try:
                await self.my_cards_command(update, context)
            except Exception as exc:
                logger.warning("my_cards callback error: %s", exc)
                await self._safe_edit_or_reply(query, user_id,
                    "⚠️ Something went wrong — please try again.",
                    reply_markup=self.get_main_menu(user_id))
        elif data == "leaderboard":
            try:
                await self.top_command(update, context)
            except Exception as exc:
                logger.warning("leaderboard callback error: %s", exc)
                await self._safe_edit_or_reply(query, user_id,
                    "⚠️ Something went wrong — please try again.",
                    reply_markup=self.get_main_menu(user_id))
        elif data == "quick_play":
            # Direct DB — avoids HTTP self-request deadlock on PA.
            room = config.ROOM_DEFAULT
            state = db.get_game_state(room)
            if state.get("phase") != "preparation":
                await query.edit_message_text("❌ The round already started.",
                                              reply_markup=self.get_main_menu(user_id))
            else:
                selections = db.get_user_selections(user_id, room)
                slots = config.MAX_CARDS_PER_PLAYER - len(selections)
                taken = {s["card_id"] for s in db.get_all_selections(room)}
                available = [c for c in db.get_all_cards() if c["id"] not in taken][:slots]
                chosen = []
                for card in available:
                    if db.get_credit(user_id) < room:
                        break
                    db.select_card(user_id, card["id"], room, room)
                    db.update_credit(user_id, -room)
                    chosen.append(card["id"])
                credit = db.get_credit(user_id)
                await query.edit_message_text(
                    f"✅ Auto-selected {len(chosen)} card(s)! Balance: {credit} ETB",
                    reply_markup=self.get_main_menu(user_id))
        elif data == "help":
            try:
                await self.help_command(update, context)
            except Exception as exc:
                logger.warning("help callback error: %s", exc)
                await self._safe_edit_or_reply(query, user_id,
                    "⚠️ Something went wrong — please try again.",
                    reply_markup=self.get_main_menu(user_id))
        elif data == "tunnel_help":
            await query.edit_message_text(HTTPS_HINT, reply_markup=self.get_main_menu(user_id),
                                          parse_mode="Markdown")
        elif data == "select":
            try:
                await self.select_command(update, context)
            except Exception as exc:
                logger.warning("select error: %s", exc)
                await self._safe_edit_or_reply(query, user_id,
                    "⚠️ Something went wrong — please try again.",
                    reply_markup=self.get_main_menu(user_id))
        elif data == "deselect":
            try:
                await self.deselect_command(update, context)
            except Exception as exc:
                logger.warning("deselect error: %s", exc)
                await self._safe_edit_or_reply(query, user_id,
                    "⚠️ Something went wrong — please try again.",
                    reply_markup=self.get_main_menu(user_id))
        elif data.startswith("select_"):
            card_id = data.split("_", 1)[1]
            # Direct DB — avoids HTTP self-request deadlock on PA.
            room = config.ROOM_DEFAULT
            state = db.get_game_state(room)
            if state.get("phase") != "preparation":
                await query.edit_message_text("❌ Selection is closed.",
                                              reply_markup=self.get_main_menu(user_id))
            elif len(db.get_user_selections(user_id, room)) >= config.MAX_CARDS_PER_PLAYER:
                await query.edit_message_text(f"❌ Max {config.MAX_CARDS_PER_PLAYER} cards.",
                                              reply_markup=self.get_main_menu(user_id))
            elif db.is_card_taken(card_id, room):
                await query.edit_message_text("❌ That card is already taken.",
                                              reply_markup=self.get_main_menu(user_id))
            elif not db.get_card(card_id):
                await query.edit_message_text("❌ Unknown card.",
                                              reply_markup=self.get_main_menu(user_id))
            elif db.get_credit(user_id) < room:
                await query.edit_message_text(f"❌ Insufficient credit — {room} ETB needed.",
                                              reply_markup=self.get_main_menu(user_id))
            else:
                db.select_card(user_id, card_id, room, room)
                db.update_credit(user_id, -room)
                credit = db.get_credit(user_id)
                await query.edit_message_text(
                    f"✅ Card #{card_id} selected · {credit} ETB left",
                    reply_markup=self.get_game_menu())
        elif data.startswith("deselect_"):
            card_id = data.split("_", 1)[1]
            # Direct DB — avoids HTTP self-request deadlock on PA.
            room = config.ROOM_DEFAULT
            state = db.get_game_state(room)
            if state.get("phase") != "preparation":
                await query.edit_message_text("❌ The round already started.",
                                              reply_markup=self.get_main_menu(user_id))
            else:
                found = False
                for sel in db.get_user_selections(user_id, room):
                    if sel["card_id"] == card_id:
                        db.update_credit(user_id, sel["bet_amount"])
                        db.deselect_card(user_id, card_id)
                        found = True
                        break
                if found:
                    credit = db.get_credit(user_id)
                    await query.edit_message_text(
                        f"✅ Card #{card_id} removed — {credit} ETB refunded",
                        reply_markup=self.get_main_menu(user_id))
                else:
                    await query.edit_message_text("❌ Card not selected.",
                                                  reply_markup=self.get_main_menu(user_id))
        elif data == "referral":
            try:
                await self._show_referral(update, context, user_id)
            except Exception as exc:
                logger.warning("referral error: %s", exc)
                await self._safe_edit_or_reply(query, user_id,
                    "⚠️ Something went wrong — please try again.",
                    reply_markup=self.get_main_menu(user_id))
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
            try:
                await self._show_referral(update, context, user_id)
            except Exception as exc:
                logger.warning("referral_stats error: %s", exc)
                await self._safe_edit_or_reply(query, user_id,
                    "⚠️ Something went wrong — please try again.",
                    reply_markup=self.get_main_menu(user_id))
        elif data in ("wallet_deposit", "wallet_withdraw"):
            try:
                await self._wallet_start(update, context,
                                         "deposit" if data == "wallet_deposit" else "withdraw")
            except Exception as exc:
                logger.warning("wallet start error: %s", exc)
                try:
                    await query.edit_message_text(
                        "⚠️ Something went wrong — the game server may be offline.",
                        reply_markup=self.get_main_menu(user_id))
                except Exception:
                    await query.message.reply_text(
                        "⚠️ Something went wrong — the game server may be offline.",
                        reply_markup=self.get_main_menu(user_id))
        elif data.startswith("wbank_"):
            try:
                await self._wallet_bank_pick(update, context)
            except Exception as exc:
                logger.warning("wbank pick error: %s", exc)
                await self._safe_edit_or_reply(query, user_id,
                    "⚠️ Something went wrong — please try again.",
                    reply_markup=self.get_main_menu(user_id))
        elif data == "wallet_cancel":
            self._wallet_flows.pop(user_id, None)
            await query.edit_message_text("❌ Request cancelled.",
                                          reply_markup=self.get_main_menu(user_id))
        elif data.startswith("admin_"):
            try:
                await self.admin_callback_handler(update, context)
            except Exception as exc:
                logger.warning("admin callback error: %s", exc)
                await self._safe_edit_or_reply(query, user_id,
                    "⚠️ Something went wrong — please try again.",
                    reply_markup=self.get_main_menu(user_id))
        elif data == "requests":
            try:
                await self.requests_command(update, context)
            except Exception as exc:
                logger.warning("requests callback error: %s", exc)
                await self._safe_edit_or_reply(query, user_id,
                    "⚠️ Something went wrong — please try again.",
                    reply_markup=self.get_main_menu(user_id))
        elif data == "appeal_list":
            try:
                await self.appeal_list(update, context)
            except Exception as exc:
                logger.warning("appeal_list error: %s", exc)
                await self._safe_edit_or_reply(query, user_id,
                    "⚠️ Something went wrong — please try again.",
                    reply_markup=self.get_main_menu(user_id))
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
    # ------------------------------------------------------------------ DB helpers
    @staticmethod
    def _wallet_settings_from_db() -> dict:
        """Read wallet settings directly from the database — avoids the
        HTTP self-request that deadlocks on PythonAnywhere (bot + Flask
        share the same process; requests.get() to the same URL blocks.
        """
        best: dict = {}
        for acc in db.get_deposit_accounts():
            best.setdefault(acc["provider"], acc)
        # super-admin fallback
        for acc in db.get_payment_accounts(active_only=True):
            if acc.get("admin_id") in config.SUPER_ADMIN_IDS:
                best.setdefault(acc["provider"], acc)
        # final fallback: any active account
        for acc in db.get_payment_accounts(active_only=True):
            prov = acc.get("provider")
            if prov and prov not in best:
                best[prov] = acc
        active_providers = db.get_distinct_providers()
        return {
            "providers": active_providers,
            "deposit_accounts": [
                {"provider": p, "account": a} for p, a in best.items()
            ],
            "payment_accounts": db.get_payment_accounts(active_only=True),
        }

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
            await self._safe_edit_or_reply(query, user_id,
                "⛔ Please send /start and enter your full name first.",
                reply_markup=self.get_main_menu(user_id))
            return
        # Bank selection comes FIRST — the user picks the bank, then the amount.
        # Read directly from DB to avoid HTTP self-request deadlock on PA.
        settings = self._wallet_settings_from_db()
        providers = settings.get("providers") or []
        accounts = {d["provider"]: d["account"]
                    for d in settings.get("deposit_accounts") or []}
        # fallback: if deposit_accounts is empty, build from ALL active accounts
        if not accounts:
            for a in (settings.get("payment_accounts") or []):
                accounts.setdefault(a["provider"], a)
        if not providers and not accounts:
            await self._safe_edit_or_reply(query, user_id,
                "⏳ No bank accounts are available right now — please try "
                "again later.", reply_markup=self.get_main_menu(user_id))
            return
        if not providers:
            providers = list(accounts.keys())
        banks = {str(a["id"]): p for p, a in accounts.items()}
        accts = {str(a["id"]): a for p, a in accounts.items()}
        # filter providers to only those with a deposit account
        available = [p for p in providers if p in accounts]
        if not available:
            # last resort: show any available accounts
            available = list(accounts.keys())
        if not available:
            await self._safe_edit_or_reply(query, user_id,
                "⏳ No bank accounts are available right now — please try "
                "again later.", reply_markup=self.get_main_menu(user_id))
            return
        self._wallet_flows[user_id] = {
            "kind": kind, "step": "bank",
            "banks": banks, "accounts": accts,
        }
        label = "DEPOSIT ⬇️" if kind == "deposit" else "WITHDRAW ⬆️"
        keyboard = [[InlineKeyboardButton(p, callback_data=f"wbank_{accounts[p]['id']}")]
                    for p in available]
        keyboard.append([InlineKeyboardButton("❌ Cancel", callback_data="wallet_cancel")])
        await self._safe_edit_or_reply(query, user_id,
            f"💰 <b>New {label}</b>\n\n🏦 Choose the bank:" if kind == "deposit"
            else f"💰 <b>New {label}</b>\n\n🏦 Which bank should receive your money?",
            reply_markup=InlineKeyboardMarkup(keyboard), parse_mode="HTML")

    async def _wallet_flow_text(self, update: Update,
                                context: ContextTypes.DEFAULT_TYPE, raw: str):
        """One text step of the deposit/withdraw chat flow."""
        user_id = update.effective_user.id
        flow = self._wallet_flows.get(user_id) or {}
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
            # Save flow state immediately before sending reply
            self._wallet_flows[user_id] = flow
            # bank is already selected — move to the next step
            if kind == "deposit":
                flow["step"] = "tx"
                provider = flow.get("provider", "")
                acc = flow.get("_selected_acc") or {}
                await update.message.reply_text(
                    f"🏦 <b>{_html(provider)}</b>\n"
                    f"Holder: {_html(acc.get('account_name', '?'))}\n"
                    f"Number: <code>{_html(acc.get('account_number', '?'))}</code>\n\n"
                    "Send the money to this account with your wallet app, then type "
                    "the <b>transaction number</b> shown there:",
                    reply_markup=cancel_kb, parse_mode="HTML")
            else:
                flow["step"] = "holder"
                await update.message.reply_text(
                    "👤 Enter the account <b>holder's name</b> (whose account "
                    "should receive the money):",
                    reply_markup=cancel_kb, parse_mode="HTML")
        elif step == "tx":
            flow["tx_id"] = raw[:100]
            self._wallet_flows[user_id] = flow
            await self._wallet_submit(update, context, flow)
        elif step == "holder":
            if len(raw) > 60:
                await update.message.reply_text("Name is too long (max 60).",
                                                reply_markup=cancel_kb)
                return
            flow["account_holder"] = raw[:60]
            flow["step"] = "acct"
            self._wallet_flows[user_id] = flow
            await update.message.reply_text(
                "🔢 Enter YOUR account number where the money should be sent:",
                reply_markup=cancel_kb)
        elif step == "acct":
            if len(raw) > 60:
                await update.message.reply_text("Account number is too long (max 60).",
                                                reply_markup=cancel_kb)
                return
            flow["account_number"] = raw[:60]
            self._wallet_flows[user_id] = flow
            await self._wallet_submit(update, context, flow)
        else:
            self._wallet_flows.pop(user_id, None)
            await update.message.reply_text("Session expired — start again.",
                                            reply_markup=self.get_main_menu(user_id))

    async def _safe_edit_or_reply(self, query, user_id: int, text: str,
                                   reply_markup=None, parse_mode=None):
        """Try to edit the callback message; if that fails, send a new reply."""
        try:
            await query.edit_message_text(
                text, reply_markup=reply_markup, parse_mode=parse_mode)
        except Exception:
            try:
                await query.message.reply_text(
                    text, reply_markup=reply_markup, parse_mode=parse_mode)
            except Exception as exc:
                logger.warning("_safe_edit_or_reply failed: %s", exc)

    async def _wallet_bank_pick(self, update: Update,
                                context: ContextTypes.DEFAULT_TYPE):
        """Handle bank selection — reads account info directly from DB
        so it works even when context.user_data is lost (webhook mode).
        """
        query = update.callback_query
        await query.answer()
        user_id = update.effective_user.id
        # Extract the account ID from callback data (e.g. "wbank_123" -> "123")
        parts = query.data.split("_", 1)
        acc_id_str = parts[1] if len(parts) > 1 else ""
        if not acc_id_str:
            await self._safe_edit_or_reply(query, user_id, "❌ Invalid selection.")
            return
        try:
            acc_id = int(acc_id_str)
        except ValueError:
            await self._safe_edit_or_reply(query, user_id, "❌ Invalid selection.")
            return
        # Read account directly from DB — no dependency on context.user_data
        acc = db.get_payment_account(acc_id)
        if not acc or not acc.get("is_active"):
            await self._safe_edit_or_reply(query, user_id,
                "❌ This account is no longer available.")
            return
        provider = acc.get("provider", "Wallet")
        # Build the flow — always start fresh from DB data
        flow = self._wallet_flows.get(user_id) or {}
        flow["kind"] = flow.get("kind") or "deposit"
        flow["account_id"] = acc_id
        flow["provider"] = provider
        flow["_selected_acc"] = acc
        flow["step"] = "amount"
        # Save flow state IMMEDIATELY — critical for webhook mode
        self._wallet_flows[user_id] = flow
        cancel_kb = InlineKeyboardMarkup(
            [[InlineKeyboardButton("❌ Cancel", callback_data="wallet_cancel")]])
        if flow["kind"] == "deposit":
            await self._safe_edit_or_reply(query, user_id,
                f"🏦 <b>{_html(provider)}</b>\n"
                f"Holder: {_html(acc.get('account_name', '?'))}\n"
                f"Number: <code>{_html(acc.get('account_number', '?'))}</code>\n\n"
                f"Now enter the amount in {config.APP_CURRENCY} you sent:",
                reply_markup=cancel_kb, parse_mode="HTML")
        else:
            await self._safe_edit_or_reply(query, user_id,
                f"🏦 <b>{_html(provider)}</b> selected.\n\n"
                f"Enter the amount in {config.APP_CURRENCY} you want to withdraw "
                f"(minimum {config.MIN_WITHDRAWAL}):",
                reply_markup=cancel_kb, parse_mode="HTML")

    async def _wallet_submit(self, update: Update,
                             context: ContextTypes.DEFAULT_TYPE, flow: dict):
        """Write the deposit/withdraw directly to the DB (avoids HTTP
        self-request deadlock on PythonAnywhere)."""
        user_id = update.effective_user.id
        kind = flow.get("kind")
        amount = flow.get("amount")
        player = db.get_player(user_id) or {}
        try:
            if kind == "deposit":
                tx_id_val = flow.get("tx_id")
                acc_id = flow.get("account_id")
                account = db.get_payment_account(acc_id) if acc_id else None
                # Check that the account owner is online (or super admin)
                owner_id = (account or {}).get("admin_id")
                is_super_owner = owner_id in config.SUPER_ADMIN_IDS if owner_id else False
                if owner_id and not is_super_owner and not db.is_admin_online(owner_id):
                    flow["_done"] = True
                    self._wallet_flows.pop(user_id, None)
                    await update.message.reply_text(
                        "❌ This payment account's admin is offline. "
                        "Please try again later.",
                        reply_markup=self.get_main_menu(user_id))
                    return
                row_id = db.add_transaction(
                    user_id, "deposit", amount, tx_id_val,
                    phone=player.get("phone"),
                    user_name=player.get("full_name") or player.get("username"),
                    account_id=(account or {}).get("id"),
                    provider=(account or {}).get("provider"),
                    account_number=(account or {}).get("account_number"),
                    account_holder=(account or {}).get("account_name"),
                )
                # Notify the account owner + super admins
                try:
                    who = player.get("full_name") or player.get("username") or str(user_id)
                    lines = ["🚨 NEW DEPOSIT REQUEST",
                             "User: " + who,
                             "Amount: " + str(amount) + " " + config.APP_CURRENCY,
                             "Details: " + (tx_id_val or "")]
                    super_ids = set(config.SUPER_ADMIN_IDS)
                    if owner_id:
                        notify_user(owner_id, lines)
                        super_ids.discard(owner_id)
                    for sa_id in super_ids:
                        notify_user(sa_id, lines)
                except Exception:
                    pass
            else:  # withdraw
                if db.get_credit(user_id) < amount:
                    flow["_done"] = True
                    self._wallet_flows.pop(user_id, None)
                    await update.message.reply_text(
                        "❌ Insufficient balance for this withdrawal.",
                        reply_markup=self.get_main_menu(user_id))
                    return
                wd_name = (flow.get("provider") or "").strip()
                wd_holder = (flow.get("account_holder") or "").strip()
                wd_number = (flow.get("account_number") or "").strip()
                if not wd_name or not wd_holder or not wd_number:
                    flow["_done"] = True
                    self._wallet_flows.pop(user_id, None)
                    await update.message.reply_text(
                        "❌ Incomplete withdrawal details.",
                        reply_markup=self.get_main_menu(user_id))
                    return
                row_id = db.add_transaction(
                    user_id, "withdraw", amount,
                    user_name=player.get("full_name") or player.get("username"),
                    provider=wd_name,
                    account_number=wd_number,
                    account_holder=wd_holder,
                )
                # Notify all admins
                try:
                    who = player.get("full_name") or player.get("username") or str(user_id)
                    lines = ["🚨 NEW WITHDRAWAL REQUEST",
                             "User: " + who,
                             "Amount: " + str(amount) + " " + config.APP_CURRENCY,
                             "Details: " + wd_name + " | " + wd_holder + " | " + wd_number]
                    notify_admins(lines)
                except Exception:
                    pass
            # log activity
            try:
                who = player.get("full_name") or player.get("username") or str(user_id)
                label = 'Deposit' if kind == 'deposit' else 'Withdrawal'
                db.log_activity(kind + '_request', user_id,
                               label + ': ' + str(amount) + ' ' + config.APP_CURRENCY + ' by ' + who)
            except Exception:
                pass
            label = "Deposit" if kind == "deposit" else "Withdrawal"
            await update.message.reply_text(
                f"✅ **{label} request submitted!**\n\n"
                f"Amount: {amount} {config.APP_CURRENCY}\n"
                "The admin has been notified on Telegram and will review it "
                "shortly. Track it under 💰 Balance → recent requests.",
                reply_markup=self.get_main_menu(user_id), parse_mode="Markdown")
        except Exception as exc:
            logger.warning("_wallet_submit error: %s", exc)
            await update.message.reply_text(
                "❌ Failed to submit — please try again.",
                reply_markup=self.get_main_menu(user_id))
        finally:
            flow["_done"] = True
            self._wallet_flows.pop(user_id, None)

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
        """Process the appeal reason text and submit directly to DB."""
        user_id = update.effective_user.id
        flow = context.user_data.get("appeal_flow") or {}
        tx_id = flow.get("tx_id")
        if not tx_id:
            context.user_data.pop("appeal_flow", None)
            await update.message.reply_text(
                "Session expired — start again.",
                reply_markup=self.get_main_menu(user_id))
            return
        reason = reason[:500]
        try:
            db.add_appeal(user_id, tx_id, reason)
            # Notify super admins
            try:
                player = db.get_player(user_id) or {}
                who = player.get("full_name") or player.get("username") or str(user_id)
                for sa_id in config.SUPER_ADMIN_IDS:
                    notify_user(sa_id, [
                        '🚨 NEW APPEAL',
                        'User: ' + who,
                        'Deposit #' + str(tx_id),
                        'Reason: ' + reason,
                    ])
            except Exception:
                pass
            context.user_data.pop("appeal_flow", None)
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
        except Exception as exc:
            logger.warning("_appeal_flow_text error: %s", exc)
            context.user_data.pop("appeal_flow", None)
            await update.message.reply_text(
                "❌ Failed to submit appeal — please try again.",
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
        if not db.is_admin(user_id) and user_id not in config.SUPER_ADMIN_IDS:
            await update.message.reply_text("⛔ Unauthorized!")
            return
        db.touch_admin(user_id)
        # Read directly from DB — avoids HTTP self-request deadlock on PA.
        s = db.game_stats()
        bots_enabled = db.get_bots_enabled()
        bots_count = db.bot_count()
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
            f"🤖  Bots: *{'ON' if bots_enabled else 'OFF'}* "
            f"({bots_count} accounts)\n"
            f"━━━━━━━━━━━━━━━━━━\n"
            f"👇 *Choose an action:*"
        )
        await update.message.reply_text(text, reply_markup=self.get_admin_menu(),
                                        parse_mode="Markdown")

    async def give_take_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE,
                                sign: int):
        user_id = update.effective_user.id
        if not db.is_admin(user_id) and user_id not in config.SUPER_ADMIN_IDS:
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
        try:
            db.create_player(target, f"Player_{target}", credit=0)
            db.update_credit(target, amount)
            try:
                target_player = db.get_player(target) or {}
                target_name = target_player.get('full_name') or target_player.get('username') or str(target)
                db.log_activity('admin_credit_adjustment', user_id,
                               f'{amount:+d} {config.APP_CURRENCY} to {target_name} (ID: {target})')
            except Exception:
                pass
            credit = db.get_credit(target)
            await update.message.reply_text(
                f"✅ User {target} now has **{credit} ETB**")
        except Exception as exc:
            logger.warning("give_take error: %s", exc)
            await update.message.reply_text("❌ Failed — please try again.")

    async def admin_callback_handler(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        query = update.callback_query
        user_id = update.effective_user.id
        if not db.is_admin(user_id) and user_id not in config.SUPER_ADMIN_IDS:
            try:
                await query.edit_message_text("⛔ Unauthorized!")
            except Exception:
                pass
            return
        data = query.data
        # All admin actions now use direct game_loop / DB calls
        # (avoids HTTP self-request deadlock on PythonAnywhere).
        room = config.ROOM_DEFAULT
        try:
            if data == "admin_start":
                result = loop.force_start(room)
                msg = "✅ Round force-started!" if result.get("ok") else f"❌ {result.get('error', 'Failed')}"
                try:
                    await query.edit_message_text(msg, reply_markup=self.get_admin_menu())
                except Exception:
                    await query.message.reply_text(msg, reply_markup=self.get_admin_menu())
            elif data == "admin_call":
                result = loop.force_call(room)
                msg = "✅ Ball called!" if result.get("ok") else f"❌ {result.get('error', 'Failed')}"
                try:
                    await query.edit_message_text(msg, reply_markup=self.get_admin_menu())
                except Exception:
                    await query.message.reply_text(msg, reply_markup=self.get_admin_menu())
            elif data == "admin_bots":
                result = loop.add_bots(room)
                msg = "✅ Bots filled the room!" if result.get("ok") else f"❌ {result.get('error', 'Failed')}"
                try:
                    await query.edit_message_text(msg, reply_markup=self.get_admin_menu())
                except Exception:
                    await query.message.reply_text(msg, reply_markup=self.get_admin_menu())
            elif data == "admin_reset":
                loop.reset_round(room)
                msg = "✅ Round reset — new preparation phase."
                try:
                    await query.edit_message_text(msg, reply_markup=self.get_admin_menu())
                except Exception:
                    await query.message.reply_text(msg, reply_markup=self.get_admin_menu())
            elif data == "admin_bots_toggle":
                current = db.get_bots_enabled(room) 
                loop.toggle_bots(not current)
                msg = "✅ Bots toggled."
                try:
                    await query.edit_message_text(msg, reply_markup=self.get_admin_menu())
                except Exception:
                    await query.message.reply_text(msg, reply_markup=self.get_admin_menu())
            elif data == "admin_status":
                # Read directly from DB — avoids HTTP self-request deadlock on PA.
                s = db.game_stats()
                try:
                    await query.edit_message_text(
                        f"📊 **Admin Stats**\n\nRounds: {s.get('rounds', '?')}\n"
                        f"Total bets: {s.get('total_bets', 0)} ETB\nPaid out: {s.get('prize_paid', 0)} ETB\n"
                        f"House kept: {s.get('house_kept', 0)} ETB\nReal winners: {s.get('real_winners', 0)}",
                        reply_markup=self.get_admin_menu(), parse_mode="Markdown")
                except Exception:
                    await query.message.reply_text(
                        f"📊 **Admin Stats**\n\nRounds: {s.get('rounds', '?')}\n"
                        f"Total bets: {s.get('total_bets', 0)} ETB\nPaid out: {s.get('prize_paid', 0)} ETB\n"
                        f"House kept: {s.get('house_kept', 0)} ETB\nReal winners: {s.get('real_winners', 0)}",
                        reply_markup=self.get_admin_menu(), parse_mode="Markdown")
        except Exception as exc:
            logger.warning("admin_callback error for '%s': %s", data, exc)
            try:
                await query.edit_message_text(f"❌ Error: {exc}", reply_markup=self.get_admin_menu())
            except Exception:
                await query.message.reply_text(f"❌ Error: {exc}", reply_markup=self.get_admin_menu())

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
                    msg = (f"🔄 **{label}** is preparing — {config.PREPARATION_SECONDS}s to pick your cards!\n"
                            f"Tap **/play** to open the Mini App 🎰")
                    for uid in players:
                        try:
                            db.add_bot_notification(uid, msg)
                        except Exception:
                            pass
                elif phase == "playing" and last["phase"] != "playing" and config.ANNOUNCE_ROUNDS:
                    pool = logic.calculate_prize_pool(room)
                    msg = (f"🎰 **{label}**: A new Bingo round has started!\n\n"
                            f"💰 Prize pool: **{pool['prize_pool']} ETB**\n"
                            f"👥 Players: **{pool['real_players']}**\n\nGood luck! 🍀")
                    for uid in players:
                        try:
                            db.add_bot_notification(uid, msg)
                        except Exception:
                            pass
                elif phase == "ended" and last["phase"] != "ended" and config.ANNOUNCE_ROUNDS:
                    if state.get("winner_user_id"):
                        info = json.loads(state["winning_pattern"] or "{}")
                        winner = db.get_player(state["winner_user_id"])
                        wname = (winner or {}).get("full_name") or (winner or {}).get("username") or (
                            bot_name(state["winner_user_id"])
                            if state["winner_user_id"] < 0 else "Player")
                        card_id = info.get('card_id', '?') 
                        msg = (f"🎉 **BINGO!** 🎉 ({label})\n\n🏆 Winner: **{_md(wname)}**\n"
                                f"🃏 Winning Card: **#{card_id}**\n"
                                f"🎯 Pattern: **{info.get('pattern')}**\n"
                                f"💰 Prize: **{info.get('prize', 0)} {config.APP_CURRENCY}**")
                    else:
                        msg = f"🛑 **{label}**: all 75 balls called — no winner. Next round soon!"
                    for uid in players:
                        try:
                            db.add_bot_notification(uid, msg)
                        except Exception:
                            pass

                if phase == "playing" and config.ANNOUNCE_NUMBERS and count > last["count"]:
                    for idx, n in enumerate(called[last["count"]:count],
                                            start=last["count"] + 1):
                        ball_msg = f"🎯 **{n}**  ·  {idx}/{config.TOTAL_NUMBERS} ({label})"
                        for uid in players:
                            try:
                                db.add_bot_notification(uid, ball_msg)
                            except Exception:
                                pass

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
        """/menu or Menu — show promo image + inline action buttons."""
        uid = update.effective_user.id
        credit = db.get_credit(uid)
        # Send promo image first
        try:
            promo_img = os.path.join(os.path.dirname(os.path.abspath(__file__)), "1.jpg")
            if os.path.isfile(promo_img):
                with open(promo_img, "rb") as photo:
                    await update.message.reply_photo(
                        photo=photo,
                        caption="🎉 *SPECIAL PROMOTION* 🎉\n\n🔥 Play Nice Bingo and win BIG!\n💰 Deposit now and get bonus credit!",
                        parse_mode="Markdown",
                    )
        except Exception as exc:
            logger.warning("menu promo image failed: %s", exc)
        text = (
            f"<b>✨ 🎰 NICE BINGO 🎰 ✨</b>\n"
            f"━━━━━━━━━━━━━━━━━━\n\n"
            f"💰 Balance: <b>{credit} {config.APP_CURRENCY}</b>\n\n"
            f"Choose an action below:"
        )
        await update.message.reply_text(
            text,
            reply_markup=self.get_main_menu_inline(uid),
            parse_mode="HTML")

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
        # Send promotion image (1.jpg) to all players on bot start
        try:
            promo_img = os.path.join(os.path.dirname(os.path.abspath(__file__)), "1.jpg")
            if os.path.isfile(promo_img):
                player_ids = db.get_all_player_ids()
                promo_caption = (
                    "🎉 **SPECIAL PROMOTION** 🎉\n\n"
                    "🔥 Play Nice Bingo and win BIG!\n"
                    "💰 Deposit now and get bonus credit!\n"
                    "🎰 Tap /play to open the Bingo Arena!"
                )
                for uid in player_ids:
                    try:
                        with open(promo_img, "rb") as photo:
                            await application.bot.send_photo(
                                chat_id=uid,
                                photo=photo,
                                caption=promo_caption,
                                parse_mode="Markdown",
                            )
                    except Forbidden:
                        db.delete_player(uid)
                    except Exception:
                        pass
                logger.info("Promotion image sent to %d players", len(player_ids))
            else:
                logger.warning("Promotion image not found: %s", promo_img)
        except Exception as exc:
            logger.warning("Promotion broadcast error: %s", exc)
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


def _send_telegram_message(chat_id: int, text: str) -> bool:
    """Send a Telegram message directly via the Bot API (best effort).
    Used by notify_user/notify_admins so announcements arrive instantly
    without waiting for the bot's job queue to drain.
    """
    if not BOT_TOKEN:
        return False
    try:
        resp = requests.post(
            f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage",
            json={"chat_id": chat_id, "text": text},
            timeout=5,
        )
        return resp.status_code == 200
    except Exception:
        return False


def notify_admins(lines: list) -> None:
    """Queue + instantly send a plain-text alert to EVERY admin.

    Tries to send directly via the Telegram Bot API first (arrives as a
    normal push notification even when the bot's job queue is idle).
    Also queues in the DB as a fallback so the bot's announcer can retry
    if the direct send fails.
    """
    text = chr(10).join(str(line) for line in lines)
    for admin_id in db.get_admin_ids():
        # queue in DB (fallback for retry)
        try:
            db.add_bot_notification(admin_id, text)
        except Exception as exc:
            logger.error("admin notify queue failed: %s", exc)
        # send directly (instant push notification)
        try:
            _send_telegram_message(admin_id, text)
        except Exception:
            pass


def notify_user(user_id: int, lines: list) -> None:
    """Queue + instantly send a Telegram alert for ONE specific chat.

    Best effort — never raises. Tries direct send first for instant
    delivery, then queues in DB as retry fallback.
    """
    text = chr(10).join(str(line) for line in lines)
    # queue in DB (fallback)
    try:
        db.add_bot_notification(user_id, text)
    except Exception as exc:
        logger.error("user notify queue failed: %s", exc)
    # send directly (instant push notification)
    try:
        _send_telegram_message(user_id, text)
    except Exception:
        pass


def dispatch_webhook(update_dict: dict) -> bool:
    """Hand an incoming Telegram update to the running webhook bot.

    Called by server.py's /webhook/<secret> route. Fire-and-forget: the update
    is scheduled on the bot's event loop and the HTTP request returns at once.
    Returns False only while the bot is still starting up (Telegram will
    retry the delivery).

    Also drains the notification queue on every incoming update so that
    deposit/withdraw alerts, daily promos, and round announcements are
    delivered promptly even when the announcer tick is slow or not running.
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
    # drain queued notifications on every webhook update so alerts are
    # delivered promptly (deposit/withdraw, daily promo, round events)
    try:
        for n in db.get_unsent_bot_notifications(50):
            try:
                asyncio.run_coroutine_threadsafe(
                    _webhook_app.bot.send_message(
                        chat_id=n["chat_id"], text=n["text"]),
                    _webhook_loop)
                db.mark_bot_notification_sent(n["id"])
            except Exception:
                pass
    except Exception:
        pass
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
