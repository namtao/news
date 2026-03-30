import asyncio
import hashlib
import json
import os
import re
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from difflib import SequenceMatcher
from html import unescape
from pathlib import Path

import asyncpg
import feedparser
import httpx
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from bs4 import BeautifulSoup
from dotenv import load_dotenv
from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates

load_dotenv()

# ─── CẤU HÌNH ───
DATABASE_URL = os.environ.get("DATABASE_URL", "")
GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY", "")
GEMINI_MODEL = "gemini-2.0-flash"
GEMINI_URL = (
    "https://generativelanguage.googleapis.com/v1beta/models/{}:generateContent"
)
HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
}
REQUEST_TIMEOUT = 15

db_pool: asyncpg.Pool | None = None
http_client: httpx.AsyncClient | None = None

# Templates
BASE_DIR = Path(__file__).parent
templates = Jinja2Templates(directory=str(BASE_DIR / "templates"))

# ─── CACHE ───
cache = {
    "gold": {"data": [], "time": "", "date": "", "updated_at": None},
    "crypto": {"data": [], "updated_at": None},
    "vn_news": {"data": [], "updated_at": None},
    "world_news": {"data": [], "updated_at": None},
    "tech_news": {"data": [], "updated_at": None},
    "github": {"data": [], "updated_at": None},
}


# ─── DATABASE ───
async def init_db():
    global db_pool
    db_pool = await asyncpg.create_pool(DATABASE_URL, min_size=2, max_size=10)
    async with db_pool.acquire() as conn:
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
    if not db_pool or not items:
        return
    async with db_pool.acquire() as conn:
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
    if not db_pool or not data.get("prices"):
        return
    async with db_pool.acquire() as conn:
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
    if not db_pool or not items:
        return
    async with db_pool.acquire() as conn:
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


# ─── TIỆN ÍCH ───
def strip_html(raw):
    return unescape(re.sub(r"<[^>]+>", "", raw)).strip() if raw else ""


def make_hash(title, url=""):
    return hashlib.md5(
        f"{title.strip().lower()}|{url.strip().lower()}".encode()
    ).hexdigest()


def is_similar(a, b, threshold=0.65):
    a_c = re.sub(r"[^\w\s]", "", a.lower()).strip()
    b_c = re.sub(r"[^\w\s]", "", b.lower()).strip()
    return (
        SequenceMatcher(None, a_c, b_c).ratio() >= threshold if a_c and b_c else False
    )


def deduplicate_batch(items, key="tieu_de"):
    result = []
    for item in items:
        t = item.get(key, "")
        if not any(is_similar(t, ex.get(key, "")) for ex in result):
            result.append(item)
    return result


async def safe_get(url, **kwargs):
    try:
        r = await http_client.get(url, **kwargs)
        r.raise_for_status()
        return r
    except httpx.HTTPError as e:
        print(f"  ⚠ {e}")
        return None


async def fetch_multiple_rss(feeds, max_per_source=3):
    all_items = []
    for source, url in feeds.items():
        try:
            resp = await http_client.get(url)
            feed = feedparser.parse(resp.content)
            for entry in feed.entries[:max_per_source]:
                desc = strip_html(entry.get("summary", entry.get("description", "")))
                title = unescape(strip_html(entry.get("title", ""))).strip()
                all_items.append({
                    "nguon": source,
                    "tieu_de": title,
                    "mo_ta": desc[:200] + "..." if len(desc) > 200 else desc,
                    "url": entry.get("link", ""),
                })
        except Exception as e:
            print(f"  ⚠ RSS {source}: {e}")
    return all_items


# ─── GEMINI ───
async def summarize_batch(
    items, context="tin tức", key="tieu_de", viet_hoa=False, batch_size=7
):
    if not GEMINI_API_KEY or not items:
        return items
    for start in range(0, min(len(items), 15), batch_size):
        chunk = items[start : start + batch_size]
        await _summarize_chunk(chunk, start, items, context, key, viet_hoa)
    missing = [
        i
        for i, it in enumerate(items[:15])
        if viet_hoa and not it.get("tieu_de_vi") and it.get(key)
    ]
    for idx in missing:
        await _summarize_single(items, idx, context, key, viet_hoa)
    return items


async def _summarize_chunk(chunk, offset, items, context, key, viet_hoa):
    count = len(chunk)
    titles = "\n".join(
        f"{i + 1}. {it.get(key, '')}: {it.get('mo_ta', '')}"
        for i, it in enumerate(chunk)
    )
    url = GEMINI_URL.format(GEMINI_MODEL) + f"?key={GEMINI_API_KEY}"
    if viet_hoa:
        prompt = f"Dịch và tóm tắt {count} mục sau sang tiếng Việt.\nĐÚNG {count} dòng. Format: số. tiêu đề tiếng Việt | tóm tắt 1 câu\nKHÔNG markdown.\n\n{titles}\n\nTrả lời:"
    else:
        prompt = f"Tóm tắt {count} {context} sau, mỗi cái 1 câu tiếng Việt.\nĐÚNG {count} dòng. Format: số. tóm tắt\nKHÔNG markdown.\n\n{titles}\n\nTrả lời:"
    try:
        resp = await http_client.post(
            url,
            json={
                "contents": [{"parts": [{"text": prompt}]}],
                "generationConfig": {"maxOutputTokens": 3000, "temperature": 0.1},
            },
            timeout=30,
        )
        if resp.status_code != 200:
            return
        data = resp.json()
        parts = data.get("candidates", [{}])[0].get("content", {}).get("parts", [])
        raw = parts[0].get("text", "") if parts else ""
        for line in raw.strip().split("\n"):
            line = re.sub(r"\*\*|__|[`#]", "", line.strip())
            line = re.sub(r"\[([^\]]*)\]", r"\1", line)
            m = re.match(r"(\d+)[.)]\s*(.+)", line)
            if m:
                idx = int(m.group(1)) - 1
                real_idx = offset + idx
                if 0 <= idx < len(chunk) and real_idx < len(items):
                    text = m.group(2).strip()
                    if viet_hoa and "|" in text:
                        vt, tt = text.split("|", 1)
                        items[real_idx]["tieu_de_vi"] = vt.strip()
                        items[real_idx]["tom_tat"] = tt.strip()
                    else:
                        items[real_idx]["tom_tat"] = text
    except Exception as e:
        print(f"  ⚠ Gemini: {e}")


async def _summarize_single(items, idx, context, key, viet_hoa):
    item = items[idx]
    title = item.get(key, "")
    if not title:
        return
    url = GEMINI_URL.format(GEMINI_MODEL) + f"?key={GEMINI_API_KEY}"
    prompt = f"Dịch sang tiếng Việt và tóm tắt 1 câu.\nFormat: tiêu đề | tóm tắt\nKHÔNG markdown.\n\nTiêu đề: {title}\nMô tả: {item.get('mo_ta', '')}"
    try:
        resp = await http_client.post(
            url,
            json={
                "contents": [{"parts": [{"text": prompt}]}],
                "generationConfig": {"maxOutputTokens": 200, "temperature": 0.1},
            },
            timeout=15,
        )
        if resp.status_code == 200:
            data = resp.json()
            parts = data.get("candidates", [{}])[0].get("content", {}).get("parts", [])
            text = parts[0].get("text", "").strip() if parts else ""
            text = re.sub(r"\*\*|__|[`#]", "", text)
            text = re.sub(r"\[([^\]]*)\]", r"\1", text)
            text = re.sub(r"^\d+[.)]\s*", "", text)
            if "|" in text:
                vt, tt = text.split("|", 1)
                items[idx]["tieu_de_vi"] = vt.strip()
                items[idx]["tom_tat"] = tt.strip()
            else:
                items[idx]["tieu_de_vi"] = text
    except Exception:
        pass


# ─── XẾP HẠNG ───
HOT_KEYWORDS = {
    "chiến tranh|war|conflict|invasion|missile|attack|strike": 8,
    "khẩn cấp|emergency|breaking|urgent|crisis": 7,
    "động đất|earthquake|tsunami|hurricane|typhoon|bão": 7,
    "đảo chính|coup|martial law|thiết quân luật": 8,
    "fed|recession|suy thoái|lãi suất|interest rate|tariff|thuế quan": 5,
    "crash|sụp đổ|phá sản|bankrupt|default": 6,
    "AI|GPT|LLM|AGI|trí tuệ nhân tạo|artificial intelligence": 4,
    "hack|breach|leak|lỗ hổng|vulnerability|zero-day": 5,
    "Trump|Biden|Putin|Tập Cận Bình|Xi Jinping|NATO|UN|WHO": 3,
    "Apple|Google|Microsoft|OpenAI|Anthropic|Meta|Tesla|Nvidia": 3,
}
SOURCE_CREDIBILITY = {
    "Reuters": 10,
    "AP News": 10,
    "BBC": 9,
    "Al Jazeera": 8,
    "The Guardian": 8,
    "NPR": 8,
    "VnExpress Thế giới": 7,
    "Tuổi Trẻ Thế giới": 7,
    "VTV Thế giới": 7,
    "Thanh Niên Thế giới": 6,
    "Dân Trí Thế giới": 6,
    "Người Lao Động": 6,
    "_default": 5,
}


def score_news_item(item):
    score = SOURCE_CREDIBILITY.get(
        item.get("nguon", ""), SOURCE_CREDIBILITY["_default"]
    )
    title = (item.get("tieu_de", "") + " " + item.get("mo_ta", "")).lower()
    for pattern, pts in HOT_KEYWORDS.items():
        if re.search(pattern, title, re.IGNORECASE):
            score += pts
            break
    if item.get("diem", 0):
        score += min(item["diem"] / 100, 10)
    if item.get("binh_luan", 0):
        score += min(item["binh_luan"] / 50, 5)
    return round(score, 1)


def rank_news(items, max_items=12):
    for item in items:
        item["_score"] = score_news_item(item)
    items.sort(key=lambda x: x["_score"], reverse=True)
    return items[:max_items]


# ─── RSS FEEDS ───
RSS_TIN_VN = {
    "VTV Chính trị": "https://vtv.vn/rss/chinh-tri.rss",
    "VTV Xã hội": "https://vtv.vn/rss/xa-hoi.rss",
    "VTV Kinh tế": "https://vtv.vn/rss/kinh-te.rss",
    "VTV Pháp luật": "https://vtv.vn/rss/phap-luat.rss",
}
RSS_TIN_QT_VN = {
    "VnExpress Thế giới": "https://vnexpress.net/rss/the-gioi.rss",
    "Tuổi Trẻ Thế giới": "https://tuoitre.vn/rss/the-gioi.rss",
    "Thanh Niên Thế giới": "https://thanhnien.vn/rss/the-gioi.rss",
    "Dân Trí Thế giới": "https://dantri.com.vn/rss/the-gioi.rss",
    "VTV Thế giới": "https://vtv.vn/rss/the-gioi.rss",
    "Người Lao Động": "https://nld.com.vn/rss/quoc-te.rss",
}
RSS_TIN_QT_INTL = {
    "AP News": "https://rsshub.app/apnews/topics/world-news",
    "Reuters": "https://www.reutersagency.com/feed/?taxonomy=best-sectors&post_type=best",
    "BBC": "https://feeds.bbci.co.uk/news/world/rss.xml",
    "Al Jazeera": "https://www.aljazeera.com/xml/rss/all.xml",
    "The Guardian": "https://www.theguardian.com/world/rss",
    "NPR": "https://feeds.npr.org/1004/rss.xml",
}
GOLD_API_URL = "https://www.vang.today/api/prices"
GOLD_NAME_MAP = {
    "SJL1L10": "Vàng miếng SJC 9999",
    "SJ9999": "Vàng nhẫn SJC 9999",
    "XAUUSD": "Vàng thế giới (XAU/USD)",
    "DOHNL": "DOJI Hà Nội",
    "DOHCML": "DOJI TP.HCM",
    "PQHNVM": "PNJ Hà Nội",
    "BT9999NTT": "Bảo Tín 9999",
    "BTSJC": "Bảo Tín SJC",
}
GOLD_PRIORITY = ["SJL1L10", "SJ9999", "DOHNL", "PQHNVM", "BT9999NTT", "XAUUSD"]
BINANCE_URL = "https://api.binance.com/api/v3/ticker/24hr"
CRYPTO_SYMBOLS = ["BTCUSDT", "ETHUSDT", "SOLUSDT", "BNBUSDT", "XRPUSDT", "DOGEUSDT"]
CRYPTO_SYM = {
    "BTCUSDT": "BTC",
    "ETHUSDT": "ETH",
    "SOLUSDT": "SOL",
    "BNBUSDT": "BNB",
    "XRPUSDT": "XRP",
    "DOGEUSDT": "DOGE",
}
HN_TOP = "https://hacker-news.firebaseio.com/v0/topstories.json"
HN_ITEM = "https://hacker-news.firebaseio.com/v0/item/{}.json"


# ═══════════════════════════════════════════════
# BACKGROUND JOBS
# ═══════════════════════════════════════════════
async def job_fetch_gold():
    resp = await safe_get(GOLD_API_URL)
    if not resp:
        return
    try:
        data = resp.json()
        if not data.get("success"):
            return
        prices = data.get("prices", {})
        ordered = GOLD_PRIORITY + [c for c in prices if c not in GOLD_PRIORITY]
        formatted = []
        for code in ordered:
            if code not in prices:
                continue
            v = prices[code]
            formatted.append({
                "code": code,
                "name": GOLD_NAME_MAP.get(code, v.get("name", code)),
                "buy": v.get("buy", 0),
                "sell": v.get("sell", 0),
                "change_sell": v.get("change_sell", 0),
                "change_buy": v.get("change_buy", 0),
                "currency": v.get("currency", "VND"),
            })
        cache["gold"] = {
            "data": formatted,
            "time": data.get("time", ""),
            "date": data.get("date", ""),
            "updated_at": datetime.now(timezone.utc).isoformat(),
        }
        await log_gold_prices(data)
    except Exception as e:
        print(f"  ⚠ gold: {e}")


async def job_fetch_crypto():
    symbols_str = json.dumps(CRYPTO_SYMBOLS, separators=(",", ":"))
    resp = await safe_get(f"{BINANCE_URL}?symbols={symbols_str}")
    if not resp:
        return
    try:
        ticker_map = {t["symbol"]: t for t in resp.json()}
        items = []
        for sym in CRYPTO_SYMBOLS:
            t = ticker_map.get(sym)
            if not t:
                continue
            items.append({
                "ky_hieu": CRYPTO_SYM.get(sym, sym),
                "usd": float(t.get("lastPrice", 0)),
                "vnd": 0,
                "thay_doi": round(float(t.get("priceChangePercent", 0)), 2),
                "von_hoa": 0,
                "kl": float(t.get("quoteVolume", 0)),
            })
        cache["crypto"] = {
            "data": items,
            "updated_at": datetime.now(timezone.utc).isoformat(),
        }
        await log_crypto_prices(items)
    except Exception as e:
        print(f"  ⚠ crypto: {e}")


async def job_fetch_vn_news():
    print(f"[{datetime.now():%H:%M:%S}] vn_news...")
    raw = await fetch_multiple_rss(RSS_TIN_VN, 3)
    unique = deduplicate_batch(raw)
    ranked = rank_news(unique, 15)
    ranked = await summarize_batch(ranked, "tin tức trong nước")
    cache["vn_news"] = {
        "data": ranked,
        "updated_at": datetime.now(timezone.utc).isoformat(),
    }
    await log_news_batch(ranked, "tinvn")


async def job_fetch_world_news():
    print(f"[{datetime.now():%H:%M:%S}] world_news...")
    vn = await fetch_multiple_rss(RSS_TIN_QT_VN, 3)
    intl = await fetch_multiple_rss(RSS_TIN_QT_INTL, 3)
    for i in intl:
        i["can_dich"] = True
    all_items = deduplicate_batch(vn + intl)
    ranked = rank_news(all_items, 15)
    vn_b = [i for i in ranked if not i.get("can_dich")]
    en_b = [i for i in ranked if i.get("can_dich")]
    if vn_b:
        vn_b = await summarize_batch(vn_b, "tin quốc tế")
    if en_b:
        en_b = await summarize_batch(en_b, "tin quốc tế", viet_hoa=True)
    result = sorted(vn_b + en_b, key=lambda x: x.get("_score", 0), reverse=True)
    cache["world_news"] = {
        "data": result,
        "updated_at": datetime.now(timezone.utc).isoformat(),
    }
    await log_news_batch(result, "tinqt")


async def job_fetch_tech_news():
    print(f"[{datetime.now():%H:%M:%S}] tech_news...")
    resp = await safe_get(HN_TOP)
    if not resp:
        return
    try:
        ds = []
        for sid in resp.json()[:30]:
            if len(ds) >= 20:
                break
            r = await safe_get(HN_ITEM.format(sid))
            if not r:
                continue
            item = r.json()
            ds.append({
                "tieu_de": item.get("title", ""),
                "url": item.get("url", ""),
                "hn_url": f"https://news.ycombinator.com/item?id={sid}",
                "diem": item.get("score", 0),
                "binh_luan": item.get("descendants", 0),
                "tac_gia": item.get("by", ""),
            })
        ds = rank_news(ds, 10)
        ds = await summarize_batch(ds, "bài viết công nghệ", viet_hoa=True)
        cache["tech_news"] = {
            "data": ds,
            "updated_at": datetime.now(timezone.utc).isoformat(),
        }
        await log_news_batch(ds, "hacker_news")
    except Exception as e:
        print(f"  ⚠ HN: {e}")


async def job_fetch_github():
    print(f"[{datetime.now():%H:%M:%S}] github...")
    resp = await safe_get("https://github.com/trending", params={"since": "daily"})
    if not resp:
        return
    try:
        soup = BeautifulSoup(resp.text, "html.parser")
        repos = []
        for art in soup.select("article.Box-row")[:10]:
            h2 = art.select_one("h2 a")
            if not h2:
                continue
            name = h2.get_text(strip=True).replace(" ", "").replace("\n", "")
            desc_el = art.select_one("p")
            desc = desc_el.get_text(strip=True) if desc_el else ""
            lang_el = art.select_one("[itemprop='programmingLanguage']")
            lang = lang_el.get_text(strip=True) if lang_el else ""
            links = art.select("a.Link--muted")
            stars = links[0].get_text(strip=True).replace(",", "") if links else ""
            today_el = art.select_one("span.d-inline-block.float-sm-right")
            today = today_el.get_text(strip=True) if today_el else ""
            repos.append({
                "ten": name,
                "tieu_de": name,
                "mo_ta": desc[:150],
                "ngon_ngu": lang,
                "sao": stars,
                "hom_nay": today,
                "url": f"https://github.com/{name}",
            })
        if repos and GEMINI_API_KEY:
            repos = await summarize_batch(
                repos, "dự án GitHub", key="ten", viet_hoa=True
            )
        cache["github"] = {
            "data": repos,
            "updated_at": datetime.now(timezone.utc).isoformat(),
        }
        await log_news_batch(repos, "github")
    except Exception as e:
        print(f"  ⚠ github: {e}")


# ═══════════════════════════════════════════════
# APP
# ═══════════════════════════════════════════════
scheduler = AsyncIOScheduler()


@asynccontextmanager
async def lifespan(app: FastAPI):
    global http_client
    http_client = httpx.AsyncClient(headers=HEADERS, timeout=REQUEST_TIMEOUT)
    await init_db()
    print("✅ PostgreSQL connected")
    bg_task = asyncio.gather(
        job_fetch_gold(),
        job_fetch_crypto(),
        job_fetch_vn_news(),
        job_fetch_world_news(),
        job_fetch_tech_news(),
        job_fetch_github(),
        return_exceptions=True,
    )
    print("✅ Background fetch started")
    scheduler.add_job(job_fetch_gold, "interval", minutes=15, id="gold")
    scheduler.add_job(job_fetch_crypto, "interval", seconds=5, id="crypto")
    scheduler.add_job(job_fetch_vn_news, "interval", minutes=15, id="vn_news")
    scheduler.add_job(job_fetch_world_news, "interval", minutes=15, id="world_news")
    scheduler.add_job(job_fetch_tech_news, "interval", minutes=15, id="tech_news")
    scheduler.start()
    print("✅ Scheduler started")
    yield
    scheduler.shutdown()
    bg_task.cancel()
    try:
        await bg_task
    except asyncio.CancelledError:
        pass
    if http_client:
        await http_client.aclose()
    if db_pool:
        await db_pool.close()


app = FastAPI(title="Bản Tin Tổng Hợp", lifespan=lifespan)


# ─── Jinja2 custom filters ───
def jinja_fmt_big(n):
    if not n:
        return "—"
    if n >= 1e9:
        return f"${n / 1e9:.2f}B"
    if n >= 1e6:
        return f"${n / 1e6:.2f}M"
    return f"${n:,.0f}"


def jinja_fmt_vnd(n):
    if not n:
        return "—"
    return f"{n / 1e6:.1f} triệu" if n >= 1e6 else f"{n:,.0f}đ"


def jinja_fmt_usd(n):
    if not n:
        return "—"
    return f"${n:,.1f}"


def jinja_fmt_usd2(n):
    """USD với 2 chữ số thập phân."""
    if not n:
        return "0.00"
    return f"{n:,.2f}"


def jinja_fmt_pct(n):
    return f"{abs(n):.2f}" if n else "0.00"


templates.env.globals["fmt_big"] = jinja_fmt_big
templates.env.globals["fmt_vnd"] = jinja_fmt_vnd
templates.env.globals["fmt_usd"] = jinja_fmt_usd
templates.env.globals["fmt_usd2"] = jinja_fmt_usd2
templates.env.globals["fmt_pct"] = jinja_fmt_pct


# ─── JSON API (cho AJAX polling) ───
_refresh_locks = {}


async def _rate_limited_refresh(key, job_fn, min_interval=60):
    now = datetime.now(timezone.utc)
    last = _refresh_locks.get(key)
    if last and (now - last).total_seconds() < min_interval:
        return cache[key]
    _refresh_locks[key] = now
    await job_fn()
    return cache[key]


@app.get("/api/data")
async def api_data():
    return cache


@app.get("/api/prices")
async def api_prices():
    return {"gold": cache["gold"], "crypto": cache["crypto"]}


@app.get("/api/gold/refresh")
async def api_gold_refresh():
    return await _rate_limited_refresh("gold", job_fetch_gold, 30)


@app.get("/api/crypto/refresh")
async def api_crypto_refresh():
    return await _rate_limited_refresh("crypto", job_fetch_crypto, 5)


@app.get("/api/vn_news/refresh")
async def api_vn_news_refresh():
    return await _rate_limited_refresh("vn_news", job_fetch_vn_news)


@app.get("/api/world_news/refresh")
async def api_world_news_refresh():
    return await _rate_limited_refresh("world_news", job_fetch_world_news)


@app.get("/api/tech_news/refresh")
async def api_tech_news_refresh():
    return await _rate_limited_refresh("tech_news", job_fetch_tech_news)


@app.get("/api/github/refresh")
async def api_github_refresh():
    return await _rate_limited_refresh("github", job_fetch_github)


# ─── HTML PAGE ───
@app.get("/", response_class=HTMLResponse)
async def index(request: Request):
    return templates.TemplateResponse(
        "index.html",
        {
            "request": request,
            "gold": cache["gold"],
            "crypto": cache["crypto"],
            "vn_news": cache["vn_news"],
            "world_news": cache["world_news"],
            "tech_news": cache["tech_news"],
            "github": cache["github"],
            "now": datetime.now().strftime("%H:%M — %d/%m/%Y"),
        },
    )
