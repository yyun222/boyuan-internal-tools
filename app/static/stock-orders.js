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
  ["基础与销售", "sales", [["internal_name","内部简称"],["cas","CAS"],["quantity","数量"],["order_type","订单类型","select"],["salesperson","业务员"],["demand_date","提需求日期","date"],["customer_name","客户名称"],["order_situation","订单情况","textarea"],["quality_requirement","质量要求","textarea"],["delivery_requirement","交货期需求","date"],["sales_note","其他说明","textarea"],["actual_delivery","实际交货","date"],["delivery_items","交货数量及备注","delivery-items"]]],
  ["采购部", "purchase", [["purchase_date","采购日期","date"],["purchase_not_required","无需采购","checkbox"],["purchase_items","采购原料预计到货时间及数量","items"],["purchase_note","采购说明","textarea"],["purchase_owner","采购负责人"],["purchase_arrival_items","实际到货明细","arrival-items"]]],
  ["生产部", "production", [["production_form_date","填表日期","date"],["production_not_required","无需生产","checkbox"],["production_expected_items","预计完成","production-expected-items"],["production_status","评估当前状态","textarea"],["production_note","生产说明","textarea"],["production_actual_items","实际完成","production-actual-items"]]],
  ["质量部", "qc", [["qc_not_required","无需检测","checkbox"],["qc_expected_items","预计完成","qc-expected-items"],["qc_note","QC备注","textarea"],["qc_owner","QC负责人"],["qc_actual_items","实际完成","qc-actual-items"]]],
];
const STOCK_QUANTITY_UNITS = ["mg", "g", "kg", "ml", "L"];

function splitStockQuantity(value) {
  const matched = String(value || "").trim().match(/^([0-9]+(?:\.[0-9]+)?)\s*(mg|g|kg|ml|L)?$/);
  return matched ? {number:matched[1], unit:matched[2] || "g"} : {number:"", unit:"g"};
}

function quantityControl(value, dataName, disabled = false) {
  const parsed = splitStockQuantity(value);
  return `<span class="stock-quantity-control"><input type="number" min="0" step="any" inputmode="decimal" placeholder="输入数量" aria-label="输入数量" data-${dataName}-number value="${escapeHtml(parsed.number)}" ${disabled ? "disabled" : ""}><select aria-label="数量单位" data-${dataName}-unit ${disabled ? "disabled" : ""}>${STOCK_QUANTITY_UNITS.map(unit => `<option value="${unit}" ${parsed.unit === unit ? "selected" : ""}>${unit}</option>`).join("")}</select></span>`;
}

function collectQuantity(row, dataName) {
  const number = row.querySelector(`[data-${dataName}-number]`)?.value.trim() || "";
  const unit = row.querySelector(`[data-${dataName}-unit]`)?.value || "";
  return number ? `${number} ${unit}` : "";
}

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
  body.innerHTML = '<tr><td colspan="15" class="empty">正在加载…</td></tr>';
  try {
    const data = await stockApi("/api/stock-orders?" + params);
    body.innerHTML = data.orders.length ? data.orders.map(stockRow).join("") : '<tr><td colspan="15" class="empty">暂无订单</td></tr>';
    stockPage = data.pagination.page;
    renderStockSortHeaders();
    renderStockPagination(data.pagination);
  } catch (err) { body.innerHTML = `<tr><td colspan="15" class="empty">${escapeHtml(err.message)}</td></tr>`; }
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
  const status = order.module_statuses?.[module] || "未填写";
  const department = {sales:"销售部",purchase:"采购部",production:"生产部",qc:"质量部"}[module];
  const warning = order.warnings?.find(item => item.department === department);
  if (warning || order.overdue?.[module]) return `<span class="stock-state late">${escapeHtml(status)}</span>`;
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
  const actions = `<button class="stock-open-btn" onclick="openStockOrder(${order.id},'view')">查看</button>${canEdit ? `<button class="stock-open-btn" onclick="openStockOrder(${order.id},'edit')">修改</button>` : ""}<button class="stock-open-btn" onclick="openOrderStockHistory('${escapeHtml(order.order_no)}')">历史</button>${cancel}`;
  return `<tr class="${order.archive_status === "已取消" ? "stock-cancelled-row" : ""}"><td><strong>${escapeHtml(order.order_no)}</strong>${order.archive_status === "已取消" ? '<br><span class="stock-state cancelled">已取消</span>' : ""}</td><td>${actions}</td><td>${escapeHtml(order.salesperson || "—")}</td><td>${escapeHtml(order.customer_name || "—")}</td><td>${escapeHtml(order.internal_name || "—")}<br><span class="muted">${escapeHtml(order.cas || "")}</span></td><td>${escapeHtml(order.quantity || "—")}</td><td>${stockState(order,"sales")}</td><td>${stockState(order,"purchase")}</td><td>${stockState(order,"production")}</td><td>${stockState(order,"qc")}</td><td>${escapeHtml(order.delivery_requirement || "—")}</td><td class="${deliveryLate ? "stock-delivery-late" : ""}">${escapeHtml(order.actual_delivery || "—")}${deliveryLate ? "<br>晚于交货期需求" : ""}</td><td>${escapeHtml((order.created_at || "").replace("T"," ").slice(0,16))}</td><td>${escapeHtml((order.updated_at || "").replace("T"," ").slice(0,16))}</td><td>${escapeHtml(order.order_type)}</td></tr>`;
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
    $("#stock-order-form").addEventListener("input", updateItemMissingHighlights);
    document.querySelectorAll("[data-stock-complete]").forEach(btn => btn.addEventListener("click", () => completeStockModule(btn.dataset.stockComplete)));
    document.querySelectorAll("[data-stock-save-module]").forEach(btn => btn.addEventListener("click", () => saveStockModule(btn.dataset.stockSaveModule)));
    document.querySelectorAll("[data-stock-recognize]").forEach(btn => btn.addEventListener("click", () => recognizeStockText(btn.dataset.stockRecognize)));
    $("#stock-add-purchase-row")?.addEventListener("click", addPurchaseRow);
    $("#stock-add-delivery-row")?.addEventListener("click", addDeliveryRow);
    $("#stock-add-arrival-row")?.addEventListener("click", addArrivalRow);
    $("#stock-add-production-expected-row")?.addEventListener("click", addProductionExpectedRow);
    $("#stock-add-production-actual-row")?.addEventListener("click", addProductionActualRow);
    $("#stock-add-qc-expected-row")?.addEventListener("click", addQcExpectedRow);
    $("#stock-add-qc-actual-row")?.addEventListener("click", addQcActualRow);
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
    if (type === "items") { try { shown = JSON.parse(value || "[]").map(x => `${x.arrival_date || ""}：${x.material || ""} × ${x.quantity || ""}`).join("\n") || "—"; } catch (_) {} }
    if (type === "delivery-items") { try { shown = JSON.parse(value || "[]").map(x => `${x.quantity || ""}（${x.note || ""}）`).join("\n") || "—"; } catch (_) {} }
    if (type === "arrival-items") { try { shown = JSON.parse(value || "[]").map(x => `${x.date || ""}：${x.material || ""} × ${x.quantity || ""}（${x.note || ""}）`).join("\n") || "—"; } catch (_) {} }
    if (type === "production-expected-items") { try { shown = JSON.parse(value || "[]").map(x => `${x.date || ""}：${x.quantity || ""}（${x.note || ""}）`).join("\n") || "—"; } catch (_) {} }
    if (type === "production-actual-items") { try { shown = JSON.parse(value || "[]").map(x => `${x.date || ""}：${x.quantity || ""}（${x.note || ""}）`).join("\n") || "—"; } catch (_) {} }
    if (type === "qc-expected-items" || type === "qc-actual-items") { try { shown = JSON.parse(value || "[]").map(x => `${x.date || ""}：${x.quantity || ""}（${x.note || ""}）`).join("\n") || "—"; } catch (_) {} }
    return `<div class="stock-view-field"><strong>${label}</strong><span>${escapeHtml(shown)}</span></div>`;
  }
  if (type === "items") {
    let items = []; try { items = JSON.parse(value || "[]"); } catch (_) {}
    if (!items.length) items = [{arrival_date:"",material:"",quantity:""}];
    return `<div class="wide stock-purchase-items" data-disabled="${disabled ? "true" : "false"}"><span>${label}${locked ? ' <em>已锁定</em>' : ''}</span><div id="stock-purchase-item-rows">${items.map(item => purchaseItemRow(item, disabled)).join("")}</div>${disabled ? "" : '<button id="stock-add-purchase-row" type="button">添加一行</button>'}</div>`;
  }
  if (type === "delivery-items") {
    let items = []; try { items = JSON.parse(value || "[]"); } catch (_) {}
    if (!items.length) items = [{quantity:"",note:""}];
    return `<div class="wide stock-delivery-items" data-disabled="${disabled ? "true" : "false"}"><span>${label}${locked ? ' <em>已锁定</em>' : ''}</span><div id="stock-delivery-item-rows">${items.map(item => deliveryItemRow(item, disabled)).join("")}</div>${disabled ? "" : '<button id="stock-add-delivery-row" type="button">添加一行</button>'}</div>`;
  }
  if (type === "arrival-items") {
    let items = []; try { items = JSON.parse(value || "[]"); } catch (_) {}
    if (!items.length) items = [{date:"",material:"",quantity:"",note:""}];
    return `<div class="wide stock-arrival-items" data-disabled="${disabled ? "true" : "false"}"><span>${label}${locked ? ' <em>已锁定</em>' : ''}</span><div id="stock-arrival-item-rows">${items.map(item => arrivalItemRow(item, disabled)).join("")}</div>${disabled ? "" : '<button id="stock-add-arrival-row" type="button">添加一行</button>'}</div>`;
  }
  if (type === "production-expected-items" || type === "production-actual-items") {
    let items = []; try { items = JSON.parse(value || "[]"); } catch (_) {}
    if (!items.length) items = [{date:"",quantity:"",note:""}];
    const actual = type === "production-actual-items";
    const kind = actual ? "actual" : "expected";
    const title = actual ? "实际完成日期" : "预计完成日期";
    return `<div class="wide stock-production-${kind}-items" data-disabled="${disabled ? "true" : "false"}"><span>${label}${locked ? ' <em>已锁定</em>' : ''}</span><div id="stock-production-${kind}-item-rows">${items.map(item => productionItemRow(item, disabled, kind, title)).join("")}</div>${disabled ? "" : `<button id="stock-add-production-${kind}-row" type="button">添加一行</button>`}</div>`;
  }
  if (type === "qc-expected-items" || type === "qc-actual-items") {
    let items = []; try { items = JSON.parse(value || "[]"); } catch (_) {}
    if (!items.length) items = [{date:"",quantity:"",note:""}];
    const actual = type === "qc-actual-items";
    const kind = actual ? "actual" : "expected";
    const title = actual ? "实际完成日期" : "预计完成日期";
    return `<div class="wide stock-qc-${kind}-items" data-disabled="${disabled ? "true" : "false"}"><span>${label}${locked ? ' <em>已锁定</em>' : ''}</span><div id="stock-qc-${kind}-item-rows">${items.map(item => qcItemRow(item, disabled, kind, title)).join("")}</div>${disabled ? "" : `<button id="stock-add-qc-${kind}-row" type="button">添加一行</button>`}</div>`;
  }
  if (type === "checkbox") return `<label class="stock-check"><input name="${key}" type="checkbox" ${value ? "checked" : ""} ${disabled ? "disabled" : ""}>${label}${locked ? ' <em>已锁定</em>' : ''}</label>`;
  if (type === "select") return `<label class="stock-field-${key}"><span>${label}${locked ? ' <em>已锁定</em>' : ''}</span><select name="${key}" ${disabled ? "disabled" : ""}><option ${value === "备货订单" ? "selected" : ""}>备货订单</option><option ${value === "现货留货" ? "selected" : ""}>现货留货</option></select></label>`;
  if (type === "textarea") return `<label class="wide stock-field-${key}"><span>${label}${locked ? ' <em>已锁定</em>' : ''}</span><textarea name="${key}" ${disabled ? "disabled" : ""}>${escapeHtml(value)}</textarea></label>`;
  if (key === "quantity") return `<label class="stock-field-${key}"><span>${label}${locked ? ' <em>已锁定</em>' : ''}</span>${quantityControl(value, "order-quantity", disabled)}</label>`;
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

function purchaseItemRow(item = {}, disabled = false) { return `<div class="stock-purchase-row"><input data-purchase-arrival-date type="date" title="预计到货时间" value="${escapeHtml(item.arrival_date || "")}" ${disabled ? "disabled" : ""}><input data-purchase-material placeholder="需采购原料" value="${escapeHtml(item.material || "")}" ${disabled ? "disabled" : ""}>${quantityControl(item.quantity, "purchase-quantity", disabled)}${disabled ? "" : '<button type="button" onclick="this.parentElement.remove()">删除</button>'}</div>`; }
function addPurchaseRow() { $("#stock-purchase-item-rows")?.insertAdjacentHTML("beforeend", purchaseItemRow()); }
function deliveryItemRow(item = {}, disabled = false) { return `<div class="stock-delivery-row">${quantityControl(item.quantity, "delivery-quantity", disabled)}<input data-delivery-note placeholder="备注" value="${escapeHtml(item.note || "")}" ${disabled ? "disabled" : ""}>${disabled ? "" : '<button type="button" onclick="this.parentElement.remove()">删除</button>'}</div>`; }
function addDeliveryRow() { $("#stock-delivery-item-rows")?.insertAdjacentHTML("beforeend", deliveryItemRow()); }
function arrivalItemRow(item = {}, disabled = false) { return `<div class="stock-arrival-row"><input data-arrival-date type="date" title="实际到货日期" value="${escapeHtml(item.date || "")}" ${disabled ? "disabled" : ""}><input data-arrival-material placeholder="需采购原料" value="${escapeHtml(item.material || "")}" ${disabled ? "disabled" : ""}>${quantityControl(item.quantity, "arrival-quantity", disabled)}<input data-arrival-note placeholder="备注" value="${escapeHtml(item.note || "")}" ${disabled ? "disabled" : ""}>${disabled ? "" : '<button type="button" onclick="this.parentElement.remove()">删除</button>'}</div>`; }
function addArrivalRow() { $("#stock-arrival-item-rows")?.insertAdjacentHTML("beforeend", arrivalItemRow()); }
function productionItemRow(item = {}, disabled = false, kind = "expected", dateTitle = "预计完成日期") { return `<div class="stock-production-row"><input data-production-${kind}-date type="date" title="${dateTitle}" value="${escapeHtml(item.date || "")}" ${disabled ? "disabled" : ""}>${quantityControl(item.quantity, `production-${kind}-quantity`, disabled)}<input data-production-${kind}-note placeholder="${kind === "actual" ? "备注（生产批号）" : "备注"}" value="${escapeHtml(item.note || "")}" ${disabled ? "disabled" : ""}>${disabled ? "" : '<button type="button" onclick="this.parentElement.remove()">删除</button>'}</div>`; }
function addProductionExpectedRow() { $("#stock-production-expected-item-rows")?.insertAdjacentHTML("beforeend", productionItemRow({}, false, "expected", "预计完成日期")); }
function addProductionActualRow() { $("#stock-production-actual-item-rows")?.insertAdjacentHTML("beforeend", productionItemRow({}, false, "actual", "实际完成日期")); }
function qcItemRow(item = {}, disabled = false, kind = "expected", dateTitle = "预计完成日期") { return `<div class="stock-qc-row"><input data-qc-${kind}-date type="date" title="${dateTitle}" value="${escapeHtml(item.date || "")}" ${disabled ? "disabled" : ""}>${quantityControl(item.quantity, `qc-${kind}-quantity`, disabled)}<input data-qc-${kind}-note placeholder="备注" value="${escapeHtml(item.note || "")}" ${disabled ? "disabled" : ""}>${disabled ? "" : '<button type="button" onclick="this.parentElement.remove()">删除</button>'}</div>`; }
function addQcExpectedRow() { $("#stock-qc-expected-item-rows")?.insertAdjacentHTML("beforeend", qcItemRow({}, false, "expected", "预计完成日期")); }
function addQcActualRow() { $("#stock-qc-actual-item-rows")?.insertAdjacentHTML("beforeend", qcItemRow({}, false, "actual", "实际完成日期")); }

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
    purchaseRows = dataRows.filter(parts => parts.length >= 3).map(parts => ({arrival_date:parts[0], material:parts[1], quantity:parts[2]}));
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
  const orderQuantityControl = document.querySelector(".stock-field-quantity .stock-quantity-control");
  if ((!onlyModule || onlyModule === "sales") && orderQuantityControl && !orderQuantityControl.querySelector("input")?.disabled) fields.quantity = collectQuantity(orderQuantityControl, "order-quantity");
  const purchaseContainer = document.querySelector(".stock-purchase-items");
  const purchaseRows = [...document.querySelectorAll(".stock-purchase-row")].filter(row => !row.querySelector("input")?.disabled).map(row => ({arrival_date:row.querySelector("[data-purchase-arrival-date]").value.trim(), material:row.querySelector("[data-purchase-material]").value.trim(), quantity:collectQuantity(row, "purchase-quantity")})).filter(x => x.arrival_date || x.material || x.quantity);
  if ((!onlyModule || onlyModule === "purchase") && !isHoldOrder && purchaseContainer?.dataset.disabled === "false" && stockMode === "edit" && (purchaseRows.length || stockCurrent.purchase_items)) {
    fields.purchase_items = JSON.stringify(purchaseRows);
    fields.arrival_date = purchaseRows.map(item => item.arrival_date).filter(Boolean).sort().slice(-1)[0] || "";
  }
  const deliveryContainer = document.querySelector(".stock-delivery-items");
  const deliveryRows = [...document.querySelectorAll(".stock-delivery-row")].filter(row => !row.querySelector("input")?.disabled).map(row => ({quantity:collectQuantity(row, "delivery-quantity"), note:row.querySelector("[data-delivery-note]").value.trim()})).filter(x => x.quantity || x.note);
  if ((!onlyModule || onlyModule === "sales") && deliveryContainer?.dataset.disabled === "false" && stockMode === "edit" && (deliveryRows.length || stockCurrent.delivery_items)) fields.delivery_items = JSON.stringify(deliveryRows);
  const arrivalContainer = document.querySelector(".stock-arrival-items");
  const arrivalRows = [...document.querySelectorAll(".stock-arrival-row")].filter(row => !row.querySelector("input")?.disabled).map(row => ({date:row.querySelector("[data-arrival-date]").value.trim(), material:row.querySelector("[data-arrival-material]").value.trim(), quantity:collectQuantity(row, "arrival-quantity"), note:row.querySelector("[data-arrival-note]").value.trim()})).filter(x => x.date || x.material || x.quantity || x.note);
  if ((!onlyModule || onlyModule === "purchase") && !isHoldOrder && arrivalContainer?.dataset.disabled === "false" && stockMode === "edit" && (arrivalRows.length || stockCurrent.purchase_arrival_items)) fields.purchase_arrival_items = JSON.stringify(arrivalRows);
  for (const kind of ["expected", "actual"]) {
    const container = document.querySelector(`.stock-production-${kind}-items`);
    const rows = [...document.querySelectorAll(`.stock-production-${kind}-items .stock-production-row`)].filter(row => !row.querySelector("input")?.disabled).map(row => ({date:row.querySelector(`[data-production-${kind}-date]`).value.trim(), quantity:collectQuantity(row, `production-${kind}-quantity`), note:row.querySelector(`[data-production-${kind}-note]`).value.trim()})).filter(x => x.date || x.quantity || x.note);
    const fieldKey = kind === "expected" ? "production_expected_items" : "production_actual_items";
    if ((!onlyModule || onlyModule === "production") && !isHoldOrder && container?.dataset.disabled === "false" && stockMode === "edit" && (rows.length || stockCurrent[fieldKey])) {
      fields[fieldKey] = JSON.stringify(rows);
      if (kind === "expected") fields.expected_delivery_date = rows.map(item => item.date).filter(Boolean).sort().slice(-1)[0] || "";
    }
  }
  for (const kind of ["expected", "actual"]) {
    const container = document.querySelector(`.stock-qc-${kind}-items`);
    const rows = [...document.querySelectorAll(`.stock-qc-${kind}-items .stock-qc-row`)].filter(row => !row.querySelector("input")?.disabled).map(row => ({date:row.querySelector(`[data-qc-${kind}-date]`).value.trim(), quantity:collectQuantity(row, `qc-${kind}-quantity`), note:row.querySelector(`[data-qc-${kind}-note]`).value.trim()})).filter(x => x.date || x.quantity || x.note);
    const fieldKey = kind === "expected" ? "qc_expected_items" : "qc_actual_items";
    if ((!onlyModule || onlyModule === "qc") && !isHoldOrder && container?.dataset.disabled === "false" && stockMode === "edit" && (rows.length || stockCurrent[fieldKey])) {
      fields[fieldKey] = JSON.stringify(rows);
      if (kind === "expected") fields.coa_time = rows.map(item => item.date).filter(Boolean).sort().slice(-1)[0] || "";
    }
  }
  return fields;
}

function markIncompleteItemRows(rowSelector, inputSelectors, forceRequired = false) {
  let incomplete = false;
  document.querySelectorAll(rowSelector).forEach(row => {
    const inputs = inputSelectors.map(selector => row.querySelector(selector)).filter(Boolean);
    const hasValue = forceRequired || inputs.some(input => input.value.trim());
    inputs.forEach(input => {
      const missing = hasValue && !input.value.trim();
      input.classList.toggle("stock-item-missing", missing);
      if (missing) incomplete = true;
    });
  });
  return incomplete;
}

function updateItemMissingHighlights(event) {
  const configs = [
    [".stock-delivery-row", ["[data-delivery-quantity-number]", "[data-delivery-note]"], () => Boolean($("#stock-order-form")?.elements.actual_delivery?.value.trim())],
    [".stock-purchase-row", ["[data-purchase-arrival-date]", "[data-purchase-material]", "[data-purchase-quantity-number]"]],
    [".stock-arrival-row", ["[data-arrival-date]", "[data-arrival-material]", "[data-arrival-quantity-number]", "[data-arrival-note]"]],
    [".stock-production-expected-items .stock-production-row", ["[data-production-expected-date]", "[data-production-expected-quantity-number]", "[data-production-expected-note]"]],
    [".stock-production-actual-items .stock-production-row", ["[data-production-actual-date]", "[data-production-actual-quantity-number]", "[data-production-actual-note]"]],
    [".stock-qc-expected-items .stock-qc-row", ["[data-qc-expected-date]", "[data-qc-expected-quantity-number]", "[data-qc-expected-note]"]],
    [".stock-qc-actual-items .stock-qc-row", ["[data-qc-actual-date]", "[data-qc-actual-quantity-number]", "[data-qc-actual-note]"]],
  ];
  configs.forEach(([rowSelector, inputSelectors, forceRequired]) => {
    const changedInRows = event.target.closest?.(rowSelector);
    const deliveryDateChanged = rowSelector === ".stock-delivery-row" && event.target.name === "actual_delivery";
    if (changedInRows || deliveryDateChanged) markIncompleteItemRows(rowSelector, inputSelectors, forceRequired?.() || false);
  });
}

function validateStockArrivalFields(fields) {
  if (!Object.prototype.hasOwnProperty.call(fields, "purchase_arrival_items")) return true;
  let items = [];
  try { items = JSON.parse(fields.purchase_arrival_items || "[]"); } catch (_) {}
  const incompleteRows = markIncompleteItemRows(".stock-arrival-row", ["[data-arrival-date]", "[data-arrival-material]", "[data-arrival-quantity-number]", "[data-arrival-note]"]);
  if (incompleteRows || items.some(item => !String(item.date || "").trim() || !String(item.material || "").trim() || !String(item.quantity || "").trim() || !String(item.note || "").trim())) {
    alert("每条实际到货明细都必须填写实际到货日期、需采购原料、到货数量和备注");
    return false;
  }
  return true;
}

function validateStockPurchaseItems(fields) {
  if (!Object.prototype.hasOwnProperty.call(fields, "purchase_items")) return true;
  let items = [];
  try { items = JSON.parse(fields.purchase_items || "[]"); } catch (_) {}
  const incompleteRows = markIncompleteItemRows(".stock-purchase-row", ["[data-purchase-arrival-date]", "[data-purchase-material]", "[data-purchase-quantity-number]"]);
  if (incompleteRows || items.some(item => !String(item.arrival_date || "").trim() || !String(item.material || "").trim() || !String(item.quantity || "").trim())) {
    alert("每条采购明细都必须填写预计到货时间、需采购原料和采购数量");
    return false;
  }
  return true;
}

function validateStockProductionItems(fields) {
  for (const [fieldKey, label] of [["production_expected_items", "预计完成"], ["production_actual_items", "实际完成"]]) {
    if (!Object.prototype.hasOwnProperty.call(fields, fieldKey)) continue;
    let items = [];
    try { items = JSON.parse(fields[fieldKey] || "[]"); } catch (_) {}
    const kind = fieldKey === "production_expected_items" ? "expected" : "actual";
    const incompleteRows = markIncompleteItemRows(`.stock-production-${kind}-items .stock-production-row`, [`[data-production-${kind}-date]`, `[data-production-${kind}-quantity-number]`, `[data-production-${kind}-note]`]);
    if (incompleteRows || items.some(item => !String(item.date || "").trim() || !String(item.quantity || "").trim() || !String(item.note || "").trim())) {
      alert(`每条${label}明细都必须填写日期、生产数量和备注`);
      return false;
    }
  }
  return true;
}

function validateStockQcItems(fields) {
  for (const [fieldKey, label] of [["qc_expected_items", "预计完成"], ["qc_actual_items", "实际完成"]]) {
    if (!Object.prototype.hasOwnProperty.call(fields, fieldKey)) continue;
    let items = [];
    try { items = JSON.parse(fields[fieldKey] || "[]"); } catch (_) {}
    const kind = fieldKey === "qc_expected_items" ? "expected" : "actual";
    const incompleteRows = markIncompleteItemRows(`.stock-qc-${kind}-items .stock-qc-row`, [`[data-qc-${kind}-date]`, `[data-qc-${kind}-quantity-number]`, `[data-qc-${kind}-note]`]);
    if (incompleteRows || items.some(item => !String(item.date || "").trim() || !String(item.quantity || "").trim() || !String(item.note || "").trim())) {
      alert(`每条${label}明细都必须填写日期、数量和备注`);
      return false;
    }
  }
  return true;
}

function normalizedStockQuantity(value) {
  const parsed = splitStockQuantity(value);
  if (!parsed.number) return null;
  const factors = {mg:["mass",1], g:["mass",1000], kg:["mass",1000000], ml:["volume",1], L:["volume",1000]};
  const [dimension, factor] = factors[parsed.unit];
  return {dimension, value:Number(parsed.number) * factor};
}

function stockQuantitiesMatch(left, right) {
  const a = normalizedStockQuantity(left);
  const b = normalizedStockQuantity(right);
  return Boolean(a && b && a.dimension === b.dimension && Math.abs(a.value - b.value) < 1e-9);
}

function parseStockItems(value) { try { return JSON.parse(value || "[]"); } catch (_) { return []; } }

function validateStockCompletionQuantities(module, fields) {
  if (module === "sales") {
    const ordered = normalizedStockQuantity(fields.quantity ?? stockCurrent.quantity);
    const delivered = parseStockItems(fields.delivery_items ?? stockCurrent.delivery_items).map(item => normalizedStockQuantity(item.quantity));
    if (!ordered || !delivered.length || delivered.some(item => !item || item.dimension !== ordered.dimension) || Math.abs(delivered.reduce((sum, item) => sum + item.value, 0) - ordered.value) >= 1e-9) {
      alert("实际交货总数量必须与订单数量相同");
      return false;
    }
    return true;
  }
  const pairs = {
    purchase:["purchase_items", "purchase_arrival_items", "实际采购到货数量必须与预计采购逐项相同"],
    production:["production_expected_items", "production_actual_items", "实际完成数量必须与预计完成逐项相同"],
    qc:["qc_expected_items", "qc_actual_items", "质量部实际完成数量必须与预计完成逐项相同"],
  };
  const skipKeys = {purchase:"purchase_not_required", production:"production_not_required", qc:"qc_not_required"};
  if (fields[skipKeys[module]] ?? stockCurrent[skipKeys[module]]) return true;
  const [expectedKey, actualKey, message] = pairs[module];
  const expected = parseStockItems(fields[expectedKey] ?? stockCurrent[expectedKey]);
  const actual = parseStockItems(fields[actualKey] ?? stockCurrent[actualKey]);
  if (!expected.length || expected.length !== actual.length || expected.some((item, index) => !stockQuantitiesMatch(item.quantity, actual[index]?.quantity))) {
    alert(message);
    return false;
  }
  return true;
}

function stockOrderSummary(order) {
  return ["新增一个备货需求：", ...[
    ["备货订单号", order.order_no],
    ["内部简称", order.internal_name],
    ["数量", order.quantity],
    ["交货期需求", order.delivery_requirement],
  ].map(([label, value]) => `${label}：${value || ""}`), "请登录小程序查看！"].join("\n");
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
    setTimeout(() => { button.textContent = "复制信息"; }, 1600);
  } catch (_) {
    alert("复制失败，请手动选择并复制内容");
  }
}

function showStockOrderSaved(order, creating = false) {
  const summary = stockOrderSummary(order);
  stockCurrent = order;
  $("#stock-modal-number").textContent = order.order_no;
  const savedTitle = creating ? "订单已保存！" : "订单修改已保存！";
  $("#stock-modal-body").innerHTML = `<div class="stock-save-result"><div class="stock-save-success"><span class="stock-save-check">✓</span><div><strong>${savedTitle}</strong><p>订单信息已成功提交，可以复制下方内容发送给相关人员。</p></div></div><div class="stock-save-summary"><div class="stock-save-summary-head"><div><strong>订单信息</strong><span>${escapeHtml(order.order_no)}</span></div><button type="button" id="stock-copy-summary">复制信息</button></div><pre>${escapeHtml(summary)}</pre></div><div class="stock-save-result-actions"><button type="button" onclick="closeStockOrder()">完成并关闭</button></div></div>`;
  $("#stock-copy-summary").addEventListener("click", event => copyStockOrderSummary(summary, event.currentTarget));
  $("#stock-modal-body").scrollIntoView({behavior:"smooth", block:"start"});
}

function validateStockDeliveryFields(fields) {
  const keys = ["actual_delivery", "delivery_items"];
  if (!keys.some(key => Object.prototype.hasOwnProperty.call(fields, key))) return true;
  const actualDelivery = String(fields.actual_delivery ?? stockCurrent.actual_delivery ?? "").trim();
  let items = [];
  try { items = JSON.parse(fields.delivery_items ?? stockCurrent.delivery_items ?? "[]"); } catch (_) {}
  const incompleteRows = markIncompleteItemRows(".stock-delivery-row", ["[data-delivery-quantity-number]", "[data-delivery-note]"], Boolean(actualDelivery));
  if ((actualDelivery && !items.length) || (!actualDelivery && items.length)) {
    alert("实际交货和交货明细必须同时填写，或者同时不填写");
    return false;
  }
  if (incompleteRows || items.some(item => !String(item.quantity || "").trim() || !String(item.note || "").trim())) {
    alert("每条交货明细都必须填写交货数量和备注");
    return false;
  }
  return true;
}

async function saveStockModule(module) {
  const form = $("#stock-order-form");
  try {
    const creating = !stockCurrent.id;
    const fields = collectStockFields(form, module);
    if (!validateStockDeliveryFields(fields)) return;
    if (!validateStockArrivalFields(fields)) return;
    if (!validateStockPurchaseItems(fields)) return;
    if (!validateStockProductionItems(fields)) return;
    if (!validateStockQcItems(fields)) return;
    const data = await stockApi(creating ? "/api/stock-orders" : `/api/stock-orders/${stockCurrent.id}`, {method:creating ? "POST" : "PUT", body:JSON.stringify({fields, reason:form.elements.reason?.value || ""})});
    if (creating) {
      showStockOrderSaved(data.order, true);
      await loadStockOrders();
      return;
    }
    if (module === "sales") showStockOrderSaved(data.order);
    else closeStockOrder();
    await loadStockOrders();
  } catch (err) { alert(err.message); }
}

async function saveStockOrder(event) {
  event.preventDefault();
  const form = event.target;
  try {
    const creating = !stockCurrent.id;
    const fields = collectStockFields(form);
    if (!validateStockDeliveryFields(fields)) return;
    if (!validateStockArrivalFields(fields)) return;
    if (!validateStockPurchaseItems(fields)) return;
    if (!validateStockProductionItems(fields)) return;
    if (!validateStockQcItems(fields)) return;
    const data = await stockApi(creating ? "/api/stock-orders" : `/api/stock-orders/${stockCurrent.id}`, {method:creating ? "POST" : "PUT", body:JSON.stringify({fields, reason:form.elements.reason?.value || ""})});
    if (creating) {
      showStockOrderSaved(data.order, true);
      await loadStockOrders();
      return;
    }
    showStockOrderSaved(data.order);
    await loadStockOrders();
  } catch (err) { alert(err.message); }
}

async function completeStockModule(module) {
  const form = $("#stock-order-form");
  const fields = collectStockFields(form, module);
  if (!validateStockDeliveryFields(fields) || !validateStockArrivalFields(fields) || !validateStockPurchaseItems(fields) || !validateStockProductionItems(fields) || !validateStockQcItems(fields)) return;
  if (!validateStockCompletionQuantities(module, fields)) return;
  if (!confirm("确认该模块已经填写完成？完成后普通账号将不能再修改。")) return;
  try { await stockApi(`/api/stock-orders/${stockCurrent.id}/complete`, {method:"POST", body:JSON.stringify({module, fields})}); closeStockOrder(); await loadStockOrders(); }
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
