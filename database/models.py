from datetime import date
from psycopg.rows import dict_row
from database import db
from config import DAILY_FREE_LIMIT

async def get_or_create_user(user_id: int, username: str | None, lang: str = "ru"):
    if lang not in ("ru", "uk", "en", "es"):
        lang = "ru"
    async with db.pool.connection() as conn:
        async with conn.cursor(row_factory=dict_row) as cur:
            await cur.execute("SELECT * FROM users WHERE user_id = %s", (user_id,))
            user = await cur.fetchone()
            if not user:
                await cur.execute(
                    "INSERT INTO users (user_id, username, language) VALUES (%s, %s, %s)",
                    (user_id, username, lang)
                )
                await cur.execute("SELECT * FROM users WHERE user_id = %s", (user_id,))
                user = await cur.fetchone()
            elif user["last_reset_date"] < date.today():
                await cur.execute(
                    "UPDATE users SET daily_free_used = 0, last_reset_date = CURRENT_DATE WHERE user_id = %s",
                    (user_id,)
                )
                await cur.execute("SELECT * FROM users WHERE user_id = %s", (user_id,))
                user = await cur.fetchone()
            return user

async def update_user_field(user_id: int, field: str, value):
    async with db.pool.connection() as conn:
        await conn.execute(f"UPDATE users SET {field} = %s WHERE user_id = %s", (value, user_id))

async def can_generate(user_id: int) -> tuple[bool, int]:
    async with db.pool.connection() as conn:
        async with conn.cursor(row_factory=dict_row) as cur:
            await cur.execute("SELECT daily_free_used, is_vip FROM users WHERE user_id = %s", (user_id,))
            user = await cur.fetchone()
            if user["is_vip"]:
                return True, 999
            remaining = DAILY_FREE_LIMIT - user["daily_free_used"]
            return remaining > 0, max(0, remaining)

async def increment_usage(user_id: int, character_code: str, mood_code: str, is_photo: bool = False, file_id: str = ""):
    async with db.pool.connection() as conn:
        await conn.execute(
            "UPDATE users SET daily_free_used = daily_free_used + 1 WHERE user_id = %s",
            (user_id,)
        )
        await conn.execute(
            """INSERT INTO generations (user_id, character_code, mood_code, is_from_photo, file_id)
               VALUES (%s, %s, %s, %s, %s)""",
            (user_id, character_code, mood_code, is_photo, file_id)
        )
