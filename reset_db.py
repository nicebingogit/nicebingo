import sqlite3
conn = sqlite3.connect("bingo_bot.db")
for room in (30, 50, 100):
    conn.execute(
        "UPDATE game_state SET phase='preparation', preparation_end_time=datetime('now', '+30 seconds'), current_call=NULL, winner_user_id=NULL, winning_pattern=NULL, prize_pool=0, total_bets=0 WHERE room=?",
        (room,),
    )
    conn.execute("DELETE FROM called_numbers WHERE room=?", (room,))
    conn.execute("DELETE FROM card_selections WHERE room=?", (room,))
conn.commit()
conn.close()
print("✅ Database reset (all rooms). Now you can select cards.")