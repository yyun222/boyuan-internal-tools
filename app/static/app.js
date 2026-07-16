const $ = (s) => document.querySelector(s);
const form = $("#upload-form");
const submitBtn = $("#submit-btn");
const statusEl = $("#status");
const resultsEl = $("#results");

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

currentUserRequest.then((d) => {
    if (!d || !d.user) return;
    currentUser = d.user;
    sessionStorage.setItem("boyuan_current_user", JSON.stringify(d.user));
    $("#current-user").textContent = d.user.email || d.user.username || "";
    applyPermissions(d.user);
    loadHomeFunFacts();
    loadNextHoliday();
    if (d.user.permissions?.manageUsers) {
      loadRoles();
      loadUsers();
      loadActivityLogs();
    }
    if (d.user.permissions?.viewAssetLedger) {
      initAssetLedger(d.user);
    }
    if (d.user.permissions?.viewStockOrders) initStockOrders(d.user);
  });

$("#logout-btn").addEventListener("click", async () => {
  await fetch("/api/logout", { method: "POST" });
  sessionStorage.removeItem("boyuan_current_user");
  sessionStorage.removeItem("boyuan_fun_facts_v1");
  sessionStorage.removeItem("boyuan_fun_facts_v2");
  window.location.href = "/login";
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

let managedRoles = [];
let managedUsers = [];

function renderRoleOptions(roles, selected = []) {
  const selectedNames = new Set(selected);
  return roles.map((role) => `
    <label class="role-option">
      <input type="checkbox" value="${escapeHtml(role.name)}" ${selectedNames.has(role.name) ? "checked" : ""} />
      <span>${escapeHtml(role.displayName)}${role.department ? ` · ${escapeHtml(role.department)}` : ""}</span>
    </label>
  `).join("");
}

async function loadRoles() {
  const target = $("#role-options");
  if (!target) return;
  const resp = await fetch("/api/roles", { cache: "no-store" });
  if (!resp.ok) return;
  const data = await resp.json();
  managedRoles = data.roles || [];
  target.innerHTML = renderRoleOptions(managedRoles);
  return managedRoles;
}

async function loadActivityLogs() {
  const table = $("#activity-log-table");
  if (!table) return;
  const resp = await fetch("/api/activity-logs", { cache: "no-store" });
  if (!resp.ok) return;
  const data = await resp.json();
  if (!data.logs.length) {
    table.innerHTML = '<tbody><tr><td class="empty">暂无操作日志</td></tr></tbody>';
    return;
  }
  table.innerHTML = `
    <thead><tr><th>时间</th><th>用户</th><th>动作</th><th>对象</th><th>详情</th></tr></thead>
    <tbody>${data.logs.map((log) => `
      <tr>
        <td>${escapeHtml(log.activityTime.replace("T", " ").slice(0, 19))}</td>
        <td>${escapeHtml(log.userEmail)}</td>
        <td>${escapeHtml(log.action)}</td>
        <td>${escapeHtml(log.target)}</td>
        <td>${escapeHtml(log.detail)}</td>
      </tr>
    `).join("")}</tbody>
  `;
}

function formatDateTime(value) {
  return value ? value.replace("T", " ").slice(0, 19) : "—";
}

async function loadUsers() {
  const table = $("#user-table");
  if (!table) return;
  const status = $("#user-status");
  table.innerHTML = '<tbody><tr><td class="empty">正在加载用户…</td></tr></tbody>';
  status.textContent = "";
  status.className = "status";
  try {
    const resp = await fetch("/api/users", { cache: "no-store" });
    const data = await resp.json().catch(() => ({}));
    if (!resp.ok) throw new Error(data.detail || `用户加载失败 (HTTP ${resp.status})`);
    if (!Array.isArray(data.users)) throw new Error("用户数据格式无效");
    managedUsers = data.users;
    if (!data.users.length) {
      table.innerHTML = '<tbody><tr><td class="empty">暂无用户</td></tr></tbody>';
      return;
    }
    table.innerHTML = `
      <thead><tr><th>用户</th><th>角色</th><th>状态</th><th>邀请时间</th><th>密码设置时间</th><th>最近活动</th><th>操作</th></tr></thead>
      <tbody>${data.users.map((user) => `
        <tr>
          <td>${escapeHtml(user.displayName || "")}<br><span class="muted">${escapeHtml(user.email)}</span></td>
          <td>${escapeHtml((user.roleDisplayNames || user.roles || []).join("、") || "—")}</td>
          <td><span class="user-state ${!user.hasPassword ? "pending" : (user.isActive ? "active" : "inactive")}">${!user.hasPassword ? "已邀请" : (user.isActive ? "正常" : "已停用")}</span></td>
          <td>${formatDateTime(user.invitedAt)}</td>
          <td>${formatDateTime(user.passwordSetAt)}</td>
          <td>${formatDateTime(user.lastActivityAt)}</td>
          <td><div class="user-row-actions"><button type="button" class="user-permission-btn" data-user-id="${user.id}">更新权限</button><button type="button" class="user-status-btn ${user.isActive ? "deactivate" : "activate"}" data-user-id="${user.id}" data-user-email="${escapeHtml(user.email)}" data-user-active="${user.isActive}" ${!user.hasPassword ? "disabled" : ""}>${user.isActive ? "停用" : "启用"}</button><button type="button" class="user-reset-btn" data-user-id="${user.id}" data-user-email="${escapeHtml(user.email)}" ${!user.hasPassword ? "disabled" : ""}>重置密码</button></div></td>
        </tr>
      `).join("")}</tbody>
    `;
  } catch (err) {
    const message = err.message || String(err);
    table.innerHTML = `<tbody><tr><td class="empty">${escapeHtml(message)}</td></tr></tbody>`;
    status.textContent = message;
    status.className = "status error";
  }
}

$("#refresh-users")?.addEventListener("click", loadUsers);
$("#user-table")?.addEventListener("click", async (event) => {
  const permissionBtn = event.target.closest(".user-permission-btn");
  if (permissionBtn) {
    await openUserPermissionEditor(Number(permissionBtn.dataset.userId));
    return;
  }
  const statusBtn = event.target.closest(".user-status-btn");
  if (statusBtn) {
    const isActive = statusBtn.dataset.userActive === "true";
    const action = isActive ? "停用" : "启用";
    if (!window.confirm(`确定${action} ${statusBtn.dataset.userEmail} 吗？${isActive ? "停用后该用户将无法登录。" : ""}`)) return;
    const status = $("#user-status");
    statusBtn.disabled = true;
    status.textContent = `正在${action}…`;
    status.className = "status";
    try {
      const resp = await fetch(`/api/users/${statusBtn.dataset.userId}/status`, {
        method: "PUT",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ is_active: !isActive }),
      });
      const data = await resp.json().catch(() => ({}));
      if (!resp.ok) throw new Error(data.detail || `${action}失败`);
      await Promise.all([loadUsers(), loadActivityLogs()]);
      status.textContent = `用户已${action}`;
      status.className = "status success";
    } catch (err) {
      status.textContent = err.message || String(err);
      status.className = "status error";
      statusBtn.disabled = false;
    }
    return;
  }
  const btn = event.target.closest(".user-reset-btn");
  if (!btn) return;
  const email = btn.dataset.userEmail;
  if (!window.confirm(`确定重置 ${email} 的密码吗？该用户会立即退出登录。`)) return;
  const status = $("#user-status");
  btn.disabled = true;
  status.textContent = "正在重置…";
  status.className = "status";
  try {
    const resp = await fetch(`/api/users/${btn.dataset.userId}/reset-password`, { method: "POST" });
    const data = await resp.json().catch(() => ({}));
    if (!resp.ok) throw new Error(data.detail || "重置失败");
    status.textContent = `密码已重置。新密码设置链接：${data.signupUrl}`;
    status.className = "status success";
    await Promise.all([loadUsers(), loadActivityLogs()]);
  } catch (err) {
    status.textContent = err.message || String(err);
    status.className = "status error";
    btn.disabled = false;
  }
});

async function openUserPermissionEditor(userId) {
  const user = managedUsers.find((item) => item.id === userId);
  if (!user) return;
  if (!managedRoles.length) await loadRoles();
  $("#user-permission-title").textContent = `更新权限 · ${user.displayName || user.email}`;
  $("#user-permission-id").value = String(user.id);
  $("#user-permission-options").innerHTML = renderRoleOptions(managedRoles, user.roles || []);
  $("#user-permission-status").textContent = "";
  $("#user-permission-mask").classList.add("active");
}

function closeUserPermissionEditor() {
  $("#user-permission-mask").classList.remove("active");
}

document.querySelectorAll("[data-user-permission-close]").forEach((button) => button.addEventListener("click", closeUserPermissionEditor));
$("#user-permission-mask")?.addEventListener("click", (event) => {
  if (event.target.id === "user-permission-mask") closeUserPermissionEditor();
});
$("#user-permission-form")?.addEventListener("submit", async (event) => {
  event.preventDefault();
  const userId = Number($("#user-permission-id").value);
  const roles = [...document.querySelectorAll("#user-permission-options input:checked")].map((input) => input.value);
  const status = $("#user-permission-status");
  const submit = $("#user-permission-submit");
  submit.disabled = true;
  status.textContent = "正在保存…";
  status.className = "status";
  try {
    const resp = await fetch(`/api/users/${userId}/roles`, {
      method: "PUT",
      headers: {"Content-Type":"application/json"},
      body: JSON.stringify({roles}),
    });
    const data = await resp.json().catch(() => ({}));
    if (!resp.ok) throw new Error(data.detail || "权限更新失败");
    await Promise.all([loadUsers(), loadActivityLogs()]);
    closeUserPermissionEditor();
    $("#user-status").textContent = "用户权限已更新";
    $("#user-status").className = "status success";
    if (currentUser?.id === userId) {
      sessionStorage.removeItem("boyuan_current_user");
      window.location.reload();
    }
  } catch (err) {
    status.textContent = err.message || String(err);
    status.className = "status error";
  } finally {
    submit.disabled = false;
  }
});

$("#refresh-logs")?.addEventListener("click", loadActivityLogs);

$("#invite-form")?.addEventListener("submit", async (e) => {
  e.preventDefault();
  const btn = $("#invite-btn");
  const status = $("#invite-status");
  const linkBox = $("#invite-link");
  const roles = Array.from(document.querySelectorAll("#role-options input:checked")).map((input) => input.value);
  status.textContent = "";
  linkBox.classList.add("hidden");
  btn.disabled = true;
  try {
    const resp = await fetch("/api/invitations", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        email: $("#invite-email").value,
        display_name: $("#invite-name").value,
        roles,
      }),
    });
    const data = await resp.json().catch(() => ({}));
    if (!resp.ok) throw new Error(data.detail || "邀请失败");
    status.textContent = "邀请已生成";
    status.className = "status success";
    linkBox.textContent = data.signupUrl;
    linkBox.classList.remove("hidden");
    await Promise.all([loadUsers(), loadActivityLogs()]);
  } catch (err) {
    status.textContent = err.message || String(err);
    status.className = "status error";
  } finally {
    btn.disabled = false;
  }
});

// --- Rendering ---
function fmtQty(v) {
  if (v === null || v === undefined) return "";
  const n = Number(v);
  if (Number.isInteger(n)) return n.toString();
  return n.toFixed(4).replace(/\.?0+$/, "");
}

function renderResults(data) {
  renderSummary(data.summary);
  document.getElementById("badge-mismatches").textContent = data.summary.mismatches;
  document.getElementById("badge-mapped_no_wh_balance").textContent = data.summary.mapped_no_wh_balance;
  document.getElementById("badge-fin_no_mapping").textContent = data.summary.fin_no_mapping;
  document.getElementById("badge-wh_only").textContent = data.summary.wh_only;
  document.getElementById("badge-matches").textContent = data.summary.matches;

  renderTable("tbl-mismatches",
    ["财务编号", "财务描述", "仓库代码", "仓库名称", "财务数量", "仓库数量", "差额"],
    data.mismatches,
    (r) => ({
      cells: [
        r.fin_code,
        r.fin_desc,
        r.wh_code,
        r.wh_name,
        { v: fmtQty(r.fin_qty), cls: "num" },
        { v: fmtQty(r.wh_qty), cls: "num" },
        { v: fmtQty(r.diff), cls: "num " + (r.diff > 0 ? "diff-pos" : "diff-neg") },
      ],
      rowClass: r.name_match ? "" : "name-mismatch",
    })
  );

  renderTable("tbl-mapped_no_wh_balance",
    ["财务编号", "财务描述", "对应仓库代码", "对应表中名称", "财务数量"],
    data.mapped_no_wh_balance,
    (r) => ({
      cells: [r.fin_code, r.fin_desc, r.wh_code, r.wh_name_in_mapping, { v: fmtQty(r.fin_qty), cls: "num" }],
    })
  );

  renderTable("tbl-fin_no_mapping",
    ["财务编号", "描述", "仓库", "单位", "财务数量"],
    data.fin_no_mapping,
    (r) => ({
      cells: [r.fin_code, r.fin_desc, r.warehouse, r.unit, { v: fmtQty(r.fin_qty), cls: "num" }],
    })
  );

  renderTable("tbl-wh_only",
    ["仓库代码", "仓库名称", "仓库数量"],
    data.wh_only,
    (r) => ({
      cells: [r.wh_code, r.wh_name, { v: fmtQty(r.wh_qty), cls: "num" }],
    })
  );

  renderTable("tbl-matches",
    ["财务编号", "财务描述", "仓库代码", "仓库名称", "数量"],
    data.matches,
    (r) => ({
      cells: [r.fin_code, r.fin_desc, r.wh_code, r.wh_name, { v: fmtQty(r.fin_qty), cls: "num" }],
    })
  );
}

function renderSummary(s) {
  const cards = [
    { label: "财务系统物料数", value: s.fin_total },
    { label: "仓库物料数", value: s.wh_total },
    { label: "完全匹配", value: s.matches, kind: "ok" },
    { label: "数量差异", value: s.mismatches, kind: s.mismatches ? "warn" : "ok" },
    { label: "其中名称疑似不一致", value: s.name_mismatches, kind: s.name_mismatches ? "bad" : "ok" },
    { label: "已映射但仓库无余额", value: s.mapped_no_wh_balance, kind: s.mapped_no_wh_balance ? "warn" : "ok" },
    { label: "财务无映射", value: s.fin_no_mapping, kind: s.fin_no_mapping ? "warn" : "ok" },
    { label: "仅在仓库", value: s.wh_only, kind: s.wh_only ? "warn" : "ok" },
  ];
  const html = cards
    .map((c) => `
      <div class="summary-card ${c.kind || ""}">
        <div class="label">${c.label}</div>
        <div class="value">${c.value}</div>
      </div>`)
    .join("");
  document.getElementById("summary").innerHTML = html;
}

function renderTable(tableId, headers, rows, rowFn) {
  const tbl = document.getElementById(tableId);
  if (!rows || rows.length === 0) {
    tbl.innerHTML = `<tbody><tr><td class="empty" colspan="${headers.length}">暂无数据</td></tr></tbody>`;
    return;
  }
  const thead = `<thead><tr>${headers.map((h) => `<th>${h}</th>`).join("")}</tr></thead>`;
  const tbody = "<tbody>" + rows.map((r) => {
    const { cells, rowClass = "" } = rowFn(r);
    const tds = cells.map((c) => {
      if (c && typeof c === "object") return `<td class="${c.cls || ""}">${escapeHtml(c.v ?? "")}</td>`;
      return `<td>${escapeHtml(c ?? "")}</td>`;
    }).join("");
    return `<tr class="${rowClass}">${tds}</tr>`;
  }).join("") + "</tbody>";
  tbl.innerHTML = thead + tbody;
}

function escapeHtml(s) {
  return String(s)
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;")
    .replace(/'/g, "&#39;");
}

// --- Fixed asset ledger ---
const assetSites = ["济阳厂区", "禹城厂区", "银丰研发中心", "公司办公/其他"];
const assetFallbackDepartments = [
  "工程部", "行政后勤", "仓储部", "销售部", "生产部", "质量部", "EHS",
  "济阳厂区", "采购部", "建筑路墙", "公共区", "动力车间",
];
const assetDepartments = assetFallbackDepartments;
const assetStatuses = ["在用", "待安装", "安装中", "维修中", "闲置", "拆解待处理", "报废待处置", "已报废"];
const assetChangeTypes = ["调拨", "报废", "拆解", "移位", "状态变更", "责任人变更"];

let assetUser = null;
let assetData = { assets: [], logs: [] };
let assetReady = false;
let assetHistoryPage = 1;
const ASSET_HISTORY_PAGE_SIZE = 50;

async function initAssetLedger(user) {
  assetUser = user;
  initAssetFilters();
  bindAssetEvents();
  const resp = await fetch("/api/asset-ledger/state", { cache: "no-store" });
  if (resp.ok) {
    assetData = await resp.json();
  }
  assetReady = true;
  renderAssetLedgerAll();
}

function initAssetFilters() {
  $("#asset-site-filter").innerHTML = assetOptionList(assetSites, "", "全部地点");
  $("#asset-dept-filter").innerHTML = assetOptionList(assetDepartments, "", "全部部门");
  $("#asset-status-filter").innerHTML = assetOptionList(assetStatuses, "", "全部状态");
  ["#asset-q", "#asset-site-filter", "#asset-dept-filter", "#asset-status-filter", "#asset-check-filter"].forEach((sel) => {
    $(sel)?.addEventListener("input", renderAssetLedger);
  });
}

function bindAssetEvents() {
  document.querySelector("[data-asset-add]")?.addEventListener("click", () => {
    if (!canUpdateAssetLedger()) return;
    openAssetModal("新增设备建账", assetForm(), (e) => {
      e.preventDefault();
      addAsset(Object.fromEntries(new FormData(e.target).entries()));
      closeAssetModal();
    });
  });
  document.querySelector("[data-asset-inventory]")?.addEventListener("click", () => {
    if (!canUpdateAssetLedger()) return;
    openAssetModal("盘点登记", inventoryForm(scopedAssets()[0]), (e) => {
      e.preventDefault();
      submitInventory(e);
      closeAssetModal();
    });
  });
  document.querySelector("[data-asset-history]")?.addEventListener("click", () => {
    const historyCard = $("#asset-history-card");
    const shouldShow = historyCard.classList.contains("hidden");
    if (shouldShow) assetHistoryPage = 1;
    historyCard.classList.toggle("hidden", !shouldShow);
    renderAssetHistory();
    if (shouldShow) {
      historyCard.scrollIntoView({ behavior: "smooth", block: "start" });
    }
  });
  document.querySelector("[data-asset-export]")?.addEventListener("click", exportAssetLedger);
  document.querySelector("[data-asset-export-history]")?.addEventListener("click", exportAssetHistory);
  $("#asset-history-pagination")?.addEventListener("click", (event) => {
    const button = event.target.closest("button[data-asset-history-page]");
    if (!button) return;
    assetHistoryPage = Number(button.dataset.assetHistoryPage);
    renderAssetHistory();
  });
  $("#asset-modal-mask")?.addEventListener("click", (e) => {
    if (e.target.id === "asset-modal-mask") closeAssetModal();
  });
}

function canUpdateAssetLedger() {
  return !!assetUser?.permissions?.updateAssetLedger;
}

function isAllAssetAccess() {
  return assetUser?.scope === "all";
}

function canAccessAsset(asset) {
  return isAllAssetAccess()
    || (assetUser?.departments || []).includes(asset.department)
    || asset.department === assetUser?.department;
}

function scopedAssets() {
  return (assetData.assets || []).filter(canAccessAsset);
}

function allowedAssetDepartmentOptions(selected = "") {
  if (!assetUser || isAllAssetAccess()) return assetOptionList(assetDepartments, selected);
  const allowed = assetUser.departments?.length ? assetUser.departments : [assetUser.department];
  return assetOptionList(allowed, selected || allowed[0]);
}

function assetToday() {
  const parts = new Intl.DateTimeFormat("en-US", {timeZone:"Asia/Shanghai", year:"numeric", month:"2-digit", day:"2-digit"}).formatToParts(new Date());
  const values = Object.fromEntries(parts.map(part => [part.type, part.value]));
  return `${values.year}-${values.month}-${values.day}`;
}

function assetUid() {
  return "FA-" + Date.now().toString().slice(-8);
}

function assetOptionList(items, selected = "", allLabel = "") {
  const first = allLabel ? `<option value="">${allLabel}</option>` : "";
  return first + items.map((item) => `<option value="${escapeHtml(item)}" ${item === selected ? "selected" : ""}>${escapeHtml(item)}</option>`).join("");
}

function assetStatusTag(status) {
  const cls = status === "在用" ? "normal"
    : status.includes("维修") ? "repair"
    : status.includes("闲置") || status.includes("拆解") ? "idle"
    : status.includes("报废") ? "scrap" : "pending";
  return `<span class="asset-tag ${cls}">${escapeHtml(status)}</span>`;
}

function renderAssetLedgerAll() {
  if (!assetReady) return;
  renderAssetLedger();
  renderAssetHistory();
  document.querySelectorAll("[data-asset-add], [data-asset-inventory]").forEach((btn) => {
    btn.style.display = canUpdateAssetLedger() ? "" : "none";
  });
}

function filteredAssets() {
  const q = $("#asset-q").value.trim().toLowerCase();
  const site = $("#asset-site-filter").value;
  const dept = $("#asset-dept-filter").value;
  const status = $("#asset-status-filter").value;
  const check = $("#asset-check-filter").value;
  return (assetData.assets || []).filter((asset) => {
    const text = [asset.assetNo, asset.name, asset.model, asset.location, asset.department, asset.owner].join(" ").toLowerCase();
    return canAccessAsset(asset)
      && (!q || text.includes(q))
      && (!site || asset.site === site)
      && (!dept || asset.department === dept)
      && (!status || asset.status === status)
      && (!check || asset.checkResult === check);
  });
}

function renderAssetLedger() {
  const visible = scopedAssets();
  const stats = [
    ["设备总数", visible.length],
    ["在用", visible.filter((a) => a.status === "在用").length],
    ["待处理状态", visible.filter((a) => ["拆解待处理", "报废待处置", "待安装", "安装中"].includes(a.status)).length],
    ["未盘点", visible.filter((a) => !a.checkResult || a.checkResult === "未盘点").length],
    ["盘点差异", visible.filter((a) => a.checkResult === "差异").length],
  ];
  $("#asset-stats").innerHTML = stats.map(([label, value]) => `<div class="asset-stat"><label>${label}</label><strong>${value}</strong></div>`).join("");
  const rows = filteredAssets();
  $("#asset-rows").innerHTML = rows.length ? rows.map((asset) => `
    <tr>
      <td><strong>${escapeHtml(asset.assetNo)}</strong></td>
      <td>${escapeHtml(asset.name)}</td>
      <td>${escapeHtml(asset.model)}</td>
      <td>${escapeHtml(asset.site)}</td>
      <td>${escapeHtml(asset.department)}</td>
      <td>${escapeHtml(asset.location)}</td>
      <td>${escapeHtml(asset.startDate)}</td>
      <td>${escapeHtml(asset.owner)}</td>
      <td>${assetStatusTag(asset.status || "")}</td>
      <td>${escapeHtml(asset.checkResult || "未盘点")}</td>
      <td><div class="asset-row-actions">${canUpdateAssetLedger() ? `<button onclick="openAssetChange('${asset.id}')">变更</button>` : ""}</div></td>
    </tr>
  `).join("") : `<tr><td colspan="11" class="empty">暂无设备台账</td></tr>`;
}

function assetForm(asset = {}) {
  return `
    <form>
      <div class="asset-form-grid">
        <div class="asset-field"><label class="required">设备编号</label><input name="assetNo" required value="${escapeHtml(asset.assetNo || assetUid())}"></div>
        <div class="asset-field"><label class="required">设备名称</label><input name="name" required value="${escapeHtml(asset.name || "")}"></div>
        <div class="asset-field"><label class="required">规格型号</label><input name="model" required value="${escapeHtml(asset.model || "")}"></div>
        <div class="asset-field"><label class="required">所属地点</label><select name="site" required>${assetOptionList(assetSites, asset.site)}</select></div>
        <div class="asset-field"><label class="required">分部门</label><select name="department" required>${allowedAssetDepartmentOptions(asset.department)}</select></div>
        <div class="asset-field"><label class="required">状态</label><select name="status" required>${assetOptionList(assetStatuses, asset.status || "在用")}</select></div>
        <div class="asset-field"><label class="required">安装/使用位置</label><input name="location" required value="${escapeHtml(asset.location || "")}"></div>
        <div class="asset-field"><label class="required">启用时间</label><input type="date" name="startDate" required value="${escapeHtml(asset.startDate || assetToday())}"></div>
        <div class="asset-field"><label class="required">部门负责人</label><input name="manager" required value="${escapeHtml(asset.manager || "")}"></div>
        <div class="asset-field"><label class="required">资产管理员</label><input name="admin" required value="${escapeHtml(asset.admin || "")}"></div>
        <div class="asset-field"><label class="required">使用责任人</label><input name="owner" required value="${escapeHtml(asset.owner || "")}"></div>
        <div class="asset-field"><label>最近盘点结果</label><select name="checkResult">${assetOptionList(["未盘点", "一致", "差异"], asset.checkResult || "未盘点")}</select></div>
        <div class="asset-field wide"><label>备注</label><textarea name="remark">${escapeHtml(asset.remark || "")}</textarea></div>
      </div>
      <div class="asset-form-footer">
        <button type="button" data-asset-close-modal>取消</button>
        <button class="primary" type="submit">保存</button>
      </div>
    </form>`;
}

function changeForm(asset) {
  const availableAssets = scopedAssets();
  if (!availableAssets.length) return `<div class="asset-notice">当前账号没有可变更的设备。</div>`;
  return `
    <form>
      <div class="asset-form-grid">
        <div class="asset-field wide"><label class="required">选择设备</label><select name="id" required>${availableAssets.map((item) => `<option value="${item.id}" ${asset && item.id === asset.id ? "selected" : ""}>${escapeHtml(item.assetNo)} - ${escapeHtml(item.name)} - ${escapeHtml(item.department)}</option>`).join("")}</select></div>
        <div class="asset-field"><label class="required">变更类型</label><select name="type" required>${assetOptionList(assetChangeTypes)}</select></div>
        <div class="asset-field"><label>新地点</label><select name="site"><option value="">不变</option>${assetOptionList(assetSites)}</select></div>
        <div class="asset-field"><label>新部门/车间</label><select name="department"><option value="">不变</option>${isAllAssetAccess() ? assetOptionList(assetDepartments) : allowedAssetDepartmentOptions()}</select></div>
        <div class="asset-field"><label>新位置</label><input name="location" placeholder="不变可留空"></div>
        <div class="asset-field"><label>新状态</label><select name="status"><option value="">不变</option>${assetOptionList(assetStatuses)}</select></div>
        <div class="asset-field"><label>新使用责任人</label><input name="owner" placeholder="不变可留空"></div>
        <div class="asset-field wide"><label class="required">变更原因/说明</label><textarea name="reason" required></textarea></div>
      </div>
      <div class="asset-form-footer">
        <button type="button" data-asset-close-modal>取消</button>
        <button class="primary" type="submit">提交登记</button>
      </div>
    </form>`;
}

function inventoryForm(asset) {
  const availableAssets = scopedAssets();
  if (!availableAssets.length) return `<div class="asset-notice">当前账号没有可盘点的设备。</div>`;
  return `
    <form>
      <div class="asset-form-grid">
        <div class="asset-field wide"><label class="required">选择设备</label><select name="id" required>${availableAssets.map((item) => `<option value="${item.id}" ${asset && item.id === asset.id ? "selected" : ""}>${escapeHtml(item.assetNo)} - ${escapeHtml(item.name)} - 台账位置：${escapeHtml(item.location)}</option>`).join("")}</select></div>
        <div class="asset-field"><label class="required">实盘结果</label><select name="checkResult" required>${assetOptionList(["一致", "差异"])}</select></div>
        <div class="asset-field"><label class="required">实盘位置</label><input name="actualLocation" required value="${escapeHtml(asset ? asset.location : "")}"></div>
        <div class="asset-field"><label class="required">盘点人</label><input name="checker" required></div>
        <div class="asset-field wide"><label>差异说明/整改措施</label><textarea name="note"></textarea></div>
      </div>
      <div class="asset-form-footer">
        <button type="button" data-asset-close-modal>取消</button>
        <button class="green" type="submit">保存盘点</button>
      </div>
    </form>`;
}

function addAsset(values) {
  if (!canUpdateAssetLedger()) return;
  if (!isAllAssetAccess()) values.department = assetUser.department;
  const asset = { id: String(Date.now() + Math.random()), createdAt: assetToday(), updatedAt: assetToday(), ...values };
  assetData.assets.unshift(asset);
  logAsset("新增建账", asset, `设备入账，位置：${asset.location}，责任人：${asset.owner}`);
  saveAssetLedger();
  renderAssetLedgerAll();
}

function applyAssetChange(values) {
  if (!canUpdateAssetLedger()) return;
  const asset = assetData.assets.find((item) => item.id === values.id);
  if (!asset || !canAccessAsset(asset)) return;
  const before = `${asset.site}/${asset.department}/${asset.location}/${asset.status}/${asset.owner}`;
  ["site", "department", "location", "status", "owner"].forEach((key) => {
    if (values[key]) asset[key] = values[key];
  });
  asset.updatedAt = assetToday();
  const after = `${asset.site}/${asset.department}/${asset.location}/${asset.status}/${asset.owner}`;
  logAsset(values.type, asset, `${values.reason}。变更前：${before}；变更后：${after}`);
  saveAssetLedger();
  renderAssetLedgerAll();
}

function submitInventory(event) {
  if (!canUpdateAssetLedger()) return;
  const values = Object.fromEntries(new FormData(event.target).entries());
  const asset = assetData.assets.find((item) => item.id === values.id);
  if (!asset || !canAccessAsset(asset)) return;
  asset.checkResult = values.checkResult;
  asset.lastCheckDate = assetToday();
  asset.actualLocation = values.actualLocation;
  asset.updatedAt = assetToday();
  logAsset("盘点登记", asset, `结果：${values.checkResult}；实盘位置：${values.actualLocation}；盘点人：${values.checker}；${values.note || ""}`);
  saveAssetLedger();
  renderAssetLedgerAll();
}

function logAsset(action, asset, detail) {
  assetHistoryPage = 1;
  assetData.logs.unshift({
    id: Date.now() + Math.random(),
    date: assetToday(),
    action,
    assetNo: asset.assetNo,
    assetName: asset.name,
    department: asset.department,
    detail,
  });
}

async function saveAssetLedger() {
  const resp = await fetch("/api/asset-ledger/state", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(assetData),
  }).catch(() => null);
  if (!resp || !resp.ok) alert("保存到服务器失败，请检查权限、网络或服务器是否运行。");
}

function renderAssetHistory() {
  const allowed = assetUser?.departments || [assetUser?.department];
  const logs = (assetData.logs || []).filter((log) => isAllAssetAccess() || allowed.includes(log.department));
  const totalPages = Math.max(1, Math.ceil(logs.length / ASSET_HISTORY_PAGE_SIZE));
  assetHistoryPage = Math.min(Math.max(assetHistoryPage, 1), totalPages);
  const start = (assetHistoryPage - 1) * ASSET_HISTORY_PAGE_SIZE;
  const pageLogs = logs.slice(start, start + ASSET_HISTORY_PAGE_SIZE);
  $("#asset-history-list").innerHTML = pageLogs.length ? pageLogs.map((log) => `
    <div class="asset-event">
      <strong>${escapeHtml(log.date)} ｜ ${escapeHtml(log.action)} ｜ ${escapeHtml(log.assetNo)} ${escapeHtml(log.assetName)}</strong>
      <p>${escapeHtml(log.department)}：${escapeHtml(log.detail)}</p>
    </div>
  `).join("") : `<div class="asset-event"><strong>暂无记录</strong><p>新增、变更和盘点后会自动生成记录。</p></div>`;
  $("#asset-history-pagination").innerHTML = logs.length > ASSET_HISTORY_PAGE_SIZE ? `
    <span>第 ${assetHistoryPage} / ${totalPages} 页，共 ${logs.length} 条</span>
    <div class="asset-history-page-buttons">
      <button type="button" data-asset-history-page="${assetHistoryPage - 1}" ${assetHistoryPage <= 1 ? "disabled" : ""}>上一页</button>
      <button type="button" data-asset-history-page="${assetHistoryPage + 1}" ${assetHistoryPage >= totalPages ? "disabled" : ""}>下一页</button>
    </div>
  ` : "";
}

function openAssetModal(title, html, onSubmit) {
  $("#asset-modal-title").textContent = title;
  $("#asset-modal-body").innerHTML = html;
  $("#asset-modal-mask").classList.add("active");
  $("#asset-modal-body form")?.addEventListener("submit", onSubmit);
  document.querySelectorAll("[data-asset-close-modal]").forEach((btn) => btn.addEventListener("click", closeAssetModal));
}

function closeAssetModal() {
  $("#asset-modal-mask").classList.remove("active");
}

window.openAssetChange = (id) => {
  if (!canUpdateAssetLedger()) return;
  const asset = assetData.assets.find((item) => item.id === id);
  openAssetModal("资产变更登记", changeForm(asset), (event) => {
    event.preventDefault();
    applyAssetChange(Object.fromEntries(new FormData(event.target).entries()));
    closeAssetModal();
  });
};

function exportAssetLedger() {
  const rows = [["设备编号","设备名称","规格型号","地点","分部门","使用部门","安装/使用位置","启用时间","部门负责人","资产管理员","使用责任人","状态","盘点结果","最近盘点日期","备注"]];
  scopedAssets().forEach((asset) => rows.push([asset.assetNo, asset.name, asset.model, asset.site, asset.department, asset.useDepartment || "", asset.location, asset.startDate, asset.manager, asset.admin, asset.owner, asset.status, asset.checkResult || "未盘点", asset.lastCheckDate || "", asset.remark || ""]));
  downloadAssetCsv("设备实物台账.csv", rows);
}

function exportAssetHistory() {
  const rows = [["日期","动作","设备编号","设备名称","部门","详情"]];
  const allowed = assetUser?.departments || [assetUser?.department];
  (assetData.logs || []).filter((log) => isAllAssetAccess() || allowed.includes(log.department)).forEach((log) => rows.push([log.date, log.action, log.assetNo, log.assetName, log.department, log.detail]));
  downloadAssetCsv("设备变更记录.csv", rows);
}

function downloadAssetCsv(name, rows) {
  const csv = rows.map((row) => row.map((value) => {
    const text = String(value ?? "");
    return /[",\n]/.test(text) ? '"' + text.replace(/"/g, '""') + '"' : text;
  }).join(",")).join("\n");
  const blob = new Blob(["\ufeff" + csv], { type: "text/csv;charset=utf-8" });
  const url = URL.createObjectURL(blob);
  const link = document.createElement("a");
  link.href = url;
  link.download = name;
  link.click();
  URL.revokeObjectURL(url);
}

// --- Stock order tracking ---
let stockUser = null;
let stockCurrent = null;
let stockHistory = [];
let stockMode = "view";
let stockPage = 1;
let stockPageSize = 10;
let stockSortBy = "";
let stockSortOrder = "asc";
const STOCK_GROUPS = [
  ["基础与销售", "sales", [["internal_name","内部简称"],["cas","CAS"],["quantity","数量"],["order_type","订单类型","select"],["salesperson","业务员"],["demand_date","提需求日期","date"],["customer_name","客户名称"],["order_situation","订单情况","textarea"],["quality_requirement","质量要求","textarea"],["delivery_requirement","交货期需求","date"],["sales_note","其他说明","textarea"],["actual_delivery","实际交货","date"]]],
  ["采购部", "purchase", [["purchase_not_required","无需采购","checkbox"],["purchase_items","采购原料及数量","items"],["purchase_date","采购日期","date"],["arrival_date","预计到货时间","date"],["purchase_note","采购说明","textarea"],["purchase_owner","采购负责人"]]],
  ["生产部", "production", [["production_not_required","无需生产","checkbox"],["production_form_date","填表日期","date"],["production_status","评估当前状态","textarea"],["expected_delivery_date","预计完成时间","date"],["production_note","生产说明","textarea"]]],
  ["质量部", "qc", [["qc_not_required","无需检测","checkbox"],["coa_time","预计完成时间","date"],["qc_note","QC备注","textarea"],["qc_owner","QC负责人"]]],
];

function initStockOrders(user) {
  stockUser = user;
  $("#stock-new-btn")?.addEventListener("click", () => openStockOrder());
  $("#stock-search-btn")?.addEventListener("click", () => {
    if (!validateStockDateRange()) return;
    stockPage = 1;
    loadStockOrders();
  });
  [$("#stock-from"), $("#stock-to")].forEach(input => input?.addEventListener("input", validateStockDateRange));
  document.querySelector(".stock-table thead")?.addEventListener("click", (event) => {
    const button = event.target.closest("[data-stock-sort]");
    if (!button) return;
    const field = button.dataset.stockSort;
    stockSortOrder = stockSortBy === field && stockSortOrder === "asc" ? "desc" : "asc";
    stockSortBy = field;
    stockPage = 1;
    loadStockOrders();
  });
  $("#stock-pagination")?.addEventListener("click", (event) => {
    const button = event.target.closest("[data-stock-page]");
    if (!button || button.disabled) return;
    stockPage = Number(button.dataset.stockPage);
    loadStockOrders();
  });
  $("#stock-pagination")?.addEventListener("change", (event) => {
    if (!event.target.matches("[data-stock-page-size]")) return;
    stockPageSize = Number(event.target.value);
    stockPage = 1;
    loadStockOrders();
  });
  $("#stock-history-btn")?.addEventListener("click", () => {
    $("#stock-history-order").value = "";
    $("#stock-history-operator").value = "";
    $("#stock-history-month").value = "";
    openStockHistory();
  });
  $("#stock-history-search")?.addEventListener("click", loadStockHistory);
  $("#stock-history-export")?.addEventListener("click", () => exportStockCsv("changes"));
  $("#stock-orders-export")?.addEventListener("click", () => exportStockCsv("orders"));
  $("#stock-performance-export")?.addEventListener("click", () => exportStockCsv("performance"));
  document.querySelector("[data-stock-close]")?.addEventListener("click", closeStockOrder);
  document.querySelector("[data-stock-history-close]")?.addEventListener("click", () => $("#stock-history-mask").classList.remove("active"));
  const canCreate = user.permissions?.updateStockOrders && (user.roles?.includes("admin") || user.departments?.includes("销售部"));
  if (!canCreate) $("#stock-new-btn")?.classList.add("hidden");
  if (!user.roles?.includes("admin")) {
    ["#stock-history-month","#stock-history-export","#stock-orders-export","#stock-performance-export"].forEach(id => $(id)?.classList.add("hidden"));
  }
  loadStockOrders();
}

async function stockApi(url, options = {}) {
  const resp = await fetch(url, {headers:{"Content-Type":"application/json", ...(options.headers || {})}, ...options});
  const data = await resp.json().catch(() => ({}));
  if (resp.status === 401) { sessionStorage.removeItem("boyuan_current_user"); window.location.replace("/login"); }
  if (!resp.ok) throw new Error(data.detail || `请求失败 (${resp.status})`);
  return data;
}

async function loadStockOrders() {
  if (!stockUser) return;
  const params = new URLSearchParams({q:$("#stock-q").value, order_type:$("#stock-type").value, incomplete:$("#stock-incomplete").value, date_from:$("#stock-from").value, date_to:$("#stock-to").value, page:String(stockPage), page_size:String(stockPageSize), sort_by:stockSortBy, sort_order:stockSortOrder});
  const body = $("#stock-rows");
  body.innerHTML = '<tr><td colspan="14" class="empty">正在加载…</td></tr>';
  try {
    const data = await stockApi("/api/stock-orders?" + params);
    body.innerHTML = data.orders.length ? data.orders.map(stockRow).join("") : '<tr><td colspan="14" class="empty">暂无订单</td></tr>';
    stockPage = data.pagination.page;
    renderStockSortHeaders();
    renderStockPagination(data.pagination);
  } catch (err) { body.innerHTML = `<tr><td colspan="14" class="empty">${escapeHtml(err.message)}</td></tr>`; }
}

function renderStockSortHeaders() {
  document.querySelectorAll("[data-stock-sort]").forEach(button => {
    const active = button.dataset.stockSort === stockSortBy;
    button.classList.toggle("active", active);
    button.querySelector("span").textContent = active ? (stockSortOrder === "asc" ? "↑" : "↓") : "↕";
  });
}

function validateStockDateRange() {
  const from = $("#stock-from");
  const to = $("#stock-to");
  const incompleteRange = Boolean(from?.value) !== Boolean(to?.value);
  from?.classList.toggle("stock-date-required", incompleteRange && !from.value);
  to?.classList.toggle("stock-date-required", incompleteRange && !to.value);
  return !incompleteRange;
}

function renderStockPagination(pagination) {
  const target = $("#stock-pagination");
  if (!target) return;
  target.innerHTML = `<div class="stock-page-summary"><label>每页显示 <select data-stock-page-size>${[10,20,50,100].map(size => `<option value="${size}" ${size === pagination.pageSize ? "selected" : ""}>${size}</option>`).join("")}</select> 条</label><span>第 ${pagination.page} / ${pagination.totalPages} 页，共 ${pagination.total} 条</span></div><div><button type="button" data-stock-page="${pagination.page - 1}" ${pagination.page <= 1 ? "disabled" : ""}>上一页</button><button type="button" data-stock-page="${pagination.page + 1}" ${pagination.page >= pagination.totalPages ? "disabled" : ""}>下一页</button></div>`;
}

function stockState(order, module) {
  if (order.archive_status === "已取消") {
    const completed = module === "sales" ? (order.sales_completed_at || order.actual_delivery) : order[`${module}_completed_at`];
    return completed ? '<span class="stock-state done">已完成</span>' : '<span class="stock-state muted-state">—</span>';
  }
  if (order.order_type === "现货留货" && module !== "sales") return '<span class="stock-state muted-state">无需处理</span>';
  const department = {sales:"销售部",purchase:"采购部",production:"生产部",qc:"质量部"}[module];
  const warning = order.warnings?.find(item => item.department === department);
  if (warning) return `<span class="stock-state late">${escapeHtml(warning.message)}</span>`;
  if (order.overdue?.[module]) return `<span class="stock-state late">${escapeHtml(order.overdue[module])}</span>`;
  const status = order.module_statuses?.[module] || "未填写";
  if (status === "已完成") return '<span class="stock-state done">已完成</span>';
  if (status === "进行中") return '<span class="stock-state pending">进行中</span>';
  return '<span class="stock-state unfilled">未填写</span>';
}

function stockRow(order) {
  const moduleByDepartment = {"销售部":"sales","采购部":"purchase","生产部":"production","质量部":"qc"};
  const ownEditableModule = stockUser.departments?.map(d => moduleByDepartment[d]).find(module => module && !(module === "sales" ? order.sales_completed_at : order[`${module}_completed_at`]));
  const canEditDepartment = stockUser.roles?.includes("admin") || Boolean(ownEditableModule);
  const canEdit = order.archive_status !== "已取消" && stockUser.permissions?.updateStockOrders && canEditDepartment;
  const cancel = stockUser.roles?.includes("admin") && order.archive_status !== "已取消" ? `<button class="danger" onclick="cancelStockOrder(${order.id})">取消订单</button>` : "";
  const deliveryLate = order.warnings?.some(item => item.type === "sales_delivery_late");
  return `<tr class="${order.archive_status === "已取消" ? "stock-cancelled-row" : ""}"><td><strong>${escapeHtml(order.order_no)}</strong>${order.archive_status === "已取消" ? '<br><span class="stock-state cancelled">已取消</span>' : ""}</td><td>${escapeHtml(order.salesperson || "—")}</td><td>${escapeHtml(order.order_type)}</td><td>${escapeHtml(order.customer_name || "—")}</td><td>${escapeHtml(order.internal_name || "—")}<br><span class="muted">${escapeHtml(order.cas || "")}</span></td><td>${escapeHtml(order.quantity || "—")}</td><td>${stockState(order,"sales")}</td><td>${stockState(order,"purchase")}</td><td>${stockState(order,"production")}</td><td>${stockState(order,"qc")}</td><td class="${deliveryLate ? "stock-delivery-late" : ""}">${escapeHtml(order.actual_delivery || "—")}${deliveryLate ? "<br>晚于交货期需求" : ""}</td><td>${escapeHtml((order.created_at || "").replace("T"," ").slice(0,16))}</td><td>${escapeHtml((order.updated_at || "").replace("T"," ").slice(0,16))}</td><td><button class="stock-open-btn" onclick="openStockOrder(${order.id},'view')">查看</button>${canEdit ? `<button class="stock-open-btn" onclick="openStockOrder(${order.id},'edit')">修改</button>` : ""}<button class="stock-open-btn" onclick="openOrderStockHistory('${escapeHtml(order.order_no)}')">历史</button>${cancel}</td></tr>`;
}

async function openStockOrder(id = null, mode = "edit") {
  try {
    stockMode = id ? mode : "edit";
    const ownModules = stockUser.roles?.includes("admin") ? ["sales","purchase","production","qc"] : ({"销售部":"sales","采购部":"purchase","生产部":"production","质量部":"qc"})[stockUser.departments?.[0]] ? stockUser.departments.map(d => ({"销售部":"sales","采购部":"purchase","生产部":"production","质量部":"qc"})[d]).filter(Boolean) : [];
    stockCurrent = id ? (await stockApi(`/api/stock-orders/${id}`)).order : {order_type:"备货订单", locks:{}, editableModules:ownModules, isAdmin:stockUser.roles?.includes("admin")};
    $("#stock-modal-title").textContent = id ? (stockMode === "view" ? "查看订单" : "修改订单") : "新建订单";
    $("#stock-modal-number").textContent = stockCurrent.order_no || "保存后自动生成订单号";
    $("#stock-modal-body").innerHTML = renderStockForm();
    $("#stock-modal-mask").classList.add("active");
    $("#stock-order-form").addEventListener("submit", saveStockOrder);
    document.querySelectorAll("[data-stock-complete]").forEach(btn => btn.addEventListener("click", () => completeStockModule(btn.dataset.stockComplete)));
    document.querySelectorAll("[data-stock-save-module]").forEach(btn => btn.addEventListener("click", () => saveStockModule(btn.dataset.stockSaveModule)));
    document.querySelectorAll("[data-stock-recognize]").forEach(btn => btn.addEventListener("click", () => recognizeStockText(btn.dataset.stockRecognize)));
    $("#stock-add-purchase-row")?.addEventListener("click", addPurchaseRow);
    $("#stock-cancel-btn")?.addEventListener("click", cancelStockOrder);
  } catch (err) { alert(err.message); }
}
window.openStockOrder = openStockOrder;

function renderStockField([key,label,type]) {
  const value = stockCurrent[key] ?? "";
  const module = STOCK_GROUPS.find(group => group[2].some(field => field[0] === key))?.[1] || "sales";
  const locked = stockCurrent.locks?.[key];
  const completed = module === "sales" ? stockCurrent.sales_completed_at : stockCurrent[`${module}_completed_at`];
  const holdModule = stockCurrent.order_type === "现货留货" && module !== "sales";
  const disabled = stockMode === "view" || holdModule || !stockUser.permissions?.updateStockOrders || !stockCurrent.editableModules.includes(module) || (completed && !stockCurrent.isAdmin) || (locked && !stockCurrent.isAdmin) || stockCurrent.archive_status === "已取消";
  if (stockMode === "view") {
    let shown = value || "—";
    if (type === "checkbox") shown = value ? "是" : "否";
    if (type === "items") { try { shown = JSON.parse(value || "[]").map(x => `${x.material || ""} × ${x.quantity || ""}`).join("；") || "—"; } catch (_) {} }
    return `<div class="stock-view-field"><strong>${label}</strong><span>${escapeHtml(shown)}</span></div>`;
  }
  if (type === "items") {
    let items = []; try { items = JSON.parse(value || "[]"); } catch (_) {}
    if (!items.length && (stockCurrent.purchase_material || stockCurrent.purchase_quantity)) items = [{material:stockCurrent.purchase_material, quantity:stockCurrent.purchase_quantity}];
    if (!items.length) items = [{material:"",quantity:""}];
    return `<div class="wide stock-purchase-items" data-disabled="${disabled ? "true" : "false"}"><span>${label}${locked ? ' <em>已锁定</em>' : ''}</span><div id="stock-purchase-item-rows">${items.map(item => purchaseItemRow(item, disabled)).join("")}</div>${disabled ? "" : '<button id="stock-add-purchase-row" type="button">添加一行</button>'}</div>`;
  }
  if (type === "checkbox") return `<label class="stock-check"><input name="${key}" type="checkbox" ${value ? "checked" : ""} ${disabled ? "disabled" : ""}>${label}${locked ? ' <em>已锁定</em>' : ''}</label>`;
  if (type === "select") return `<label class="stock-field-${key}"><span>${label}${locked ? ' <em>已锁定</em>' : ''}</span><select name="${key}" ${disabled ? "disabled" : ""}><option ${value === "备货订单" ? "selected" : ""}>备货订单</option><option ${value === "现货留货" ? "selected" : ""}>现货留货</option></select></label>`;
  if (type === "textarea") return `<label class="wide stock-field-${key}"><span>${label}${locked ? ' <em>已锁定</em>' : ''}</span><textarea name="${key}" ${disabled ? "disabled" : ""}>${escapeHtml(value)}</textarea></label>`;
  return `<label class="stock-field-${key}"><span>${label}${locked ? ' <em>已锁定</em>' : ''}</span><input name="${key}" type="${type || "text"}" value="${escapeHtml(value)}" ${disabled ? "disabled" : ""}></label>`;
}

function renderStockForm() {
  const hold = stockCurrent.order_type === "现货留货";
  const cancelled = stockCurrent.archive_status === "已取消";
  return `<form id="stock-order-form"><div class="stock-modules">${STOCK_GROUPS.map(([title,module,fields]) => {
    const done = stockCurrent[`${module}_completed_at`];
    const moduleDone = module === "sales" ? stockCurrent.sales_completed_at : done;
    const canComplete = stockMode === "edit" && stockCurrent.id && (!hold || module === "sales") && !cancelled && stockCurrent.editableModules.includes(module) && !moduleDone;
    const recognize = stockMode === "edit" && ["sales","purchase"].includes(module) && stockCurrent.editableModules.includes(module) && (!moduleDone || stockCurrent.isAdmin) ? `<button type="button" data-stock-recognize="${module}">粘贴并识别</button>` : "";
    const canSaveModule = stockMode === "edit" && (stockCurrent.id || module === "sales") && (!hold || module === "sales") && !cancelled && stockCurrent.editableModules.includes(module) && (!moduleDone || stockCurrent.isAdmin);
    return `<section class="stock-module"><div class="stock-module-head"><h4>${title}</h4><div class="stock-module-actions">${recognize}${canSaveModule ? `<button class="stock-module-save" type="button" data-stock-save-module="${module}">保存</button>` : ""}${moduleDone ? `<span class="stock-state done">完成于 ${escapeHtml(moduleDone.slice(0,16).replace("T"," "))}</span>` : (canComplete ? `<button type="button" data-stock-complete="${module}">完成确认</button>` : "")}</div></div><div class="stock-form-grid ${stockMode === "view" ? "stock-view-grid" : ""}">${fields.map(renderStockField).join("")}</div></section>`;
  }).join("")}</div>${stockMode === "edit" && stockCurrent.isAdmin ? '<label class="stock-reason"><span>管理员修正原因（修改跨日锁定字段时必填）</span><input name="reason"></label>' : ''}<div class="stock-form-footer"><span></span><div><button type="button" data-stock-close onclick="closeStockOrder()">关闭</button>${stockMode === "edit" && !cancelled && stockUser.permissions?.updateStockOrders ? '<button class="primary" type="submit">保存</button>' : ''}</div></div></form>`;
}

function purchaseItemRow(item = {}, disabled = false) { return `<div class="stock-purchase-row"><input data-purchase-material placeholder="需采购原料" value="${escapeHtml(item.material || "")}" ${disabled ? "disabled" : ""}><input data-purchase-quantity placeholder="采购数量" value="${escapeHtml(item.quantity || "")}" ${disabled ? "disabled" : ""}>${disabled ? "" : '<button type="button" onclick="this.parentElement.remove()">删除</button>'}</div>`; }
function addPurchaseRow() { $("#stock-purchase-item-rows")?.insertAdjacentHTML("beforeend", purchaseItemRow()); }

function recognizeStockText(module) {
  const pasted = prompt("请粘贴文字或从 Excel 复制的表格内容：");
  if (!pasted) return;
  const labelToKey = {};
  STOCK_GROUPS.flatMap(g => g[2]).forEach(([key,label]) => { labelToKey[label.replace(/\s/g, "")] = key; });
  const rows = pasted.split(/\r?\n/).map(line => line.split("\t").map(x => x.trim())).filter(parts => parts.some(Boolean));
  const assignments = {};
  const hasHeaderRow = rows.length >= 2 && rows[0].some(label => labelToKey[label.replace(/\s/g, "")]);
  if (hasHeaderRow) {
    rows[0].forEach((label, index) => {
      const key = labelToKey[label.replace(/\s/g, "")];
      if (key && rows[1][index] != null) assignments[key] = rows[1][index];
    });
  }
  pasted.split(/\r?\n/).forEach((line, rowIndex) => {
    if (hasHeaderRow && rowIndex === 0) return;
    const parts = line.split(/\t|[:：]/);
    if (parts.length < 2) return;
    const key = labelToKey[parts.shift().replace(/\s/g, "")];
    if (key) assignments[key] = parts.join(" ").trim();
  });
  let purchaseRows = [];
  if (module === "purchase") {
    const dataRows = rows.filter(parts => !["原料", "物料"].includes(parts[0]) || parts.length < 2);
    purchaseRows = dataRows.filter(parts => parts.length >= 2).map(parts => ({material:parts[0], quantity:parts[1]}));
  }
  const labels = Object.entries(assignments).map(([key,value]) => `${STOCK_GROUPS.flatMap(g => g[2]).find(field => field[0] === key)?.[1] || key}：${value}`);
  if (purchaseRows.length) labels.push(`采购明细：${purchaseRows.length} 行`);
  if (!labels.length) { alert("未识别到可填写的字段，请检查字段名称或表格格式。"); return; }
  if (!confirm(`识别到以下内容，确认填入表单？\n\n${labels.join("\n")}`)) return;
  Object.entries(assignments).forEach(([key,value]) => {
    const input = key && $("#stock-order-form")?.elements[key];
    if (input && !input.disabled) input.value = value;
  });
  if (purchaseRows.length) $("#stock-purchase-item-rows").innerHTML = purchaseRows.map(item => purchaseItemRow(item)).join("");
}

function collectStockFields(form, onlyModule = null) {
  const fields = {};
  const isHoldOrder = form.elements.order_type?.value === "现货留货";
  STOCK_GROUPS.forEach(([,module,moduleFields]) => moduleFields.forEach(([key,,type]) => {
    if (onlyModule && module !== onlyModule) return;
    if (isHoldOrder && module !== "sales") return;
    const input = form.elements[key];
    if (!input || input.disabled) return;
    fields[key] = type === "checkbox" ? input.checked : input.value;
  }));
  const purchaseContainer = document.querySelector(".stock-purchase-items");
  const purchaseRows = [...document.querySelectorAll(".stock-purchase-row")].filter(row => !row.querySelector("input")?.disabled).map(row => ({material:row.querySelector("[data-purchase-material]").value.trim(), quantity:row.querySelector("[data-purchase-quantity]").value.trim()})).filter(x => x.material || x.quantity);
  if ((!onlyModule || onlyModule === "purchase") && !isHoldOrder && purchaseContainer?.dataset.disabled === "false" && stockMode === "edit" && (purchaseRows.length || stockCurrent.purchase_items)) fields.purchase_items = JSON.stringify(purchaseRows);
  return fields;
}

function stockOrderSummary(order) {
  return [
    ["备货订单号", order.order_no],
    ["内部简称", order.internal_name],
    ["CAS", order.cas],
    ["数量", order.quantity],
    ["业务员", order.salesperson],
    ["提需求日期", order.demand_date],
    ["客户名称", order.customer_name],
    ["订单情况", order.order_situation],
    ["质量要求", order.quality_requirement],
    ["交货期需求", order.delivery_requirement],
    ["销售其他说明", order.sales_note],
  ].map(([label, value]) => `${label}：${value || ""}`).join("\n");
}

async function copyStockOrderSummary(text, button) {
  try {
    if (navigator.clipboard?.writeText && window.isSecureContext) {
      await navigator.clipboard.writeText(text);
    } else {
      const textarea = document.createElement("textarea");
      textarea.value = text;
      textarea.style.position = "fixed";
      textarea.style.opacity = "0";
      document.body.appendChild(textarea);
      textarea.select();
      if (!document.execCommand("copy")) throw new Error("copy failed");
      textarea.remove();
    }
    button.textContent = "已复制";
    setTimeout(() => { button.textContent = "复制内容"; }, 1600);
  } catch (_) {
    alert("复制失败，请手动选择并复制内容");
  }
}

function showStockOrderSaved(order) {
  const summary = stockOrderSummary(order);
  stockCurrent = order;
  $("#stock-modal-number").textContent = order.order_no;
  $("#stock-modal-body").innerHTML = `<div class="stock-save-result"><div class="stock-save-success"><span class="stock-save-check">✓</span><div><strong>订单已保存！</strong><p>订单信息已成功提交，可以复制下方内容发送给相关人员。</p></div></div><div class="stock-save-summary"><div class="stock-save-summary-head"><div><strong>订单信息</strong><span>${escapeHtml(order.order_no)}</span></div><button type="button" id="stock-copy-summary">复制内容</button></div><pre>${escapeHtml(summary)}</pre></div><div class="stock-save-result-actions"><button type="button" onclick="closeStockOrder()">完成并关闭</button></div></div>`;
  $("#stock-copy-summary").addEventListener("click", event => copyStockOrderSummary(summary, event.currentTarget));
  $("#stock-modal-body").scrollIntoView({behavior:"smooth", block:"start"});
}

async function saveStockModule(module) {
  const form = $("#stock-order-form");
  try {
    const creating = !stockCurrent.id;
    const data = await stockApi(creating ? "/api/stock-orders" : `/api/stock-orders/${stockCurrent.id}`, {method:creating ? "POST" : "PUT", body:JSON.stringify({fields:collectStockFields(form, module), reason:form.elements.reason?.value || ""})});
    if (creating) {
      showStockOrderSaved(data.order);
      await loadStockOrders();
      return;
    }
    closeStockOrder();
    await loadStockOrders();
  } catch (err) { alert(err.message); }
}

async function saveStockOrder(event) {
  event.preventDefault();
  const form = event.target;
  try {
    const creating = !stockCurrent.id;
    const data = await stockApi(creating ? "/api/stock-orders" : `/api/stock-orders/${stockCurrent.id}`, {method:creating ? "POST" : "PUT", body:JSON.stringify({fields:collectStockFields(form), reason:form.elements.reason?.value || ""})});
    if (creating) {
      showStockOrderSaved(data.order);
      await loadStockOrders();
      return;
    }
    closeStockOrder();
    await loadStockOrders();
  } catch (err) { alert(err.message); }
}

async function completeStockModule(module) {
  if (!confirm("确认该模块已经填写完成？完成后普通账号将不能再修改。")) return;
  const form = $("#stock-order-form");
  try { await stockApi(`/api/stock-orders/${stockCurrent.id}/complete`, {method:"POST", body:JSON.stringify({module, fields:collectStockFields(form)})}); closeStockOrder(); await loadStockOrders(); }
  catch (err) { alert(err.message); }
}

async function cancelStockOrder(id = null) {
  try {
    if (id && stockCurrent?.id !== id) stockCurrent = (await stockApi(`/api/stock-orders/${id}`)).order;
    if (!confirm("确定要取消该订单吗？取消后各部门无需继续填写。")) return;
    const reason = prompt("请输入取消原因：");
    if (!reason) return;
    await stockApi(`/api/stock-orders/${stockCurrent.id}/cancel`, {method:"POST", body:JSON.stringify({reason})}); closeStockOrder(); await loadStockOrders();
  }
  catch (err) { alert(err.message); }
}

function closeStockOrder() { $("#stock-modal-mask").classList.remove("active"); }
window.closeStockOrder = closeStockOrder;

async function openStockHistory() { $("#stock-history-mask").classList.add("active"); await loadStockHistory(); }
async function openOrderStockHistory(orderNo) {
  $("#stock-history-order").value = orderNo;
  $("#stock-history-operator").value = "";
  $("#stock-history-month").value = "";
  await openStockHistory();
}
window.openOrderStockHistory = openOrderStockHistory;
async function loadStockHistory() {
  const params = stockHistoryParams();
  try { const data = await stockApi("/api/stock-orders-history?" + params); stockHistory = data.logs; $("#stock-history-rows").innerHTML = stockHistory.length ? stockHistory.map(log => `<tr><td>${escapeHtml(log.operatedAt.replace("T"," ").slice(0,19))}</td><td>${escapeHtml(log.orderNo)}</td><td>${escapeHtml(log.module)} / ${escapeHtml(log.label)}</td><td class="stock-log-detail">${escapeHtml(log.newValue)}</td><td>${escapeHtml(log.operator)}</td><td>${escapeHtml(log.reason || "—")}</td></tr>`).join("") : '<tr><td colspan="6" class="empty">暂无记录</td></tr>'; } catch(err) { alert(err.message); }
}
function stockHistoryParams() { return new URLSearchParams({order:$("#stock-history-order").value, operator:$("#stock-history-operator").value, month:$("#stock-history-month").value}); }
async function exportStockCsv(kind) {
  try {
    const resp = await fetch(`/api/stock-orders-export/${kind}?${stockHistoryParams()}`);
    if (resp.status === 401) { sessionStorage.removeItem("boyuan_current_user"); window.location.replace("/login"); return; }
    if (!resp.ok) { const err = await resp.json().catch(() => ({})); throw new Error(err.detail || "导出失败"); }
    const blob = await resp.blob();
    const disposition = resp.headers.get("Content-Disposition") || "";
    const matched = disposition.match(/filename\*=UTF-8''([^;]+)/);
    const link = document.createElement("a");
    link.href = URL.createObjectURL(blob);
    link.download = matched ? decodeURIComponent(matched[1]) : "备货订单.csv";
    link.click();
    URL.revokeObjectURL(link.href);
  } catch (err) { alert(err.message); }
}
