"""
Offline API smoke test — verifies the whole Flask backend WITHOUT Telegram.

Covers: bot full-name onboarding, phone-only registration, card selection/
refund, quick-play, force start, auto number calling, winner detection +
80% payout, dynamic payout, claim-bingo verification (incl. false-BINGO
elimination), bot toggle, admin credit (target-only), payment accounts CRUD,
deposit/withdraw with account snapshots, admin review, account lifecycle,
and round announcements without round numbers.

Run:  venv\\Scripts\\python.exe api_smoke.py
"""
import asyncio
import os
import sys
import time

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

for _f in ("api_smoke.db", "api_smoke.db-wal", "api_smoke.db-shm"):
    if os.path.exists(_f):
        try:
            os.remove(_f)
        except OSError:
            pass

os.environ["DB_PATH"] = "api_smoke.db"
os.environ["PREPARATION_SECONDS"] = "60"
# the test buys cards in the 30/50/100 rooms, so the player needs enough
# credit regardless of whatever the ambient .env sets (default is only 50)
os.environ["NEW_PLAYER_CREDIT"] = "1000"

import config  # noqa: E402
import server  # noqa: E402
import bot as bot_module  # noqa: E402  (real bot handlers, tested with fakes)

COLUMNS = ["B", "I", "N", "G", "O"]
TEST_USER = 555001
OTHER_USER = 555002
BOT_USER = 777111
ADMIN = config.ADMIN_IDS[0]

client = server.app.test_client()
db, loop = server.db, server.loop  # loop.scheduler is NOT started in tests
server.seed_cards()  # main() does this in production; do it here for the test client


def get(path, **kw):
    r = client.get(path, **kw)
    return r.status_code, r.get_json()


def post(path, payload):
    r = client.post(path, json=payload)
    return r.status_code, r.get_json()


def step(n, label, ok=True, extra=""):
    print(f"[{n}] {'✅' if ok else '❌'} {label} {extra}", flush=True)
    assert ok, label


def main():
    t0 = time.time()

    # ------------------------------------- 1. registration flow (new contract)
    # the FULL NAME comes from the Telegram bot; the Mini App only adds the phone
    code, data = get(f"/api/init?user_id={TEST_USER}&username=Tester")
    step(1, "New user starts unregistered (no credit yet)",
         code == 200 and data["is_registered"] is False and data["credit"] == 0)

    # simulate what the bot does in the chat: collect the full name (once)
    db.update_profile(TEST_USER, full_name="Test User")
    db.set_credit(TEST_USER, config.NEW_PLAYER_CREDIT)

    # without a stored full name the Mini App must NOT be able to register
    code, data = post("/api/register",
                      {"user_id": OTHER_USER, "phone": "+251911223344"})
    step(1, "Registering without a stored full name is rejected (name onboarding required)",
         code == 400 and "full name" in (data.get("error") or "").lower())

    code, data = post("/api/register",
                      {"user_id": TEST_USER, "phone": "+251911223344"})
    step(1, "Phone registration completes the profile (no double bonus)",
         code == 200 and data["user"]["is_registered"] is True
         and data["user"]["credit"] == config.NEW_PLAYER_CREDIT)
    step(1, "Stored full name is the display identity",
         data["user"]["display_name"] == "Test User")

    db.create_player(OTHER_USER, "Other", credit=0)
    db.update_profile(OTHER_USER, full_name="Other")
    code, data = post("/api/register",
                      {"user_id": OTHER_USER, "phone": "+251911223344"})
    step(1, "Duplicate phone number rejected (409)", code == 409)

    code, data = post("/api/register",
                      {"user_id": TEST_USER, "phone": "+251922334455"})
    step(1, "New wallet phone wipes the old account, keeps the name, fresh bonus",
         code == 200 and data["user"]["phone"] == "+251922334455"
         and data["user"]["full_name"] == "Test User"
         and data["user"]["credit"] == config.NEW_PLAYER_CREDIT)

    code, data = get("/api/cards", query_string={"user_id": TEST_USER})
    step(1, f"Card pool OK ({data['total']} unique cards, lightweight payload)",
         code == 200 and data["total"] == config.NUM_CARDS == 400
         and "numbers" not in data["cards"][0])

    # ------------------------------------- 2. bot full-name onboarding (chat)
    class _FakeUser:
        def __init__(self, uid, first="Tester", username="tester"):
            self.id = uid
            self.first_name = first
            self.username = username

    class _FakeMsg:
        def __init__(self, text=None):
            self.text = text
            self.sent = []

        async def reply_text(self, text, **kw):
            self.sent.append(text)

    class _FakeUpdate:
        def __init__(self, uid, text=None):
            self.effective_user = _FakeUser(uid)
            self.message = _FakeMsg(text)

    class _FakeCtx:
        def __init__(self):
            self.user_data = {}

    bot_obj = bot_module.PremiumBingoBot()

    async def _run(fn, uid, text=None, awaiting=False):
        u = _FakeUpdate(uid, text)
        ctx = _FakeCtx()
        if awaiting:
            ctx.user_data["awaiting_full_name"] = True
        await fn(u, ctx)
        return u.message.sent

    msgs = asyncio.run(_run(bot_obj.start_command, BOT_USER))
    step(2, "Bot /start asks a NEW user for their full name",
         any("full name" in m.lower() for m in msgs))
    step(2, "/start alone does NOT grant the welcome bonus",
         db.get_credit(BOT_USER) == 0)

    msgs = asyncio.run(_run(bot_obj.text_handler, BOT_USER, "Alice_B*Wonder",
                            awaiting=True))
    p = db.get_player(BOT_USER)
    step(2, "Full name is saved", bool(p) and p["full_name"] == "Alice_B*Wonder")
    step(2, "Name is markdown-escaped in chat replies",
         any("Alice\\_B\\*Wonder" in m for m in msgs))
    step(2, "Welcome bonus granted exactly once at name registration",
         db.get_credit(BOT_USER) == config.NEW_PLAYER_CREDIT)
    step(2, "Registration confirmation is shown",
         any("Registration complete" in m for m in msgs))

    msgs = asyncio.run(_run(bot_obj.start_command, BOT_USER))
    step(2, "Existing user is NOT asked for the name again",
         not any("full name" in m.lower() for m in msgs))

    msgs = asyncio.run(_run(bot_obj.text_handler, 777222, "   ", awaiting=True))
    step(2, "Empty/whitespace name is rejected",
         any("can't be empty" in m.lower() for m in msgs))
    step(2, "Rejected name is not saved",
         (db.get_player(777222) or {}).get("full_name") is None)

    # ------------------------------------------------------ 3. select/deselect
    # the bet is FIXED per room (30 / 50 / 100) — no bet input anymore; the
    # room is chosen with the listbox and any bet_amount sent is ignored
    code, data = post("/api/select-card", {"user_id": TEST_USER, "card_id": "1"})
    step(3, "Select card #1 in Room by 30 (fixed 30 ETB)",
         code == 200 and data["user"]["credit"] == config.NEW_PLAYER_CREDIT - 30)
    code, data = post("/api/select-card",
                      {"user_id": TEST_USER, "card_id": "2", "bet_amount": 10})
    step(3, "Card #2 also costs the room's fixed 30 ETB (bet_amount ignored)",
         code == 200 and data["user"]["credit"] == config.NEW_PLAYER_CREDIT - 60)
    code, data = post("/api/select-card", {"user_id": TEST_USER, "card_id": "7", "room": 50})
    step(3, "Room by 50 charges its OWN fixed 50 ETB",
         code == 200 and data["user"]["credit"] == config.NEW_PLAYER_CREDIT - 60 - 50)
    code, _ = post("/api/select-card", {"user_id": TEST_USER, "card_id": "1"})
    step(3, "Double-picking the same card rejected", code == 400)
    code, data = post("/api/deselect-card", {"user_id": TEST_USER, "card_id": "7", "room": 50})
    step(3, "Refund on deselect (room 50)",
         code == 200 and data["user"]["credit"] == config.NEW_PLAYER_CREDIT - 60)
    code, data = post("/api/deselect-card", {"user_id": TEST_USER, "card_id": "2"})
    step(3, "Refund on deselect", code == 200 and data["user"]["credit"] == config.NEW_PLAYER_CREDIT - 30)
    code, data = post("/api/quick-play", {"user_id": TEST_USER})
    step(3, f"Quick-play auto-selected {len(data.get('chosen', []))} cards", code == 200)

    # -------------------------------------------------------- 4. admin guards
    code, _ = post("/api/admin/credit", {"admin_id": TEST_USER, "user_id": TEST_USER, "amount": 100})
    step(4, "Non-admin rejected (403)", code == 403)

    # ------------------------------------------------------------- 5. round
    code, data = post("/api/admin/force-start", {"admin_id": ADMIN})
    step(5, "Force start", code == 200 and data.get("ok"))
    code, data = get("/api/game-state", query_string={"user_id": TEST_USER})
    step(5, f"Phase=playing · pool={data['win_pool']} ETB · players={data['real_players']}",
         data["phase"] == "playing" and data["win_pool"] > 0)

    # ---------------------------------- 6. auto calling (winner only on claim)
    # a winner is ONLY announced when a player presses the BINGO button —
    # calling balls alone must never declare/announce a winner
    before = get("/api/game-state", query_string={"user_id": TEST_USER})[1]["called_count"]
    ok_calls = True
    for _ in range(3):
        code, data = post("/api/admin/force-call", {"admin_id": ADMIN})
        ok_calls = ok_calls and code == 200 and data.get("ok") and data.get("winner") is None
    after = get("/api/game-state", query_string={"user_id": TEST_USER})[1]
    step(6, "Auto calling advances the board WITHOUT announcing a winner",
         ok_calls and after["called_count"] == before + 3
         and after["winner"] is None and after["phase"] == "playing")

    # -------------------------------------------- 7. exact 80% payout + claim
    post("/api/admin/reset", {"admin_id": ADMIN})
    code, data = post("/api/select-card", {"user_id": TEST_USER, "card_id": "3", "bet_amount": 30})
    step(7, "Pick card #3 for payout test", code == 200)
    post("/api/admin/force-start", {"admin_id": ADMIN})
    for sel in db.get_all_selections():          # remove bots -> pool = 1 card
        if sel["user_id"] < 0:
            db.deselect_card(sel["user_id"], sel["card_id"])
    card = db.get_card("3")
    row0 = [f"{c}-{card[c][0]}" for c in COLUMNS]  # top row completes on the 5th ball
    db.set_ball_order(30, row0 + [n for n in loop.logic.new_ball_order() if n not in row0])
    credit_before = db.get_credit(TEST_USER)

    for _ in range(4):                            # 4 balls — row not complete yet
        post("/api/admin/force-call", {"admin_id": ADMIN})
    post("/api/admin/force-call", {"admin_id": ADMIN})  # 5th ball completes the row
    # the row is complete but NO winner is announced until the player claims
    code, state = get("/api/game-state", query_string={"user_id": TEST_USER})
    step(7, "Winning pattern present but NOT announced until BINGO is pressed",
         state["phase"] == "playing" and state["winner"] is None)
    code, data = post("/api/claim-bingo", {"user_id": TEST_USER, "card_id": "3"})
    step(7, "BINGO claim declares the winner", code == 200 and data.get("winner"))
    expected = int(30 * config.PRIZE_PERCENT)
    step(7, f"Exact payout: won {data['winner']['prize']} ETB (= 80% of 30)",
         data["winner"]["prize"] == expected)
    step(7, f"Credit updated: +{db.get_credit(TEST_USER) - credit_before} ETB",
         db.get_credit(TEST_USER) == credit_before + expected)

    code, data = post("/api/claim-bingo", {"user_id": TEST_USER, "card_id": "3"})
    step(7, "Second claim rejected (round already won)", code == 409)

    # dynamic payout: total pool = sum of the ACTUAL bets in the room
    # (two Room-by-30 cards -> 30 + 30 = 60 pool -> 48 prize)
    post("/api/admin/reset", {"admin_id": ADMIN})
    post("/api/select-card", {"user_id": TEST_USER, "card_id": "5"})
    post("/api/select-card", {"user_id": TEST_USER, "card_id": "6"})
    post("/api/admin/force-start", {"admin_id": ADMIN})
    for sel in db.get_all_selections():
        if sel["user_id"] < 0:
            db.deselect_card(sel["user_id"], sel["card_id"])
    card5 = db.get_card("5")
    row5 = [f"{c}-{card5[c][0]}" for c in COLUMNS]
    db.set_ball_order(30, row5 + [n for n in loop.logic.new_ball_order() if n not in row5])
    for _ in range(5):
        post("/api/admin/force-call", {"admin_id": ADMIN})
    code, data = post("/api/claim-bingo", {"user_id": TEST_USER, "card_id": "5"})
    step(7, f"Dynamic payout: pool 30+30=60 -> prize {data['winner']['prize'] if data.get('winner') else '?'} ETB",
         code == 200 and bool(data.get("winner"))
         and data["winner"]["prize"] == int(60 * config.PRIZE_PERCENT))

    # ---------------------------------------------------------------- 8. admin
    code, data = post("/api/admin/bots/toggle", {"admin_id": ADMIN, "enabled": False})
    step(8, "Bots toggled OFF", code == 200 and data["enabled"] is False)
    code, data = get("/api/admin/bots", query_string={"admin_id": ADMIN})
    step(8, "Bots status endpoint", data["enabled"] is False)
    code, data = post("/api/admin/bots/toggle", {"admin_id": ADMIN, "enabled": True})
    step(8, "Bots toggled back ON", data["enabled"] is True)

    admin_before = db.get_credit(ADMIN)
    code, data = post("/api/admin/credit",
                      {"admin_id": ADMIN, "user_id": TEST_USER, "amount": 500})
    step(8, "Admin credit +500 changes ONLY the target user (admin untouched)",
         code == 200 and data["credit"] == db.get_credit(TEST_USER)
         and db.get_credit(ADMIN) == admin_before)

    code, stats = get("/api/admin/stats", query_string={"admin_id": ADMIN})
    step(8, f"Stats: rounds={stats['stats']['rounds']} paid={stats['stats']['prize_paid']}",
         stats["stats"]["rounds"] >= 2 and stats["stats"]["prize_paid"] >= expected)

    # ------------------------------------- 9. payment accounts + wallet review
    code, data = post("/api/admin/accounts",
                      {"admin_id": ADMIN, "provider": "TeleBirr",
                       "account_name": "ELCOTECH", "account_number": "0911226070"})
    step(9, "Admin adds a TeleBirr account", code == 200 and data["account"]["provider"] == "TeleBirr")
    acc1 = data["account"]["id"]
    code, data = post("/api/admin/accounts",
                      {"admin_id": ADMIN, "provider": "CBE", "account_name": "ELCOTECH",
                       "account_number": "1000XXXX", "is_active": False})
    step(9, "Admin adds a CBE account (inactive)",
         code == 200 and data["account"]["is_active"] is False)
    acc2 = data["account"]["id"]
    code, data = get("/api/admin/accounts", query_string={"admin_id": ADMIN})
    step(9, "Admin views all accounts", code == 200 and len(data["accounts"]) == 2)
    code, data = post("/api/admin/accounts/update",
                      {"admin_id": ADMIN, "id": acc1, "account_number": "0911226071"})
    step(9, "Admin edits an account number",
         code == 200 and data["account"]["account_number"] == "0911226071")
    code, data = post("/api/admin/accounts/update",
                      {"admin_id": ADMIN, "id": acc2, "is_active": True})
    step(9, "Admin activates an account", code == 200 and data["account"]["is_active"] is True)
    code, data = post("/api/admin/accounts/delete", {"admin_id": ADMIN, "id": acc2})
    step(9, "Admin deletes an account", code == 200)

    code, data = post("/api/transactions",
                      {"user_id": TEST_USER, "type": "deposit", "amount": 200,
                       "tx_id": "TRX-ABC-123"})
    step(9, "Deposit without selecting a payment account rejected", code == 400)
    code, data = post("/api/transactions",
                      {"user_id": TEST_USER, "type": "deposit", "amount": 200,
                       "tx_id": "TRX-ABC-123", "payment_account_id": acc1})
    step(9, "Deposit with selected account + tx number created",
         code == 200 and data["transaction"]["status"] == "pending")
    tx = data["transaction"]
    step(9, "Transaction snapshots user full name + account details",
         tx["user_name"] == "Test User" and tx["provider"] == "TeleBirr"
         and tx["account_number"] == "0911226071" and tx["account_holder"] == "ELCOTECH")
    tx_id = tx["id"]

    # edit the account AFTER the deposit -> historical snapshot must not change
    post("/api/admin/accounts/update",
         {"admin_id": ADMIN, "id": acc1, "account_number": "9999999999"})
    step(9, "Historical transaction keeps the original account snapshot",
         db.get_transaction(tx_id)["account_number"] == "0911226071")

    bal_before = db.get_credit(TEST_USER)
    code, data = post("/api/admin/transactions/review",
                      {"admin_id": ADMIN, "id": tx_id, "action": "approve"})
    step(9, f"Admin approves deposit -> +200 ETB (balance {data['transaction']['credit']})",
         code == 200 and db.get_credit(TEST_USER) == bal_before + 200)

    code, data = post("/api/transactions",
                      {"user_id": TEST_USER, "type": "withdraw", "amount": 100})
    step(9, "Withdraw without account details rejected", code == 400)
    code, data = post("/api/transactions",
                      {"user_id": TEST_USER, "type": "withdraw", "amount": 100,
                       "account_name": "TeleBirr", "account_holder": "Test User",
                       "account_number": "+251922334455"})
    step(9, "Withdraw request created (with account details)", code == 200)
    step(9, "Withdraw snapshots the destination account details",
         data["transaction"]["provider"] == "TeleBirr"
         and data["transaction"]["account_holder"] == "Test User"
         and data["transaction"]["account_number"] == "+251922334455")
    tx_id2 = data["id"]
    bal_before = db.get_credit(TEST_USER)
    code, data = post("/api/admin/transactions/review",
                      {"admin_id": ADMIN, "id": tx_id2, "action": "approve"})
    step(9, f"Admin approves withdraw -> -100 ETB (balance {data['transaction']['credit']})",
         code == 200 and db.get_credit(TEST_USER) == bal_before - 100)

    code, data = get("/api/admin/transactions", query_string={"admin_id": ADMIN})
    step(9, "Admin wallet panel shows user name + phone + account + tx number",
         any(t["id"] == tx_id and t["user_name"] == "Test User"
             and t["provider"] == "TeleBirr" and t["tx_id"] == "TRX-ABC-123"
             for t in data["transactions"]))

    code, data = get("/api/transactions", query_string={"user_id": TEST_USER})
    step(9, f"User sees {len(data['transactions'])} wallet records",
         code == 200 and len(data["transactions"]) >= 2)

    code, data = get("/api/admin/users", query_string={"admin_id": ADMIN})
    step(9, "Admin user list (name/phone/credit)",
         code == 200 and any(u["user_id"] == TEST_USER and u["full_name"] == "Test User"
                             and u.get("phone") == "+251922334455" for u in data["users"]))
    code, data = get("/api/game-state", query_string={"user_id": TEST_USER})
    step(9, "User sees the ACTIVE payment accounts in settings",
         any(a["provider"] == "TeleBirr" for a in data["settings"]["payment_accounts"]))

    # ------------------------------------- 9b. profile editing (Settings)
    # the wallet phone is editable in Settings -> Profile (no account wipe)
    code, data = post("/api/profile",
                      {"user_id": TEST_USER, "phone": "+251944556677"})
    step(9, "User edits their wallet phone in Settings -> Profile (no account wipe)",
         code == 200 and data["user"]["phone"] == "+251944556677"
         and data["user"]["full_name"] == "Test User"
         and data["user"]["credit"] == db.get_credit(TEST_USER))
    code, data = post("/api/profile",
                      {"user_id": OTHER_USER, "phone": "+251944556677"})
    step(9, "Editing to a phone owned by another user is rejected (409)", code == 409)
    code, data = post("/api/profile", {"user_id": TEST_USER})
    step(9, "Empty profile edit rejected", code == 400)

    # ------------------------------------------------- account lifecycle
    code, data = post("/api/delete-account", {"user_id": TEST_USER, "confirm": True})
    step(10, "User deletes their account", code == 200 and data.get("ok"))
    code, data = get("/api/game-state", query_string={"user_id": TEST_USER})
    step(10, "Deleted account is unregistered again (gate re-shows)",
         data["user"]["is_registered"] is False)
    code, data = post("/api/register",
                      {"user_id": TEST_USER, "phone": "+251977778888"})
    step(10, "Registering after deletion is blocked until the bot re-collects the name",
         code == 400)
    # the user re-does the bot onboarding in the chat
    db.create_player(TEST_USER, "Test User", credit=0)
    db.update_profile(TEST_USER, full_name="Test User")
    db.set_credit(TEST_USER, config.NEW_PLAYER_CREDIT)
    code, data = post("/api/register",
                      {"user_id": TEST_USER, "phone": "+251977778888"})
    step(10, "Re-registration after deletion completes (no duplicate bonus)",
         code == 200 and data["user"]["is_registered"] is True
         and data["user"]["credit"] == config.NEW_PLAYER_CREDIT)

    # -------------------------------------------- 11. false-BINGO elimination
    post("/api/admin/reset", {"admin_id": ADMIN})
    code, data = post("/api/select-card", {"user_id": TEST_USER, "card_id": "4", "bet_amount": 30})
    step(11, "Pick card #4 for the false-BINGO test", code == 200)
    credit_after_select = db.get_credit(TEST_USER)
    post("/api/admin/force-start", {"admin_id": ADMIN})
    for sel in db.get_all_selections():
        if sel["user_id"] < 0:
            db.deselect_card(sel["user_id"], sel["card_id"])
    game_id = db.get_game_state()["current_game_id"]

    code, data = post("/api/claim-bingo", {"user_id": TEST_USER, "card_id": "4"})
    step(11, "False BINGO eliminates the player",
         code == 409 and data.get("eliminated") is True)
    step(11, "No refund for the lost bet",
         db.get_credit(TEST_USER) == credit_after_select)
    step(11, "Elimination is persisted in the DB",
         TEST_USER in db.get_eliminated_user_ids(game_id))
    code, state = get("/api/game-state", query_string={"user_id": TEST_USER})
    step(11, "game-state reports the player as eliminated",
         state["user"]["eliminated"] is True)

    code, data = post("/api/claim-bingo", {"user_id": TEST_USER, "card_id": "4"})
    step(11, "Eliminated player cannot claim again",
         code == 409 and data.get("eliminated") is True)

    # their cards no longer participate -> no winner even after all 75 balls
    for _ in range(80):
        code, data = post("/api/admin/force-call", {"admin_id": ADMIN})
        if not data.get("ok"):
            break
        if data.get("winner"):
            break
    code, state = get("/api/game-state", query_string={"user_id": TEST_USER})
    step(11, "Eliminated player's cards cannot win the round",
         state["phase"] == "ended"
         and (state.get("winner") is None or state["winner"]["user_id"] != TEST_USER))

    # restart persistence: a fresh connection still sees the elimination
    from database import Database
    db2 = Database("api_smoke.db")
    step(11, "Elimination survives a server restart",
         TEST_USER in db2.get_eliminated_user_ids(game_id))

    # next round -> eligible again
    post("/api/admin/reset", {"admin_id": ADMIN})
    post("/api/admin/force-start", {"admin_id": ADMIN})
    new_game = db.get_game_state()["current_game_id"]
    step(11, "Player is eligible again in the next round",
         TEST_USER not in db.get_eliminated_user_ids(new_game))

    # ------------------------------ 12. announcements never show a round number
    captured = []

    async def fake_broadcast(player_ids, message):
        captured.append(message)

    bot_obj.broadcast = fake_broadcast
    bot_obj._last = {30: {"phase": "ended", "count": 0, "round": 41},
                     50: {"phase": "ended", "count": 0, "round": 0},
                     100: {"phase": "ended", "count": 0, "round": 0}}
    db.clear_selections()
    db.update_game_state(30, phase="playing", round_number=42)
    old_r, old_n = config.ANNOUNCE_ROUNDS, config.ANNOUNCE_NUMBERS
    config.ANNOUNCE_ROUNDS, config.ANNOUNCE_NUMBERS = True, False

    async def _tick():
        await bot_obj._announcer_tick(None)

    asyncio.run(_tick())
    config.ANNOUNCE_ROUNDS, config.ANNOUNCE_NUMBERS = old_r, old_n

    playing_msgs = [m for m in captured if "started" in m.lower()]
    step(12, "Round announcement uses a simple message (no round number)",
         len(playing_msgs) == 1
         and "A new Bingo round has started" in playing_msgs[0]
         and "42" not in playing_msgs[0])
    step(12, "Winner/display name uses the stored full name",
         loop._name_of(TEST_USER) == "Test User")

    # -------------------------------------------------------------- 13. reset
    post("/api/admin/reset", {"admin_id": ADMIN})
    code, state = get("/api/game-state", query_string={"user_id": TEST_USER})
    step(13, f"Reset → preparation ({state['preparation_remaining']}s countdown)",
         state["phase"] == "preparation" and state["preparation_remaining"] > 0)

    # ------------ 14. called numbers are PER-ROOM (cross-room ball collisions)
    # the same ball can be drawn in two rooms — both calling boards must show
    # it. A global UNIQUE(number) would silently drop the second room's call.
    for r in (30, 50):
        post("/api/admin/reset", {"admin_id": ADMIN, "room": r})
        post("/api/admin/force-start", {"admin_id": ADMIN, "room": r})
        db.set_ball_order(r, ["B-7"] + [n for n in loop.logic.new_ball_order() if n != "B-7"])
        post("/api/admin/force-call", {"admin_id": ADMIN, "room": r})
    s30 = get("/api/game-state", query_string={"user_id": TEST_USER, "room": 30})[1]
    s50 = get("/api/game-state", query_string={"user_id": TEST_USER, "room": 50})[1]
    step(14, "Same ball called in two rooms is highlighted on BOTH boards",
         "B-7" in s30["called_numbers"] and "B-7" in s50["called_numbers"])

    # --------------------- 15. bots press BINGO — other players can win too
    # bots hold cards by default and claim like humans (with a short random
    # delay), so a bot genuinely wins rounds — the player is never alone
    from game_logic import bot_name, BOT_MALE_FIRST_NAMES
    sample = [bot_name(-(1000 + i)) for i in range(30)]
    step(15, "All bot names are human MALE names (first + surname)",
         all(n.split()[0] in BOT_MALE_FIRST_NAMES for n in sample)
         and len(sample[0].split()) == 2)

    post("/api/admin/reset", {"admin_id": ADMIN, "room": 30})
    code, data = post("/api/admin/force-start", {"admin_id": ADMIN, "room": 30})
    step(15, "Round starts with bots already in the room",
         code == 200 and data.get("ok"))
    bots = [s for s in db.get_all_selections(30) if s["user_id"] < 0]
    step(15, f"Bots hold cards in the round ({len(bots)} bot cards)", len(bots) > 0)
    # force the FIRST bot's top row to complete in the first 5 balls
    bot_sel = bots[0]
    bot_card = db.get_card(bot_sel["card_id"])
    row = [f"{c}-{bot_card[c][0]}" for c in COLUMNS]
    db.set_ball_order(30, row + [n for n in loop.logic.new_ball_order() if n not in row])
    winner = None
    for _ in range(25):
        code, data = post("/api/admin/force-call", {"admin_id": ADMIN, "room": 30})
        if not data.get("ok"):
            break
        if data.get("winner"):
            winner = data["winner"]
            break
    code, state = get("/api/game-state", query_string={"user_id": TEST_USER, "room": 30})
    step(15, "A BOT wins the round (other players are winning too)",
         state["phase"] == "ended" and bool(state.get("winner"))
         and state["winner"]["user_id"] < 0)
    step(15, "Winner payload carries the DRAWN pattern (winning_cells + card)",
         bool(state["winner"]["winning_cells"])
         and state["winner"]["card"] is not None
         and "numbers" in state["winner"]["card"]
         and "B" in state["winner"]["card"]["numbers"])
    step(15, "Bot winner gets a human male display name",
         bool(state["winner"]["name"].strip()))

    print(f"\nAPI SMOKE TEST PASSED ✅  ({time.time() - t0:.1f}s)", flush=True)


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
