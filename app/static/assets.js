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

