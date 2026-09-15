const THEME_KEY = "theme";

function applyTheme(theme) {
  document.documentElement.dataset.theme = theme;
  localStorage.setItem(THEME_KEY, theme);
  const btn = document.getElementById("themeBtn");
  if (btn) {
    btn.textContent = theme === "light" ? "☀" : "🌙";
    btn.title = theme === "light" ? "Chuyển sang nền tối" : "Chuyển sang nền sáng";
  }
}

function toggleTheme() {
  applyTheme(document.documentElement.dataset.theme === "light" ? "dark" : "light");
}

// ─── CONFIG ───
const PANELS_META = [
  { key: "gold", label: "💰 Giá Vàng" },
  { key: "crypto", label: "🪙 Crypto" },
  { key: "futures", label: "📉 Futures" },
  { key: "vn_news", label: "📰 Tin Trong Nước" },
  { key: "world_news", label: "🌍 Tin Quốc Tế" },
  { key: "tech_news", label: "💻 Hacker News" },
  { key: "jobs", label: "💼 Việc Làm" },
  { key: "github", label: "🔥 GitHub Trending" },
  { key: "forex", label: "💱 Tỷ Giá VCB" },
  { key: "stock", label: "📈 Chứng Khoán VN30" },
  { key: "oil", label: "⛽ Giá Xăng Dầu VN" },
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
  const collapsed = cfg.collapsed || [];
  document.querySelectorAll(".pnl[data-key]").forEach((el) => {
    el.classList.toggle("pnl-hidden", hidden.includes(el.dataset.key));
    el.classList.toggle("pnl-collapsed", collapsed.includes(el.dataset.key));
  });
  // Cột chủ đề nào bị ẩn hết panel thì bỏ luôn khỏi lưới.
  let visibleCols = 0;
  document.querySelectorAll(".col").forEach((col) => {
    const empty = !col.querySelector(".pnl:not(.pnl-hidden)");
    col.classList.toggle("col-hidden", empty);
    if (!empty) visibleCols++;
  });
  const grid = document.getElementById("mainGrid");
  const cols =
    cfg.cols && cfg.cols !== "auto"
      ? Math.min(Number(cfg.cols), visibleCols || 1)
      : visibleCols || 1;
  grid.style.gridTemplateColumns = `repeat(${cols}, 1fr)`;
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

function togglePanelCollapse(key) {
  const cfg = loadCfg();
  const collapsed = new Set(cfg.collapsed || []);
  collapsed.has(key) ? collapsed.delete(key) : collapsed.add(key);
  cfg.collapsed = [...collapsed];
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

function renderFutures(data) {
  if (!data?.length) return;
  document.getElementById("futures-body").innerHTML = data
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

const DEFAULT_CITY = "Hà Nội";
let weatherData = [];

function wIcon(c) {
  c = parseInt(c);
  if (c === 113) return "☀️";
  if (c === 116) return "⛅";
  if (c === 119 || c === 122) return "☁️";
  if ([176, 263, 266, 293, 296, 299, 302, 305, 308, 353, 356, 359].includes(c)) return "🌧️";
  if ([200, 386, 389, 392, 395].includes(c)) return "⛈️";
  if ([227, 230, 320, 323, 326, 329, 332, 335, 338, 368, 371, 374, 377].includes(c)) return "❄️";
  if ([143, 248, 260].includes(c)) return "🌫️";
  return "🌤️";
}

function setCity(city) {
  const cfg = loadCfg();
  cfg.city = city;
  saveCfg(cfg);
  renderWeather(weatherData);
}

function renderWeather(data) {
  if (!data?.length) return;
  weatherData = data;
  const el = document.getElementById("hdrWeather");
  if (!el) return;
  const wanted = loadCfg().city || DEFAULT_CITY;
  const cur = data.find((r) => r.thanh_pho === wanted) || data[0];
  const options = data
    .map(
      (r) =>
        `<option value="${esc(r.thanh_pho)}"${r.thanh_pho === cur.thanh_pho ? " selected" : ""}>${esc(r.thanh_pho)}</option>`,
    )
    .join("");
  el.innerHTML =
    `<span class="wx-emoji" onclick="refreshWeather(this)" title="Bấm để cập nhật">${wIcon(cur.icon)}</span>` +
    `<select class="hdr-city" onchange="setCity(this.value)">${options}</select>` +
    `<b>${cur.nhiet_do}°C</b>`;
  el.title = `${cur.thanh_pho}: ${cur.mo_ta}\nCảm giác như ${cur.cam_giac}°C · Độ ẩm ${cur.do_am}% · Gió ${cur.gio} km/h`;
}

async function refreshWeather(el) {
  el.textContent = "⏳";
  try {
    const d = await (await fetch("/api/weather/refresh")).json();
    if (d?.data?.length) renderWeather(d.data);
  } catch (e) {
    renderWeather(weatherData);
  }
}


let lunarData = null;

function renderLunar(data) {
  if (!data) return;
  lunarData = data;
  const el = document.getElementById("hdrLunar");
  if (!el) return;
  const tot = data.ngay_tot
    ? `<span class="lunar-good">✦ Ngày tốt</span>`
    : `<span class="lunar-bad">✦ Ngày xấu</span>`;
  el.innerHTML = `📅 <b>${esc(data.am_lich)}</b> · ngày ${esc(data.can_chi_ngay)} ${tot}`;
  el.title = "Bấm để xem lịch âm chi tiết";
  el.onclick = openLunar;
  if (document.getElementById("lunarOverlay").classList.contains("open")) buildLunarDetail();
}

function buildLunarDetail() {
  const d = lunarData;
  if (!d) return;
  const sec = (title, rows) =>
    `<div class="ld-sec"><div class="ld-sec-t">${title}</div>${rows
      .filter(([, v]) => v || v === 0)
      .map(([k, v]) => `<div class="ld-row"><span>${esc(k)}</span><span>${esc(String(v))}</span></div>`)
      .join("")}</div>`;

  const gio = (d.gio_chi_tiet || [])
    .map(
      (g) =>
        `<div class="ld-gio ${g.tot ? "tot" : "xau"}"><span>${esc(g.can_chi)}</span>` +
        `<span>${esc(g.khung)}</span><span>${esc(g.sao)}</span></div>`,
    )
    .join("");

  const le = (d.le_sap_toi || []).length
    ? sec(
        "Lễ sắp tới",
        d.le_sap_toi.map((h) => [
          `${h.ten} (${h.ngay})`,
          h.con_lai === 0 ? "Hôm nay" : `còn ${h.con_lai} ngày`,
        ]),
      )
    : "";

  document.getElementById("lunarDetail").innerHTML =
    sec("Ngày", [
      ["Dương lịch", `${d.thu}, ${d.ngay_duong}`],
      ["Âm lịch", d.am_lich],
      ["Tháng", `${d.am_lich_thang} — ${d.thang_du}`],
      ["Tiết khí", d.tiet_khi],
    ]) +
    sec("Tứ trụ (can chi)", [
      ["Giờ hiện tại", d.can_chi_gio],
      ["Ngày", d.can_chi_ngay],
      ["Tháng", d.can_chi_thang],
      ["Năm", d.can_chi_nam],
    ]) +
    sec("Nạp âm ngũ hành", [
      ["Ngày", d.nap_am_ngay],
      ["Tháng", d.nap_am_thang],
      ["Năm", d.nap_am_nam],
    ]) +
    sec("Sao và cát hung", [
      ["Sao trực nhật", d.sao_truc_nhat],
      ["Loại ngày", d.hoang_dao ? "Hoàng đạo (tốt)" : "Hắc đạo (xấu)"],
      ["Xung tuổi", d.xung_ngay],
    ]) +
    `<div class="ld-sec"><div class="ld-sec-t">12 giờ trong ngày</div>${gio}</div>` +
    le;
}

function openLunar() {
  buildLunarDetail();
  document.getElementById("lunarOverlay").classList.add("open");
}

function closeLunar(e) {
  if (!e || e.target === document.getElementById("lunarOverlay")) {
    document.getElementById("lunarOverlay").classList.remove("open");
  }
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

function renderJobs(data) {
  if (!data?.length) return;
  document.getElementById("jobs-body").innerHTML = data
    .map((j) => {
      const luong = j.luong && j.luong !== "Thỏa thuận" ? `<span class="job-sal">${esc(j.luong)}</span>` : "";
      const meta = [j.dia_diem, j.loai_hinh, j.nguon].filter(Boolean);
      const x = `<button class="job-x" data-url="${esc(j.url)}" title="Ẩn job này và lưu vào DB để lần sau không gợi ý lại">✕</button>`;
      return `<div class="n-item"><div class="n-title"><a href="${esc(j.url)}" target="_blank">${esc(j.tieu_de)}</a>${luong}${x}</div><div class="n-sum">${esc(j.cong_ty || "")}</div><div class="n-meta">${meta.map((m) => `<span>${esc(m)}</span>`).join("")}${j.diem_goi_y ? `<span class="job-score">${j.diem_goi_y}đ</span>` : ""}</div></div>`;
    })
    .join("");
}

// Ẩn job: lưu vào job_history qua MCP nên các lần tìm sau không gợi ý lại nữa.
document.getElementById("jobs-body").addEventListener("click", async (e) => {
  const btn = e.target.closest(".job-x");
  if (!btn || btn.disabled) return;
  btn.disabled = true;
  btn.textContent = "⏳";
  try {
    const r = await fetch("/api/jobs/hide", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ url: btn.dataset.url }),
    });
    if (!r.ok) throw new Error(r.status);
    btn.closest(".n-item").remove();
  } catch (err) {
    btn.textContent = "⚠";
    btn.title = "Không ẩn được, thử lại sau";
    btn.disabled = false;
  }
});

const renderers = {
  gold: (d) => renderGold(d.data),
  crypto: (d) => renderCrypto(d.data),
  futures: (d) => renderFutures(d.data),
  vn_news: (d) => renderVnNews(d.data),
  world_news: (d) => renderWorldNews(d.data),
  tech_news: (d) => renderTechNews(d.data),
  github: (d) => renderGithub(d.data),
  jobs: (d) => renderJobs(d.data),
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
// Panel Việc Làm phải chờ MCP crawl nên lần đầu có thể mất hơn một phút.
const POLL_GIVE_UP_MS = 180000;

function showEmptyPanels() {
  document.querySelectorAll(".pnl-body .loading").forEach((el) => {
    el.textContent = "Chưa có dữ liệu — bấm ↻ để thử lại";
  });
}

async function loadAll() {
  const batDau = Date.now();
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
      // Chốt theo danh sách panel của trang: server thiếu key nào thì vẫn phải hỏi tiếp.
      return Object.keys(renderers).every((k) =>
        k === "lunar" ? !!d[k]?.data : d[k]?.data?.length > 0,
      );
    } catch (e) {
      return false;
    }
  };
  if (await poll()) return;
  const iv = setInterval(async () => {
    if ((await poll()) || Date.now() - batDau > POLL_GIVE_UP_MS) {
      clearInterval(iv);
      showEmptyPanels();
    }
  }, 3000);
}
// Bấm bất kỳ đâu trên thanh tiêu đề để thu gọn, trừ các nút bên trong nó.
document.getElementById("mainGrid").addEventListener("click", (e) => {
  const header = e.target.closest(".pnl-h");
  if (!header || e.target.closest("button")) return;
  togglePanelCollapse(header.closest(".pnl").dataset.key);
});

applyTheme(document.documentElement.dataset.theme || "dark");
loadAll();

// ─── CRYPTO POLL ───
setInterval(async () => {
  try {
    const r = await fetch("/api/prices");
    const d = await r.json();
    if (d.crypto?.data?.length) renderCrypto(d.crypto.data);
    if (d.gold?.data?.length) renderGold(d.gold.data);
    if (d.futures?.data?.length) renderFutures(d.futures.data);
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
