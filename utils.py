import hashlib
import re
from difflib import SequenceMatcher
from html import unescape

import feedparser
import httpx

import state
from config import HOT_KEYWORDS, SOURCE_CREDIBILITY


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
        r = await state.http_client.get(url, **kwargs)
        r.raise_for_status()
        return r
    except httpx.HTTPError as e:
        print(f"  ⚠ {e}")
        return None


async def fetch_multiple_rss(feeds, max_per_source=3):
    all_items = []
    for source, url in feeds.items():
        try:
            resp = await state.http_client.get(url)
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
