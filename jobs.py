import json
import math
from datetime import datetime, timezone
from html import unescape

from bs4 import BeautifulSoup

import state
from config import (
    BINANCE_URL,
    CRYPTO_SYM,
    CRYPTO_SYMBOLS,
    GOLD_API_URL,
    GOLD_NAME_MAP,
    GOLD_PRIORITY,
    HN_ITEM,
    HN_TOP,
    RSS_DEV_BLOGS,
    RSS_TIN_QT_INTL,
    RSS_TIN_QT_VN,
    RSS_TIN_VN,
    TECH_EVENTS,
    VN30,
)
from db import log_crypto_prices, log_gold_prices, log_news_batch
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
            formatted.append({
                "code": code,
                "name": GOLD_NAME_MAP.get(code, v.get("name", code)),
                "buy": v.get("buy", 0),
                "sell": v.get("sell", 0),
                "change_sell": v.get("change_sell", 0),
                "change_buy": v.get("change_buy", 0),
                "currency": v.get("currency", "VND"),
            })
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
        state.cache["crypto"] = {
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
            ds.append({
                "tieu_de": item.get("title", ""),
                "url": item.get("url", ""),
                "hn_url": f"https://news.ycombinator.com/item?id={sid}",
                "diem": item.get("score", 0),
                "binh_luan": item.get("descendants", 0),
                "tac_gia": item.get("by", ""),
            })
        ds = rank_news(ds, 10)
        state.cache["tech_news"] = {
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
        state.cache["github"] = {
            "data": repos,
            "updated_at": datetime.now(timezone.utc).isoformat(),
        }
        await log_news_batch(repos, "github")
    except Exception as e:
        print(f"  ⚠ github: {e}")


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
            items.append({
                "ma": ma,
                "gia": gia,
                "thay_doi": thay_doi,
                "phan_tram": phan_tram,
                "kl": row.get("n", 0),
            })
        items.sort(key=lambda x: x["ma"])
        state.cache["stock"] = {
            "data": items,
            "updated_at": datetime.now(timezone.utc).isoformat(),
        }
    except Exception as e:
        print(f"  ⚠ stock: {e}")


async def job_fetch_oil():
    print(f"[{datetime.now():%H:%M:%S}] oil...")
    resp = await safe_get("https://www.pvoil.com.vn/tin-gia-xang-dau")
    if not resp:
        return
    try:
        soup = BeautifulSoup(resp.text, "html.parser")
        table = soup.select_one("table")
        if not table:
            return
        items = []
        for row in table.select("tr")[1:]:
            cols = [td.get_text(strip=True) for td in row.select("td")]
            if len(cols) < 3:
                continue
            name = cols[1].strip()
            price_str = (
                cols[2].replace("đ", "").replace(".", "").replace(",", "").strip()
            )
            chg_str = cols[3].strip() if len(cols) > 3 else "0"
            try:
                gia = int(price_str)
            except Exception:
                continue
            try:
                chg = int(chg_str.replace("+", "").replace(".", "").replace(",", ""))
            except Exception:
                chg = 0
            pct = round((chg / (gia - chg)) * 100, 2) if (gia - chg) else 0
            items.append({"ten": name, "gia": gia, "thay_doi": chg, "phan_tram": pct})
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
            items.append({
                "thanh_pho": city_names.get(city, city),
                "nhiet_do": int(cur["temp_C"]),
                "cam_giac": int(cur["FeelsLikeC"]),
                "do_am": int(cur["humidity"]),
                "mo_ta": cur["lang_vi"][0]["value"]
                if cur.get("lang_vi")
                else cur["weatherDesc"][0]["value"],
                "icon": cur["weatherCode"],
                "gio": round(int(cur["windspeedKmph"]), 1),
            })
        except Exception:
            pass
    if items:
        state.cache["weather"] = {
            "data": items,
            "updated_at": datetime.now(timezone.utc).isoformat(),
        }


def job_fetch_lunar():
    from datetime import date

    today = date.today()
    solar_day, solar_month, solar_year = today.day, today.month, today.year

    def solar_to_lunar(dd, mm, yy):
        def jd(d, m, y):
            a = (14 - m) // 12
            y2 = y + 4800 - a
            m2 = m + 12 * a - 3
            return (
                d
                + (153 * m2 + 2) // 5
                + 365 * y2
                + y2 // 4
                - y2 // 100
                + y2 // 400
                - 32045
            )

        def new_moon(k):
            T = k / 1236.85
            T2 = T * T
            T3 = T2 * T
            dr = math.pi / 180
            Jd1 = 2415020.75933 + 29.53058868 * k + 0.0001178 * T2 - 0.000000155 * T3
            Jd1 += 0.00033 * math.sin((166.56 + 132.87 * T - 0.009173 * T2) * dr)
            M = 359.2242 + 29.10535608 * k - 0.0000333 * T2 - 0.00000347 * T3
            Mpr = 306.0253 + 385.81691806 * k + 0.0107306 * T2 + 0.00001236 * T3
            F = 21.2964 + 390.67050646 * k - 0.0016528 * T2 - 0.00000239 * T3
            C1 = (0.1734 - 0.000393 * T) * math.sin(M * dr) + 0.0021 * math.sin(
                2 * dr * M
            )
            C1 -= 0.4068 * math.sin(Mpr * dr) - 0.0161 * math.sin(dr * 2 * Mpr)
            C1 -= 0.0004 * math.sin(dr * 3 * Mpr) - 0.0104 * math.sin(dr * 2 * F)
            C1 -= 0.0051 * math.sin(dr * (M + Mpr)) + 0.0074 * math.sin(dr * (M - Mpr))
            C1 += 0.0004 * math.sin(dr * (2 * F + M)) - 0.0004 * math.sin(
                dr * (2 * F - M)
            )
            C1 -= 0.0006 * math.sin(dr * (2 * F + Mpr)) - 0.001 * math.sin(
                dr * (2 * F - Mpr)
            )
            C1 += 0.0005 * math.sin(dr * (2 * Mpr + M))
            delta_T = 0.5 / 1440 if T < -11 else 0
            return Jd1 + C1 - delta_T

        def sun_longitude(jdn):
            T = (jdn - 2451545.0) / 36525
            T2 = T * T
            dr = math.pi / 180
            M = 357.5291 + 35999.0503 * T - 0.0001559 * T2 - 0.00000048 * T * T2
            L0 = 280.46646 + 36000.76983 * T + 0.0003032 * T2
            C = (1.9146 - 0.004817 * T - 0.000014 * T2) * math.sin(dr * M)
            C += (0.019993 - 0.000101 * T) * math.sin(dr * 2 * M) + 0.00029 * math.sin(
                dr * 3 * M
            )
            theta = L0 + C
            omega = 125.04 - 1934.136 * T
            lon = theta - 0.00569 - 0.00478 * math.sin(omega * dr)
            return lon * dr

        def get_lunar_month11(yy):
            off = jd(31, 12, yy) - 2415021
            k = int(off / 29.530588853)
            nm = new_moon(k)
            sun = int(sun_longitude(nm) / (math.pi * 2) * 12)
            if sun >= 9:
                nm = new_moon(k - 1)
            return nm

        jdn = jd(dd, mm, yy)
        k = int((jdn - 2415021.076998695) / 29.530588853 + 0.5)
        month_start = new_moon(k)
        while month_start > jdn:
            k -= 1
            month_start = new_moon(k)
        lunar_day = jdn - int(month_start) + 1
        a11 = get_lunar_month11(yy)
        b11 = get_lunar_month11(yy - 1)
        lunar_year = yy
        if int(a11) >= jdn:
            lunar_year = yy - 1
            a11 = b11
        diff = int((int(month_start) - int(a11)) / 29)
        lunar_month = diff + 11
        if lunar_month > 12:
            lunar_month -= 12
        if lunar_month >= 11 and diff < 4:
            lunar_year -= 1
        return int(lunar_day), lunar_month, lunar_year

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
    GIO_HOANG_DAO = {
        0: ["Tý", "Sửu", "Mão", "Ngọ", "Thân", "Dậu"],
        1: ["Dần", "Mão", "Tỵ", "Thân", "Tuất", "Hợi"],
        2: ["Tý", "Sửu", "Thìn", "Tỵ", "Mùi", "Tuất"],
        3: ["Dần", "Thìn", "Ngọ", "Mùi", "Dậu", "Hợi"],
        4: ["Tý", "Mão", "Thìn", "Ngọ", "Dậu", "Tuất"],
        5: ["Dần", "Tỵ", "Ngọ", "Thân", "Hợi", "Hợi"],
    }

    ld, lm, ly = solar_to_lunar(solar_day, solar_month, solar_year)
    can_nam = CAN[(ly - 4) % 10]
    chi_nam = CHI[(ly - 4) % 12]
    can_thang_idx = ((ly - 4) * 12 + lm + 1) % 10
    can_thang = CAN[can_thang_idx]
    chi_thang = CHI[(lm + 1) % 12]
    jdn_today = (
        solar_day
        + (153 * ((solar_month + 9) % 12 + 3) + 2) // 5
        + 365 * (solar_year + 4800 - (14 - solar_month) // 12)
        + (solar_year + 4800 - (14 - solar_month) // 12) // 4
        - (solar_year + 4800 - (14 - solar_month) // 12) // 100
        + (solar_year + 4800 - (14 - solar_month) // 12) // 400
        - 32045
    )
    can_ngay = CAN[(jdn_today + 9) % 10]
    chi_ngay = CHI[(jdn_today + 1) % 12]
    thu = THU[today.weekday() + 1 if today.weekday() < 6 else 0]
    chi_ngay_idx = CHI.index(chi_ngay)
    gio_hd = GIO_HOANG_DAO.get(chi_ngay_idx % 6, [])
    ngay_tot = ld in [1, 6, 8, 13, 15, 19, 25, 27]

    upcoming = []
    vn_holidays = [
        (1, 1, "Tết Dương lịch"),
        (10, 3, "Giỗ Tổ Hùng Vương"),
        (30, 4, "Giải phóng miền Nam"),
        (1, 5, "Quốc tế Lao động"),
        (2, 9, "Quốc khánh"),
    ]
    for d, m, name in vn_holidays:
        hdate = date(solar_year, m, d)
        if hdate >= today:
            delta = (hdate - today).days
            if delta <= 120:
                upcoming.append({
                    "ten": name,
                    "ngay": hdate.strftime("%d/%m"),
                    "con_lai": delta,
                })

    state.cache["lunar"] = {
        "data": {
            "thu": thu,
            "ngay_duong": today.strftime("%d/%m/%Y"),
            "am_lich": f"Ngày {ld} tháng {lm} năm {ly}",
            "can_chi_ngay": f"{can_ngay} {chi_ngay}",
            "can_chi_thang": f"{can_thang} {chi_thang}",
            "can_chi_nam": f"{can_nam} {chi_nam}",
            "gio_hoang_dao": " · ".join(gio_hd),
            "ngay_tot": ngay_tot,
            "le_sap_toi": upcoming[:5],
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
            items.append({
                "ten": title,
                "mo_ta": desc[:120],
                "url": entry.get("link", ""),
            })
        if items:
            state.cache["producthunt"] = {
                "data": items,
                "updated_at": datetime.now(timezone.utc).isoformat(),
            }
    except Exception as e:
        print(f"  ⚠ producthunt: {e}")


async def job_fetch_devblog():
    print(f"[{datetime.now():%H:%M:%S}] devblog...")
    raw = await fetch_multiple_rss(RSS_DEV_BLOGS, 2)
    unique = deduplicate_batch(raw)
    state.cache["devblog"] = {
        "data": unique[:12],
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
            upcoming.append({
                "ten": evt["ten"],
                "ngay": evt_date.strftime("%d/%m/%Y"),
                "con_lai": delta,
                "loai": evt["loai"],
            })
    upcoming.sort(key=lambda x: x["con_lai"])
    state.cache["events"] = {
        "data": upcoming,
        "updated_at": datetime.now(timezone.utc).isoformat(),
    }
