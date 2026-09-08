import sqlite3
from datetime import datetime, timedelta

conn = sqlite3.connect("bingo_bot.db")
new_time = (datetime.now() + timedelta(seconds=30)).isoformat()
for room in (30, 50, 100):
    conn.execute("UPDATE game_state SET preparation_end_time = ? WHERE room = ?", (new_time, room))
conn.commit()
conn.close()
print("✅ Countdown reset to 30 seconds (all rooms). Restart the bot.")