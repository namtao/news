import json

import asyncpg

import state
from config import DATABASE_URL
from utils import make_hash


async def init_db():
    state.db_pool = await asyncpg.create_pool(DATABASE_URL, min_size=2, max_size=10)
    async with state.db_pool.acquire() as conn:
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS news (
                id SERIAL PRIMARY KEY,
                hash TEXT NOT NULL UNIQUE,
                module TEXT NOT NULL,
                title TEXT NOT NULL,
                title_vi TEXT,
                url TEXT,
                source TEXT,
                summary TEXT,
                score REAL DEFAULT 0,
                fetched_at TIMESTAMPTZ DEFAULT NOW()
            )
        """)
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS prices (
                id SERIAL PRIMARY KEY,
                module TEXT NOT NULL,
                symbol TEXT,
                buy REAL,
                sell REAL,
                change_pct REAL,
                raw_json JSONB,
                fetched_at TIMESTAMPTZ DEFAULT NOW()
            )
        """)
        for idx_sql in [
            "CREATE INDEX IF NOT EXISTS idx_news_module ON news(module)",
            "CREATE INDEX IF NOT EXISTS idx_news_hash ON news(hash)",
            "CREATE INDEX IF NOT EXISTS idx_news_fetched ON news(fetched_at)",
            "CREATE INDEX IF NOT EXISTS idx_prices_module ON prices(module, fetched_at)",
            "CREATE INDEX IF NOT EXISTS idx_prices_symbol ON prices(symbol, fetched_at)",
        ]:
            await conn.execute(idx_sql)


async def log_news_batch(items: list[dict], module: str):
    if not state.db_pool or not items:
        return
    async with state.db_pool.acquire() as conn:
        for item in items:
            h = make_hash(item.get("tieu_de", ""), item.get("url", ""))
            try:
                await conn.execute(
                    """INSERT INTO news (hash,module,title,title_vi,url,source,summary,score)
                       VALUES ($1,$2,$3,$4,$5,$6,$7,$8) ON CONFLICT (hash) DO NOTHING""",
                    h,
                    module,
                    item.get("tieu_de", ""),
                    item.get("tieu_de_vi", ""),
                    item.get("url", ""),
                    item.get("nguon", ""),
                    item.get("tom_tat", ""),
                    item.get("_score", 0),
                )
            except Exception:
                pass


async def log_gold_prices(data: dict):
    if not state.db_pool or not data.get("prices"):
        return
    async with state.db_pool.acquire() as conn:
        for code, v in data["prices"].items():
            await conn.execute(
                "INSERT INTO prices (module,symbol,buy,sell,change_pct,raw_json) VALUES ($1,$2,$3,$4,$5,$6)",
                "gold",
                code,
                v.get("buy", 0),
                v.get("sell", 0),
                v.get("change_sell", 0),
                json.dumps(v, ensure_ascii=False),
            )


async def log_crypto_prices(items: list[dict]):
    if not state.db_pool or not items:
        return
    async with state.db_pool.acquire() as conn:
        for c in items:
            await conn.execute(
                "INSERT INTO prices (module,symbol,buy,sell,change_pct,raw_json) VALUES ($1,$2,$3,$4,$5,$6)",
                "crypto",
                c["ky_hieu"],
                float(c["usd"]),
                0.0,
                float(c["thay_doi"]),
                json.dumps(c, ensure_ascii=False),
            )
