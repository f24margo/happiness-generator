from psycopg_pool import AsyncConnectionPool
from config import DATABASE_URL

pool: AsyncConnectionPool | None = None

async def init_db():
    global pool
    pool = AsyncConnectionPool(conninfo=DATABASE_URL, open=False)
    await pool.open()
    async with pool.connection() as conn:
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS users (
                user_id BIGINT PRIMARY KEY,
                username TEXT,
                language VARCHAR(5) DEFAULT 'ru',
                character_code VARCHAR(30) DEFAULT 'girl',
                daily_free_used INT DEFAULT 0,
                last_reset_date DATE DEFAULT CURRENT_DATE,
                is_vip BOOLEAN DEFAULT FALSE,
                vip_until TIMESTAMP NULL,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );
        """)
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS generations (
                id SERIAL PRIMARY KEY,
                user_id BIGINT REFERENCES users(user_id),
                character_code VARCHAR(30),
                mood_code VARCHAR(30),
                is_from_photo BOOLEAN DEFAULT FALSE,
                file_id TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );
        """)

async def close_db():
    if pool:
        await pool.close()
