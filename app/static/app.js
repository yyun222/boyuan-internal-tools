const $ = (s) => document.querySelector(s);
const form = $("#upload-form");
const submitBtn = $("#submit-btn");
const statusEl = $("#status");
const resultsEl = $("#results");

function escapeHtml(value) {
  return String(value)
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;")
    .replace(/'/g, "&#39;");
}

let lastResult = null;
let currentUser = null;

const beijingDateFormatter = new Intl.DateTimeFormat("zh-CN", {
  timeZone:"Asia/Shanghai", year:"numeric", month:"2-digit", day:"2-digit", weekday:"long",
});
const beijingTimeFormatter = new Intl.DateTimeFormat("zh-CN", {
  timeZone:"Asia/Shanghai", hour:"2-digit", minute:"2-digit", second:"2-digit", hour12:false,
});
let homeFunFacts = [];
let homeFunFactIndex = 0;

function updateHomeClock() {
  const now = new Date();
  if ($("#home-date")) $("#home-date").textContent = beijingDateFormatter.format(now);
  if ($("#home-time")) {
    $("#home-time").textContent = beijingTimeFormatter.format(now);
    $("#home-time").dateTime = now.toISOString();
  }
}

function renderHomeFunFacts(facts) {
  homeFunFacts = Array.isArray(facts) ? facts : [];
  homeFunFactIndex = 0;
  showHomeFunFact();
}

function showHomeFunFact() {
  const fact = homeFunFacts[homeFunFactIndex];
  if (!fact) return;
  $("#home-fun-fact-english").textContent = fact.english || "";
  $("#home-fun-fact-chinese").textContent = fact.chinese || "";
  $("#home-fun-fact-number").textContent = `趣味知识 · ${homeFunFactIndex + 1} / ${homeFunFacts.length}`;
}

async function loadHomeFunFacts() {
  try {
    const cached = JSON.parse(sessionStorage.getItem("boyuan_fun_facts_v2") || "[]");
    if (Array.isArray(cached) && cached.length === 10) { renderHomeFunFacts(cached); return; }
  } catch (_) {}
  try {
    const response = await fetch("/api/fun-facts", {cache:"no-store"});
    if (!response.ok) throw new Error("趣味知识加载失败");
    const data = await response.json();
    sessionStorage.setItem("boyuan_fun_facts_v2", JSON.stringify(data.facts || []));
    renderHomeFunFacts(data.facts);
  } catch (_) {
    $("#home-fun-fact-english").textContent = "Fun facts are temporarily unavailable.";
    $("#home-fun-fact-chinese").textContent = "暂时无法获取趣味知识，请稍后再试。";
  }
}

async function loadNextHoliday() {
  const target = $("#home-holiday-countdown");
  if (!target) return;
  try {
    const response = await fetch("/api/next-holiday", {cache:"no-store"});
    if (!response.ok) throw new Error("节假日加载失败");
    const data = await response.json();
    const holiday = data.holiday;
    target.classList.remove("hidden");
    target.textContent = holiday.days === 0
      ? `今天是法定节假日「${holiday.name}」`
      : `距离下一个法定节假日「${holiday.name}」还剩 ${holiday.days} 天`;
  } catch (_) {
    target.textContent = "";
    target.classList.add("hidden");
  }
}

updateHomeClock();
setInterval(updateHomeClock, 1000);
$("#home-prev-fun-fact")?.addEventListener("click", () => {
  if (!homeFunFacts.length) return;
  homeFunFactIndex = (homeFunFactIndex - 1 + homeFunFacts.length) % homeFunFacts.length;
  showHomeFunFact();
});
$("#home-next-fun-fact")?.addEventListener("click", () => {
  if (!homeFunFacts.length) return;
  homeFunFactIndex = (homeFunFactIndex + 1) % homeFunFacts.length;
  showHomeFunFact();
});

// --- Auth: reuse the permission snapshot returned by login. Direct visits and
// new tabs fall back to one /api/me request; backend authorization remains live.
const cachedLoginUser = (() => {
  try { return JSON.parse(sessionStorage.getItem("boyuan_current_user") || "null"); }
  catch (_) { return null; }
})();

const currentUserRequest = cachedLoginUser
  ? Promise.resolve({user: cachedLoginUser})
  : fetch("/api/me", { cache: "no-store" })
  .then((r) => {
    if (r.status === 401) {
      window.location.replace("/login");
      return null;
    }
    return r.ok ? r.json() : null;
  });

const logoutBtn = $("#logout-btn");
logoutBtn?.addEventListener("click", async () => {
  logoutBtn.disabled = true;
  const originalText = logoutBtn.textContent;
  logoutBtn.textContent = "退出中…";
  try {
    const response = await fetch("/api/logout", { method: "POST" });
    if (!response.ok) throw new Error(`退出失败 (HTTP ${response.status})`);
    sessionStorage.removeItem("boyuan_current_user");
    window.location.replace("/login");
  } catch (error) {
    logoutBtn.disabled = false;
    logoutBtn.textContent = originalText;
    window.alert(error.message || "退出失败，请稍后重试");
  }
});


// --- Mobile sidebar toggle ---
const menuBtn = $("#menu-btn");
const overlay = $("#sidebar-overlay");
const closeSidebar = () => document.body.classList.remove("sidebar-open");
menuBtn.addEventListener("click", () => document.body.classList.toggle("sidebar-open"));
overlay.addEventListener("click", closeSidebar);
document.querySelectorAll(".nav-item").forEach((el) => el.addEventListener("click", closeSidebar));
window.addEventListener("resize", () => {
  if (window.innerWidth > 640) closeSidebar();
});
const sidebarCollapseBtn = $("#sidebar-collapse-btn");
if (localStorage.getItem("boyuan_sidebar_collapsed") === "true") document.body.classList.add("sidebar-collapsed");
sidebarCollapseBtn?.addEventListener("click", () => {
  const collapsed = document.body.classList.toggle("sidebar-collapsed");
  sidebarCollapseBtn.setAttribute("aria-label", collapsed ? "显示左侧菜单" : "隐藏左侧菜单");
  sidebarCollapseBtn.title = collapsed ? "显示左侧菜单" : "隐藏左侧菜单";
  localStorage.setItem("boyuan_sidebar_collapsed", String(collapsed));
});

function applyPermissions(user) {
  const permissions = user.permissions || {};
  const reconcileNav = document.querySelector('[data-view="reconcile"]');
  const reconcileView = $("#view-reconcile");
  const assetLedgerNav = $("#asset-ledger-nav");
  const adminNav = $("#admin-nav");
  const activityLogsNav = $("#activity-logs-nav");
  const stockOrdersNav = $("#stock-orders-nav");

  if (!permissions.viewReconcile) {
    reconcileNav?.classList.add("hidden");
    reconcileView?.classList.remove("active");
  }
  if (permissions.manageUsers) {
    adminNav?.classList.remove("hidden");
    activityLogsNav?.classList.remove("hidden");
  }
  if (!permissions.viewAssetLedger) {
    assetLedgerNav?.classList.add("hidden");
  }
  if (!permissions.viewStockOrders) stockOrdersNav?.classList.add("hidden");
  if (!permissions.updateReconcile) {
    submitBtn.disabled = true;
    submitBtn.title = "当前账号没有对账权限";
    $("#export-btn").disabled = true;
  }
  const activeNav = document.querySelector(".nav-item:not(.hidden)");
  if (!document.querySelector(".view.active") && activeNav?.dataset.view) {
    activeNav.classList.add("active");
    $(`#view-${activeNav.dataset.view}`)?.classList.add("active");
  }
}

// --- Export to Excel ---
$("#export-btn").addEventListener("click", async () => {
  if (!lastResult) {
    setStatus("请先完成对账", "error");
    return;
  }
  const btn = $("#export-btn");
  btn.disabled = true;
  const original = btn.innerHTML;
  btn.innerHTML = '<span class="export-icon">⏳</span> 生成中…';
  try {
    const resp = await fetch("/api/export", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(lastResult),
    });
    if (!resp.ok) {
      const err = await resp.json().catch(() => ({}));
      throw new Error(err.detail || `导出失败 (HTTP ${resp.status})`);
    }
    const blob = await resp.blob();
    const filename = parseFilename(resp.headers.get("Content-Disposition")) || "对账结果.xlsx";
    triggerDownload(blob, filename);
    setStatus(`已导出：${filename}`, "success");
  } catch (err) {
    setStatus(err.message || String(err), "error");
  } finally {
    btn.disabled = false;
    btn.innerHTML = original;
  }
});

function parseFilename(disposition) {
  if (!disposition) return null;
  const m = disposition.match(/filename\*=UTF-8''([^;]+)/i);
  if (m) return decodeURIComponent(m[1]);
  const m2 = disposition.match(/filename="?([^";]+)"?/i);
  return m2 ? m2[1] : null;
}

function triggerDownload(blob, filename) {
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = filename;
  document.body.appendChild(a);
  a.click();
  setTimeout(() => {
    URL.revokeObjectURL(url);
    a.remove();
  }, 0);
}

form.addEventListener("submit", async (e) => {
  e.preventDefault();
  const wh = $("#warehouse").files[0];
  const mp = $("#mapping").files[0];
  const fn = $("#finance").files[0];
  if (!wh || !mp || !fn) {
    setStatus("请上传全部三个文件", "error");
    return;
  }
  const fd = new FormData();
  fd.append("warehouse", wh);
  fd.append("mapping", mp);
  fd.append("finance", fn);

  submitBtn.disabled = true;
  setStatus("正在解析并对账，请稍候…", "");
  try {
    const resp = await fetch("/api/reconcile", { method: "POST", body: fd });
    if (!resp.ok) {
      const err = await resp.json().catch(() => ({}));
      throw new Error(err.detail || `请求失败 (HTTP ${resp.status})`);
    }
    const data = await resp.json();
    lastResult = data;
    renderResults(data);
    setStatus("对账完成", "success");
    resultsEl.classList.remove("hidden");
    resultsEl.scrollIntoView({ behavior: "smooth", block: "start" });
  } catch (err) {
    setStatus(err.message || String(err), "error");
  } finally {
    submitBtn.disabled = false;
  }
});

function setStatus(msg, kind) {
  statusEl.textContent = msg;
  statusEl.className = "status" + (kind ? " " + kind : "");
}

// --- Tab switching ---
document.querySelectorAll(".tab").forEach((tab) => {
  tab.addEventListener("click", () => {
    document.querySelectorAll(".tab").forEach((t) => t.classList.remove("active"));
    document.querySelectorAll(".tab-panel").forEach((p) => p.classList.remove("active"));
    tab.classList.add("active");
    const name = tab.dataset.tab;
    document.querySelector(`.tab-panel[data-panel="${name}"]`).classList.add("active");
  });
});

document.querySelectorAll(".nav-item[data-view]").forEach((item) => {
  item.addEventListener("click", () => {
    document.querySelectorAll(".nav-item[data-view]").forEach((el) => el.classList.remove("active"));
    document.querySelectorAll(".view").forEach((el) => el.classList.remove("active"));
    item.classList.add("active");
    $(`#view-${item.dataset.view}`)?.classList.add("active");
    if (item.dataset.view === "activity-logs") loadActivityLogs();
    if (item.dataset.view === "asset-ledger") renderAssetLedgerAll();
    if (item.dataset.view === "stock-orders") loadStockOrders();
  });
});
