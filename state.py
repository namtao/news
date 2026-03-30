import asyncpg
import httpx

db_pool: asyncpg.Pool | None = None
http_client: httpx.AsyncClient | None = None

cache = {
    "gold": {"data": [], "time": "", "date": "", "updated_at": None},
    "crypto": {"data": [], "updated_at": None},
    "vn_news": {"data": [], "updated_at": None},
    "world_news": {"data": [], "updated_at": None},
    "tech_news": {"data": [], "updated_at": None},
    "github": {"data": [], "updated_at": None},
    "forex": {"data": [], "updated_at": None},
    "stock": {"data": [], "updated_at": None},
    "oil": {"data": [], "updated_at": None},
    "weather": {"data": {}, "updated_at": None},
    "lunar": {"data": {}, "updated_at": None},
    "producthunt": {"data": [], "updated_at": None},
    "devblog": {"data": [], "updated_at": None},
    "events": {"data": [], "updated_at": None},
}
