// ─── CONFIG ───
const PANELS_META = [
  { key: "gold", label: "💰 Giá Vàng" },
  { key: "crypto", label: "🪙 Crypto" },
  { key: "vn_news", label: "📰 Tin Trong Nước" },
  { key: "world_news", label: "🌍 Tin Quốc Tế" },
  { key: "tech_news", label: "💻 Hacker News" },
  { key: "github", label: "🔥 GitHub Trending" },
  { key: "forex", label: "💱 Tỷ Giá VCB" },
  { key: "stock", label: "📈 Chứng Khoán VN30" },
  { key: "oil", label: "⛽ Giá Xăng Dầu VN" },
  { key: "weather", label: "🌤 Thời Tiết" },
  { key: "lunar", label: "📅 Lịch Âm" },
  { key: "producthunt", label: "🚀 Product Hunt" },
  { key: "devblog", label: "📝 Dev Blog" },
  { key: "events", label: "📆 Sự Kiện Tech" },
];

const CFG_KEY = "dashboard_cfg";

function loadCfg() {
  try {
    return JSON.parse(localStorage.getItem(CFG_KEY)) || {};
  } catch {
    return {};
  }
}
function saveCfg(cfg) {
  localStorage.setItem(CFG_KEY, JSON.stringify(cfg));
}

function applyConfig() {
  const cfg = loadCfg();
  const hidden = cfg.hidden || [];
  let visibleCount = 0;
  document.querySelectorAll(".pnl[data-key]").forEach((el) => {
    const key = el.dataset.key;
    const isHidden = hidden.includes(key);
    el.classList.toggle("pnl-hidden", isHidden);
    if (!isHidden) visibleCount++;
  });
  const grid = document.getElementById("mainGrid");
  if (cfg.cols && cfg.cols !== "auto") {
    grid.style.gridTemplateColumns = `repeat(${cfg.cols}, 1fr)`;
  } else {
    const cols = visibleCount <= 2 ? 1 : visibleCount <= 6 ? 2 : 3;
    grid.style.gridTemplateColumns = `repeat(${cols}, 1fr)`;
  }
  document.querySelectorAll(".cfg-col-btn").forEach((btn) => {
    btn.classList.toggle("active", String(btn.dataset.cols) === String(cfg.cols || "auto"));
  });
}

function buildConfigPanel() {
  const cfg = loadCfg();
  const hidden = cfg.hidden || [];
  const list = document.getElementById("cfgPanelList");
  list.innerHTML = PANELS_META.map(
    (p) => `
    <div class="cfg-row">
      <label class="cfg-label" for="chk-${p.key}">${p.label}</label>
      <label class="cfg-toggle">
        <input type="checkbox" id="chk-${p.key}" ${hidden.includes(p.key) ? "" : "checked"}
          onchange="togglePanel('${p.key}', this.checked)">
        <span class="cfg-slider"></span>
      </label>
    </div>`,
  ).join("");
}

function togglePanel(key, visible) {
  const cfg = loadCfg();
  const hidden = new Set(cfg.hidden || []);
  visible ? hidden.delete(key) : hidden.add(key);
  cfg.hidden = [...hidden];
  saveCfg(cfg);
  applyConfig();
}

function setColsOverride(cols) {
  const cfg = loadCfg();
  cfg.cols = cols;
  saveCfg(cfg);
  applyConfig();
}

function showAllPanels() {
  const cfg = loadCfg();
  cfg.hidden = [];
  saveCfg(cfg);
  buildConfigPanel();
  applyConfig();
}

function resetConfig() {
  localStorage.removeItem(CFG_KEY);
  buildConfigPanel();
  applyConfig();
}

function openConfig() {
  buildConfigPanel();
  applyConfig();
  document.getElementById("cfgOverlay").classList.add("open");
}

function closeConfig(e) {
  if (!e || e.target === document.getElementById("cfgOverlay")) {
    document.getElementById("cfgOverlay").classList.remove("open");
  }
}

applyConfig();

// ─── CLOCK ───
setInterval(() => {
  const d = new Date();
  document.getElementById("clock").textContent =
    d.toLocaleTimeString("vi", { hour: "2-digit", minute: "2-digit", second: "2-digit" }) +
    " — " +
    d.toLocaleDateString("vi");
}, 1000);

const esc = (s) => {
  if (!s) return "";
  const d = document.createElement("div");
  d.textContent = String(s);
  return d.innerHTML;
};
const fV = (n) => (!n ? "—" : n >= 1e6 ? (n / 1e6).toFixed(1) + " triệu" : n.toLocaleString("vi") + "đ");
const fU = (n) => (!n ? "—" : "$" + n.toLocaleString("en", { maximumFractionDigits: 2 }));
const fB = (n) =>
  !n
    ? "—"
    : n >= 1e9
      ? "$" + (n / 1e9).toFixed(1) + "B"
      : n >= 1e6
        ? "$" + (n / 1e6).toFixed(1) + "M"
        : "$" + n.toLocaleString("en");
const cc = (v) => (v >= 0 ? "up" : "dn");
const ca = (v) => (v >= 0 ? "▲" : "▼");
const fP = (n) => (n ? Math.abs(n).toFixed(2) : "0.00");
const fires = (s) => (s ? "🔥".repeat(Math.min(Math.floor(s / 5), 5)) : "");

// ─── RENDERERS ───
function renderGold(data) {
  if (!data?.length) return;
  const hdr = `<div class="g-row g-hdr"><span class="g-name">Loại vàng</span><span class="g-col">Mua</span><span class="g-col">Bán</span><span class="g-col">Thay đổi</span></div>`;
  document.getElementById("gold-body").innerHTML =
    hdr +
    data
      .map((g) => {
        if (g.currency === "VND") {
          const chg = g.change_sell ? `${g.change_sell > 0 ? "▲" : "▼"}${fV(Math.abs(g.change_sell))}` : "—";
          return `<div class="g-row"><span class="g-name">${esc(g.name)}</span><span class="g-val">${fV(g.buy)}</span><span class="g-val">${fV(g.sell)}</span><span class="g-col ${g.change_sell > 0 ? "up" : "dn"}">${chg}</span></div>`;
        }
        const chg = g.change_buy ? `${g.change_buy > 0 ? "▲" : "▼"}$${fP(g.change_buy)}` : "—";
        return `<div class="g-row"><span class="g-name">${esc(g.name)}</span><span class="g-val">${fU(g.buy)}/oz</span><span class="g-val">—</span><span class="g-col ${g.change_buy > 0 ? "up" : "dn"}">${chg}</span></div>`;
      })
      .join("");
}

function renderCrypto(data) {
  if (!data?.length) return;
  document.getElementById("crypto-body").innerHTML = data
    .map(
      (c) =>
        `<div class="c-row"><span class="c-sym">${esc(c.ky_hieu)}</span><span class="c-price">${fU(c.usd)}</span><span class="c-chg ${cc(c.thay_doi)}">${ca(c.thay_doi)}${fP(c.thay_doi)}%</span><span class="c-cap">${fB(c.von_hoa)}</span></div>`,
    )
    .join("");
}

function renderVnNews(data) {
  if (!data?.length) return;
  document.getElementById("vn-body").innerHTML = data
    .map(
      (t) =>
        `<div class="n-item"><div class="n-title"><a href="${esc(t.url)}" target="_blank">${esc(t.tieu_de)}</a></div>${t.tom_tat ? `<div class="n-sum">${esc(t.tom_tat)}</div>` : ""}<div class="n-meta"><span class="n-src">${esc(t.nguon)}</span>${t._score ? `<span class="fire">${fires(t._score)}</span>` : ""}</div></div>`,
    )
    .join("");
}

function renderWorldNews(data) {
  if (!data?.length) return;
  document.getElementById("world-body").innerHTML = data
    .map((t) => {
      const title = t.tieu_de_vi || t.tieu_de;
      return `<div class="n-item"><div class="n-title">${t.can_dich ? "🌐" : ""}<a href="${esc(t.url)}" target="_blank">${esc(title)}</a></div>${t.tieu_de_vi ? `<div class="n-orig">${esc(t.tieu_de)}</div>` : ""}${t.tom_tat ? `<div class="n-sum">${esc(t.tom_tat)}</div>` : ""}<div class="n-meta"><span class="n-src">${esc(t.nguon)}</span>${t._score ? `<span class="fire">${fires(t._score)}</span>` : ""}</div></div>`;
    })
    .join("");
}

function renderTechNews(data) {
  if (!data?.length) return;
  document.getElementById("tech-body").innerHTML = data
    .map((t) => {
      const title = t.tieu_de_vi || t.tieu_de;
      const url = t.url || t.hn_url;
      return `<div class="n-item"><div class="n-title"><a href="${esc(url)}" target="_blank">${esc(title)}</a></div>${t.tieu_de_vi ? `<div class="n-orig">${esc(t.tieu_de)}</div>` : ""}${t.tom_tat ? `<div class="n-sum">${esc(t.tom_tat)}</div>` : ""}<div class="n-meta"><span>▲${t.diem} · 💬${t.binh_luan}</span>${t._score ? `<span class="fire">${fires(t._score)}</span>` : ""}<a href="${esc(t.hn_url)}" target="_blank">HN</a></div></div>`;
    })
    .join("");
}

function renderGithub(data) {
  if (!data?.length) return;
  document.getElementById("gh-body").innerHTML = data
    .map(
      (r) =>
        `<div class="n-item"><div class="n-title"><a href="${esc(r.url)}" target="_blank">${esc(r.ten)}</a>${r.ngon_ngu ? `<span class="gh-lang">${esc(r.ngon_ngu)}</span>` : ""}</div>${r.tieu_de_vi ? `<div class="n-orig">${esc(r.tieu_de_vi)}</div>` : ""}${r.tom_tat ? `<div class="n-sum">${esc(r.tom_tat)}</div>` : r.mo_ta ? `<div class="n-sum">${esc(r.mo_ta)}</div>` : ""}<div class="n-meta">${r.sao ? `<span>⭐${esc(r.sao)}</span>` : ""}${r.hom_nay ? `<span>${esc(r.hom_nay)}</span>` : ""}</div></div>`,
    )
    .join("");
}

function renderForex(data) {
  if (!data?.length) return;
  const hdr = `<div class="g-row g-hdr"><span class="g-name">Mã</span><span class="g-col">Mua TM</span><span class="g-col">Mua CK</span><span class="g-col">Bán</span></div>`;
  document.getElementById("forex-body").innerHTML =
    hdr +
    data
      .map(
        (r) =>
          `<div class="g-row"><span class="g-name"><b>${esc(r.ma)}</b></span><span class="g-col">${fV(r.mua_tm)}</span><span class="g-col">${fV(r.mua_ck)}</span><span class="g-val">${fV(r.ban)}</span></div>`,
      )
      .join("");
}

function renderStock(data) {
  if (!data?.length) return;
  const hdr = `<div class="g-row g-hdr"><span class="g-name">Mã</span><span class="g-col">Giá</span><span class="g-col">+/-</span><span class="g-col">%</span><span class="g-col">KL</span></div>`;
  document.getElementById("stock-body").innerHTML =
    hdr +
    data
      .map((r) => {
        const cls = r.thay_doi > 0 ? "up" : r.thay_doi < 0 ? "dn" : "";
        return `<div class="g-row"><span class="g-name"><b>${esc(r.ma)}</b></span><span class="g-val">${fV(r.gia)}</span><span class="g-col ${cls}">${r.thay_doi > 0 ? "▲" : r.thay_doi < 0 ? "▼" : ""}${fP(r.thay_doi)}</span><span class="g-col ${cls}">${r.phan_tram > 0 ? "+" : ""}${(r.phan_tram || 0).toFixed(2)}%</span><span class="g-col">${r.kl >= 1e6 ? (r.kl / 1e6).toFixed(1) + "M" : r.kl >= 1e3 ? (r.kl / 1e3).toFixed(0) + "K" : r.kl}</span></div>`;
      })
      .join("");
}

function renderOil(data) {
  if (!data?.length) return;
  const hdr = `<div class="g-row g-hdr"><span class="g-name">Mặt hàng</span><span class="g-col">Giá (đ/lít)</span><span class="g-col">Thay đổi</span></div>`;
  document.getElementById("oil-body").innerHTML =
    hdr +
    data
      .map((r) => {
        const cls = r.thay_doi > 0 ? "up" : r.thay_doi < 0 ? "dn" : "";
        const arrow = r.thay_doi > 0 ? "▲" : r.thay_doi < 0 ? "▼" : "—";
        return `<div class="g-row"><span class="g-name">${esc(r.ten)}</span><span class="g-val">${(r.gia || 0).toLocaleString("vi")}đ</span><span class="g-col ${cls}">${r.thay_doi !== 0 ? arrow + Math.abs(r.thay_doi).toLocaleString("vi") : "—"}</span></div>`;
      })
      .join("");
}

function renderWeather(data) {
  if (!data?.length) return;
  const wIcon = (c) => {
    c = parseInt(c);
    if (c === 113) return "☀️";
    if (c === 116) return "⛅";
    if (c === 119 || c === 122) return "☁️";
    if ([176, 263, 266, 293, 296, 299, 302, 305, 308, 353, 356, 359].includes(c)) return "🌧️";
    if ([200, 386, 389, 392, 395].includes(c)) return "⛈️";
    if ([227, 230, 320, 323, 326, 329, 332, 335, 338, 368, 371, 374, 377].includes(c)) return "❄️";
    if ([143, 248, 260].includes(c)) return "🌫️";
    return "🌤️";
  };
  document.getElementById("weather-body").innerHTML = data
    .map(
      (r) =>
        `<div class="wx-row"><span style="font-size:22px">${wIcon(r.icon)}</span><div style="flex:1"><b>${esc(r.thanh_pho)}</b><br><span style="color:var(--t2)">${esc(r.mo_ta)}</span></div><div style="text-align:right"><b>${r.nhiet_do}°C</b><br><span style="color:var(--t3)">💧${r.do_am}% 💨${r.gio}km/h</span></div></div>`,
    )
    .join("");
}

function renderLunar(data) {
  if (!data) return;
  const el = document.getElementById("lunar-body");
  const tot = data.ngay_tot
    ? `<span class="lunar-good">✦ Ngày tốt</span>`
    : `<span class="lunar-bad">✦ Ngày bình thường</span>`;
  const rows = [
    ["Dương lịch", `${data.thu}, ${data.ngay_duong}`],
    ["Âm lịch", data.am_lich],
    ["Can chi ngày", data.can_chi_ngay],
    ["Can chi tháng", data.can_chi_thang],
    ["Can chi năm", data.can_chi_nam],
    ["Giờ hoàng đạo", data.gio_hoang_dao || "—"],
  ]
    .map(
      ([label, val]) =>
        `<div class="lunar-row"><span class="lunar-label">${esc(label)}</span><span class="lunar-val">${esc(val)}</span></div>`,
    )
    .join("");
  const holidays = data.le_sap_toi?.length
    ? `<div style="margin-top:6px;border-top:1px solid rgba(42,53,80,.4);padding-top:6px">${data.le_sap_toi.map((h) => `<div class="lunar-row"><span class="lunar-label">🎉 ${esc(h.ten)}</span><span style="color:var(--yl);font-weight:600">${h.con_lai === 0 ? "Hôm nay" : h.con_lai + " ngày"}</span></div>`).join("")}</div>`
    : "";
  el.innerHTML = `<div class="lunar-box"><div style="margin-bottom:6px">${tot}</div>${rows}${holidays}</div>`;
}

function renderProductHunt(data) {
  if (!data?.length) return;
  document.getElementById("ph-body").innerHTML = data
    .map(
      (r) =>
        `<div class="n-item"><div class="n-title"><a href="${esc(r.url)}" target="_blank">${esc(r.ten)}</a></div><div class="n-sum">${esc(r.mo_ta)}</div></div>`,
    )
    .join("");
}

function renderDevblog(data) {
  if (!data?.length) return;
  document.getElementById("devblog-body").innerHTML = data
    .map(
      (r) =>
        `<div class="n-item"><div class="n-title"><a href="${esc(r.url)}" target="_blank">${esc(r.tieu_de)}</a></div><div class="n-meta"><span>${esc(r.nguon)}</span></div></div>`,
    )
    .join("");
}

function renderEvents(data) {
  if (!data?.length) return;
  document.getElementById("events-body").innerHTML = data
    .map((r) => {
      const cls = r.con_lai <= 7 ? "soon" : r.con_lai <= 30 ? "near" : "far";
      return `<div class="evt-row"><div><b>${esc(r.ten)}</b><br><small>${esc(r.ngay)}</small></div><div class="evt-days ${cls}">${r.con_lai <= 0 ? "Đang diễn ra" : r.con_lai + " ngày"}</div></div>`;
    })
    .join("");
}

const renderers = {
  gold: (d) => renderGold(d.data),
  crypto: (d) => renderCrypto(d.data),
  vn_news: (d) => renderVnNews(d.data),
  world_news: (d) => renderWorldNews(d.data),
  tech_news: (d) => renderTechNews(d.data),
  github: (d) => renderGithub(d.data),
  forex: (d) => renderForex(d.data),
  stock: (d) => renderStock(d.data),
  oil: (d) => renderOil(d.data),
  weather: (d) => renderWeather(d.data),
  lunar: (d) => renderLunar(d.data),
  producthunt: (d) => renderProductHunt(d.data),
  devblog: (d) => renderDevblog(d.data),
  events: (d) => renderEvents(d.data),
};

// ─── INITIAL LOAD ───
async function loadAll() {
  const poll = async () => {
    try {
      const r = await fetch("/api/data");
      const d = await r.json();
      for (const [key, render] of Object.entries(renderers)) {
        const v = d[key];
        if (!v) continue;
        if (key === "lunar") {
          if (v.data) render(v);
        } else if (v?.data?.length) render(v);
      }
      return Object.entries(d).every(([k, v]) => (k === "lunar" ? !!v?.data : v?.data?.length > 0));
    } catch (e) {
      return false;
    }
  };
  if (await poll()) return;
  const iv = setInterval(async () => {
    if (await poll()) clearInterval(iv);
  }, 3000);
}
loadAll();

// ─── CRYPTO POLL ───
setInterval(async () => {
  try {
    const r = await fetch("/api/prices");
    const d = await r.json();
    if (d.crypto?.data?.length) renderCrypto(d.crypto.data);
    if (d.gold?.data?.length) renderGold(d.gold.data);
  } catch (e) {}
}, 5000);

// ─── REFRESH BUTTON ───
async function refreshPanel(key, url, btn) {
  btn.disabled = true;
  const orig = btn.textContent;
  btn.textContent = "⏳";
  try {
    const r = await fetch(url);
    const d = await r.json();
    if (d?.data?.length && renderers[key]) renderers[key](d);
  } catch (e) {}
  btn.disabled = false;
  btn.textContent = orig;
}
