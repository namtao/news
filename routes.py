from datetime import datetime, timezone

from fastapi import APIRouter

import state
from jobs import (
    job_fetch_crypto,
    job_fetch_devblog,
    job_fetch_events,
    job_fetch_forex,
    job_fetch_github,
    job_fetch_gold,
    job_fetch_lunar,
    job_fetch_oil,
    job_fetch_producthunt,
    job_fetch_stock,
    job_fetch_tech_news,
    job_fetch_vn_news,
    job_fetch_weather,
    job_fetch_world_news,
)

router = APIRouter()
_refresh_locks: dict = {}


async def _rate_limited_refresh(key, job_fn, min_interval=60):
    now = datetime.now(timezone.utc)
    last = _refresh_locks.get(key)
    if last and (now - last).total_seconds() < min_interval:
        return state.cache[key]
    _refresh_locks[key] = now
    await job_fn()
    return state.cache[key]


@router.get("/api/data")
async def api_data():
    return state.cache


@router.get("/api/prices")
async def api_prices():
    return {"gold": state.cache["gold"], "crypto": state.cache["crypto"]}


@router.get("/api/gold/refresh")
async def api_gold_refresh():
    return await _rate_limited_refresh("gold", job_fetch_gold, 30)


@router.get("/api/crypto/refresh")
async def api_crypto_refresh():
    return await _rate_limited_refresh("crypto", job_fetch_crypto, 5)


@router.get("/api/vn_news/refresh")
async def api_vn_news_refresh():
    return await _rate_limited_refresh("vn_news", job_fetch_vn_news)


@router.get("/api/world_news/refresh")
async def api_world_news_refresh():
    return await _rate_limited_refresh("world_news", job_fetch_world_news)


@router.get("/api/tech_news/refresh")
async def api_tech_news_refresh():
    return await _rate_limited_refresh("tech_news", job_fetch_tech_news)


@router.get("/api/github/refresh")
async def api_github_refresh():
    return await _rate_limited_refresh("github", job_fetch_github)


@router.get("/api/forex/refresh")
async def api_forex_refresh():
    return await _rate_limited_refresh("forex", job_fetch_forex, 30)


@router.get("/api/stock/refresh")
async def api_stock_refresh():
    return await _rate_limited_refresh("stock", job_fetch_stock, 10)


@router.get("/api/oil/refresh")
async def api_oil_refresh():
    return await _rate_limited_refresh("oil", job_fetch_oil, 30)


@router.get("/api/weather/refresh")
async def api_weather_refresh():
    return await _rate_limited_refresh("weather", job_fetch_weather, 60)


@router.get("/api/producthunt/refresh")
async def api_producthunt_refresh():
    return await _rate_limited_refresh("producthunt", job_fetch_producthunt, 120)


@router.get("/api/devblog/refresh")
async def api_devblog_refresh():
    return await _rate_limited_refresh("devblog", job_fetch_devblog, 30)


@router.get("/api/events/refresh")
async def api_events_refresh():
    job_fetch_events()
    return state.cache["events"]


@router.get("/api/lunar/refresh")
async def api_lunar_refresh():
    job_fetch_lunar()
    return state.cache["lunar"]
