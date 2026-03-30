import asyncio
from contextlib import asynccontextmanager
from datetime import datetime
from pathlib import Path

import httpx
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

import state
from config import HEADERS, REQUEST_TIMEOUT
from db import init_db
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
from routes import router

scheduler = AsyncIOScheduler()


@asynccontextmanager
async def lifespan(app: FastAPI):
    state.http_client = httpx.AsyncClient(headers=HEADERS, timeout=REQUEST_TIMEOUT)
    await init_db()
    print("✅ PostgreSQL connected")
    bg_task = asyncio.gather(
        job_fetch_gold(),
        job_fetch_crypto(),
        job_fetch_vn_news(),
        job_fetch_world_news(),
        job_fetch_tech_news(),
        job_fetch_github(),
        job_fetch_forex(),
        job_fetch_stock(),
        job_fetch_oil(),
        job_fetch_weather(),
        job_fetch_producthunt(),
        job_fetch_devblog(),
        return_exceptions=True,
    )
    job_fetch_lunar()
    job_fetch_events()
    print("✅ Background fetch started")
    scheduler.add_job(job_fetch_gold, "interval", minutes=15, id="gold")
    scheduler.add_job(job_fetch_crypto, "interval", seconds=5, id="crypto")
    scheduler.add_job(job_fetch_vn_news, "interval", minutes=15, id="vn_news")
    scheduler.add_job(job_fetch_world_news, "interval", minutes=15, id="world_news")
    scheduler.add_job(job_fetch_tech_news, "interval", minutes=15, id="tech_news")
    scheduler.add_job(job_fetch_forex, "interval", minutes=30, id="forex")
    scheduler.add_job(job_fetch_stock, "interval", minutes=5, id="stock")
    scheduler.add_job(job_fetch_oil, "interval", minutes=30, id="oil")
    scheduler.add_job(job_fetch_weather, "interval", minutes=30, id="weather")
    scheduler.add_job(job_fetch_lunar, "interval", hours=1, id="lunar")
    scheduler.add_job(job_fetch_producthunt, "interval", hours=2, id="producthunt")
    scheduler.add_job(job_fetch_devblog, "interval", minutes=30, id="devblog")
    scheduler.add_job(job_fetch_events, "interval", hours=6, id="events")
    scheduler.start()
    print("✅ Scheduler started")
    yield
    scheduler.shutdown()
    bg_task.cancel()
    try:
        await bg_task
    except asyncio.CancelledError:
        pass
    if state.http_client:
        await state.http_client.aclose()
    if state.db_pool:
        await state.db_pool.close()


app = FastAPI(title="Bản Tin Tổng Hợp", lifespan=lifespan)
app.mount("/static", StaticFiles(directory="static"), name="static")
app.include_router(router)

BASE_DIR = Path(__file__).parent
templates = Jinja2Templates(directory=str(BASE_DIR / "templates"))


def _fmt_big(n):
    if not n:
        return "—"
    if n >= 1e9:
        return f"${n / 1e9:.2f}B"
    if n >= 1e6:
        return f"${n / 1e6:.2f}M"
    return f"${n:,.0f}"


def _fmt_vnd(n):
    if not n:
        return "—"
    return f"{n / 1e6:.1f} triệu" if n >= 1e6 else f"{n:,.0f}đ"


def _fmt_usd(n):
    if not n:
        return "—"
    return f"${n:,.1f}"


def _fmt_usd2(n):
    if not n:
        return "0.00"
    return f"{n:,.2f}"


def _fmt_pct(n):
    return f"{abs(n):.2f}" if n else "0.00"


templates.env.globals["fmt_big"] = _fmt_big
templates.env.globals["fmt_vnd"] = _fmt_vnd
templates.env.globals["fmt_usd"] = _fmt_usd
templates.env.globals["fmt_usd2"] = _fmt_usd2
templates.env.globals["fmt_pct"] = _fmt_pct


@app.get("/", response_class=HTMLResponse)
async def index(request: Request):
    return templates.TemplateResponse(
        "index.html",
        {
            "request": request,
            "gold": state.cache["gold"],
            "crypto": state.cache["crypto"],
            "vn_news": state.cache["vn_news"],
            "world_news": state.cache["world_news"],
            "tech_news": state.cache["tech_news"],
            "github": state.cache["github"],
            "now": datetime.now().strftime("%H:%M — %d/%m/%Y"),
        },
    )
