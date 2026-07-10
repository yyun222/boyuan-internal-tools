const $ = (s) => document.querySelector(s);
const form = $("#upload-form");
const submitBtn = $("#submit-btn");
const statusEl = $("#status");
const resultsEl = $("#results");

let lastResult = null;
let currentUser = null;

// --- Auth: show current user, handle logout ---
// If /api/me returns 401, the server-side redirect was bypassed (e.g. cached
// HTML, stale cookie). Force a navigation to /login as a client-side guard.
fetch("/api/me", { cache: "no-store" })
  .then((r) => {
    if (r.status === 401) {
      window.location.replace("/login");
      return null;
    }
    return r.ok ? r.json() : null;
  })
  .then((d) => {
    if (!d || !d.user) return;
    currentUser = d.user;
    $("#current-user").textContent = d.user.email || d.user.username || "";
    applyPermissions(d.user);
    if (d.user.permissions?.manageUsers) {
      loadRoles();
      loadActivityLogs();
    }
    if (d.user.permissions?.viewAssetLedger) {
      initAssetLedger(d.user);
    }
  });

$("#logout-btn").addEventListener("click", async () => {
  await fetch("/api/logout", { method: "POST" });
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

function applyPermissions(user) {
  const permissions = user.permissions || {};
  const reconcileNav = document.querySelector('[data-view="reconcile"]');
  const reconcileView = $("#view-reconcile");
  const assetLedgerNav = $("#asset-ledger-nav");
  const adminNav = $("#admin-nav");
  const activityLogsNav = $("#activity-logs-nav");

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
  });
});

async function loadRoles() {
  const target = $("#role-options");
  if (!target) return;
  const resp = await fetch("/api/roles", { cache: "no-store" });
  if (!resp.ok) return;
  const data = await resp.json();
  target.innerHTML = data.roles.map((role) => `
    <label class="role-option">
      <input type="checkbox" value="${escapeHtml(role.name)}" />
      <span>${escapeHtml(role.displayName)}${role.department ? ` · ${escapeHtml(role.department)}` : ""}</span>
    </label>
  `).join("");
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
    await loadActivityLogs();
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
  "济阳厂区", "采购部", "建筑路墙", "202", "公共区", "动力车间", "201",
  "203", "204", "302", "303", "301", "206", "305", "306"
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
  return new Date().toISOString().slice(0, 10);
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
