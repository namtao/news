import os

from dotenv import load_dotenv

load_dotenv()

DATABASE_URL = os.environ.get("DATABASE_URL", "")
OWM_API_KEY = os.environ.get("OWM_API_KEY", "")
REQUEST_TIMEOUT = 15
HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
}

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

RSS_DEV_BLOGS = {
    "Vercel": "https://vercel.com/atom",
    "Cloudflare": "https://blog.cloudflare.com/rss/",
    "Docker": "https://www.docker.com/blog/feed/",
    "GitHub Blog": "https://github.blog/feed/",
    "Go Blog": "https://go.dev/blog/feed.atom",
    "Tailwind CSS": "https://tailwindcss.com/feeds/feed.xml",
}

TECH_EVENTS = [
    {"ten": "WWDC 2026", "ngay": "2026-06-08", "loai": "Apple"},
    {"ten": "Google I/O 2026", "ngay": "2026-05-19", "loai": "Google"},
    {"ten": "AWS re:Invent 2026", "ngay": "2026-12-01", "loai": "AWS"},
    {"ten": "Microsoft Build 2026", "ngay": "2026-05-19", "loai": "Microsoft"},
    {"ten": "GitHub Universe 2026", "ngay": "2026-10-27", "loai": "GitHub"},
    {"ten": "KubeCon NA 2026", "ngay": "2026-11-10", "loai": "CNCF"},
]

VN30 = [
    "ACB",
    "BID",
    "BVH",
    "CTG",
    "FPT",
    "GAS",
    "GVR",
    "HDB",
    "HPG",
    "KDH",
    "MBB",
    "MSN",
    "MWG",
    "NVL",
    "PDR",
    "PLX",
    "POW",
    "SAB",
    "SHB",
    "SSI",
    "STB",
    "TCB",
    "TPB",
    "VCB",
    "VHM",
    "VIC",
    "VJC",
    "VNM",
    "VPB",
    "VRE",
]
