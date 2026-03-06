import argparse
import hashlib
import json
import os
import re
import sqlite3
import sys
from datetime import datetime, timezone
from difflib import SequenceMatcher
from html import unescape
from pathlib import Path

import feedparser
import requests
from bs4 import BeautifulSoup
from dotenv import load_dotenv

load_dotenv()

# ─────────────────────────────────────────────
# CẤU HÌNH
# ─────────────────────────────────────────────
HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
}
REQUEST_TIMEOUT = 15
DB_PATH = Path(__file__).parent / "news_history.db"
GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY", "")
GEMINI_MODEL = "gemini-3-flash-preview"
GEMINI_URL = (
    "https://generativelanguage.googleapis.com/v1beta/models/{}:generateContent"
)


def init_db() -> sqlite3.Connection:
    conn = sqlite3.connect(str(DB_PATH))
    conn.execute("PRAGMA journal_mode=WAL")

    # Bảng tin — lưu mọi lần fetch, cho phép trùng title khác thời điểm
    conn.execute("""
        CREATE TABLE IF NOT EXISTS news (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            hash TEXT NOT NULL,
            module TEXT NOT NULL,
            title TEXT NOT NULL,
            title_vi TEXT,
            url TEXT,
            source TEXT,
            summary TEXT,
            score REAL DEFAULT 0,
            fetched_at TEXT DEFAULT (datetime('now', 'localtime'))
        )
    """)

    # Bảng giá — time series cho chart
    conn.execute("""
        CREATE TABLE IF NOT EXISTS prices (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            module TEXT NOT NULL,
            symbol TEXT,
            buy REAL,
            sell REAL,
            change_pct REAL,
            raw_json TEXT,
            fetched_at TEXT DEFAULT (datetime('now', 'localtime'))
        )
    """)

    # Index cho dashboard query
    conn.execute("CREATE INDEX IF NOT EXISTS idx_news_module ON news(module)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_news_fetched ON news(fetched_at)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_news_hash ON news(hash)")
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_prices_module ON prices(module, fetched_at)"
    )
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_prices_symbol ON prices(symbol, fetched_at)"
    )
    conn.commit()
    return conn


# ─────────────────────────────────────────────
# GHI DỮ LIỆU — append-only, không filter
# ─────────────────────────────────────────────


def log_news_batch(conn: sqlite3.Connection, items: list[dict], module: str):
    """Ghi batch tin vào DB. Dùng hash để tránh ghi trùng CÙNG lần fetch,
    nhưng KHÔNG chặn hiển thị."""
    rows = []
    for item in items:
        h = make_hash(item.get("tieu_de", ""), item.get("url", ""))
        rows.append((
            h,
            module,
            item.get("tieu_de", ""),
            item.get("tieu_de_vi", ""),
            item.get("url", ""),
            item.get("nguon", ""),
            item.get("tom_tat", ""),
            item.get("_score", 0),
        ))
    conn.executemany(
        """INSERT OR IGNORE INTO news
           (hash, module, title, title_vi, url, source, summary, score)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
        rows,
    )
    conn.commit()


def log_gold_prices(conn: sqlite3.Connection, data: dict):
    """Ghi giá vàng — 1 row per loại vàng, dễ chart."""
    if not data.get("prices"):
        return
    rows = []
    for code, v in data["prices"].items():
        rows.append((
            "gold",
            code,
            v.get("buy", 0),
            v.get("sell", 0),
            v.get("change_sell", 0),
            json.dumps(v, ensure_ascii=False),
        ))
    conn.executemany(
        """INSERT INTO prices (module, symbol, buy, sell, change_pct, raw_json)
           VALUES (?, ?, ?, ?, ?, ?)""",
        rows,
    )
    conn.commit()


def log_crypto_prices(conn: sqlite3.Connection, items: list[dict]):
    """Ghi giá crypto — 1 row per coin."""
    rows = []
    for c in items:
        rows.append((
            "crypto",
            c["ky_hieu"],
            c["usd"],
            0,
            c["thay_doi"],
            json.dumps(c, ensure_ascii=False),
        ))
    conn.executemany(
        """INSERT INTO prices (module, symbol, buy, sell, change_pct, raw_json)
           VALUES (?, ?, ?, ?, ?, ?)""",
        rows,
    )
    conn.commit()


def deduplicate_batch(items: list[dict], key: str = "tieu_de") -> list[dict]:
    """Lọc trùng trong 1 batch (giữa các nguồn RSS).
    VD: VnExpress và Tuổi Trẻ cùng đăng 1 tin → giữ 1."""
    result = []
    for item in items:
        t = item.get(key, "")
        if not any(is_similar(t, ex.get(key, "")) for ex in result):
            result.append(item)
    return result


def make_hash(title: str, url: str = "") -> str:
    """Tạo hash từ tiêu đề + url để nhận diện tin trùng."""
    raw = f"{title.strip().lower()}|{url.strip().lower()}"
    return hashlib.md5(raw.encode()).hexdigest()


def is_in_db(conn: sqlite3.Connection, title: str, url: str = "") -> bool:
    """Kiểm tra tin đã có trong DB chưa (theo hash)."""
    h = make_hash(title, url)
    row = conn.execute("SELECT 1 FROM news_history WHERE hash=?", (h,)).fetchone()
    return row is not None


def is_similar_in_db(
    conn: sqlite3.Connection, title: str, module: str, threshold: float = 0.65
) -> bool:
    """Kiểm tra xem có tin tương tự trong DB gần đây không (24h)."""
    rows = conn.execute(
        "SELECT title FROM news_history WHERE module=? AND created_at >= datetime('now', '-1 day', 'localtime')",
        (module,),
    ).fetchall()
    title_clean = re.sub(r"[^\w\s]", "", title.lower()).strip()
    for (existing,) in rows:
        existing_clean = re.sub(r"[^\w\s]", "", existing.lower()).strip()
        if SequenceMatcher(None, title_clean, existing_clean).ratio() >= threshold:
            return True
    return False


def save_news(
    conn: sqlite3.Connection,
    module: str,
    title: str,
    url: str = "",
    source: str = "",
    summary: str = "",
):
    """Lưu tin vào DB."""
    h = make_hash(title, url)
    try:
        conn.execute(
            "INSERT OR IGNORE INTO news_history (hash, module, title, url, source, summary) VALUES (?,?,?,?,?,?)",
            (h, module, title, url, source, summary),
        )
        conn.commit()
    except sqlite3.Error:
        pass


def save_price(conn: sqlite3.Connection, module: str, data: dict):
    """Lưu giá vàng/crypto vào lịch sử."""
    try:
        conn.execute(
            "INSERT INTO price_history (module, data) VALUES (?,?)",
            (module, json.dumps(data, ensure_ascii=False)),
        )
        conn.commit()
    except sqlite3.Error:
        pass


def get_db_stats(conn: sqlite3.Connection) -> dict:
    """Thống kê DB."""
    total = conn.execute("SELECT COUNT(*) FROM news_history").fetchone()[0]
    by_module = conn.execute(
        "SELECT module, COUNT(*) FROM news_history GROUP BY module ORDER BY COUNT(*) DESC"
    ).fetchall()
    today = conn.execute(
        "SELECT COUNT(*) FROM news_history WHERE created_at >= date('now', 'localtime')"
    ).fetchone()[0]
    prices = conn.execute("SELECT COUNT(*) FROM price_history").fetchone()[0]
    return {
        "tong": total,
        "hom_nay": today,
        "theo_module": dict(by_module),
        "lich_su_gia": prices,
    }


# ─────────────────────────────────────────────
# AI TÓM TẮT — Gemini (tùy chọn)
# ─────────────────────────────────────────────
def summarize_text(text: str, context: str = "tin tức") -> str:
    """Tóm tắt nội dung bằng Gemini API. Trả về '' nếu không có key."""
    if not GEMINI_API_KEY or not text.strip():
        return ""
    try:
        url = GEMINI_URL.format(GEMINI_MODEL) + f"?key={GEMINI_API_KEY}"
        prompt = (
            f"Tóm tắt ngắn gọn bằng tiếng Việt (1-2 câu, tối đa 80 từ) "
            f"nội dung {context} sau:\n\n{text[:2000]}"
        )
        resp = requests.post(
            url,
            json={
                "contents": [{"parts": [{"text": prompt}]}],
                "generationConfig": {"maxOutputTokens": 200, "temperature": 0.3},
            },
            timeout=20,
        )
        if resp.status_code == 200:
            data = resp.json()
            parts = data.get("candidates", [{}])[0].get("content", {}).get("parts", [])
            return parts[0].get("text", "").strip() if parts else ""
        return ""
    except Exception:
        return ""


def summarize_batch(
    items: list[dict],
    context: str = "tin tức",
    key: str = "tieu_de",
    viet_hoa: bool = False,
    batch_size: int = 7,  # ← FIX 1: chia nhỏ batch
) -> list[dict]:
    """Tóm tắt hàng loạt bằng Gemini API.
    viet_hoa=True: dịch tiếng Anh sang tiếng Việt + tóm tắt.
    Tự động chia batch nhỏ và retry nếu thiếu dòng.
    """
    if not GEMINI_API_KEY or not items:
        return items

    # FIX 1: Chia nhỏ thành các batch <= batch_size
    for start in range(0, min(len(items), 15), batch_size):
        chunk = items[start : start + batch_size]
        _summarize_chunk(chunk, start, items, context, key, viet_hoa)

    # FIX 2: Retry từng item bị thiếu
    missing = [
        i
        for i, it in enumerate(items[:15])
        if viet_hoa and not it.get("tieu_de_vi") and it.get(key)
    ]
    if missing:
        print(f"  ⚠ Retry {len(missing)} mục chưa dịch: {missing}")
        for idx in missing:
            _summarize_single(items, idx, context, key, viet_hoa)

    return items


def _summarize_chunk(
    chunk: list[dict],
    offset: int,
    items: list[dict],
    context: str,
    key: str,
    viet_hoa: bool,
):
    """Xử lý 1 batch nhỏ."""
    count = len(chunk)
    titles = "\n".join(
        f"{i + 1}. {it.get(key, '')}: {it.get('mo_ta', '')}"
        for i, it in enumerate(chunk)
    )
    url = GEMINI_URL.format(GEMINI_MODEL) + f"?key={GEMINI_API_KEY}"

    if viet_hoa:
        prompt = (
            f"Nhiệm vụ: Dịch và tóm tắt {count} mục sau sang tiếng Việt.\n\n"
            f"QUY TẮC BẮT BUỘC:\n"
            f"- Trả về ĐÚNG {count} dòng, mỗi dòng 1 mục, KHÔNG ĐƯỢC BỎ DÒNG NÀO\n"
            f"- Format mỗi dòng: số thứ tự. tiêu đề tiếng Việt | tóm tắt 1 câu tiếng Việt\n"
            f"- Dùng text thuần, TUYỆT ĐỐI KHÔNG dùng markdown (**, [], #, `, _)\n"
            f"- Nếu tiêu đề đã là tiếng Việt thì giữ nguyên\n"
            f"- Mỗi tóm tắt tối đa 30 từ\n"
            f"- QUAN TRỌNG: Phải có ĐỦ {count} dòng từ 1 đến {count}\n\n"
            f"Danh sách {context}:\n{titles}\n\n"
            f"Trả lời (ĐÚNG {count} dòng, từ 1 đến {count}):"
        )
    else:
        prompt = (
            f"Nhiệm vụ: Tóm tắt {count} {context} sau, mỗi cái 1 câu tiếng Việt.\n\n"
            f"QUY TẮC BẮT BUỘC:\n"
            f"- Trả về ĐÚNG {count} dòng, KHÔNG ĐƯỢC BỎ DÒNG NÀO\n"
            f"- Format: số thứ tự. tóm tắt tiếng Việt\n"
            f"- KHÔNG dùng markdown\n"
            f"- Mỗi tóm tắt tối đa 30 từ\n\n"
            f"Danh sách:\n{titles}\n\n"
            f"Trả lời (ĐÚNG {count} dòng):"
        )

    try:
        resp = requests.post(
            url,
            json={
                "contents": [{"parts": [{"text": prompt}]}],
                "generationConfig": {
                    "maxOutputTokens": 3000,  # ← FIX 3: tăng token limit
                    "temperature": 0.1,
                },
            },
            timeout=30,
        )
        if resp.status_code != 200:
            print(f"  ⚠ Gemini trả mã {resp.status_code}")
            return

        data = resp.json()
        parts = data.get("candidates", [{}])[0].get("content", {}).get("parts", [])
        raw = parts[0].get("text", "") if parts else ""

        for line in raw.strip().split("\n"):
            line = line.strip()
            if not line:
                continue
            line = re.sub(r"\*\*|__|[`#]", "", line)
            line = re.sub(r"\[([^\]]*)\]", r"\1", line)
            m = re.match(r"(\d+)[.)]\s*(.+)", line)
            if m:
                idx = int(m.group(1)) - 1  # index trong chunk
                real_idx = offset + idx  # index trong items gốc
                if 0 <= idx < len(chunk) and real_idx < len(items):
                    text = m.group(2).strip()
                    if viet_hoa and "|" in text:
                        viet_title, tom_tat = text.split("|", 1)
                        items[real_idx]["tieu_de_vi"] = viet_title.strip()
                        items[real_idx]["tom_tat"] = tom_tat.strip()
                    else:
                        items[real_idx]["tom_tat"] = text
    except Exception as e:
        print(f"  ⚠ Lỗi Gemini batch: {e}")


def _summarize_single(
    items: list[dict], idx: int, context: str, key: str, viet_hoa: bool
):
    """Retry dịch 1 item đơn lẻ khi batch bị thiếu."""
    item = items[idx]
    title = item.get(key, "")
    desc = item.get("mo_ta", "")
    if not title:
        return
    url = GEMINI_URL.format(GEMINI_MODEL) + f"?key={GEMINI_API_KEY}"
    prompt = (
        f"Dịch tiêu đề sau sang tiếng Việt và tóm tắt 1 câu (tối đa 30 từ).\n"
        f"Format: tiêu đề tiếng Việt | tóm tắt\n"
        f"KHÔNG dùng markdown.\n\n"
        f"Tiêu đề: {title}\nMô tả: {desc}\n\nTrả lời (1 dòng):"
    )
    try:
        resp = requests.post(
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
            # Bỏ số thứ tự nếu model tự thêm
            text = re.sub(r"^\d+[.)]\s*", "", text)
            if "|" in text:
                viet_title, tom_tat = text.split("|", 1)
                items[idx]["tieu_de_vi"] = viet_title.strip()
                items[idx]["tom_tat"] = tom_tat.strip()
            else:
                items[idx]["tieu_de_vi"] = text
    except Exception:
        pass


# ─────────────────────────────────────────────
# TIỆN ÍCH
# ─────────────────────────────────────────────
def strip_html(raw: str) -> str:
    if not raw:
        return ""
    return unescape(re.sub(r"<[^>]+>", "", raw)).strip()


def format_number(n: float, prefix: str = "", suffix: str = "") -> str:
    if n >= 1e9:
        return f"{prefix}{n / 1e9:.2f}B{suffix}"
    if n >= 1e6:
        return f"{prefix}{n / 1e6:.2f}M{suffix}"
    if n >= 1e3:
        return f"{prefix}{n:,.0f}{suffix}"
    return f"{prefix}{n:.2f}{suffix}"


def format_vnd(n: float) -> str:
    return f"{n / 1e6:.1f} triệu" if n >= 1e6 else f"{n:,.0f}đ".replace(",", ".")


def safe_get(url: str, **kwargs) -> requests.Response | None:
    try:
        r = requests.get(url, headers=HEADERS, timeout=REQUEST_TIMEOUT, **kwargs)
        r.raise_for_status()
        return r
    except requests.RequestException as e:
        print(f"  ⚠ Lỗi kết nối: {e}")
        return None


def print_header(title: str):
    print(f"\n{'━' * 50}")
    print(f"  {title}")
    print(f"{'━' * 50}")


def is_similar(a: str, b: str, threshold: float = 0.65) -> bool:
    a_c = re.sub(r"[^\w\s]", "", a.lower()).strip()
    b_c = re.sub(r"[^\w\s]", "", b.lower()).strip()
    return (
        SequenceMatcher(None, a_c, b_c).ratio() >= threshold if a_c and b_c else False
    )


def deduplicate_news(items: list[dict], key: str = "tieu_de") -> list[dict]:
    """Lọc trùng trong batch hiện tại."""
    result = []
    for item in items:
        t = item.get(key, "")
        if not any(is_similar(t, ex.get(key, "")) for ex in result):
            result.append(item)
    return result


def filter_and_save(
    conn: sqlite3.Connection, items: list[dict], module: str
) -> list[dict]:
    """Lọc trùng với DB + lọc trùng trong batch + lưu mới vào DB."""
    # Bước 1: Lọc trùng trong batch
    unique = deduplicate_news(items)
    # Bước 2: Lọc trùng với DB
    new_items = []
    for item in unique:
        t = item.get("tieu_de", "")
        u = item.get("url", "")
        if not is_in_db(conn, t, u) and not is_similar_in_db(conn, t, module):
            new_items.append(item)
    return new_items


def save_batch(conn: sqlite3.Connection, items: list[dict], module: str):
    """Lưu batch tin vào DB."""
    for item in items:
        save_news(
            conn,
            module,
            item.get("tieu_de", ""),
            item.get("url", ""),
            item.get("nguon", ""),
            item.get("tom_tat", ""),
        )


def fetch_multiple_rss(feeds: dict, max_per_source: int = 3) -> list[dict]:
    all_items = []
    for source, url in feeds.items():
        try:
            # feedparser cần User-Agent để một số site (VTV) trả kết quả
            resp = requests.get(url, headers=HEADERS, timeout=REQUEST_TIMEOUT)
            feed = feedparser.parse(resp.content)
            for entry in feed.entries[:max_per_source]:
                desc = strip_html(entry.get("summary", entry.get("description", "")))
                all_items.append({
                    "nguon": source,
                    "tieu_de": entry.get("title", "").strip(),
                    "mo_ta": desc[:200] + "..." if len(desc) > 200 else desc,
                    "url": entry.get("link", ""),
                })
        except Exception as e:
            print(f"  ⚠ Lỗi RSS {source}: {e}")
    return all_items


# ═══════════════════════════════════════════════
# MODULE 1: TIN TRONG NƯỚC
# ═══════════════════════════════════════════════
RSS_TIN_VN = {
    "VTV Chính trị": "https://vtv.vn/rss/chinh-tri.rss",
    "VTV Xã hội": "https://vtv.vn/rss/xa-hoi.rss",
    "VTV Kinh tế": "https://vtv.vn/rss/kinh-te.rss",
    "VTV Pháp luật": "https://vtv.vn/rss/phap-luat.rss",
}


def fetch_vn_news(conn: sqlite3.Connection, max_total: int = 15) -> list[dict]:
    raw = fetch_multiple_rss(RSS_TIN_VN, 3)
    unique = deduplicate_batch(raw)  # dedup trong batch
    ranked = rank_news(unique, max_total)  # xếp hạng
    ranked = summarize_batch(ranked, "tin tức trong nước")
    log_news_batch(conn, ranked, "tinvn")  # ghi log, không filter
    return ranked


def display_vn_news(conn: sqlite3.Connection):
    print_header("📰 TIN TỨC TRONG NƯỚC")
    ds = fetch_vn_news(conn)
    if not ds:
        print("  Không có tin mới (có thể đã cập nhật trước đó).")
        return
    print(f"  📌 {len(ds)} tin mới\n")
    for i, t in enumerate(ds, 1):
        print(f"  {i}. {t['tieu_de']}")
        print(f"     📌 {t['nguon']}")
        if t.get("tom_tat"):
            print(f"     💡 {t['tom_tat']}")
        elif t.get("mo_ta"):
            print(f"     {t['mo_ta']}")
        print(f"     🔗 {t['url']}")
        print()


# ═══════════════════════════════════════════════
# HỆ THỐNG XẾP HẠNG TIN
# ═══════════════════════════════════════════════

# Từ khóa nóng — xuất hiện trong tiêu đề = tăng điểm
HOT_KEYWORDS = {
    # Địa chính trị / khẩn cấp
    "chiến tranh|war|conflict|invasion|missile|attack|strike": 8,
    "khẩn cấp|emergency|breaking|urgent|crisis": 7,
    "động đất|earthquake|tsunami|hurricane|typhoon|bão": 7,
    "đảo chính|coup|martial law|thiết quân luật": 8,
    # Kinh tế lớn
    "fed|recession|suy thoái|lãi suất|interest rate|tariff|thuế quan": 5,
    "crash|sụp đổ|phá sản|bankrupt|default": 6,
    # Công nghệ
    "AI|GPT|LLM|AGI|trí tuệ nhân tạo|artificial intelligence": 4,
    "hack|breach|leak|lỗ hổng|vulnerability|zero-day": 5,
    # Nhân vật / tổ chức lớn
    "Trump|Biden|Putin|Tập Cận Bình|Xi Jinping|NATO|UN|WHO": 3,
    "Apple|Google|Microsoft|OpenAI|Anthropic|Meta|Tesla|Nvidia": 3,
}

# Điểm uy tín nguồn
SOURCE_CREDIBILITY = {
    # Quốc tế gốc — ưu tiên cao
    "Reuters": 10,
    "AP News": 10,
    "BBC": 9,
    "Al Jazeera": 8,
    "The Guardian": 8,
    "NPR": 8,
    # Báo Việt
    "VnExpress Thế giới": 7,
    "Tuổi Trẻ Thế giới": 7,
    "Thanh Niên Thế giới": 6,
    "VTV Thế giới": 7,
    "Dân Trí Thế giới": 6,
    "Người Lao Động": 6,
    # Mặc định
    "_default": 5,
}


def score_news_item(item: dict) -> float:
    """Chấm điểm 1 tin dựa trên nguồn + từ khóa + metadata."""
    score = 0.0
    source = item.get("nguon", "")
    title = (item.get("tieu_de", "") + " " + item.get("mo_ta", "")).lower()

    # 1) Điểm uy tín nguồn (0-10)
    score += SOURCE_CREDIBILITY.get(source, SOURCE_CREDIBILITY["_default"])

    # 2) Điểm từ khóa nóng
    for pattern, pts in HOT_KEYWORDS.items():
        if re.search(pattern, title, re.IGNORECASE):
            score += pts
            break  # chỉ tính keyword nhóm cao nhất để tránh inflate

    # 3) Điểm HN (nếu có) — normalize score/100
    hn_score = item.get("diem", 0)
    if hn_score:
        score += min(hn_score / 100, 10)  # cap 10 điểm

    # 4) Điểm bình luận HN — nhiều thảo luận = quan trọng
    comments = item.get("binh_luan", 0)
    if comments:
        score += min(comments / 50, 5)  # cap 5 điểm

    return round(score, 1)


def rank_news(items: list[dict], max_items: int = 12) -> list[dict]:
    """Xếp hạng và cắt danh sách tin theo điểm."""
    for item in items:
        item["_score"] = score_news_item(item)
    items.sort(key=lambda x: x["_score"], reverse=True)
    return items[:max_items]


# ═══════════════════════════════════════════════
# MODULE 2: TIN QUỐC TẾ (mở rộng nguồn gốc)
# ═══════════════════════════════════════════════

# Nguồn Việt — giữ nguyên
RSS_TIN_QT_VN = {
    "VnExpress Thế giới": "https://vnexpress.net/rss/the-gioi.rss",
    "Tuổi Trẻ Thế giới": "https://tuoitre.vn/rss/the-gioi.rss",
    "Thanh Niên Thế giới": "https://thanhnien.vn/rss/the-gioi.rss",
    "Dân Trí Thế giới": "https://dantri.com.vn/rss/the-gioi.rss",
    "VTV Thế giới": "https://vtv.vn/rss/the-gioi.rss",
    "Người Lao Động": "https://nld.com.vn/rss/quoc-te.rss",
}

# Nguồn quốc tế gốc — tiếng Anh, cần Việt hóa
RSS_TIN_QT_INTL = {
    "Reuters": "https://feeds.reuters.com/reuters/topNews",
    "AP News": "https://rsshub.app/apnews/topics/world-news",
    "BBC": "https://feeds.bbci.co.uk/news/world/rss.xml",
    "Al Jazeera": "https://www.aljazeera.com/xml/rss/all.xml",
    "The Guardian": "https://www.theguardian.com/world/rss",
    "NPR": "https://feeds.npr.org/1004/rss.xml",
}


def fetch_world_news(conn: sqlite3.Connection, max_total: int = 15) -> list[dict]:
    vn_items = fetch_multiple_rss(RSS_TIN_QT_VN, 3)
    intl_items = fetch_multiple_rss(RSS_TIN_QT_INTL, 3)
    for item in intl_items:
        item["can_dich"] = True

    all_items = deduplicate_batch(vn_items + intl_items)
    ranked = rank_news(all_items, max_total)

    vn_batch = [i for i in ranked if not i.get("can_dich")]
    en_batch = [i for i in ranked if i.get("can_dich")]
    if vn_batch:
        vn_batch = summarize_batch(vn_batch, "tin quốc tế")
    if en_batch:
        en_batch = summarize_batch(en_batch, "tin quốc tế", viet_hoa=True)

    result = sorted(vn_batch + en_batch, key=lambda x: x.get("_score", 0), reverse=True)
    log_news_batch(conn, result, "tinqt")
    return result


def display_world_news(conn: sqlite3.Connection):
    print_header("🌍 TIN TỨC QUỐC TẾ")
    ds = fetch_world_news(conn)
    if not ds:
        print("  Không có tin mới.")
        return
    print(f"  📌 {len(ds)} tin mới (xếp theo độ quan trọng)\n")
    for i, t in enumerate(ds, 1):
        score_bar = "🔥" * min(int(t.get("_score", 0) / 5), 5)
        is_intl = t.get("can_dich", False)
        flag = "🌐" if is_intl else "🇻🇳"

        title_vi = t.get("tieu_de_vi", "")
        if title_vi:
            print(f"  {i}. {flag} {title_vi}")
            print(f"     📝 {t['tieu_de']}")
        else:
            print(f"  {i}. {flag} {t['tieu_de']}")

        print(f"     📌 {t['nguon']} {score_bar}")
        if t.get("tom_tat"):
            print(f"     💡 {t['tom_tat']}")
        elif t.get("mo_ta"):
            print(f"     {t['mo_ta']}")
        print(f"     🔗 {t['url']}")
        print()


# ═══════════════════════════════════════════════
# MODULE 3: GIÁ VÀNG
# ═══════════════════════════════════════════════
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
    "VIETTINMSJC": "Việt Tín SJC",
    "VNGSJC": "VN Gold SJC",
}
GOLD_PRIORITY = ["SJL1L10", "SJ9999", "DOHNL", "PQHNVM", "BT9999NTT", "XAUUSD"]


def fetch_gold_price(conn: sqlite3.Connection) -> dict:
    resp = safe_get(GOLD_API_URL)
    if not resp:
        return {}
    try:
        data = resp.json()
        if data.get("success"):
            log_gold_prices(conn, data)  # ghi từng loại vàng riêng
            return data
        return {}
    except Exception as e:
        print(f"  ⚠ Lỗi đọc giá vàng: {e}")
        return {}


def display_gold_price(conn: sqlite3.Connection):
    print_header("💰 GIÁ VÀNG")
    data = fetch_gold_price(conn)
    if not data:
        print("  Không lấy được giá vàng.")
        return
    print(f"  🕐 Cập nhật: {data.get('time', '')} — {data.get('date', '')}\n")
    prices = data.get("prices", {})
    shown = set()
    for code in GOLD_PRIORITY:
        if code in prices:
            _print_gold(code, prices[code])
            shown.add(code)
    for code, v in prices.items():
        if code not in shown:
            _print_gold(code, v)


def _print_gold(code: str, v: dict):
    name = GOLD_NAME_MAP.get(code, v.get("name", code))
    buy, sell = v.get("buy", 0), v.get("sell", 0)
    chg = v.get("change_sell", 0)
    cur = v.get("currency", "VND")
    if cur == "VND" and buy > 0:
        arrow = f" {'📈' if chg > 0 else '📉'} {chg / 1e6:+.1f} triệu" if chg else ""
        print(f"  {name}")
        print(
            f"    Mua: {format_vnd(buy)}  |  Bán: {format_vnd(sell) if sell else '—'}{arrow}\n"
        )
    elif cur == "USD" and buy > 0:
        c = v.get("change_buy", 0)
        print(f"  {name}")
        print(
            f"    Giá: ${buy:,.1f}/oz  {'📈' if c > 0 else '📉' if c < 0 else '➡️'} {c:+.1f} USD\n"
        )


# ═══════════════════════════════════════════════
# MODULE 4: CRYPTO
# ═══════════════════════════════════════════════
CRYPTO_IDS = ["bitcoin", "ethereum", "solana", "binancecoin", "ripple", "dogecoin"]
CRYPTO_SYM = {
    "bitcoin": "BTC",
    "ethereum": "ETH",
    "solana": "SOL",
    "binancecoin": "BNB",
    "ripple": "XRP",
    "dogecoin": "DOGE",
}
CG_URL = "https://api.coingecko.com/api/v3/simple/price"


def fetch_crypto_prices(conn: sqlite3.Connection) -> list[dict]:
    params = {
        "ids": ",".join(CRYPTO_IDS),
        "vs_currencies": "usd,vnd",
        "include_24hr_change": "true",
        "include_market_cap": "true",
        "include_24hr_vol": "true",
    }
    resp = safe_get(CG_URL, params=params)
    if not resp:
        return []
    try:
        data = resp.json()
        items = [
            {
                "ky_hieu": CRYPTO_SYM.get(c, c.upper()),
                "usd": data[c].get("usd", 0),
                "vnd": data[c].get("vnd", 0),
                "thay_doi": data[c].get("usd_24h_change", 0),
                "von_hoa": data[c].get("usd_market_cap", 0),
                "kl": data[c].get("usd_24h_vol", 0),
            }
            for c in CRYPTO_IDS
            if c in data
        ]
        log_crypto_prices(conn, items)  # ghi từng coin riêng
        return items
    except Exception as e:
        print(f"  ⚠ Lỗi CoinGecko: {e}")
        return []


def display_crypto_prices(conn: sqlite3.Connection):
    print_header("🪙 GIÁ TIỀN ĐIỆN TỬ")
    ds = fetch_crypto_prices(conn)
    if not ds:
        print("  Không lấy được giá.")
        return
    print(f"  {'Coin':<6} {'Giá (USD)':>12} {'24h':>10} {'Vốn hóa':>10} {'KL 24h':>10}")
    print(f"  {'─' * 54}")
    for c in ds:
        arr = "📈" if c["thay_doi"] >= 0 else "📉"
        print(
            f"  {c['ky_hieu']:<6} ${c['usd']:>11,.2f} {arr} {c['thay_doi']:+.1f}%".ljust(
                36
            )
            + f"{format_number(c['von_hoa'], '$'):>10} {format_number(c['kl'], '$'):>10}"
        )
    btc = next((c for c in ds if c["ky_hieu"] == "BTC"), None)
    if btc and btc["vnd"]:
        print(f"\n  💱 1 BTC = {btc['vnd']:,.0f} VNĐ")


# ═══════════════════════════════════════════════
# MODULE 5: GITHUB TRENDING
# ═══════════════════════════════════════════════
GH_URL = "https://github.com/trending"


def fetch_github_trending(
    conn: sqlite3.Connection, language: str = "", limit: int = 10
) -> list[dict]:
    url = f"{GH_URL}/{language}" if language else GH_URL
    resp = safe_get(url, params={"since": "daily"})
    if not resp:
        return []
    try:
        soup = BeautifulSoup(resp.text, "html.parser")
        repos = []
        for art in soup.select("article.Box-row")[:limit]:
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
            repos = summarize_batch(repos, "dự án GitHub", key="ten", viet_hoa=True)
        log_news_batch(conn, repos, "github")
        return repos
    except Exception as e:
        print(f"  ⚠ Lỗi GitHub: {e}")
        return []


def display_github_trending(conn: sqlite3.Connection):
    print_header("🔥 GITHUB TRENDING HÔM NAY")
    repos = fetch_github_trending(conn, limit=10)
    if not repos:
        print("  Không lấy được GitHub trending.")
        return
    for i, r in enumerate(repos, 1):
        nn = f"[{r['ngon_ngu']}]" if r["ngon_ngu"] else ""
        s = f"⭐ {r['sao']}" if r["sao"] else ""
        hn = f"(+{r['hom_nay']})" if r["hom_nay"] else ""
        title_vi = r.get("tieu_de_vi", "")
        print(f"  {i:>2}. {r['ten']} {nn}")
        if title_vi:
            print(f"      📝 {title_vi}")
        if r.get("tom_tat"):
            print(f"      💡 {r['tom_tat']}")
        elif r.get("mo_ta"):
            print(f"      {r['mo_ta']}")
        print(f"      {s} {hn}")
        print(f"      🔗 {r['url']}\n")

    print(f"  {'─' * 40}\n  🐍 Top 5 Python đang nổi:\n")
    # ← save_to_db=False: chỉ hiển thị, không lọc DB
    py_repos = fetch_github_trending(conn, language="python", limit=5, save_to_db=False)
    for i, r in enumerate(py_repos, 1):
        s = f"⭐ {r['sao']}" if r["sao"] else ""
        title_vi = r.get("tieu_de_vi", "")
        print(f"  {i}. {r['ten']} {s}")
        if title_vi:
            print(f"     📝 {title_vi}")
        if r.get("tom_tat"):
            print(f"     💡 {r['tom_tat']}")
        elif r.get("mo_ta"):
            print(f"     {r['mo_ta']}")
        print()


# ═══════════════════════════════════════════════
# MODULE 6: TIN CÔNG NGHỆ
# ═══════════════════════════════════════════════
HN_TOP = "https://hacker-news.firebaseio.com/v0/topstories.json"
HN_ITEM = "https://hacker-news.firebaseio.com/v0/item/{}.json"


def fetch_hacker_news(conn: sqlite3.Connection, limit: int = 10) -> list[dict]:
    resp = safe_get(HN_TOP)
    if not resp:
        return []
    try:
        ds = []
        for sid in resp.json()[: limit * 3]:
            if len(ds) >= limit * 2:
                break
            r = safe_get(HN_ITEM.format(sid))
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
        ds = rank_news(ds, max_items=limit)
        ds = summarize_batch(ds, "bài viết công nghệ", viet_hoa=True)
        log_news_batch(conn, ds, "hacker_news")
        return ds
    except Exception as e:
        print(f"  ⚠ Lỗi HN: {e}")
        return []


def display_tech_news(conn: sqlite3.Connection):
    print_header("💻 TIN CÔNG NGHỆ — HACKER NEWS")
    hn = fetch_hacker_news(conn, 10)
    if not hn:
        print("  Không có bài mới từ Hacker News.")
        return
    ai_on = "" if GEMINI_API_KEY else "⚠ Chưa có GEMINI_API_KEY — hiển thị tiếng Anh"
    if ai_on:
        print(f"  {ai_on}")
    print(f"  📌 {len(hn)} bài mới (xếp theo độ hot)\n")
    for i, b in enumerate(hn, 1):
        score_bar = "🔥" * min(int(b.get("_score", 0) / 5), 5)
        title_vi = b.get("tieu_de_vi", "")
        if title_vi:
            print(f"  {i}. {title_vi}")
            print(f"     📝 {b['tieu_de']}")
        else:
            print(f"  {i}. {b['tieu_de']}")
        if b.get("tom_tat"):
            print(f"     💡 {b['tom_tat']}")
        print(
            f"     {score_bar} {b['diem']} điểm · 💬 {b['binh_luan']} bình luận · bởi {b['tac_gia']}"
        )
        if b.get("url"):
            print(f"     🔗 {b['url']}")
        print(f"     💬 {b.get('hn_url', '')}\n")


# ═══════════════════════════════════════════════
# TỔNG HỢP
# ═══════════════════════════════════════════════
def display_full_bulletin(conn: sqlite3.Connection):
    now = datetime.now()
    print()
    print(" ╔══════════════════════════════════════════════════╗")
    print(" ║       📋 BẢN TIN TỔNG HỢP                        ║")
    print(f"║  🕐 {now.strftime('%H:%M — %d/%m/%Y'):>44}       ║")
    print(" ╚══════════════════════════════════════════════════╝")

    for name, fn in [
        ("Giá vàng", display_gold_price),
        ("Crypto", display_crypto_prices),
        ("Tin trong nước", display_vn_news),
        ("Tin quốc tế", display_world_news),
        ("GitHub Trending", display_github_trending),
        ("Tin công nghệ", display_tech_news),
    ]:
        try:
            fn(conn)
        except Exception as e:
            print(f"\n  ❌ Lỗi {name}: {e}")

    stats = get_db_stats(conn)
    print(f"\n{'═' * 50}")
    print(f"  ✅ Hoàn tất — {datetime.now().strftime('%H:%M:%S')}")
    print(
        f"  📊 DB: {stats['tong']} tin tổng | {stats['hom_nay']} tin hôm nay | {stats['lich_su_gia']} bản ghi giá"
    )
    print(f"{'═' * 50}")


def display_stats(conn: sqlite3.Connection):
    print_header("📊 THỐNG KÊ DATABASE")
    s = get_db_stats(conn)
    print(f"  📁 File: {DB_PATH}")
    print(f"  📰 Tổng tin: {s['tong']}")
    print(f"  📅 Hôm nay: {s['hom_nay']}")
    print(f"  💰 Lịch sử giá: {s['lich_su_gia']} bản ghi\n")
    print("  Theo module:")
    for mod, cnt in s["theo_module"].items():
        print(f"    {mod}: {cnt}")


# ═══════════════════════════════════════════════
# CLI
# ═══════════════════════════════════════════════
MODULE_MAP = {
    "vang": ("💰 Giá vàng", display_gold_price),
    "crypto": ("🪙 Crypto", display_crypto_prices),
    "tinvn": ("📰 Tin trong nước", display_vn_news),
    "tinqt": ("🌍 Tin quốc tế", display_world_news),
    "github": ("🔥 GitHub", display_github_trending),
    "congnghe": ("💻 Công nghệ", display_tech_news),
}


def main():
    parser = argparse.ArgumentParser(
        description="📋 Bản Tin Tổng Hợp",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "--module",
        "-m",
        type=str,
        help="Module: vang, crypto, tinvn, tinqt, github, congnghe",
    )
    parser.add_argument("--all", "-a", action="store_true", help="Bản tin đầy đủ")
    parser.add_argument("--json", "-j", action="store_true", help="Xuất JSON")
    parser.add_argument("--stats", "-s", action="store_true", help="Thống kê DB")
    parser.add_argument("--reset-db", action="store_true", help="Xóa toàn bộ DB")
    args = parser.parse_args()

    # Load .env nếu có
    env_file = Path(__file__).parent / ".env"
    if env_file.exists():
        for line in env_file.read_text().splitlines():
            if "=" in line and not line.startswith("#"):
                k, v = line.split("=", 1)
                os.environ.setdefault(k.strip(), v.strip())
    global GEMINI_API_KEY
    GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY", "")

    conn = init_db()

    if args.reset_db:
        conn.execute("DELETE FROM news_history")
        conn.execute("DELETE FROM price_history")
        conn.commit()
        print("✅ Đã xóa toàn bộ DB.")
        conn.close()
        return

    if args.stats:
        display_stats(conn)
        conn.close()
        return

    if args.json:
        data = {}
        print("Đang thu thập...", file=sys.stderr)
        data["vang"] = fetch_gold_price(conn)
        data["crypto"] = fetch_crypto_prices(conn)
        data["tin_vn"] = fetch_vn_news(conn)
        data["tin_qt"] = fetch_world_news(conn)
        data["github"] = fetch_github_trending(conn)
        data["hacker_news"] = fetch_hacker_news(conn)
        data["thoi_gian"] = datetime.now(timezone.utc).isoformat()
        print(json.dumps(data, ensure_ascii=False, indent=2))
        conn.close()
        return

    if args.module:
        if args.module in MODULE_MAP:
            label, fn = MODULE_MAP[args.module]
            print(f"\n⏳ Đang lấy {label}...")
            fn(conn)
        else:
            print(
                f"❌ Không có module: {args.module}\n   Có: {', '.join(MODULE_MAP.keys())}"
            )
        conn.close()
        return

    if args.all:
        display_full_bulletin(conn)
        conn.close()
        return

    # Menu tương tác
    print()
    print("╔═════════════════════════════════╗")
    print("║       📋 BẢN TIN TỔNG HỢP       ║")
    print("╚═════════════════════════════════╝")
    print()
    print("  1. 💰 Giá vàng")
    print("  2. 🪙 Tiền điện tử")
    print("  3. 📰 Tin trong nước")
    print("  4. 🌍 Tin quốc tế")
    print("  5. 🔥 GitHub Trending")
    print("  6. 💻 Tin công nghệ")
    print("  7. 📋 TẤT CẢ")
    print("  8. 📊 Thống kê DB")
    print("  0. ❌ Thoát")
    print()

    actions = {
        "1": display_gold_price,
        "2": display_crypto_prices,
        "3": display_vn_news,
        "4": display_world_news,
        "5": display_github_trending,
        "6": display_tech_news,
        "7": display_full_bulletin,
        "8": display_stats,
    }

    while True:
        try:
            c = input("  Chọn (0-8): ").strip()
        except (EOFError, KeyboardInterrupt):
            print("\n  👋 Tạm biệt!")
            break
        if c == "0":
            print("  👋 Tạm biệt!")
            break
        elif c in actions:
            print("\n  ⏳ Đang tải...")
            actions[c](conn)
            print()
        else:
            print("  ⚠ Không hợp lệ.")

    conn.close()


if __name__ == "__main__":
    main()
