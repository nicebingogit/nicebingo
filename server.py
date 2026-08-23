"""
Local web server (Flask) for the immersive Bingo experience.

* Hosts the Telegram Mini App (built React app) as static files.
* Exposes the JSON API the Mini App talks to.
* Runs the game loop (APScheduler) — the single source of truth for game state.
* SQLite persists everything, so a restart continues exactly where it stopped.

Run:  python server.py
"""
import json
import logging
import os
import sys
import urllib.parse
import hmac
import hashlib
import time
from typing import Optional

from dotenv import load_dotenv
from flask import Flask, jsonify, request, send_from_directory

load_dotenv()

import config
import cards_data
from database import Database
from game_logic import GameLogic
from game_loop import GameLoop

logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO,
)
logger = logging.getLogger("server")

app = Flask(__name__, static_folder=None)
db = Database(config.DB_PATH)
logic = GameLogic(db)
loop = GameLoop(db, logic)


def _base_dir() -> str:
    """Project root — the exe's bundle dir when frozen (PyInstaller), the repo
    folder when running from source. The built Mini App lives at frontend/dist."""
    if getattr(sys, "frozen", False):
        return getattr(sys, "_MEIPASS", os.path.dirname(sys.executable))
    return os.path.dirname(os.path.abspath(__file__))


FRONTEND_DIR = os.path.join(_base_dir(), "frontend", "dist")


# --------------------------------------------------------------------------- init
def seed_cards() -> int:
    """Insert the pre-generated cards (idempotent, config.NUM_CARDS)."""
    if db.count_cards() >= config.NUM_CARDS:
        return db.count_cards()
    for card in cards_data.ALL_CARDS:
        db.insert_card(card["id"], card["numbers"])
    return db.count_cards()


# -------------------------------------------------------------- telegram helpers
def _verify_init_data(init_data: str) -> bool:
    """Validate Telegram Web App initData signature (HMAC-SHA256 of the bot token)."""
    try:
        params = dict(p.split("=", 1) for p in init_data.split("&"))
        received_hash = params.pop("hash", None)
        if not received_hash:
            return False
        auth_date = int(params.get("auth_date", 0))
        if time.time() - auth_date > 86400 * 1:  # 24h window
            return False
        secret_key = hmac.new(b"WebAppData", config.BOT_TOKEN.encode(), hashlib.sha256).digest()
        data_check_string = "\n".join(f"{k}={params[k]}" for k in sorted(params))
        calc = hmac.new(secret_key, data_check_string.encode(), hashlib.sha256).hexdigest()
        return hmac.compare_digest(calc, received_hash)
    except Exception:
        return False


def _touch_admin_if_admin(user_id: Optional[int]) -> None:
    """Mark an admin as ONLINE (last_seen = now) when they make any request.

    An admin is "online" while they are actively using the app / bot — only
    ONLINE admins' payment accounts are shown to users for deposits, and the
    richest ONLINE admin is selected for each bank.
    """
    if user_id is not None and db.is_admin(user_id):
        try:
            db.touch_admin(user_id)
        except Exception:
            pass


def _user_id_from_request() -> Optional[int]:
    """Resolve the caller's identity, leniently.

    Priority:
      1. A *valid* Telegram initData signature -> the Telegram user id (trusted).
      2. An explicit user_id (query param / JSON body) -> used as-is. This is
         how browser testing works and also rescues edge cases where initData
         is present but can't be verified (old sessions, clock drift, proxies).
      3. Nothing -> None (caller must supply a real identity).
    """
    uid: Optional[int] = None
    init_data = request.args.get("init_data") or \
        (request.get_json(silent=True) or {}).get("init_data")
    if init_data:
        if _verify_init_data(init_data):
            params = dict(p.split("=", 1) for p in init_data.split("&"))
            try:
                # the `user` value is percent-encoded JSON (e.g. %7B%22id%22...)
                user = json.loads(urllib.parse.unquote(params.get("user", "{}")))
                uid = int(user.get("id"))
            except (ValueError, TypeError):
                uid = None
        # invalid / unverifiable initData -> fall through to explicit user_id
    if not uid:
        raw = request.args.get("user_id") or \
            (request.get_json(silent=True) or {}).get("user_id")
        try:
            uid = int(raw) if raw else None
        except (TypeError, ValueError):
            uid = None
    _touch_admin_if_admin(uid)
    return uid


# ------------------------------------------------------------------ serializers
def _room_from_request(default: Optional[int] = None) -> int:
    """Resolve the room (fixed bet) the caller is acting on.

    Reads `room` from the JSON body or a query param and falls back to the
    default room when absent or invalid, so old clients/tests keep working.
    """
    data = request.get_json(silent=True) or {}
    raw = data.get("room") or request.args.get("room")
    try:
        room = int(raw)
    except (TypeError, ValueError):
        room = default if default is not None else config.ROOM_DEFAULT
    if room not in config.ROOM_BETS:
        room = default if default is not None else config.ROOM_DEFAULT
    return room


def _card_payload(card_id: str, user_id: int, taken: dict) -> dict:
    """Lightweight picker entry — NO numbers (the picker only needs the taken
    status; the player's own card numbers come from the user payload). This
    keeps the 400-card pool payload tiny, which keeps the app fast."""
    taken_by = taken.get(card_id)
    return {
        "id": card_id,
        "taken": taken_by is not None,
        "taken_by_me": taken_by == user_id,
    }


def _user_payload(user_id: int, room: int = 30) -> dict:
    player = db.get_player(user_id) or {"user_id": user_id, "username": None, "credit": 0}
    selections = []
    for sel in db.get_user_selections(user_id, room):
        selections.append({
            "card_id": sel["card_id"],
            "bet_amount": sel["bet_amount"],
            "numbers": db.get_card(sel["card_id"]) or {},
        })
    state = db.get_game_state(room)
    eliminated = user_id in db.get_eliminated_user_ids(state.get("current_game_id"))
    full_name = player.get("full_name") or ""
    return {
        "user_id": user_id,
        "username": player.get("username"),
        "full_name": full_name or None,
        # the stored full name is the display identity everywhere
        "display_name": full_name or player.get("username") or f"Player_{user_id}",
        "phone": player.get("phone"),
        # a missing row (account deleted / never registered) must resolve to
        # is_registered=False so the Mini App shows the registration gate again
        "is_registered": bool(player.get("is_registered", 0)),
        "credit": player.get("credit", 0),
        "is_admin": db.is_admin(user_id),
        # the ONE admin who controls everything (credit selling, logs, appeals)
        "is_super_admin": user_id in config.SUPER_ADMIN_IDS,
        # false-BINGO elimination for the CURRENT round only
        "eliminated": eliminated,
        "selections": selections,
    }


def _account_payload(account: dict) -> dict:
    """JSON-safe payment account (is_active as a real boolean).

    Includes the OWNING admin's identity + credit + online status so the
    Super Admin panel and the user deposit picker can show who stands behind
    the account and whether the account is currently selectable.
    """
    admin_id = account.get("admin_id")
    admin_name = account.get("admin_name")
    admin_credit = account.get("admin_credit")
    admin_online = None
    if admin_id:
        owner = db.get_player(admin_id) or {}
        admin_name = admin_name or owner.get("full_name") or owner.get("username")
        admin_credit = owner.get("credit", 0)
        admin_online = db.is_admin_online(admin_id)
    return {
        "id": account["id"],
        "provider": account["provider"],
        "account_name": account["account_name"],
        "account_number": account["account_number"],
        "is_active": bool(account.get("is_active")),
        "admin_id": admin_id,
        "admin_name": admin_name,
        "admin_credit": admin_credit,
        "admin_online": admin_online,
        "created_at": account.get("created_at"),
        "updated_at": account.get("updated_at"),
    }


def _settings_payload() -> dict:
    """Public wallet settings shown in every user's Settings -> Wallet panel.

    * `payment_accounts` — every ACTIVE account (kept for compatibility).
    * `deposit_accounts` — ONE account per bank/provider: always the ONLINE
      admin with the MOST credit. If NO admin is online for a provider, the
      SUPER ADMIN's account is used as fallback so users can always pay.
    """
    # get_deposit_accounts() is ordered by owner credit DESC, so the
    # first row per provider IS the selected account
    best: dict = {}
    for acc in db.get_deposit_accounts():
        best.setdefault(acc["provider"], acc)
    # If no online admin has a certain provider, fall back to the super admin's
    # account so users always have somewhere to pay.
    super_accounts = {}
    for acc in db.get_payment_accounts(active_only=True):
        if acc.get("admin_id") in config.SUPER_ADMIN_IDS:
            super_accounts.setdefault(acc["provider"], acc)
    for provider, acc in super_accounts.items():
        if provider not in best:
            best[provider] = acc
    return {
        "currency": config.APP_CURRENCY,
        "payment_accounts": [_account_payload(a)
                              for a in db.get_payment_accounts(active_only=True)],
        "deposit_accounts": [
            {"provider": p, "account": _account_payload(a)}
            for p, a in best.items()
        ],
    }


def _state_payload(user_id: int, room: int = 30) -> dict:
    state = db.get_game_state(room)
    called = db.get_called_numbers(room)
    pool = logic.calculate_prize_pool(room)
    winner = None
    if state.get("phase") == "ended" and state.get("winner_user_id"):
        info = json.loads(state["winning_pattern"] or "{}")
        # the winning card + its exact winning cells let the Mini App DRAW the
        # winning pattern visually for every player, not just describe it
        winner = {
            "user_id": state["winner_user_id"],
            "name": loop._name_of(state["winner_user_id"]),
            "pattern": info.get("pattern"),
            "prize": info.get("prize", 0),
            "winning_cells": info.get("winning_cells", []),
        }
        # the winning card uses the same {numbers: {...}} shape as the user's
        # own card payload, so the Mini App can draw the pattern on it
        card_numbers = db.get_card(info.get("card_id"))
        winner["card"] = {"numbers": card_numbers} if card_numbers else None
    remaining = 0
    from datetime import datetime
    try:
        end = datetime.fromisoformat(state["preparation_end_time"]) if state.get("preparation_end_time") else None
        if end:
            remaining = max(0, int((end - datetime.now()).total_seconds()))
    except (ValueError, TypeError):
        remaining = 0
    return {
        "phase": state.get("phase"),
        "round": state.get("round_number", 0),
        "preparation_remaining": remaining,
        "current_call": state.get("current_call"),
        "called_numbers": called,
        "called_count": len(called),
        "total_numbers": config.TOTAL_NUMBERS,
        "win_pool": pool["prize_pool"],
        "total_bets": pool["total_bets"],
        "real_players": pool["real_players"],
        "bots_players": logic.player_breakdown(room)["bots"],
        "cards_in_play": len(db.get_all_selections(room)),
        "bots_enabled": bool(state.get("bots_enabled", 1)),
        "paused": bool(state.get("paused", 0)),
        "winner": winner,
        "settings": _settings_payload(),
        "config": {
            "rooms": config.ROOM_BETS,
            "room": room,
            "room_default": config.ROOM_DEFAULT,
            "bet_min": config.BET_MIN_CARD,
            "bet_default": config.BET_PER_CARD,
            "max_cards": config.MAX_CARDS_PER_PLAYER,
            "call_interval": config.CALL_INTERVAL_SECONDS,
            "preparation": config.PREPARATION_SECONDS,
            "currency": config.APP_CURRENCY,
            "new_player_credit": config.NEW_PLAYER_CREDIT,
        },
    }


# ------------------------------------------------------------------------ API
@app.after_request
def _cors(resp):
    resp.headers["Access-Control-Allow-Origin"] = "*"
    resp.headers["Access-Control-Allow-Headers"] = "Content-Type"
    resp.headers["Access-Control-Allow-Methods"] = "GET, POST, OPTIONS"
    return resp


@app.route("/api/init")
def api_init():
    user_id = _user_id_from_request()
    if user_id is None:
        return jsonify({"error": "Missing or invalid user_id / init_data"}), 400
    room = _room_from_request()
    username = request.args.get("username") or f"Player_{user_id}"
    player = db.get_player(user_id)
    if player is None:
        # brand-new visitor: placeholder account, NOT registered yet -> the
        # Mini App shows the registration screen (full name + phone) before
        # any gameplay. The welcome bonus is granted on successful registration.
        db.create_player(user_id, username, credit=0)
        db.update_profile(user_id, registered=False)
        try:
            db.log_activity('new_player_joined', user_id,
                           f'Username: {username}')
            from bot import notify_admins
            notify_admins(['🆕 NEW PLAYER JOINED',
                          f'User: {username} (ID: {user_id})'])
        except Exception:
            pass
    else:
        db.update_username(user_id, username)
    return jsonify({**_user_payload(user_id, room), "state": _state_payload(user_id, room)})


@app.route("/api/register", methods=["POST"])
def api_register():
    """Complete the wallet half of registration: store the phone number.

    The FULL NAME is collected once by the Telegram bot (/start -> chat asks
    for the name); the Mini App must NOT bypass that onboarding, so a caller
    without a stored full name is rejected here.

    Re-registration semantics (account is phone-bound):
      * same phone again          -> just updates the profile (no bonus).
      * different phone number    -> the old account is wiped and recreated
        with the SAME identity name + a fresh welcome bonus (this is how a
        user who deleted the bot / their account registers again with new
        credentials).
      * a phone already owned by a *different* registered user -> rejected.
    The welcome bonus itself is granted exactly once per identity, when the
    bot first stores the full name — /api/register never double-grants it.
    """
    data = request.get_json(silent=True) or {}
    user_id = _user_id_from_request()
    if user_id is None:
        return jsonify({"error": "Missing or invalid user_id / init_data"}), 400
    room = _room_from_request()
    phone = (data.get("phone") or "").strip()
    if not phone:
        return jsonify({"error": "A phone number is required to open a wallet."}), 400

    existing = db.get_player(user_id)
    if not existing or not (existing.get("full_name") or "").strip():
        # name onboarding has not been completed in the bot chat
        return jsonify({
            "error": "Please enter your full name in the bot chat first — "
                     "send /start to the bot and type your name when asked."
        }), 400

    other = db.get_player_by_phone(phone)
    if other and other["user_id"] != user_id:
        return jsonify({
            "error": "This phone number is already registered to another account."
        }), 409

    if existing.get("phone") and existing["phone"] != phone:
        # new wallet credentials -> wipe the old account, keep the identity
        # name, and start fresh with a new welcome bonus
        name = existing["full_name"]
        db.delete_player(user_id)
        db.create_player(user_id, name, credit=0)
        db.update_profile(user_id, full_name=name, phone=phone, registered=True)
        db.set_credit(user_id, config.NEW_PLAYER_CREDIT)
    else:
        db.update_profile(user_id, phone=phone, registered=True)
    # log the activity
    try:
        reg_name = (existing.get('full_name') or player.get('full_name') or '') or f'User_{user_id}'
        db.log_activity('player_registered', user_id,
                       f'{reg_name} registered with phone {phone}')
    except Exception:
        pass
    return jsonify({"ok": True, "user": _user_payload(user_id, room)})


@app.route("/api/profile", methods=["POST"])
def api_update_profile():
    """User edits their own profile (Settings -> Profile).

    At least one of the two editable fields must be present:
      * full_name — the display identity (collected once by the bot, editable
        here on purpose, never re-asked automatically at /start).
      * phone     — the wallet account number; editable here too. A phone
        already owned by a *different* registered user is rejected, matching
        the /api/register duplicate rule.
    """
    data = request.get_json(silent=True) or {}
    user_id = _user_id_from_request()
    if user_id is None:
        return jsonify({"error": "Missing or invalid user_id / init_data"}), 400
    room = _room_from_request()
    full_name = (data.get("full_name") or "").strip() \
        if data.get("full_name") is not None else None
    phone = (data.get("phone") or "").strip() \
        if data.get("phone") is not None else None
    if full_name is None and phone is None:
        return jsonify({"error": "Nothing to update."}), 400
    if full_name is not None:
        if not full_name:
            return jsonify({"error": "Please enter your full name."}), 400
        if len(full_name) > 60:
            return jsonify({"error": "Name is too long (max 60 characters)."}), 400
    if phone is not None:
        if not phone:
            return jsonify({"error": "A phone number is required (used as your wallet account)."}), 400
        if len(phone) > 30:
            return jsonify({"error": "Phone number is too long."}), 400
        other = db.get_player_by_phone(phone)
        if other and other["user_id"] != user_id:
            return jsonify({
                "error": "This phone number is already registered to another account."
            }), 409
    db.update_profile(user_id, full_name=full_name, phone=phone)
    return jsonify({"ok": True, "user": _user_payload(user_id, room)})


@app.route("/api/delete-account", methods=["POST"])
def api_delete_account():
    """User self-service: delete their own account (Settings -> Profile)."""
    data = request.get_json(silent=True) or {}
    user_id = _user_id_from_request()
    if user_id is None:
        return jsonify({"error": "Missing or invalid user_id / init_data"}), 400
    if not data.get("confirm"):
        return jsonify({"error": "Confirmation required."}), 400
    db.delete_player(user_id)
    return jsonify({"ok": True})


@app.route("/api/transactions")
def api_transactions():
    """The caller's own wallet requests."""
    user_id = _user_id_from_request()
    if user_id is None:
        return jsonify({"error": "Missing or invalid user_id / init_data"}), 400
    return jsonify({"transactions": db.get_user_transactions(user_id)})


@app.route("/api/transactions", methods=["POST"])
def api_create_transaction():
    """User submits a deposit (with the wallet transaction number) or withdraw."""
    data = request.get_json(silent=True) or {}
    user_id = _user_id_from_request()
    if user_id is None:
        return jsonify({"error": "Missing or invalid user_id / init_data"}), 400
    player = db.get_player(user_id)
    if not player or not player.get("is_registered"):
        return jsonify({"error": "Register first."}), 400
    type_ = (data.get("type") or "").strip().lower()
    if type_ not in ("deposit", "withdraw"):
        return jsonify({"error": "type must be deposit or withdraw"}), 400
    try:
        amount = int(data.get("amount"))
    except (TypeError, ValueError):
        return jsonify({"error": "Invalid amount."}), 400
    if amount <= 0:
        return jsonify({"error": "Amount must be positive."}), 400
    if amount > 1_000_000:
        return jsonify({"error": "Amount is too large."}), 400
    tx_id = (data.get("tx_id") or "").strip()
    account = None
    if type_ == "deposit":
        # a deposit MUST name the active payment account the user paid into
        if not tx_id:
            return jsonify({"error": "Please enter the transaction number from your wallet app."}), 400
        if len(tx_id) > 100:
            return jsonify({"error": "Transaction number looks too long."}), 400
        raw_acc = data.get("payment_account_id")
        try:
            acc_id = int(raw_acc) if raw_acc not in (None, "") else None
        except (TypeError, ValueError):
            return jsonify({"error": "Please select one of the payment accounts."}), 400
        account = db.get_payment_account(acc_id) if acc_id else None
        if not account or not account.get("is_active"):
            return jsonify({"error": "Please select one of the active payment accounts."}), 400
        # only ONLINE admins' accounts can be paid into — the account shown in
        # Settings is always the online admin with the most credit, and an
        # account whose owner just went offline is no longer selectable
        owner_id = account.get("admin_id")
        if not owner_id or not db.is_admin_online(owner_id):
            return jsonify({
                "error": "This payment account is not available right now — "
                         "its admin is offline. Please use the account shown "
                         "in Settings."
            }), 400
    if type_ == "withdraw":
        if amount < config.MIN_WITHDRAWAL:
            return jsonify({"error": f"Minimum withdrawal is {config.MIN_WITHDRAWAL} {config.APP_CURRENCY}."}), 400
        # the payout goes to the account details the user provides — all three
        # are required (account name / holder's name / account number), so the
        # admin knows exactly where to send the money.
        if db.get_credit(user_id) < amount:
            return jsonify({"error": "Insufficient balance for this withdrawal."}), 400
        wd_account_name = (data.get("account_name") or "").strip()
        wd_account_holder = (data.get("account_holder") or "").strip()
        wd_account_number = (data.get("account_number") or "").strip()
        if not wd_account_name:
            return jsonify({"error": "Please enter the account name (TeleBirr, CBE, CBB…)."}), 400
        if len(wd_account_name) > 60:
            return jsonify({"error": "Account name is too long."}), 400
        if not wd_account_holder:
            return jsonify({"error": "Please enter the account holder's name."}), 400
        if len(wd_account_holder) > 60:
            return jsonify({"error": "Account holder's name is too long."}), 400
        if not wd_account_number:
            return jsonify({"error": "Please enter the account number to withdraw to."}), 400
        if len(wd_account_number) > 60:
            return jsonify({"error": "Account number is too long."}), 400
    row_id = db.add_transaction(
        user_id, type_, amount, tx_id or None, phone=player.get("phone"),
        # full name + account details are snapshotted onto the record so the
        # admin can identify the payer and later edits never corrupt history.
        # For a DEPOSIT the account is the admin's payment account the user
        # paid into; for a WITHDRAW it is the destination the user provided.
        user_name=player.get("full_name") or player.get("username"),
        account_id=(account or {}).get("id"),
        provider=(account or {}).get("provider") if type_ == "deposit" else wd_account_name,
        account_number=(account or {}).get("account_number") if type_ == "deposit" else wd_account_number,
        account_holder=(account or {}).get("account_name") if type_ == "deposit" else wd_account_holder,
    )
    # log the activity
    try:
        who = player.get("full_name") or player.get("username") or str(user_id)
        label = 'Deposit' if type_ == 'deposit' else 'Withdrawal'
        db.log_activity(f'{type_}_request', user_id,
                       f'{label}: {amount} {config.APP_CURRENCY} by {who}')
    except Exception:
        pass
    # alert the right admin(s) in Telegram — high priority, so nothing sits
    # unreviewed: a DEPOSIT goes to the admin who owns the paid-in account
    # (only they can approve it and it consumes THEIR credit); a WITHDRAW goes
    # to every admin (any of them can pay it out).
    try:
        from bot import notify_admins, notify_user
        label = "WITHDRAW" if type_ == "withdraw" else "DEPOSIT"
        who = str(player.get("full_name") or player.get("username") or user_id)
        details = tx_id or ""
        if type_ == "withdraw":
            details = wd_account_name + " | " + wd_account_holder + " | " + wd_account_number
        lines = ["🚨 NEW " + label + " REQUEST",
                 "User: " + who,
                 "Amount: " + str(amount) + " " + config.APP_CURRENCY]
        if details:
            lines.append("Details: " + details)
        if type_ == "deposit" and account and account.get("admin_id"):
            owner_id = account["admin_id"]
            owner_online = db.is_admin_online(owner_id)
            owner_credit = db.get_credit(owner_id)
            if owner_online and owner_credit >= amount:
                # admin is online and has enough credit — notify them
                notify_user(owner_id, lines)
            else:
                # admin offline or insufficient credit — HIGH PRIORITY alert to super admin
                alert_lines = ["🚨⚠️ HIGH PRIORITY: No admin available for this transaction!",
                               "User: " + who,
                               "Amount: " + str(amount) + " " + config.APP_CURRENCY,
                               "Bank: " + str((account or {}).get("provider", "?"))]
                if not owner_online:
                    alert_lines.append("Reason: Admin offline")
                else:
                    alert_lines.append("Reason: Admin has insufficient credit (" + str(owner_credit) + " ETB)")
                alert_lines.append("Please handle this transaction manually.")
                for sa_id in config.SUPER_ADMIN_IDS:
                    notify_user(sa_id, alert_lines)
        else:
            notify_admins(lines)
    except Exception:
        pass  # notifications must never break the request
    return jsonify({"ok": True, "id": row_id,
                    "transaction": db.get_transaction(row_id)})


@app.route("/api/game-state")
def api_game_state():
    user_id = _user_id_from_request()
    if user_id is None:
        return jsonify({"error": "Missing or invalid user_id / init_data"}), 400
    room = _room_from_request()
    return jsonify({**_state_payload(user_id, room), "user": _user_payload(user_id, room)})


@app.route("/api/spectate")
def api_spectate():
    """Return a random other player's card for spectating.

    If spectate_user_id is provided, re-fetch that same player's card
    (so the spectator stays on the same player across refreshes).
    Otherwise, pick a new random player.
    """
    user_id = _user_id_from_request()
    if user_id is None:
        return jsonify({"error": "Missing or invalid user_id / init_data"}), 400
    room = _room_from_request()
    state = db.get_game_state(room)
    if state.get("phase") != "playing":
        return jsonify({"error": "Spectating only available during gameplay"}), 400
    # Get all selections for this room, excluding the current user
    all_selections = db.get_all_selections(room)
    other_selections = [s for s in all_selections if s["user_id"] != user_id]
    if not other_selections:
        return jsonify({"error": "No other players to spectate"}), 404
    # If a specific player was requested, stick with them
    spectate_id = request.args.get('spectate_user_id', type=int)
    if spectate_id:
        pinned = [s for s in other_selections if s["user_id"] == spectate_id]
        if pinned:
            pick = pinned[0]
        else:
            # Target player left or has no cards — pick random
            import random
            pick = random.choice(other_selections)
    else:
        import random
        pick = random.choice(other_selections)
    card_numbers = db.get_card(pick["card_id"])
    player = db.get_player(pick["user_id"]) or {}
    return jsonify({
        "card_id": pick["card_id"],
        "numbers": card_numbers,
        "player_name": player.get("full_name") or player.get("username") or f"Player_{pick['user_id']}",
        "bet_amount": pick.get("bet_amount", 0),
        "spectate_user_id": pick["user_id"],
    })


@app.route("/api/cards")
def api_cards():
    user_id = _user_id_from_request()
    if user_id is None:
        return jsonify({"error": "Missing or invalid user_id / init_data"}), 400
    room = _room_from_request()
    # one pass over the room's selections instead of scanning them per card
    taken = {sel["card_id"]: sel["user_id"] for sel in db.get_all_selections(room)}
    cards = [_card_payload(cid, user_id, taken) for cid in db.get_all_card_ids()]
    return jsonify({"cards": cards, "total": len(cards),
                    "max_cards": config.MAX_CARDS_PER_PLAYER,
                    "room": room})


@app.route("/api/select-card", methods=["POST"])
def api_select_card():
    data = request.get_json(silent=True) or {}
    user_id = _user_id_from_request()
    card_id = data.get("card_id")
    if user_id is None or not card_id:
        return jsonify({"error": "user_id and card_id are required"}), 400
    room = _room_from_request()
    state = db.get_game_state(room)
    if state.get("phase") != "preparation":
        return jsonify({"error": "Selection is closed — the round already started."}), 400
    selections = db.get_user_selections(user_id, room)
    if len(selections) >= config.MAX_CARDS_PER_PLAYER:
        return jsonify({"error": f"You can hold at most {config.MAX_CARDS_PER_PLAYER} cards."}), 400
    if db.is_card_taken(card_id, room):
        return jsonify({"error": "That card is already taken."}), 400
    if not db.get_card(card_id):
        return jsonify({"error": "Unknown card."}), 400
    # the bet is FIXED per room (30 / 50 / 100) — any bet_amount from the
    # client is ignored; there is no bet input anymore
    bet = room
    credit = db.get_credit(user_id)
    if credit < bet:
        return jsonify({"error": f"Insufficient credit — {bet} ETB needed for this room."}), 400
    inserted = db.select_card(user_id, card_id, bet, room)
    if not inserted:
        return jsonify({"error": "That card is already taken."}), 400
    db.update_credit(user_id, -bet)
    return jsonify({"ok": True, "user": _user_payload(user_id, room)})


@app.route("/api/deselect-card", methods=["POST"])
def api_deselect_card():
    data = request.get_json(silent=True) or {}
    user_id = _user_id_from_request()
    card_id = data.get("card_id")
    if user_id is None or not card_id:
        return jsonify({"error": "user_id and card_id are required"}), 400
    room = _room_from_request()
    state = db.get_game_state(room)
    if state.get("phase") != "preparation":
        return jsonify({"error": "The round already started."}), 400
    for sel in db.get_user_selections(user_id, room):
        if sel["card_id"] == card_id:
            db.update_credit(user_id, sel["bet_amount"])  # refund
            db.deselect_card(user_id, card_id)
            return jsonify({"ok": True, "user": _user_payload(user_id, room)})
    return jsonify({"error": "Card not selected."}), 400


@app.route("/api/quick-play", methods=["POST"])
def api_quick_play():
    data = request.get_json(silent=True) or {}
    user_id = _user_id_from_request()
    if user_id is None:
        return jsonify({"error": "Missing user_id"}), 400
    room = _room_from_request()
    state = db.get_game_state(room)
    if state.get("phase") != "preparation":
        return jsonify({"error": "The round already started."}), 400
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
    return jsonify({"ok": True, "chosen": chosen, "user": _user_payload(user_id, room)})


@app.route("/api/claim-bingo", methods=["POST"])
def api_claim_bingo():
    data = request.get_json(silent=True) or {}
    user_id = _user_id_from_request()
    if user_id is None:
        return jsonify({"error": "Missing user_id"}), 400
    room = _room_from_request()
    result = loop.claim_bingo(user_id, data.get("card_id"), room)
    if result["ok"]:
        return jsonify({"ok": True, "winner": result["winner"],
                        "eliminated": False, "user": _user_payload(user_id, room)})
    body = {"ok": False, "message": result["message"]}
    if result.get("eliminated"):
        body["eliminated"] = True  # lets the Mini App show the elimination modal
    return jsonify(body), 409


@app.route("/api/history")
def api_history():
    user_id = _user_id_from_request()
    if user_id is None:
        return jsonify({"error": "Missing user_id"}), 400
    return jsonify({"history": db.get_user_history(user_id)})


@app.route("/api/leaderboard")
def api_leaderboard():
    return jsonify({"players": db.top_players(20)})


# ------------------------------------------------------------------- admin API
def _require_admin() -> Optional[int]:
    """Resolve admin_id from the JSON body OR a query param (GET endpoints)."""
    data = request.get_json(silent=True) or {}
    admin_id = data.get("admin_id") or request.args.get("admin_id")
    try:
        admin_id = int(admin_id) if admin_id is not None else None
    except (TypeError, ValueError):
        admin_id = None
    if admin_id is None or not db.is_admin(admin_id):
        return None
    _touch_admin_if_admin(admin_id)
    return admin_id


def _require_super_admin() -> Optional[int]:
    """Only a SUPER ADMIN passes this guard.

    A super admin is identified purely by membership in SUPER_ADMIN_IDS
    (from .env). They do NOT need to be in ADMIN_IDS or have is_admin=1
    in the DB — super-admin status is the highest privilege and grants
    access to every account, every transaction log, admin credits, and
    wallet appeals.
    """
    data = request.get_json(silent=True) or {}
    admin_id = data.get("admin_id") or request.args.get("admin_id")
    try:
        admin_id = int(admin_id) if admin_id is not None else None
    except (TypeError, ValueError):
        admin_id = None
    if admin_id is None or admin_id not in config.SUPER_ADMIN_IDS:
        return None
    _touch_admin_if_admin(admin_id)
    return admin_id


@app.route("/api/admin/credit", methods=["POST"])
def api_admin_credit():
    if _require_admin() is None:
        return jsonify({"error": "Unauthorized"}), 403
    data = request.get_json(silent=True) or {}
    target = data.get("user_id")
    amount = data.get("amount")
    try:
        target, amount = int(target), int(amount)
    except (TypeError, ValueError):
        return jsonify({"error": "user_id and amount are required"}), 400
    # the target's credit changes — the admin's own balance is never touched
    db.create_player(target, f"Player_{target}", credit=0)
    db.update_credit(target, amount)
    # log the activity
    try:
        target_player = db.get_player(target) or {}
        target_name = target_player.get('full_name') or target_player.get('username') or str(target)
        db.log_activity('admin_credit_adjustment', admin_id,
                       f'{amount:+d} {config.APP_CURRENCY} to {target_name} (ID: {target})')
    except Exception:
        pass
    return jsonify({"ok": True, "user_id": target, "credit": db.get_credit(target)})


@app.route("/api/admin/force-start", methods=["POST"])
def api_admin_force_start():
    if _require_admin() is None:
        return jsonify({"error": "Unauthorized"}), 403
    return jsonify(loop.force_start(_room_from_request()))


@app.route("/api/admin/force-call", methods=["POST"])
def api_admin_force_call():
    if _require_admin() is None:
        return jsonify({"error": "Unauthorized"}), 403
    return jsonify(loop.force_call(_room_from_request()))


@app.route("/api/admin/reset", methods=["POST"])
def api_admin_reset():
    if _require_admin() is None:
        return jsonify({"error": "Unauthorized"}), 403
    loop.reset_round(_room_from_request())
    return jsonify({"ok": True})


@app.route("/api/admin/bots/add", methods=["POST"])
def api_admin_bots_add():
    if _require_admin() is None:
        return jsonify({"error": "Unauthorized"}), 403
    return jsonify(loop.add_bots(_room_from_request()))


@app.route("/api/admin/bots/toggle", methods=["POST"])
def api_admin_bots_toggle():
    if _require_admin() is None:
        return jsonify({"error": "Unauthorized"}), 403
    data = request.get_json(silent=True) or {}
    return jsonify(loop.toggle_bots(data.get("enabled")))


@app.route("/api/admin/bots")
def api_admin_bots():
    admin_id = request.args.get("admin_id")
    try:
        admin_id = int(admin_id) if admin_id is not None else None
    except (TypeError, ValueError):
        admin_id = None
    if admin_id is None or not db.is_admin(admin_id):
        return jsonify({"error": "Unauthorized"}), 403
    _touch_admin_if_admin(admin_id)
    room = _room_from_request()
    return jsonify({"enabled": db.get_bots_enabled(room),
                    "count": db.bot_count(),
                    "breakdown": logic.player_breakdown(room),
                    "room": room})


@app.route("/api/admin/stats")
def api_admin_stats():
    admin_id = request.args.get("admin_id")
    try:
        admin_id = int(admin_id) if admin_id is not None else None
    except (TypeError, ValueError):
        admin_id = None
    if admin_id is None or not db.is_admin(admin_id):
        return jsonify({"error": "Unauthorized"}), 403
    _touch_admin_if_admin(admin_id)
    return jsonify({"stats": db.game_stats(), "recent": db.recent_games(8)})


@app.route("/api/admin/users")
def api_admin_users():
    """Full user list (name, phone, credit, history) for the admin panel."""
    if _require_admin() is None:
        return jsonify({"error": "Unauthorized"}), 403
    return jsonify({"users": db.get_all_players()})


@app.route("/api/admin/users/delete", methods=["POST"])
def api_admin_user_delete():
    """Admin deletes a user account entirely."""
    if _require_admin() is None:
        return jsonify({"error": "Unauthorized"}), 403
    data = request.get_json(silent=True) or {}
    try:
        target = int(data.get("user_id"))
    except (TypeError, ValueError):
        return jsonify({"error": "user_id required"}), 400
    if target <= 0:
        return jsonify({"error": "Invalid user id"}), 400
    db.delete_player(target)
    try:
        db.log_activity('user_deleted', admin_id, f'Deleted user {target}')
    except Exception:
        pass
    return jsonify({"ok": True, "user_id": target})


@app.route("/api/admin/transactions")
def api_admin_transactions():
    """Wallet requests visible to THIS admin only:
    - Deposits paid into THIS admin's own account(s)
    - Transactions this admin has personally reviewed (approved/rejected)
    - Pending transactions that need attention
    Super admins see ALL transactions via their own endpoint.
    """
    admin_id = _require_admin()
    if admin_id is None:
        return jsonify({"error": "Unauthorized"}), 403
    txs = db.get_all_transactions()
    # Collect the admin's own payment account IDs
    own_acc_ids = set()
    for acc in db.get_payment_accounts():
        if acc.get("admin_id") == admin_id:
            own_acc_ids.add(acc["id"])
    filtered = []
    for tx in txs:
        # 1. Transactions this admin personally reviewed
        if tx.get("reviewed_by") == admin_id:
            filtered.append(tx)
            continue
        # 2. Deposits paid into THIS admin's own account (pending or not)
        acc_id = tx.get("payment_account_id")
        if acc_id and acc_id in own_acc_ids:
            filtered.append(tx)
            continue
        # 3. Withdrawals pending that any admin can handle
        if tx["type"] == "withdraw" and tx["status"] == "pending":
            filtered.append(tx)
            continue
    for tx in filtered:
        # the row already snapshots user_name/provider/account — only fill
        # gaps for legacy rows created before the snapshot columns existed
        if not tx.get("user_name"):
            p = db.get_player(tx["user_id"]) or {}
            tx["user_name"] = p.get("full_name") or p.get("username") or f"#{tx['user_id']}"
        if tx.get("payment_account_id") and not tx.get("provider"):
            acc = db.get_payment_account(tx["payment_account_id"])
            if acc:
                tx["provider"] = acc["provider"]
                tx["account_number"] = acc["account_number"]
                tx["account_holder"] = acc["account_name"]
    return jsonify({"transactions": filtered})


def _apply_review(tx: dict, action: str, reviewer_id: int):
    """Move the money for an approved deposit/withdraw.

    Admins use their OWN player credit — no separate admin_credit float.
    * Approving a DEPOSIT credits the user the full amount.
    * Approving a WITHDRAW debits the user the full amount.
    """
    if action == "approve":
        if tx["type"] == "deposit":
            db.update_credit(tx["user_id"], tx["amount"])
        else:  # withdraw: take the money back (must be affordable)
            if db.get_credit(tx["user_id"]) < tx["amount"]:
                return False, "User has insufficient balance for this withdrawal."
            db.update_credit(tx["user_id"], -tx["amount"])
    return True, None


@app.route("/api/admin/transactions/review", methods=["POST"])
def api_admin_transaction_review():
    """Approve/reject a wallet request; approving moves the money AND the
    account-owner admin's credit (see _apply_review)."""
    admin_id = _require_admin()
    if admin_id is None:
        return jsonify({"error": "Unauthorized"}), 403
    data = request.get_json(silent=True) or {}
    try:
        tx_id = int(data.get("id"))
    except (TypeError, ValueError):
        return jsonify({"error": "id required"}), 400
    action = (data.get("action") or "").strip().lower()
    if action not in ("approve", "reject"):
        return jsonify({"error": "action must be approve or reject"}), 400
    tx = db.get_transaction(tx_id)
    if not tx:
        return jsonify({"error": "Transaction not found"}), 404
    if tx["status"] != "pending":
        return jsonify({"error": "Transaction already reviewed"}), 400
    if action == "approve":
        # Admins can only approve deposits paid into THEIR OWN account.
        # Withdrawals can be approved by any admin (the money comes from the
        # user's balance, not the admin's).
        if tx["type"] == "deposit" and tx.get("payment_account_id"):
            acc = db.get_payment_account(tx["payment_account_id"])
            if acc and acc.get("admin_id") and acc["admin_id"] != admin_id:
                return jsonify({"error": "You can only approve deposits paid into your own account."}), 403
        ok, err = _apply_review(tx, "approve", admin_id)
        if not ok:
            return jsonify({"error": err}), 400
    db.review_transaction(tx_id, "approved" if action == "approve" else "rejected",
                          reviewed_by=admin_id)
    # log the activity
    try:
        tx = db.get_transaction(tx_id)
        tx_user = (tx or {}).get('user_name', str((tx or {}).get('user_id', '?')))
        db.log_activity(f'transaction_{action}ed', admin_id,
                       f'{action.title()} {tx.get("type","?")} {tx.get("amount","?")} {config.APP_CURRENCY} by {tx_user}')
    except Exception:
        pass
    updated = db.get_transaction(tx_id)
    updated["credit"] = db.get_credit(tx["user_id"])
    return jsonify({"ok": True, "transaction": updated})


# ------------------------------------------------- payment accounts (admin)
@app.route("/api/admin/accounts")
def api_admin_accounts():
    """All payment accounts (active + inactive) for the admin panel."""
    if _require_admin() is None:
        return jsonify({"error": "Unauthorized"}), 403
    return jsonify({"accounts": [_account_payload(a) for a in db.get_payment_accounts()]})


@app.route("/api/admin/accounts", methods=["POST"])
def api_admin_account_add():
    """Add a payment account (TeleBirr / CBE / CBB / bank ...).

    The account belongs to the ADMIN who creates it — that admin's credit is
    what gets consumed when deposits into this account are approved, and the
    account is only shown to users while that admin is ONLINE.
    """
    admin_id = _require_admin()
    if admin_id is None:
        return jsonify({"error": "Unauthorized"}), 403
    data = request.get_json(silent=True) or {}
    provider = (data.get("provider") or "").strip()
    account_name = (data.get("account_name") or "").strip()
    account_number = (data.get("account_number") or "").strip()
    if not provider or not account_name or not account_number:
        return jsonify({"error": "Provider, account name and account number are required."}), 400
    if len(account_number) > 60:
        return jsonify({"error": "Account number is too long."}), 400
    is_active = data.get("is_active") not in (False, 0, "0", "false", "False")
    account_id = db.add_payment_account(provider, account_name, account_number,
                                        is_active, admin_id=admin_id)
    return jsonify({"ok": True, "account": _account_payload(db.get_payment_account(account_id))})


@app.route("/api/admin/accounts/update", methods=["POST"])
def api_admin_account_update():
    """Edit a payment account and/or toggle its active status."""
    if _require_admin() is None:
        return jsonify({"error": "Unauthorized"}), 403
    data = request.get_json(silent=True) or {}
    try:
        account_id = int(data.get("id"))
    except (TypeError, ValueError):
        return jsonify({"error": "id required"}), 400
    if not db.get_payment_account(account_id):
        return jsonify({"error": "Account not found"}), 404
    fields = {}
    if data.get("provider") is not None:
        fields["provider"] = (data.get("provider") or "").strip()
    if data.get("account_name") is not None:
        fields["account_name"] = (data.get("account_name") or "").strip()
    if data.get("account_number") is not None:
        fields["account_number"] = (data.get("account_number") or "").strip()
    if any(not v for v in fields.values()):
        return jsonify({"error": "Provider, account name and account number can't be empty."}), 400
    if data.get("is_active") is not None:
        fields["is_active"] = data.get("is_active") not in (False, 0, "0", "false", "False")
    db.update_payment_account(account_id, **fields)
    return jsonify({"ok": True, "account": _account_payload(db.get_payment_account(account_id))})


@app.route("/api/admin/accounts/delete", methods=["POST"])
def api_admin_account_delete():
    """Delete a payment account. Historical transactions keep their snapshot."""
    if _require_admin() is None:
        return jsonify({"error": "Unauthorized"}), 403
    data = request.get_json(silent=True) or {}
    try:
        account_id = int(data.get("id"))
    except (TypeError, ValueError):
        return jsonify({"error": "id required"}), 400
    db.delete_payment_account(account_id)
    return jsonify({"ok": True})


# ------------------------------------------------------- user appeals
@app.route("/api/appeals")
def api_my_appeals():
    """The caller's own wallet appeals."""
    user_id = _user_id_from_request()
    if user_id is None:
        return jsonify({"error": "Missing or invalid user_id / init_data"}), 400
    return jsonify({"appeals": db.get_user_appeals(user_id)})


@app.route("/api/appeals", methods=["POST"])
def api_file_appeal():
    """A user appeals a DEPOSIT the admin never approved (they sent the money
    for real). The SUPER ADMIN resolves the appeal."""
    data = request.get_json(silent=True) or {}
    user_id = _user_id_from_request()
    if user_id is None:
        return jsonify({"error": "Missing or invalid user_id / init_data"}), 400
    try:
        tx_id = int(data.get("transaction_id"))
    except (TypeError, ValueError):
        return jsonify({"error": "transaction_id required"}), 400
    reason = (data.get("reason") or "").strip()
    if not reason:
        return jsonify({"error": "Please describe your appeal."}), 400
    if len(reason) > 500:
        return jsonify({"error": "Appeal reason is too long (max 500 characters)."}), 400
    tx = db.get_transaction(tx_id)
    if not tx or tx["user_id"] != user_id:
        return jsonify({"error": "Transaction not found."}), 404
    if tx["type"] != "deposit":
        return jsonify({"error": "Only deposits can be appealed."}), 400
    if tx["status"] not in ("pending", "rejected"):
        return jsonify({"error": "This transaction is already finished."}), 400
    existing = [a for a in db.get_user_appeals(user_id)
                if a["transaction_id"] == tx_id and a["status"] == "pending"]
    if existing:
        return jsonify({"error": "You already have a pending appeal for this deposit."}), 400
    appeal_id = db.add_appeal(user_id, tx_id, reason)
    # log the activity + alert EVERY super admin
    try:
        who = str(tx.get("user_name") or user_id)
        db.log_activity('appeal_filed', user_id,
                       f'Appeal for {tx["amount"]} {config.APP_CURRENCY} deposit by {who}: {reason}')
        from bot import notify_user
        appeal_lines = [
            "🚨 NEW WALLET APPEAL",
            "User: " + who,
            "Deposit: " + str(tx["amount"]) + " " + config.APP_CURRENCY,
            "Reason: " + reason,
        ]
        for sa_id in config.SUPER_ADMIN_IDS:
            notify_user(sa_id, appeal_lines)
    except Exception:
        pass
    return jsonify({"ok": True, "appeal": db.get_appeal(appeal_id)})


# ------------------------------------------------------- super admin console
@app.route("/api/superadmin/users")
def api_superadmin_users():
    """Every account — admins AND users — with credits, admin credit, online
    status and history, so the super admin controls everything."""
    if _require_super_admin() is None:
        return jsonify({"error": "Unauthorized"}), 403
    users = db.get_all_players()
    for u in users:
        u["online"] = db.is_admin_online(u["user_id"])
        u["env_admin"] = u["user_id"] in config.ADMIN_IDS
    return jsonify({"users": users})


@app.route("/api/superadmin/admin", methods=["POST"])
def api_superadmin_set_admin():
    """The super admin PROMOTES a user to admin (or demotes a promoted admin).

    Promoted admins get the full 🛠 Admin panel, can add their own payment
    accounts and approve wallet requests with their own admin credit. Core
    admins (config.ADMIN_IDS) cannot be demoted here — they are defined in
    .env.
    """
    if _require_super_admin() is None:
        return jsonify({"error": "Unauthorized"}), 403
    data = request.get_json(silent=True) or {}
    try:
        target = int(data.get("user_id"))
    except (TypeError, ValueError):
        return jsonify({"error": "user_id required"}), 400
    is_admin = data.get("is_admin") not in (False, 0, "0", "false", "False")
    if not is_admin and target in config.ADMIN_IDS:
        return jsonify({
            "error": "Core admins are defined in .env (ADMIN_IDS) and cannot "
                     "be demoted from the panel."
        }), 400
    db.create_player(target, f"Player_{target}", credit=0)
    db.set_admin(target, is_admin)
    # log the activity
    try:
        target_player = db.get_player(target) or {}
        target_name = target_player.get('full_name') or target_player.get('username') or str(target)
        verb = 'promoted' if is_admin else 'demoted'
        db.log_activity('admin_role_change', target,
                       f'{target_name} (ID: {target}) {verb} to admin')
    except Exception:
        pass
    # when promoting, touch the user so they appear online immediately
    if is_admin:
        db.touch_admin(target)
    return jsonify({"ok": True, "user_id": target, "is_admin": bool(is_admin),
                    "is_super_admin": target in config.SUPER_ADMIN_IDS})


@app.route("/api/superadmin/credit", methods=["POST"])
def api_superadmin_credit():
    """The super admin manually increases/decreases ANY account's credit:
    `target` "user" -> the player wallet, "admin" -> the admin credit float
    (selling / buying back credit to admins)."""
    if _require_super_admin() is None:
        return jsonify({"error": "Unauthorized"}), 403
    data = request.get_json(silent=True) or {}
    try:
        target = int(data.get("user_id"))
        amount = int(data.get("amount"))
    except (TypeError, ValueError):
        return jsonify({"error": "user_id and amount are required"}), 400
    target_kind = (data.get("target") or "user").strip().lower()
    if target_kind not in ("user", "admin"):
        return jsonify({"error": "target must be 'user' or 'admin'"}), 400
    db.create_player(target, f"Player_{target}", credit=0)
    # all credit is unified — admin and user credit are the same field
    db.update_credit(target, amount)
    # log the activity
    try:
        target_player = db.get_player(target) or {}
        target_name = target_player.get('full_name') or target_player.get('username') or str(target)
        db.log_activity('manual_credit_adjustment', target,
                       f'{amount:+d} {config.APP_CURRENCY} (target: {target_name})')
        from bot import notify_admins
        notify_admins(['💰 CREDIT ADJUSTMENT',
                      f'Target: {target_name} (ID: {target})',
                      f'Amount: {amount:+d} {config.APP_CURRENCY}'])
    except Exception:
        pass
    return jsonify({
        "ok": True, "user_id": target, "target": target_kind,
        "credit": db.get_credit(target),
    })


@app.route("/api/superadmin/edit-user", methods=["POST"])
def api_superadmin_edit_user():
    """Super admin can edit ANY user's profile details (name, phone).

    Works for both regular players and admins — full control.
    """
    if _require_super_admin() is None:
        return jsonify({"error": "Unauthorized"}), 403
    data = request.get_json(silent=True) or {}
    try:
        target = int(data.get("user_id"))
    except (TypeError, ValueError):
        return jsonify({"error": "user_id is required"}), 400
    full_name = data.get("full_name")
    phone = data.get("phone")
    credit = data.get("credit")
    if full_name is not None:
        full_name = str(full_name).strip()[:60] or None
    if phone is not None:
        phone = str(phone).strip()[:20] or None
    if credit is not None:
        try:
            credit = int(credit)
        except (TypeError, ValueError):
            return jsonify({"error": "credit must be a number"}), 400
        db.update_credit(target, credit - db.get_credit(target))
    db.create_player(target, f"Player_{target}", credit=0)  # ensure row exists
    db.update_profile(target, full_name=full_name, phone=phone)
    player = db.get_player(target)
    try:
        target_name = (player or {}).get('full_name') or (player or {}).get('username') or str(target)
        details = []
        if full_name:
            details.append(f'name={full_name}')
        if phone:
            details.append(f'phone={phone}')
        if credit is not None:
            details.append(f'credit={credit}')
        db.log_activity('superadmin_edited_user', target,
                       f'Edited {target_name} ({target}): {"; ".join(details)}')
    except Exception:
        pass
    return jsonify({
        "ok": True, "user_id": target,
        "full_name": (player or {}).get('full_name'),
        "phone": (player or {}).get('phone'),
        "credit": db.get_credit(target),
    })


@app.route("/api/superadmin/transactions")
def api_superadmin_transactions():
    """Every wallet log (all deposits/withdraws, any status) with the owning
    admin's credit impact for deposits."""
    if _require_super_admin() is None:
        return jsonify({"error": "Unauthorized"}), 403
    txs = db.get_all_transactions()
    for tx in txs:
        if not tx.get("user_name"):
            p = db.get_player(tx["user_id"]) or {}
            tx["user_name"] = p.get("full_name") or p.get("username") or f"#{tx['user_id']}"
        owner = None
        if tx.get("payment_account_id"):
            acc = db.get_payment_account(tx["payment_account_id"])
            owner = (acc or {}).get("admin_id")
        tx["owner_admin_id"] = owner
        if owner:
            owner_p = db.get_player(owner) or {}
            tx["owner_admin_name"] = owner_p.get("full_name") or owner_p.get("username")
            tx["owner_admin_credit"] = owner_p.get("credit", 0)
    return jsonify({"transactions": txs})


@app.route("/api/superadmin/transactions/review", methods=["POST"])
def api_superadmin_transaction_review():
    """The super admin can review ANY pending wallet request (same money
    movement rules as the admin panel, including the owner's credit)."""
    if _require_super_admin() is None:
        return jsonify({"error": "Unauthorized"}), 403
    data = request.get_json(silent=True) or {}
    try:
        tx_id = int(data.get("id"))
    except (TypeError, ValueError):
        return jsonify({"error": "id required"}), 400
    action = (data.get("action") or "").strip().lower()
    if action not in ("approve", "reject"):
        return jsonify({"error": "action must be approve or reject"}), 400
    tx = db.get_transaction(tx_id)
    if not tx:
        return jsonify({"error": "Transaction not found"}), 404
    if tx["status"] != "pending":
        return jsonify({"error": "Transaction already reviewed"}), 400
    if action == "approve":
        ok, err = _apply_review(tx, "approve", config.SUPER_ADMIN_ID)
        if not ok:
            return jsonify({"error": err}), 400
    db.review_transaction(tx_id, "approved" if action == "approve" else "rejected",
                          reviewed_by=config.SUPER_ADMIN_ID)
    # log the activity
    try:
        tx_info = db.get_transaction(tx_id)
        tx_user = (tx_info or {}).get('user_name', str((tx_info or {}).get('user_id', '?')))
        db.log_activity(f'superadmin_{action}_transaction', config.SUPER_ADMIN_ID,
                       f'{action.title()} {tx_info.get("type","?")} {tx_info.get("amount","?")} {config.APP_CURRENCY} by {tx_user}')
    except Exception:
        pass
    updated = db.get_transaction(tx_id)
    updated["credit"] = db.get_credit(tx["user_id"])
    return jsonify({"ok": True, "transaction": updated})


# ------------------------------------------------ super admin game controls
@app.route("/api/superadmin/game/pause", methods=["POST"])
def api_superadmin_game_pause():
    """Pause the game — ball calling stops but the round stays active."""
    if _require_super_admin() is None:
        return jsonify({"error": "Unauthorized"}), 403
    room = _room_from_request()
    state = db.get_game_state(room)
    if state.get("phase") != "playing":
        return jsonify({"error": "Can only pause during playing phase."}), 400
    db.update_game_state(room, paused=1)
    try:
        db.log_activity('game_paused', config.SUPER_ADMIN_ID, f'Paused game in room {room}')
    except Exception:
        pass
    return jsonify({"ok": True, "paused": True})


@app.route("/api/superadmin/game/resume", methods=["POST"])
def api_superadmin_game_resume():
    """Resume a paused game."""
    if _require_super_admin() is None:
        return jsonify({"error": "Unauthorized"}), 403
    room = _room_from_request()
    db.update_game_state(room, paused=0)
    try:
        db.log_activity('game_resumed', config.SUPER_ADMIN_ID, f'Resumed game in room {room}')
    except Exception:
        pass
    return jsonify({"ok": True, "paused": False})


@app.route("/api/superadmin/game/stop", methods=["POST"])
def api_superadmin_game_stop():
    """Force stop the current round (no winner). Resets to preparation."""
    if _require_super_admin() is None:
        return jsonify({"error": "Unauthorized"}), 403
    room = _room_from_request()
    loop.end_round_no_winner(room)
    try:
        db.log_activity('game_stopped', config.SUPER_ADMIN_ID,
                       f'Stopped round in room {room}')
    except Exception:
        pass
    return jsonify({"ok": True})


@app.route("/api/superadmin/game/start", methods=["POST"])
def api_superadmin_game_start():
    """Force start the round from preparation."""
    if _require_super_admin() is None:
        return jsonify({"error": "Unauthorized"}), 403
    room = _room_from_request()
    result = loop.force_start(room)
    try:
        db.log_activity('game_started', config.SUPER_ADMIN_ID,
                       f'Started round in room {room}')
    except Exception:
        pass
    return jsonify(result)


@app.route("/api/superadmin/game/add-bots", methods=["POST"])
def api_superadmin_game_add_bots():
    """Manually add bots to the game."""
    if _require_super_admin() is None:
        return jsonify({"error": "Unauthorized"}), 403
    room = _room_from_request()
    return jsonify(loop.add_bots(room))


@app.route("/api/superadmin/accounts")
def api_superadmin_accounts():
    """Every payment account (all admins') with owner + online status."""
    if _require_super_admin() is None:
        return jsonify({"error": "Unauthorized"}), 403
    return jsonify({"accounts": [_account_payload(a)
                                  for a in db.get_payment_accounts()]})


@app.route("/api/superadmin/accounts/update", methods=["POST"])
def api_superadmin_account_update():
    """Super admin edits ANY account — details, active toggle, or re-assigns
    the owner admin (admin_id)."""
    if _require_super_admin() is None:
        return jsonify({"error": "Unauthorized"}), 403
    data = request.get_json(silent=True) or {}
    try:
        account_id = int(data.get("id"))
    except (TypeError, ValueError):
        return jsonify({"error": "id required"}), 400
    if not db.get_payment_account(account_id):
        return jsonify({"error": "Account not found"}), 404
    fields = {}
    if data.get("provider") is not None:
        fields["provider"] = (data.get("provider") or "").strip()
    if data.get("account_name") is not None:
        fields["account_name"] = (data.get("account_name") or "").strip()
    if data.get("account_number") is not None:
        fields["account_number"] = (data.get("account_number") or "").strip()
    if data.get("is_active") is not None:
        fields["is_active"] = data.get("is_active") not in (False, 0, "0", "false", "False")
    if data.get("admin_id") is not None:
        try:
            fields["admin_id"] = int(data.get("admin_id"))
        except (TypeError, ValueError):
            return jsonify({"error": "Invalid admin_id"}), 400
    if any(not v for k, v in fields.items()
           if k in ("provider", "account_name", "account_number")):
        return jsonify({"error": "Provider, account name and account number can't be empty."}), 400
    db.update_payment_account(account_id, **fields)
    return jsonify({"ok": True, "account": _account_payload(db.get_payment_account(account_id))})


@app.route("/api/superadmin/accounts/delete", methods=["POST"])
def api_superadmin_account_delete():
    """Super admin deletes any account. Historical transactions keep their
    snapshot."""
    if _require_super_admin() is None:
        return jsonify({"error": "Unauthorized"}), 403
    data = request.get_json(silent=True) or {}
    try:
        account_id = int(data.get("id"))
    except (TypeError, ValueError):
        return jsonify({"error": "id required"}), 400
    db.delete_payment_account(account_id)
    return jsonify({"ok": True})


@app.route("/api/superadmin/appeals")
def api_superadmin_appeals():
    """All wallet appeals (with user + transaction info) for the super admin."""
    if _require_super_admin() is None:
        return jsonify({"error": "Unauthorized"}), 403
    return jsonify({"appeals": db.get_all_appeals()})


@app.route("/api/superadmin/activity-log")
def api_superadmin_activity_log():
    """Every critical activity for the super admin activity log."""
    if _require_super_admin() is None:
        return jsonify({"error": "Unauthorized"}), 403
    return jsonify({"activities": db.get_activity_log(200)})


@app.route("/api/superadmin/house-profit")
def api_superadmin_house_profit():
    """House profit summary for the super admin."""
    if _require_super_admin() is None:
        return jsonify({"error": "Unauthorized"}), 403
    return jsonify(db.house_profit_summary())


@app.route("/api/superadmin/appeals/resolve", methods=["POST"])
def api_superadmin_appeal_resolve():
    """Resolve an appeal:
    * approve -> the deposit is approved (user credited, the account owner's
      admin credit charged at ADMIN_APPROVAL_RATE) even if the admin had
      rejected it;
    * reject  -> the appeal is dismissed with an optional resolution note.
    """
    if _require_super_admin() is None:
        return jsonify({"error": "Unauthorized"}), 403
    data = request.get_json(silent=True) or {}
    try:
        appeal_id = int(data.get("id"))
    except (TypeError, ValueError):
        return jsonify({"error": "id required"}), 400
    action = (data.get("action") or "").strip().lower()
    if action not in ("approve", "reject"):
        return jsonify({"error": "action must be approve or reject"}), 400
    resolution = (data.get("resolution") or "").strip()
    appeal = db.get_appeal(appeal_id)
    if not appeal:
        return jsonify({"error": "Appeal not found"}), 404
    if appeal["status"] != "pending":
        return jsonify({"error": "Appeal already resolved"}), 400
    tx = db.get_transaction(appeal["transaction_id"])
    if action == "approve":
        # the deposit may still be pending (admin never got to it) or rejected
        # (admin said no) — either way the user paid, so approve it now
        if tx and tx["status"] != "approved":
            ok, err = _apply_review(tx, "approve", config.SUPER_ADMIN_ID)
            if not ok:
                return jsonify({"error": err}), 400
            db.set_transaction_status(tx["id"], "approved",
                                      reviewed_by=config.SUPER_ADMIN_ID,
                                      admin_note="Approved via appeal")
        db.resolve_appeal(appeal_id, "approved",
                          resolution or "Deposit approved on appeal",
                          config.SUPER_ADMIN_ID)
        if tx:
            try:
                from bot import notify_user
                notify_user(tx["user_id"], [
                    "✅ Your appeal was APPROVED",
                    "Deposit: " + str(tx["amount"]) + " " + config.APP_CURRENCY,
                    "Your balance has been credited.",
                ])
            except Exception:
                pass
    else:
        db.resolve_appeal(appeal_id, "rejected", resolution or "Appeal dismissed",
                          config.SUPER_ADMIN_ID)
        if tx:
            try:
                from bot import notify_user
                notify_user(tx["user_id"], [
                    "❌ Your appeal was rejected",
                    "Deposit: " + str(tx["amount"]) + " " + config.APP_CURRENCY,
                    ("Note: " + resolution) if resolution else "",
                ])
            except Exception:
                pass
    # log the activity
    try:
        appeal_info = db.get_appeal(appeal_id)
        who = (appeal_info or {}).get('user_name', str((appeal_info or {}).get('user_id', '?')))
        db.log_activity(f'appeal_{action}ed', config.SUPER_ADMIN_ID,
                       f'{action.title()} appeal by {who}: {resolution or "no note"}')
    except Exception:
        pass
    return jsonify({"ok": True, "appeal": db.get_appeal(appeal_id)})


# ------------------------------------------------------- health / diagnostics
@app.route("/health")
def health_check():
    """Non-sensitive health check — reports system status without secrets.

    Safe to expose publicly; never reveals BOT_TOKEN, WEBHOOK_SECRET,
    ADMIN_IDS, database contents, player data, or credentials.
    """
    try:
        game_loop_ok = loop.scheduler.running
    except Exception:
        game_loop_ok = False
    try:
        db_ok = db.count_cards() > 0
    except Exception:
        db_ok = False
    # bot webhook status (only in webhook mode)
    bot_info = {"webhook_mode": bool(config.BOT_WEBHOOK)}
    if config.BOT_WEBHOOK:
        try:
            from bot import _webhook_app, _webhook_thread, _webhook_registered
            bot_info["thread_alive"] = bool(_webhook_thread and _webhook_thread.is_alive())
            bot_info["app_ready"] = bool(_webhook_app is not None)
            bot_info["webhook_registered"] = bool(_webhook_registered)
        except Exception:
            bot_info["error"] = "could not read bot state"
    return jsonify({
        "status": "ok" if (game_loop_ok and db_ok) else "degraded",
        "game_loop": game_loop_ok,
        "database": db_ok,
        "bot": bot_info,
    })


# ------------------------------------------------------- telegram webhook
@app.route("/webhook/<secret>", methods=["POST"])
def telegram_webhook(secret: str):
    """Telegram pushes bot updates here in webhook mode (BOT_WEBHOOK=1).

    Used on always-on hosts (PythonAnywhere) whose free tier cannot run a
    background polling process. The update is forwarded to the in-process bot
    (bot.dispatch_webhook). The secret path comes from config.WEBHOOK_SECRET,
    so only Telegram's configured URL is ever accepted; anything else gets 403.
    """
    if secret != config.WEBHOOK_SECRET:
        return ("Forbidden", 403)
    body = request.get_json(silent=True)
    if not body:
        return ("ok", 200)
    try:
        from bot import dispatch_webhook
        ok = dispatch_webhook(body)
    except Exception as exc:
        logger.error("webhook route error: %s", exc)
        return (f"webhook route error: {exc}", 500)
    # 500 makes Telegram retry — useful while the bot is still starting up
    if ok:
        return ("ok", 200)
    # include bot state in the 500 body so delivery failures are diagnosable
    # without digging through logs
    try:
        from bot import _webhook_app, _webhook_thread
        state = ("app=" + ("set" if _webhook_app else "none") +
                 " thread=" + ("alive" if _webhook_thread and _webhook_thread.is_alive() else "dead"))
    except Exception:
        state = "unknown"
    return ("webhook dispatch failed (" + state + ")", 500)


# ----------------------------------------------------------------- frontend
@app.route("/")
def index():
    index_path = os.path.join(FRONTEND_DIR, "index.html")
    if os.path.exists(index_path):
        return send_from_directory(FRONTEND_DIR, "index.html")
    return ("<h1>Bingo Mini App</h1><p>Frontend not built yet. "
            "Run <code>npm install && npm run build</code> inside the "
            "<code>frontend/</code> folder.</p>", 200)


@app.route("/<path:path>")
def static_files(path):
    file_path = os.path.join(FRONTEND_DIR, path)
    if os.path.isfile(file_path):
        return send_from_directory(FRONTEND_DIR, path)
    index_path = os.path.join(FRONTEND_DIR, "index.html")
    if os.path.exists(index_path):
        return send_from_directory(FRONTEND_DIR, "index.html")
    return ("Not found", 404)


# ----------------------------------------------------------------------- main
def main():
    seed_cards()
    logger.info("Cards in pool: %s", db.count_cards())
    loop.start()
    logger.info("Mini App server → http://%s:%s", config.SERVER_HOST, config.SERVER_PORT)
    try:
        app.run(host=config.SERVER_HOST, port=config.SERVER_PORT, debug=False,
                threaded=True, use_reloader=False)
    except KeyboardInterrupt:
        pass
    finally:
        loop.stop()


if __name__ == "__main__":
    main()
