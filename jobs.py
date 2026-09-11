import asyncio
import json
import math
import re
from datetime import date, datetime, timezone
from html import unescape
from itertools import zip_longest
from urllib.parse import unquote

from bs4 import BeautifulSoup

import state
from config import (
    CRYPTO_SYM,
    CRYPTO_SYMBOLS,
    DEVBLOG_LIMIT,
    DEVBLOG_PER_SOURCE,
    GITHUB_TRENDING_LANGS,
    GITHUB_TRENDING_URL,
    GOLD_API_URL,
    GOLD_NAME_MAP,
    GOLD_PRIORITY,
    HN_ITEM,
    HN_TOP,
    JOBS_LIMIT,
    OIL_URL,
    OKX_TICKER_URL,
    RSS_DEV_BLOGS,
    RSS_TIN_QT_INTL,
    RSS_TIN_QT_VN,
    RSS_TIN_VN,
    TECH_EVENTS,
    UBER_BLOG_URL,
    VN30,
)
from db import log_crypto_prices, log_gold_prices, log_news_batch
from mcp_client import call_tool
from utils import deduplicate_batch, fetch_multiple_rss, rank_news, safe_get, strip_html


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
            formatted.append(
                {
                    "code": code,
                    "name": GOLD_NAME_MAP.get(code, v.get("name", code)),
                    "buy": v.get("buy", 0),
                    "sell": v.get("sell", 0),
                    "change_sell": v.get("change_sell", 0),
                    "change_buy": v.get("change_buy", 0),
                    "currency": v.get("currency", "VND"),
                }
            )
        state.cache["gold"] = {
            "data": formatted,
            "time": data.get("time", ""),
            "date": data.get("date", ""),
            "updated_at": datetime.now(timezone.utc).isoformat(),
        }
        await log_gold_prices(data)
    except Exception as e:
        print(f"  ⚠ gold: {e}")


async def job_fetch_crypto():
    responses = await asyncio.gather(
        *(safe_get(f"{OKX_TICKER_URL}?instId={sym}") for sym in CRYPTO_SYMBOLS)
    )
    items = []
    for sym, resp in zip(CRYPTO_SYMBOLS, responses):
        if not resp:
            continue
        try:
            ticker = (resp.json().get("data") or [None])[0]
            if not ticker:
                continue
            last = float(ticker["last"])
            open24h = float(ticker.get("open24h") or 0)
            items.append(
                {
                    "ky_hieu": CRYPTO_SYM.get(sym, sym),
                    "usd": last,
                    "vnd": 0,
                    "thay_doi": round((last - open24h) / open24h * 100, 2)
                    if open24h
                    else 0,
                    "von_hoa": 0,
                    "kl": float(ticker.get("volCcy24h") or 0),
                }
            )
        except Exception as e:
            print(f"  ⚠ crypto {sym}: {e}")
    if not items:
        return
    state.cache["crypto"] = {
        "data": items,
        "updated_at": datetime.now(timezone.utc).isoformat(),
    }
    await log_crypto_prices(items)


async def job_fetch_vn_news():
    print(f"[{datetime.now():%H:%M:%S}] vn_news...")
    raw = await fetch_multiple_rss(RSS_TIN_VN, 3)
    unique = deduplicate_batch(raw)
    ranked = rank_news(unique, 15)
    state.cache["vn_news"] = {
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
    result = sorted(vn_b + en_b, key=lambda x: x.get("_score", 0), reverse=True)
    state.cache["world_news"] = {
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
            ds.append(
                {
                    "tieu_de": item.get("title", ""),
                    "url": item.get("url", ""),
                    "hn_url": f"https://news.ycombinator.com/item?id={sid}",
                    "diem": item.get("score", 0),
                    "binh_luan": item.get("descendants", 0),
                    "tac_gia": item.get("by", ""),
                }
            )
        ds = rank_news(ds, 10)
        state.cache["tech_news"] = {
            "data": ds,
            "updated_at": datetime.now(timezone.utc).isoformat(),
        }
        await log_news_batch(ds, "hacker_news")
    except Exception as e:
        print(f"  ⚠ HN: {e}")


def _parse_trending(html, limit):
    soup = BeautifulSoup(html, "html.parser")
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
        repos.append(
            {
                "ten": name,
                "tieu_de": name,
                "mo_ta": desc[:150],
                "ngon_ngu": lang,
                "sao": stars,
                "hom_nay": today,
                "url": f"https://github.com/{name}",
            }
        )
    return repos


async def job_fetch_github():
    print(f"[{datetime.now():%H:%M:%S}] github...")
    responses = await asyncio.gather(
        *(
            safe_get(f"{GITHUB_TRENDING_URL}/{lang}", params={"since": "daily"})
            for lang in GITHUB_TRENDING_LANGS
        )
    )
    repos = []
    seen = set()
    for (lang, limit), resp in zip(GITHUB_TRENDING_LANGS.items(), responses):
        if not resp:
            continue
        try:
            for repo in _parse_trending(resp.text, limit):
                if repo["ten"] in seen:
                    continue
                seen.add(repo["ten"])
                repos.append(repo)
        except Exception as e:
            print(f"  ⚠ github {lang or 'all'}: {e}")
    if not repos:
        return
    state.cache["github"] = {
        "data": repos,
        "updated_at": datetime.now(timezone.utc).isoformat(),
    }
    await log_news_batch(repos, "github")


async def job_fetch_forex():
    print(f"[{datetime.now():%H:%M:%S}] forex...")
    today_str = datetime.now().strftime("%Y-%m-%d")
    resp = await safe_get(
        f"https://www.vietcombank.com.vn/api/exchangerates?date={today_str}",
        headers={"Referer": "https://www.vietcombank.com.vn/"},
    )
    if not resp:
        return
    try:
        data = resp.json()
        priority = [
            "USD",
            "EUR",
            "GBP",
            "JPY",
            "CNY",
            "KRW",
            "SGD",
            "THB",
            "AUD",
            "CAD",
        ]
        all_rates = {}
        for ex in data.get("Data", []):
            code = ex.get("currencyCode", "").strip()
            if not code:
                continue
            all_rates[code] = {
                "ma": code,
                "mua_tm": float((ex.get("cash") or "0").replace(",", "")),
                "mua_ck": float((ex.get("transfer") or "0").replace(",", "")),
                "ban": float((ex.get("sell") or "0").replace(",", "")),
            }
        items = [all_rates[c] for c in priority if c in all_rates]
        items += [v for c, v in all_rates.items() if c not in priority]
        state.cache["forex"] = {
            "data": items[:15],
            "updated_at": datetime.now(timezone.utc).isoformat(),
        }
    except Exception as e:
        print(f"  ⚠ forex: {e}")


async def job_fetch_stock():
    print(f"[{datetime.now():%H:%M:%S}] stock...")
    resp = await safe_get("https://banggia.cafef.vn/stockhandler.ashx?center=1")
    if not resp:
        return
    try:
        data = resp.json()
        vn30_set = set(VN30)
        items = []
        for row in data:
            ma = row.get("a", "")
            if ma not in vn30_set:
                continue
            gia = row.get("l", 0)
            thay_doi = row.get("k", 0)
            phan_tram = (
                round((thay_doi / (gia - thay_doi)) * 100, 2) if (gia - thay_doi) else 0
            )
            items.append(
                {
                    "ma": ma,
                    "gia": gia,
                    "thay_doi": thay_doi,
                    "phan_tram": phan_tram,
                    "kl": row.get("n", 0),
                }
            )
        items.sort(key=lambda x: x["ma"])
        state.cache["stock"] = {
            "data": items,
            "updated_at": datetime.now(timezone.utc).isoformat(),
        }
    except Exception as e:
        print(f"  ⚠ stock: {e}")


def _parse_vnd(text):
    digits = re.sub(r"[^\d]", "", text)
    if not digits:
        return 0
    value = int(digits)
    return -value if ("-" in text or "▼" in text) else value


async def job_fetch_oil():
    print(f"[{datetime.now():%H:%M:%S}] oil...")
    resp = await safe_get(OIL_URL)
    if not resp:
        return
    try:
        soup = BeautifulSoup(resp.text, "html.parser")
        table = next(
            (t for t in soup.select("table") if "vùng 1" in t.get_text().lower()), None
        )
        if not table:
            print("  ⚠ oil: không tìm thấy bảng giá")
            return
        items = []
        for row in table.select("tr"):
            # Cột: tên | thay đổi so với hôm qua | thay đổi kỳ gần nhất | vùng 1 | vùng 2
            cols = [td.get_text(strip=True) for td in row.select("td")]
            if len(cols) < 4:
                continue
            gia = _parse_vnd(cols[3])
            if not gia:
                continue
            chg = _parse_vnd(cols[2])
            pct = round((chg / (gia - chg)) * 100, 2) if (gia - chg) else 0
            items.append(
                {
                    "ten": cols[0],
                    "gia": gia,
                    "thay_doi": chg,
                    "phan_tram": pct,
                }
            )
        if items:
            state.cache["oil"] = {
                "data": items,
                "updated_at": datetime.now(timezone.utc).isoformat(),
            }
    except Exception as e:
        print(f"  ⚠ oil: {e}")


async def job_fetch_weather():
    print(f"[{datetime.now():%H:%M:%S}] weather...")
    cities = ["Hanoi", "HoChiMinh", "DaNang", "HaiPhong", "CanTho"]
    city_names = {
        "Hanoi": "Hà Nội",
        "HoChiMinh": "TP.HCM",
        "DaNang": "Đà Nẵng",
        "HaiPhong": "Hải Phòng",
        "CanTho": "Cần Thơ",
    }
    items = []
    for city in cities:
        resp = await safe_get(f"https://wttr.in/{city}?format=j1")
        if not resp:
            continue
        try:
            d = resp.json()
            cur = d["current_condition"][0]
            items.append(
                {
                    "thanh_pho": city_names.get(city, city),
                    "nhiet_do": int(cur["temp_C"]),
                    "cam_giac": int(cur["FeelsLikeC"]),
                    "do_am": int(cur["humidity"]),
                    "mo_ta": cur["lang_vi"][0]["value"]
                    if cur.get("lang_vi")
                    else cur["weatherDesc"][0]["value"],
                    "icon": cur["weatherCode"],
                    "gio": round(int(cur["windspeedKmph"]), 1),
                }
            )
        except Exception:
            pass
    if items:
        state.cache["weather"] = {
            "data": items,
            "updated_at": datetime.now(timezone.utc).isoformat(),
        }


LUNAR_TZ = 7.0
CAN = ["Giáp", "Ất", "Bính", "Đinh", "Mậu", "Kỷ", "Canh", "Tân", "Nhâm", "Quý"]
CHI = [
    "Tý",
    "Sửu",
    "Dần",
    "Mão",
    "Thìn",
    "Tỵ",
    "Ngọ",
    "Mùi",
    "Thân",
    "Dậu",
    "Tuất",
    "Hợi",
]
THU = ["Chủ Nhật", "Thứ Hai", "Thứ Ba", "Thứ Tư", "Thứ Năm", "Thứ Sáu", "Thứ Bảy"]
# Mười hai sao xếp vòng quanh 12 chi, bắt đầu từ vị trí khởi Thanh Long.
# Vị trí khởi phụ thuộc chi của ngày (khi xét giờ) hoặc chi của tháng (khi xét ngày).
SAO_12 = [
    "Thanh Long",
    "Minh Đường",
    "Thiên Hình",
    "Chu Tước",
    "Kim Quỹ",
    "Thiên Đức",
    "Bạch Hổ",
    "Ngọc Đường",
    "Thiên Lao",
    "Nguyên Vũ",
    "Tư Mệnh",
    "Câu Trần",
]
SAO_HOANG_DAO = (0, 1, 4, 5, 7, 10)
# 30 cặp can chi liên tiếp dùng chung một nạp âm ngũ hành.
NAP_AM = [
    "Hải Trung Kim",
    "Lư Trung Hỏa",
    "Đại Lâm Mộc",
    "Lộ Bàng Thổ",
    "Kiếm Phong Kim",
    "Sơn Đầu Hỏa",
    "Giản Hạ Thủy",
    "Thành Đầu Thổ",
    "Bạch Lạp Kim",
    "Dương Liễu Mộc",
    "Tuyền Trung Thủy",
    "Ốc Thượng Thổ",
    "Tích Lịch Hỏa",
    "Tùng Bách Mộc",
    "Trường Lưu Thủy",
    "Sa Trung Kim",
    "Sơn Hạ Hỏa",
    "Bình Địa Mộc",
    "Bích Thượng Thổ",
    "Kim Bạch Kim",
    "Phú Đăng Hỏa",
    "Thiên Hà Thủy",
    "Đại Trạch Thổ",
    "Thoa Xuyến Kim",
    "Tang Đố Mộc",
    "Đại Khê Thủy",
    "Sa Trung Thổ",
    "Thiên Thượng Hỏa",
    "Thạch Lựu Mộc",
    "Đại Hải Thủy",
]
# 24 tiết khí theo kinh độ mặt trời, mốc 0° là Xuân Phân.
TIET_KHI = [
    "Xuân Phân",
    "Thanh Minh",
    "Cốc Vũ",
    "Lập Hạ",
    "Tiểu Mãn",
    "Mang Chủng",
    "Hạ Chí",
    "Tiểu Thử",
    "Đại Thử",
    "Lập Thu",
    "Xử Thử",
    "Bạch Lộ",
    "Thu Phân",
    "Hàn Lộ",
    "Sương Giáng",
    "Lập Đông",
    "Tiểu Tuyết",
    "Đại Tuyết",
    "Đông Chí",
    "Tiểu Hàn",
    "Đại Hàn",
    "Lập Xuân",
    "Vũ Thủy",
    "Kinh Trập",
]
LE_DUONG_LICH = [
    (1, 1, "Tết Dương lịch"),
    (30, 4, "Giải phóng miền Nam"),
    (1, 5, "Quốc tế Lao động"),
    (2, 9, "Quốc khánh"),
]


def _jd_from_date(dd, mm, yy):
    a = (14 - mm) // 12
    y = yy + 4800 - a
    m = mm + 12 * a - 3
    return dd + (153 * m + 2) // 5 + 365 * y + y // 4 - y // 100 + y // 400 - 32045


def _jd_to_date(jdn):
    a = jdn + 32044
    b = (4 * a + 3) // 146097
    c = a - (b * 146097) // 4
    d = (4 * c + 3) // 1461
    e = c - (1461 * d) // 4
    m = (5 * e + 2) // 153
    return date(
        b * 100 + d - 4800 + m // 10, m + 3 - 12 * (m // 10), e - (153 * m + 2) // 5 + 1
    )


def _new_moon(k):
    """Thời điểm sóc thứ k tính theo ngày Julius (giờ UTC)."""
    T = k / 1236.85
    T2 = T * T
    T3 = T2 * T
    dr = math.pi / 180
    Jd1 = 2415020.75933 + 29.53058868 * k + 0.0001178 * T2 - 0.000000155 * T3
    Jd1 += 0.00033 * math.sin((166.56 + 132.87 * T - 0.009173 * T2) * dr)
    M = 359.2242 + 29.10535608 * k - 0.0000333 * T2 - 0.00000347 * T3
    Mpr = 306.0253 + 385.81691806 * k + 0.0107306 * T2 + 0.00001236 * T3
    F = 21.2964 + 390.67050646 * k - 0.0016528 * T2 - 0.00000239 * T3
    C1 = (0.1734 - 0.000393 * T) * math.sin(M * dr) + 0.0021 * math.sin(2 * dr * M)
    C1 -= 0.4068 * math.sin(Mpr * dr) - 0.0161 * math.sin(dr * 2 * Mpr)
    C1 -= 0.0004 * math.sin(dr * 3 * Mpr) - 0.0104 * math.sin(dr * 2 * F)
    C1 -= 0.0051 * math.sin(dr * (M + Mpr)) + 0.0074 * math.sin(dr * (M - Mpr))
    C1 += 0.0004 * math.sin(dr * (2 * F + M)) - 0.0004 * math.sin(dr * (2 * F - M))
    C1 -= 0.0006 * math.sin(dr * (2 * F + Mpr)) - 0.001 * math.sin(dr * (2 * F - Mpr))
    C1 += 0.0005 * math.sin(dr * (2 * Mpr + M))
    delta_t = 0.5 / 1440 if T < -11 else 0
    return Jd1 + C1 - delta_t


def _sun_longitude(jdn):
    """Kinh độ mặt trời (radian, đã chuẩn hoá về 0..2π)."""
    T = (jdn - 2451545.0) / 36525
    T2 = T * T
    dr = math.pi / 180
    M = 357.5291 + 35999.0503 * T - 0.0001559 * T2 - 0.00000048 * T * T2
    L0 = 280.46646 + 36000.76983 * T + 0.0003032 * T2
    C = (1.9146 - 0.004817 * T - 0.000014 * T2) * math.sin(dr * M)
    C += (0.019993 - 0.000101 * T) * math.sin(dr * 2 * M) + 0.00029 * math.sin(
        dr * 3 * M
    )
    omega = 125.04 - 1934.136 * T
    lon = (L0 + C - 0.00569 - 0.00478 * math.sin(omega * dr)) * dr
    return lon - math.pi * 2 * int(lon / (math.pi * 2))


def _new_moon_day(k):
    """Ngày (múi giờ Việt Nam) chứa điểm sóc thứ k."""
    return int(_new_moon(k) + 0.5 + LUNAR_TZ / 24)


def _sun_longitude_slot(day_number):
    return int(_sun_longitude(day_number - 0.5 - LUNAR_TZ / 24) / math.pi * 6)


def _lunar_month11(yy):
    off = _jd_from_date(31, 12, yy) - 2415021
    k = int(off / 29.530588853)
    nm = _new_moon_day(k)
    if _sun_longitude_slot(nm) >= 9:
        nm = _new_moon_day(k - 1)
    return nm


def _leap_month_offset(a11):
    k = int((a11 - 2415021.076998695) / 29.530588853 + 0.5)
    i = 1
    arc = _sun_longitude_slot(_new_moon_day(k + i))
    while True:
        last = arc
        i += 1
        arc = _sun_longitude_slot(_new_moon_day(k + i))
        if arc == last or i >= 14:
            break
    return i - 1


def solar_to_lunar(dd, mm, yy):
    """Đổi ngày dương sang âm lịch Việt Nam, trả về (ngày, tháng, năm, nhuận)."""
    day_number = _jd_from_date(dd, mm, yy)
    k = int((day_number - 2415021.076998695) / 29.530588853)
    month_start = _new_moon_day(k + 1)
    if month_start > day_number:
        month_start = _new_moon_day(k)
    a11 = _lunar_month11(yy)
    b11 = a11
    if a11 >= month_start:
        lunar_year = yy
        a11 = _lunar_month11(yy - 1)
    else:
        lunar_year = yy + 1
        b11 = _lunar_month11(yy + 1)
    lunar_day = day_number - month_start + 1
    diff = int((month_start - a11) / 29)
    leap = 0
    lunar_month = diff + 11
    if b11 - a11 > 365:
        leap_off = _leap_month_offset(a11)
        if diff >= leap_off:
            lunar_month = diff + 10
            if diff == leap_off:
                leap = 1
    if lunar_month > 12:
        lunar_month -= 12
    if lunar_month >= 11 and diff < 4:
        lunar_year -= 1
    return lunar_day, lunar_month, lunar_year, leap


def lunar_to_solar(lunar_day, lunar_month, lunar_year, leap=0):
    """Đổi ngày âm lịch Việt Nam sang ngày dương lịch."""
    if lunar_month < 11:
        a11 = _lunar_month11(lunar_year - 1)
        b11 = _lunar_month11(lunar_year)
    else:
        a11 = _lunar_month11(lunar_year)
        b11 = _lunar_month11(lunar_year + 1)
    off = lunar_month - 11
    if off < 0:
        off += 12
    if b11 - a11 > 365:
        leap_off = _leap_month_offset(a11)
        leap_month = leap_off - 2
        if leap_month < 0:
            leap_month += 12
        if leap and lunar_month != leap_month:
            return None
        if leap or off >= leap_off:
            off += 1
    k = int(0.5 + (a11 - 2415021.076998695) / 29.530588853)
    return _jd_to_date(_new_moon_day(k + off) + lunar_day - 1)


def _le_sap_toi(today, days_ahead=120):
    upcoming = []
    for year in (today.year, today.year + 1):
        days = [(date(year, m, d), ten) for d, m, ten in LE_DUONG_LICH]
        gio_to = lunar_to_solar(10, 3, year)
        if gio_to:
            days.append((gio_to, "Giỗ Tổ Hùng Vương"))
        for ngay, ten in days:
            con_lai = (ngay - today).days
            if 0 <= con_lai <= days_ahead:
                upcoming.append(
                    {
                        "ten": ten,
                        "ngay": ngay.strftime("%d/%m"),
                        "con_lai": con_lai,
                    }
                )
    upcoming.sort(key=lambda le: le["con_lai"])
    return upcoming[:5]


def _can_chi(can_idx, chi_idx):
    return f"{CAN[can_idx % 10]} {CHI[chi_idx % 12]}"


def _nap_am(can_idx, chi_idx):
    """Nạp âm ngũ hành của một cặp can chi trong vòng 60 hoa giáp."""
    for n in range(60):
        if n % 10 == can_idx % 10 and n % 12 == chi_idx % 12:
            return NAP_AM[n // 2]
    return ""


def _tiet_khi(jdn):
    """Tiết khí đang diễn ra, suy từ kinh độ mặt trời lúc giữa trưa giờ Việt Nam."""
    do = _sun_longitude(jdn - 0.5 - LUNAR_TZ / 24) * 180 / math.pi
    return TIET_KHI[int(do // 15) % 24]


def _sao_theo_chi(chi_goc, chi_xet):
    """Sao trong vòng 12 sao và việc nó có phải sao hoàng đạo hay không."""
    khoi_thanh_long = (chi_goc * 2 + 8) % 12
    vi_tri = (chi_xet - khoi_thanh_long) % 12
    return SAO_12[vi_tri], vi_tri in SAO_HOANG_DAO


def _chi_tiet_gio(can_ngay_idx, chi_ngay_idx):
    """12 giờ trong ngày kèm can chi, sao và khung giờ."""
    gio = []
    for chi_idx in range(12):
        bat_dau = (chi_idx * 2 + 23) % 24
        ket_thuc = (bat_dau + 1) % 24
        sao, tot = _sao_theo_chi(chi_ngay_idx, chi_idx)
        gio.append(
            {
                "chi": CHI[chi_idx],
                "khung": f"{bat_dau:02d}:00–{ket_thuc:02d}:59",
                "can_chi": _can_chi(can_ngay_idx * 2 + chi_idx, chi_idx),
                "sao": sao,
                "tot": tot,
            }
        )
    return gio


def job_fetch_lunar():
    today = date.today()
    ld, lm, ly, leap = solar_to_lunar(today.day, today.month, today.year)
    jdn = _jd_from_date(today.day, today.month, today.year)

    can_ngay_idx = (jdn + 9) % 10
    chi_ngay_idx = (jdn + 1) % 12
    can_thang_idx = ((ly - 4) * 12 + lm + 1) % 10
    chi_thang_idx = (lm + 1) % 12
    can_nam_idx = (ly - 4) % 10
    chi_nam_idx = (ly - 4) % 12

    sao_ngay, hoang_dao = _sao_theo_chi(chi_thang_idx, chi_ngay_idx)
    gio_chi_tiet = _chi_tiet_gio(can_ngay_idx, chi_ngay_idx)
    gio_tot = [g for g in gio_chi_tiet if g["tot"]]

    gio_hien_tai = datetime.now().hour
    chi_gio_idx = ((gio_hien_tai + 1) % 24) // 2

    # Tháng đủ có 30 ngày, tháng thiếu 29: so mốc sóc của tháng này với tháng kế tiếp.
    k = int((jdn - 2415021.076998695) / 29.530588853)
    dau_thang = _new_moon_day(k + 1)
    if dau_thang > jdn:
        dau_thang = _new_moon_day(k)
        thang_sau = _new_moon_day(k + 1)
    else:
        thang_sau = _new_moon_day(k + 2)

    state.cache["lunar"] = {
        "data": {
            "thu": THU[(today.weekday() + 1) % 7],
            "ngay_duong": today.strftime("%d/%m/%Y"),
            "am_lich": f"Ngày {ld} tháng {lm}{' nhuận' if leap else ''} năm {ly}",
            "am_lich_ngay": ld,
            "am_lich_thang": f"{lm}{' (nhuận)' if leap else ''}",
            "thang_du": "Đủ (30 ngày)"
            if thang_sau - dau_thang == 30
            else "Thiếu (29 ngày)",
            "can_chi_gio": _can_chi(can_ngay_idx * 2 + chi_gio_idx, chi_gio_idx),
            "can_chi_ngay": _can_chi(can_ngay_idx, chi_ngay_idx),
            "can_chi_thang": _can_chi(can_thang_idx, chi_thang_idx),
            "can_chi_nam": _can_chi(can_nam_idx, chi_nam_idx),
            "nap_am_ngay": _nap_am(can_ngay_idx, chi_ngay_idx),
            "nap_am_thang": _nap_am(can_thang_idx, chi_thang_idx),
            "nap_am_nam": _nap_am(can_nam_idx, chi_nam_idx),
            "tiet_khi": _tiet_khi(jdn),
            "sao_truc_nhat": sao_ngay,
            "hoang_dao": hoang_dao,
            "ngay_tot": hoang_dao,
            "xung_ngay": CHI[(chi_ngay_idx + 6) % 12],
            "gio_hoang_dao": " · ".join(g["chi"] for g in gio_tot),
            "gio_chi_tiet": gio_chi_tiet,
            "le_sap_toi": _le_sap_toi(today),
        },
        "updated_at": datetime.now(timezone.utc).isoformat(),
    }


async def job_fetch_producthunt():
    print(f"[{datetime.now():%H:%M:%S}] producthunt...")
    import feedparser as fp

    resp = await safe_get("https://www.producthunt.com/feed")
    if not resp:
        return
    try:
        feed = fp.parse(resp.content)
        items = []
        for entry in feed.entries[:12]:
            title = unescape(strip_html(entry.get("title", ""))).strip()
            desc = strip_html(entry.get("summary", entry.get("description", "")))
            items.append(
                {
                    "ten": title,
                    "mo_ta": desc[:120],
                    "url": entry.get("link", ""),
                }
            )
        if items:
            state.cache["producthunt"] = {
                "data": items,
                "updated_at": datetime.now(timezone.utc).isoformat(),
            }
    except Exception as e:
        print(f"  ⚠ producthunt: {e}")


async def fetch_uber_blog(max_items):
    """Uber Engineering không phát hành RSS, bài viết nằm trong JSON nhúng sẵn của trang."""
    resp = await safe_get(UBER_BLOG_URL)
    if not resp:
        return []
    items = []
    try:
        soup = BeautifulSoup(resp.text, "html.parser")
        for script in soup.find_all("script", attrs={"type": "application/json"}):
            if "Article Feed Store" not in (script.get("id") or ""):
                continue
            feed = json.loads(unquote(script.string.strip()))
            pages = feed.get("relatedPages", {}).get("relatedPages", [])
            for page in pages[:max_items]:
                url = page.get("fullURL", "")
                if url and not url.startswith("http"):
                    url = f"https://{url}"
                items.append(
                    {
                        "nguon": "Uber Engineering",
                        "tieu_de": unescape(page.get("title", "")).strip(),
                        "mo_ta": "",
                        "url": url,
                    }
                )
            break
    except Exception as e:
        print(f"  ⚠ Uber Engineering: {e}")
    return items


def _xen_ke_nguon(items):
    """Trộn xen kẽ theo nguồn để mỗi blog đều có bài lọt vào danh sách cuối."""
    theo_nguon = {}
    for item in items:
        theo_nguon.setdefault(item["nguon"], []).append(item)
    mixed = []
    for lot in zip_longest(*theo_nguon.values()):
        mixed.extend(item for item in lot if item)
    return mixed


async def job_fetch_devblog():
    print(f"[{datetime.now():%H:%M:%S}] devblog...")
    raw = await fetch_multiple_rss(RSS_DEV_BLOGS, DEVBLOG_PER_SOURCE)
    raw += await fetch_uber_blog(DEVBLOG_PER_SOURCE)
    unique = deduplicate_batch(_xen_ke_nguon(raw))
    state.cache["devblog"] = {
        "data": unique[:DEVBLOG_LIMIT],
        "updated_at": datetime.now(timezone.utc).isoformat(),
    }


def job_fetch_events():
    from datetime import date

    today = date.today()
    upcoming = []
    for evt in TECH_EVENTS:
        evt_date = date.fromisoformat(evt["ngay"])
        delta = (evt_date - today).days
        if -1 <= delta <= 180:
            upcoming.append(
                {
                    "ten": evt["ten"],
                    "ngay": evt_date.strftime("%d/%m/%Y"),
                    "con_lai": delta,
                    "loai": evt["loai"],
                }
            )
    upcoming.sort(key=lambda x: x["con_lai"])
    state.cache["events"] = {
        "data": upcoming,
        "updated_at": datetime.now(timezone.utc).isoformat(),
    }


async def job_fetch_jobs():
    """Lấy việc làm khớp hồ sơ từ MCP server, xếp theo điểm gợi ý sẵn có."""
    print(f"[{datetime.now():%H:%M:%S}] jobs...")
    result = await call_tool("search_my_jobs", {"gioi_han": 300})
    items = result.get("data") if isinstance(result, dict) else None
    if not items:
        return
    items.sort(key=lambda j: j.get("diem_goi_y", 0), reverse=True)
    top = items[:JOBS_LIMIT]
    state.cache["jobs"] = {
        "data": top,
        "tong_tim_thay": result.get("tong_tim_thay", len(items)),
        "updated_at": datetime.now(timezone.utc).isoformat(),
    }
    await log_news_batch(
        [
            {
                "tieu_de": j.get("tieu_de", ""),
                "url": j.get("url", ""),
                "nguon": j.get("nguon", ""),
                "tom_tat": f"{j.get('cong_ty', '')} · {j.get('dia_diem', '')} · {j.get('luong', '')}",
                "_score": j.get("diem_goi_y", 0),
            }
            for j in top
        ],
        "jobs",
    )


async def job_hide(url: str) -> dict:
    """Ẩn một job khỏi card và lưu vào job_history để lần sau không gợi ý lại."""
    cached = state.cache["jobs"]["data"]
    job = next((j for j in cached if j.get("url") == url), None)
    if not job:
        return {"ok": False, "ly_do": "khong_tim_thay"}
    result = await call_tool("luu_jobs_da_chon", {"jobs": [job]})
    if not isinstance(result, dict):
        return {"ok": False, "ly_do": "mcp_loi"}
    state.cache["jobs"]["data"] = [j for j in cached if j.get("url") != url]
    return {"ok": True, "da_luu": result.get("da_luu", 0), "bo_qua": result.get("bo_qua", 0)}
