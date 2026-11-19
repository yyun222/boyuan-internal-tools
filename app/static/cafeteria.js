(() => {
  const site = document.querySelector("#cafeteria-site");
  const pageNav = document.querySelector("#cafeteria-pages");
  const sectionSelect = document.querySelector("#cafeteria-section-select");
  const content = document.querySelector("#cafeteria-content");
  const status = document.querySelector("#cafeteria-status");
  const dialog = document.querySelector("#cafeteria-dialog");
  const body = document.querySelector("#cafeteria-dialog-body");
  const dialogStatus = document.querySelector("#cafeteria-dialog-status");
  const kinds = { purchase: "采购申请", batch: "采购批次", opening: "期初库存", issue: "领用", transfer: "调拨", count: "盘点", loss: "报损", return: "退货", correction: "冲销" };
  const states = { approval: "待审批", purchasing: "待采购登记", receipt: "待验收", completed: "已完成", issue_pending: "待领用确认", transit: "调拨在途", batch_pending: "待分批验收", rejected: "已退回", cancelled: "已撤销", reversed: "已冲销" };
  const actions = { create: "创建", approve: "审批通过", reject: "退回", purchase: "登记采购", receive: "确认验收", confirm_issue: "确认领用", receive_transfer: "确认调入", close: "结束剩余采购", cancel: "撤销", reversed: "冲销完成" };
  const sites = { jiyang: "济阳", yucheng: "禹城" };
  const units = ["斤", "个", "瓶", "袋", "桶", "箱", "包", "升"];
  let currentSection = "documents";
  let access = [], revision = 0, currentPage = 1, documentStatus = "";
  const esc = value => escapeHtml(String(value ?? ""));
  const options = entries => entries.map(([value, label]) => `<option value="${esc(value)}">${esc(label)}</option>`).join("");
  function table(headers, rows) {
    if (!rows.length) return '<p class="empty">暂无记录</p>';
    return `<div class="table-wrap cafeteria-table"><table role="table">
      <thead role="rowgroup"><tr role="row">${headers.map(label => `<th scope="col" role="columnheader">${esc(label)}</th>`).join("")}</tr></thead>
      <tbody role="rowgroup">${rows.map(values => `<tr role="row">${values.map((value, index) =>
        `<td role="cell"><span class="cafeteria-cell-label" aria-hidden="true">${esc(headers[index])}</span><div>${value}</div></td>`).join("")}</tr>`).join("")}</tbody>
    </table></div>`;
  }
  const button = (label, attributes) => `<button type="button" ${attributes}>${esc(label)}</button>`;
  const selected = () => access.find(entry => entry.id === site.value);
  const has = (...jobs) => jobs.some(job => selected()?.jobs.includes(job));

  async function api(path, { data, method = "POST", key, scope = site.value } = {}) {
    const multipart = data instanceof FormData;
    const headers = data === undefined || multipart ? {} : { "Content-Type": "application/json" };
    if (key) headers["Idempotency-Key"] = key;
    const response = await fetch(`/api/cafeteria/${scope ? scope + "/" : ""}${path}`, {
      cache: "no-store", ...(data === undefined ? {} : { method, headers, body: multipart ? data : JSON.stringify(data) }),
    });
    const result = await response.json();
    if (!response.ok) throw new Error(typeof result.detail === "string" ? result.detail : "请检查填写内容");
    return result;
  }

  function keyFor(form, payload) {
    const serialized = JSON.stringify(payload);
    if (form.requestBody !== serialized) {
      form.requestKey = [...crypto.getRandomValues(new Uint32Array(4))].map(n => n.toString(16).padStart(8, "0")).join("");
      form.requestBody = serialized;
    }
    return form.requestKey;
  }

  function show(title, html, submit) {
    document.querySelector("#cafeteria-dialog-title").textContent = title;
    dialogStatus.textContent = "";
    body.innerHTML = html;
    if (!dialog.open) dialog.showModal();
    dialog.scrollTop = 0;
    const form = body.querySelector("form");
    if (!form || !submit) return;
    form.addEventListener("submit", async event => {
      event.preventDefault();
      const control = event.submitter;
      if (control) control.disabled = true;
      dialogStatus.textContent = "";
      try {
        await submit(new FormData(form), form);
      } catch (error) {
        dialogStatus.textContent = error.message;
      } finally {
        if (control) control.disabled = false;
      }
    });
  }

  const field = (label, name, type = "text", attrs = "") =>
    `<label><span>${esc(label)}</span><input name="${name}" type="${type}" ${attrs}></label>`;
  const select = (label, name, values) =>
    `<label><span>${esc(label)}</span><select name="${name}" required>${options(values)}</select></label>`;
  const submitButton = label => `<div class="admin-field-wide"><button type="submit">${esc(label)}</button></div>`;
  const formHtml = html => `<form class="admin-form">${html}</form>`;
  const today = () => new Intl.DateTimeFormat("sv-SE", { timeZone: "Asia/Shanghai" }).format(new Date());
  const roleOptions = (roles, current = []) => Object.entries(roles).map(([key, label]) =>
    `<label class="role-option"><input type="checkbox" name="roles" value="${esc(key)}" ${current.includes(key) ? "checked" : ""}> ${esc(label)}</label>`).join("");

  async function staff(scope, token) {
    const data = await api("staff", { scope });
    if (token !== revision) return;
    content.innerHTML = `<div class="card-header"><h2>人员与权限</h2>${button("邀请新员工", "data-invite")}</div>` +
      table(["姓名", "邮箱或用户名", "岗位", "状态", "操作"], data.users.map(user => [
        esc(user.displayName), esc(user.email || user.username), esc(user.roleDisplayNames.join("、")),
        user.pending ? "待注册" : user.mustSetPassword ? "待设置密码" : "已注册", button("修改岗位", `data-staff="${user.id}"`),
      ]));
    content.querySelector("[data-invite]").onclick = () => {
      show("邀请新员工", formHtml(
        select("登录方式", "login_type", [["email", "Boyuan 邮箱"], ["username", "用户名（无邮箱）"]]) +
        field("邮箱", "email", "email", "required maxlength=255") +
        field("用户名", "username", "text", 'disabled minlength=3 maxlength=40 pattern="[A-Za-z0-9_]{3,40}" autocapitalize="none"') +
        field("显示名称", "display_name", "text", "maxlength=120") +
        `<div class="admin-field-wide role-options">${roleOptions(data.roles)}</div>` + submitButton("邀请员工")), async fields => {
        const result = await api("invitations", {
          scope,
          data: { email: fields.get("email"), username: fields.get("username"),
            display_name: fields.get("display_name"), roles: fields.getAll("roles") },
        });
        if (result.signupUrl) {
          show("邀请链接", `<label>注册链接 <input readonly value="${esc(result.signupUrl)}"></label>`);
        } else {
          show("账号已创建", `<p>用户名：<strong>${esc(result.username)}</strong></p><p>员工使用食堂默认密码登录，首次登录时需设置个人密码。</p>`);
        }
        await refresh();
      });
      const username = body.querySelector('[name="username"]');
      const sanitizeUsername = () => {
        const end = username.selectionStart;
        const valid = username.value.replace(/[^A-Za-z0-9_]/g, "");
        if (valid === username.value) return;
        const cursor = username.value.slice(0, end).replace(/[^A-Za-z0-9_]/g, "").length;
        username.value = valid;
        username.setSelectionRange(cursor, cursor);
      };
      username.addEventListener("input", event => { if (!event.isComposing) sanitizeUsername(); });
      username.addEventListener("compositionend", sanitizeUsername);
      const type = body.querySelector('[name="login_type"]');
      const updateFields = () => {
        for (const name of ["username", "email"]) {
          const input = body.querySelector(`[name="${name}"]`);
          const enabled = type.value === name;
          input.disabled = !enabled;
          input.required = enabled;
          input.closest("label").hidden = !enabled;
        }
      };
      type.onchange = updateFields;
      updateFields();
    };
    content.querySelectorAll("[data-staff]").forEach(control => {
      const user = data.users.find(entry => entry.id === Number(control.dataset.staff));
      control.onclick = () => show(`修改岗位 · ${user.displayName}`, formHtml(
        `<p class="admin-field-wide">取消全部勾选会撤销本食堂普通岗位。</p><div class="admin-field-wide role-options">${roleOptions(data.roles, user.roles)}</div>` +
        submitButton("保存权限")), async fields => {
        await api(`staff/${user.id}/roles`, { scope, method: "PUT", data: { roles: fields.getAll("roles") } });
        dialog.close();
        await refresh();
      });
    });
  }

  function lineEditor(catalog, kind, requestLines = []) {
    const items = catalog.items.map(item => [item.id, `${item.name} · ${item.spec || "通用"} · ${item.unit}`]);
    const suppliers = catalog.suppliers.map(item => [item.id, item.name]);
    const purchasing = kind === "batch";
    let index = 0;
    const add = (base = null) => {
      const node = document.createElement("fieldset");
      const key = `line${index++}`;
      node.dataset.line = key;
      node.className = "admin-form";
      node.innerHTML =
        (purchasing ? select("原申请物资", key + "request", requestLines.map(line => [line.id, line.name])) : "") +
        select("实际物资", key + "item", [["", "请选择"], ...items]) +
        field("数量", key + "quantity", "number", `required min="${kind === "count" ? 0 : 0.0001}" step="0.0001"`) +
        field("规格", key + "spec", "text", "maxlength=120") +
        (purchasing || kind === "opening" ? field("单价", key + "price", "number", "required min=0.0001 step=0.0001") +
          field("到期日", key + "expiry", "date") : "") +
        (purchasing ? select("供应商", key + "supplier", [["", "请选择"], ...suppliers]) + field("凭证说明", key + "voucher") : "") +
        button("移除此项", "data-remove");
      body.querySelector("[data-lines]").append(node);
      if (base) {
        node.querySelector(`[name="${key}request"]`).value = base.id;
        node.querySelector(`[name="${key}item"]`).value = base.item_id;
        node.querySelector(`[name="${key}quantity"]`).value = base.remaining;
        node.querySelector(`[name="${key}spec"]`).value = base.spec;
      }
      node.querySelector("[data-remove]").onclick = () => node.remove();
    };
    body.querySelector("[data-add-line]").onclick = () => add();
    if (purchasing) requestLines.filter(line => Number(line.remaining) > 0).forEach(add);
    else add();
    return fields => [...body.querySelectorAll("[data-line]")].map(node => {
      const key = node.dataset.line;
      const spec = fields.get(key + "spec");
      return { item_id: Number(fields.get(key + "item")), quantity: fields.get(key + "quantity"),
        spec: spec || null, price: fields.get(key + "price") || null, expiry: fields.get(key + "expiry") || null,
        supplier_id: Number(fields.get(key + "supplier")) || null, request_line_id: Number(fields.get(key + "request")) || null,
        voucher: fields.get(key + "voucher") || "" };
    });
  }

  async function newDocument(scope, kind) {
    const catalog = await api("catalog", { scope });
    const extra = kind === "transfer" ? select("调入食堂", "destination", Object.entries(sites).filter(([key]) => key !== scope))
      : kind === "issue" ? select("指定领用人", "target_id", [["", "请选择"], ...catalog.recipients.map(user => [user.id, user.name])])
      : kind === "correction" ? field("原单编号", "original_id", "number", "required min=1") : "";
    let collect = () => [];
    show(kinds[kind], formHtml(field("业务日期", "business_date", "date", `required value="${today()}"`) + extra +
      field("说明／原因", "note", "text", "maxlength=1000") +
      (kind !== "correction" ? `<div data-lines class="admin-field-wide"></div>${button("添加物资", "data-add-line")}` : "") +
      submitButton("提交单据")), async (fields, form) => {
      const data = { kind, business_date: fields.get("business_date"), note: fields.get("note"),
        target_id: Number(fields.get("target_id")) || null, original_id: Number(fields.get("original_id")) || null,
        destination: fields.get("destination"), lines: collect(fields) };
      await api("documents", { scope, data, key: keyFor(form, data) });
      dialog.close();
      await refresh();
    });
    if (kind !== "correction") collect = lineEditor(catalog, kind);
  }

  function permittedActions(doc, scope) {
    const { jobs, status: state } = doc;
    const can = (...values) => values.some(value => jobs.includes(value));
    if (doc.site !== scope) return state === "transit" && can("store") ? ["receive_transfer"] : [];
    const available = [];
    if (state === "approval" && !doc.mine && can("manager", "supervisor")) available.push("approve", "reject");
    if (state === "purchasing" && can("buyer")) available.push("purchase", "close");
    if (state === "receipt" && !doc.buyer && can("store")) available.push("receive");
    if (state === "issue_pending" && doc.recipient && can("kitchen", "manager", "supervisor")) available.push("confirm_issue");
    if (doc.mine && ["approval", "issue_pending", "rejected"].includes(state)) available.push("cancel");
    return available;
  }

  async function actionForm(scope, doc, action) {
    const purchasing = action === "purchase";
    const receiving = action === "receive";
    const catalog = purchasing ? await api("catalog", { scope }) : null;
    let collect = () => [];
    show(actions[action], formHtml(
      (purchasing ? field("采购日期", "purchase_date", "date", `required value="${today()}"`) +
        select("采购方式", "purchase_method", [["市场采购", "市场采购"], ["供应商配送", "供应商配送"]]) +
        '<div data-lines class="admin-field-wide"></div>' + button("拆分或添加采购行", "data-add-line") +
        '<label><input type="checkbox" name="keep_remaining"> 保留剩余数量，继续采购</label>' : "") +
      (receiving ? doc.lines.map(line => field(`${line.name} · 实收数量（${line.unit}）`, `accepted-${line.id}`, "number",
        `required min=0 max="${esc(line.quantity)}" step=0.0001 value="${esc(line.quantity)}"`)).join("") +
        '<label><input type="checkbox" name="verified" required> 已现场核对实物、数量和质量</label>' : "") +
      field("说明／原因", "note", "text", "maxlength=1000") + submitButton("确认")), async (fields, form) => {
      const accepted = Object.fromEntries(doc.lines.filter(line => fields.has(`accepted-${line.id}`))
        .map(line => [line.id, fields.get(`accepted-${line.id}`)]));
      const data = { action, version: doc.version, note: fields.get("note"), lines: collect(fields),
        accepted, verified: fields.has("verified"), keep_remaining: fields.has("keep_remaining"),
        purchase_date: fields.get("purchase_date"), purchase_method: fields.get("purchase_method") || "市场采购" };
      await api(`documents/${doc.id}/actions`, { scope, data, key: keyFor(form, data) });
      dialog.close();
      await refresh();
    });
    if (purchasing) collect = lineEditor(catalog, "batch", doc.lines);
  }

  async function prepareAttachment(file) {
    if (!file.type.startsWith("image/")) return file;
    if (file.size > 30 * 1024 * 1024 || typeof createImageBitmap !== "function") return file;
    let bitmap;
    try {
      bitmap = await createImageBitmap(file);
      if (Math.max(bitmap.width, bitmap.height) <= 1920 && file.size <= 8 * 1024 * 1024) return file;
      const scale = Math.min(1, 1920 / Math.max(bitmap.width, bitmap.height));
      const canvas = document.createElement("canvas");
      canvas.width = Math.max(1, Math.round(bitmap.width * scale));
      canvas.height = Math.max(1, Math.round(bitmap.height * scale));
      const context = canvas.getContext("2d", { alpha: false });
      context.drawImage(bitmap, 0, 0, canvas.width, canvas.height);
      const blob = await new Promise(resolve => canvas.toBlob(resolve, "image/jpeg", .85));
      return blob ? new File([blob], file.name.replace(/\.[^.]*$/, "") + ".jpg", { type: blob.type }) : file;
    } catch {
      return file;
    } finally {
      bitmap?.close();
    }
  }

  async function detail(scope, id) {
    const doc = await api(`documents/${id}`, { scope });
    const canUpload = doc.site === scope && doc.jobs.some(job => ["buyer", "store", "kitchen", "supervisor", "manager"].includes(job))
      && !["completed", "rejected", "cancelled", "reversed"].includes(doc.status);
    show(`${kinds[doc.kind]} #${doc.id}`, `<p>${esc(sites[doc.site])} ${doc.destination ? " → " + esc(sites[doc.destination]) : ""}
      · ${esc(states[doc.status])} · ${esc(doc.business_date)} ${esc(doc.purchase_method)}</p><p>${esc(doc.note)}</p>` +
      (doc.parent_id ? button(`采购申请 #${doc.parent_id}`, `data-related="${doc.parent_id}"`) : "") +
      (doc.original_id ? button(`原单 #${doc.original_id}`, `data-related="${doc.original_id}"`) : "") +
      table(["物资", "规格", "数量", "单价", "实收", "待采购", "到期日"], doc.lines.map(line => [
        esc(line.name), esc(line.spec), esc(line.quantity + " " + line.unit), esc(line.price),
        esc(line.accepted), esc(line.remaining), esc(line.expiry),
      ])) +
      `<div class="admin-actions">${permittedActions(doc, scope).map(action => button(actions[action], `data-action="${action}"`)).join("")}</div>` +
      `<h4>附件</h4><ul>${doc.files.map(file => `<li><a href="/api/cafeteria/${scope}/files/${file.id}">${esc(file.name)}</a></li>`).join("")}</ul>` +
      (canUpload ? button("上传照片或 PDF", "data-upload") : "") +
      table(["时间", "办理人", "动作", "说明"], doc.events.map(event => [
        esc(event.created_at), esc(event.actor), esc(actions[event.action] || event.action), esc(event.detail),
      ])));
    body.querySelector("[data-related]")?.addEventListener("click", event => {
      detail(scope, event.currentTarget.dataset.related).catch(report);
    });
    body.querySelector("[data-upload]")?.addEventListener("click", () => show("上传凭证", formHtml(
      field("拍照", "camera", "file", 'accept="image/*" capture="environment"') +
      field("相册或 PDF", "file", "file", 'accept="image/*,.pdf"') + submitButton("上传")), async (fields, form) => {
      const file = fields.get("camera").size ? fields.get("camera") : fields.get("file");
      if (!file.size) throw new Error("请先选择文件");
      const key = keyFor(form, [file.name, file.size, file.lastModified]);
      if (form.attachmentKey !== key) {
        form.attachment = await prepareAttachment(file);
        form.attachmentKey = key;
      }
      const payload = new FormData();
      payload.set("file", form.attachment);
      await api(`documents/${id}/files`, { scope, data: payload, key });
      await detail(scope, id);
    }));
    body.querySelectorAll("[data-action]").forEach(control => {
      control.onclick = () => actionForm(scope, doc, control.dataset.action).catch(report);
    });
  }

  async function documents(scope, token) {
    const [listing, catalog] = await Promise.all([api(`documents?page=${currentPage}&status=${encodeURIComponent(documentStatus)}`, { scope }), api("catalog", { scope })]);
    if (token !== revision) return;
    content.innerHTML = `<div class="card-header"><h2>业务单据</h2><div class="admin-actions">${catalog.createKinds.map(kind =>
      button(kinds[kind], `data-new-doc="${kind}"`)).join("")}</div></div>` +
      table(["单号", "食堂", "类型", "业务日期", "状态"], listing.documents.map(doc => [
        button(String(doc.id), `data-doc="${doc.id}"`), esc(sites[doc.site]), esc(kinds[doc.kind]),
        esc(doc.business_date), esc(states[doc.status]),
      ])) +
      `<div class="admin-actions">${button("上一页", `data-offset="-1" ${currentPage === 1 ? "disabled" : ""}`)}
      <span>第 ${currentPage} 页</span>${button("下一页", `data-offset="1" ${listing.more ? "" : "disabled"}`)}</div>`;
    if (has("store")) {
      const control = document.createElement("button");
      control.type = "button";
      control.textContent = "导入期初库存";
      control.onclick = () => intake(scope, "opening");
      content.querySelector(".card-header .admin-actions").append(control);
    }
    if (has("admin", "manager", "supervisor", "finance")) {
      const exportButton = document.createElement("button");
      exportButton.type = "button";
      exportButton.textContent = "导出 CSV";
      exportButton.onclick = () => window.location.assign(`/api/cafeteria/${scope}/export`);
      content.querySelector(".card-header").append(exportButton);
    }
    const filter = document.createElement("label");
    filter.className = "cafeteria-status-filter";
    filter.innerHTML = select("单据状态", "document-status", [["", "全部状态"], ...Object.entries(states)]).replace(/^<label>|<\/label>$/g, "");
    const selector = filter.querySelector("select");
    selector.value = documentStatus;
    selector.onchange = () => { documentStatus = selector.value; currentPage = 1; refresh(); };
    content.querySelector(".card-header").append(filter);
    content.querySelectorAll("[data-doc]").forEach(control => control.onclick = () => detail(scope, control.dataset.doc).catch(report));
    content.querySelectorAll("[data-new-doc]").forEach(control => control.onclick = () => newDocument(scope, control.dataset.newDoc).catch(report));
    content.querySelectorAll("[data-offset]").forEach(control => control.onclick = () => {
      currentPage += Number(control.dataset.offset);
      refresh();
    });
  }

  async function inventory(scope, token) {
    const { lots, values } = await api("inventory", { scope });
    if (token !== revision) return;
    const totals = new Map();
    for (const lot of lots) {
      if (!totals.has(lot.item_id)) totals.set(lot.item_id, { ...lot, quantity: 0 });
      totals.get(lot.item_id).quantity += Number(lot.quantity);
    }
    content.innerHTML = "<h2>库存汇总</h2>" +
      table(["物资", "库存", "库存金额"], [...totals.values()].map(item => [
        esc(item.name), esc(item.quantity.toFixed(4) + " " + item.unit), esc(Number(values[item.item_id]).toFixed(2)),
      ])) + "<h2>现存批次</h2>" +
      table(["批次", "物资", "规格", "供应商", "余量", "到期日"], lots.map(lot => [
        esc(lot.id), esc(lot.name), esc(lot.spec), esc(lot.supplier), esc(lot.quantity + " " + lot.unit), esc(lot.expiry),
      ]));
  }

  async function catalog(scope, token) {
    const { items, suppliers } = await api("catalog", { scope });
    if (token !== revision) return;
    content.innerHTML = `<div class="card-header"><h2>物资目录</h2>${has("admin", "manager", "supervisor", "buyer", "store", "kitchen") ? button("新增物资", 'data-catalog="items"') : ""}</div>` +
      table(["名称", "分类", "单位", "规格"], items.map(item => [item.name, item.category, item.unit, item.spec].map(esc))) +
      `<div class="card-header"><h2>供应商</h2>${has("admin", "manager", "supervisor", "buyer") ? button("新增供应商", 'data-catalog="suppliers"') : ""}</div>` +
      table(["名称", "类型", "位置", "联系方式"], suppliers.map(item => [item.name, item.source_type, item.location, item.contact].map(esc)));
    if (has("admin", "manager")) {
      for (const [index, kind, label] of [[0, "items", "导入物资目录"], [1, "suppliers", "导入供应商"]]) {
        const control = document.createElement("button");
        control.type = "button";
        control.textContent = label;
        control.onclick = () => intake(scope, kind);
        content.querySelectorAll(".card-header")[index].append(control);
      }
    }
    content.querySelectorAll("[data-catalog]").forEach(control => control.onclick = () => {
      const path = control.dataset.catalog;
      const item = path === "items";
      const fields = field("名称", "name", "text", "required maxlength=120") + (item
        ? select("单位", "unit", units.map(unit => [unit, unit])) + field("分类", "category", "text", 'required value="其他食品类"') + field("规格", "spec")
        : select("来源类型", "source_type", ["有名商户", "无名固定菜商", "临时菜商"].map(value => [value, value])) + field("位置", "location") + field("联系方式", "contact"));
      show(control.textContent, formHtml(fields + submitButton("保存")), async data => {
        await api(path, { scope, data: [Object.fromEntries(data)] });
        dialog.close();
        await refresh();
      });
    });
  }

  function intake(scope, kind) {
    const opening = kind === "opening";
    const title = { opening: "导入期初库存", items: "导入物资目录", suppliers: "导入供应商" }[kind];
    let rows = null;
    show(title, formHtml(`<a href="/api/cafeteria/${scope}/intake/${kind}/template">下载 CSV 模板</a>` +
      field("CSV 文件", "file", "file", 'required accept=".csv"') +
      (opening ? field("启用日期", "business_date", "date", `required value="${today()}"`) +
        field("期初盘点说明", "note", "text", "required maxlength=1000") : "") +
      '<div class="admin-field-wide" data-preview></div>' + button("预览", "data-intake-preview") +
      submitButton(opening ? "提交期初审批" : "确认导入")), async (fields, form) => {
      if (!rows) throw new Error("请先预览文件");
      if (opening) {
        const data = { kind, business_date: fields.get("business_date"), note: fields.get("note"), lines: rows };
        await api("documents", { scope, data, key: keyFor(form, data) });
      } else {
        await api(kind, { scope, data: rows });
      }
      dialog.close();
      await refresh();
    });
    const preview = body.querySelector("[data-preview]");
    const input = body.querySelector('[name="file"]');
    input.onchange = () => { rows = null; preview.replaceChildren(); };
    body.querySelector("[data-intake-preview]").onclick = async () => {
      try {
        const file = input.files[0];
        if (!file) throw new Error("请先选择文件");
        const data = new FormData();
        data.set("file", file);
        const result = await api(`intake/${kind}/preview`, { scope, data });
        if (input.files[0] !== file) return;
        rows = result.rows;
        const columns = opening ? [["name", "物资"], ["spec", "规格"], ["unit", "单位"], ["quantity", "数量"], ["price", "单价"], ["expiry", "到期日期"]]
          : kind === "items" ? [["name", "名称"], ["category", "分类"], ["unit", "单位"], ["spec", "规格"]]
          : [["name", "名称"], ["source_type", "类型"], ["location", "位置"], ["contact", "联系方式"]];
        preview.innerHTML = `<p>共 ${rows.length} 行 · 显示前 20 行</p>` +
          table(columns.map(([, label]) => label), rows.slice(0, 20).map(entry =>
            columns.map(([field]) => esc(entry[field]))));
      } catch (error) { report(error); }
    };
  }

  const mealTable = rows => table(["日期", "餐次", "人次", "单价", "金额", "原表金额"], rows.map(entry => [
    esc(entry.date || "整期汇总"), esc(entry.meal), esc(entry.count), esc(entry.price),
    esc((Number(entry.price) * entry.count).toFixed(2)), esc(entry.source_amount),
  ]));

  async function meals(scope, token) {
    const { records } = await api("meals", { scope });
    if (token !== revision) return;
    content.innerHTML = `<div class="card-header"><h2>用餐月结</h2>${has("admin", "manager", "supervisor") ? button("导入用餐统计", "data-meal-import") : ""}</div>` +
      table(["月份", "版本", "周期", "金额", "状态"], records.map(entry => [
        button(entry.month, `data-meal="${entry.id}"`), esc(entry.version), esc(entry.period_start + " 至 " + entry.period_end),
        esc(entry.total), entry.locked_at ? "已锁定" : "待确认",
      ]));
    content.querySelectorAll("[data-meal]").forEach(control => control.onclick = async () => {
      try {
        const entry = await api(`meals/${control.dataset.meal}`, { scope });
        const canLock = has("manager", "supervisor") && !entry.locked_at &&
          records.find(record => record.month === entry.month)?.id === entry.id;
        show(`${entry.month} · V${entry.version}`, `<p>${esc(entry.period_start)} 至 ${esc(entry.period_end)}</p>
          <p>${esc(entry.comment)}</p><a href="/api/cafeteria/${scope}/files/${entry.file_id}">下载原始文件</a>` +
          mealTable(entry.rows) + (canLock ? button("确认并锁定", "data-meal-lock") : ""));
        body.querySelector("[data-meal-lock]")?.addEventListener("click", async () => {
          if (!window.confirm("锁定后该月不能重新导入。确认锁定？")) return;
          try {
            await api(`meals/${entry.id}/lock`, { scope, data: {} });
            dialog.close();
            await refresh();
          } catch (error) { report(error); }
        });
      } catch (error) { report(error); }
    });
    content.querySelector("[data-meal-import]")?.addEventListener("click", () => {
      show("导入用餐统计", formHtml(field("月份", "month", "month", `required value="${today().slice(0, 7)}"`) +
        field("周期开始", "period_start", "date", `required value="${today().slice(0, 7)}-01"`) +
        field("周期结束", "period_end", "date", `required value="${today()}"`) +
        field("说明／更正原因", "comment", "text", "maxlength=1000") +
        field("原始文件", "file", "file", 'required accept=".csv,.xls,.xlsx"') +
        '<div class="admin-field-wide" data-preview></div>' + button("预览文件", "data-meal-preview") + submitButton("确认导入")), async fields => {
        if (!body.querySelector("[data-preview]").dataset.ready) throw new Error("请先预览并核对文件");
        fields.set("month", fields.get("month") + "-01");
        await api("meals", { scope, data: fields });
        dialog.close();
        await refresh();
      });
      const preview = body.querySelector("[data-preview]");
      body.querySelector('[name="file"]').onchange = () => {
        delete preview.dataset.ready;
        preview.replaceChildren();
      };
      body.querySelector("[data-meal-preview]").onclick = async () => {
        try {
          const input = body.querySelector('[name="file"]');
          const file = input.files[0];
          if (!file) throw new Error("请先选择文件");
          const payload = new FormData();
          payload.set("file", file);
          const result = await api("meal-preview", { scope, data: payload });
          if (input.files[0] !== file) return;
          preview.innerHTML = mealTable(result.rows);
          preview.dataset.ready = "true";
        } catch (error) { report(error); }
      };
    });
  }

  const report = error => { (dialog.open ? dialogStatus : status).textContent = error.message; };
  async function refresh() {
    const token = ++revision;
    const scope = site.value;
    status.textContent = "";
    content.replaceChildren();
    if (!scope) return;
    const render = { documents, inventory, catalog, staff, meals }[currentSection];
    try {
      await render(scope, token);
    } catch (error) {
      if (token === revision) report(error);
    }
  }

  function choosePage() {
    const pages = [["documents", "业务单据"], ["inventory", "库存批次"], ["catalog", "物资与供应商"]];
    if (has("admin", "manager", "supervisor", "finance")) pages.push(["meals", "用餐月结"]);
    if (selected()?.manageStaff) pages.push(["staff", "人员与权限"]);
    if (!pages.some(([value]) => value === currentSection)) currentSection = "documents";
    pageNav.innerHTML = pages.map(([value, label]) =>
      button(label, `class="tab" data-section="${value}"`)).join("");
    sectionSelect.innerHTML = options(pages);
    highlightPage();
    currentPage = 1;
  }

  function highlightPage() {
    sectionSelect.value = currentSection;
    pageNav.querySelectorAll("[data-section]").forEach(control => {
      const active = control.dataset.section === currentSection;
      control.classList.toggle("active", active);
      control.setAttribute("aria-pressed", String(active));
      if (active) {
        const rail = pageNav.getBoundingClientRect();
        const tab = control.getBoundingClientRect();
        if (tab.left < rail.left) pageNav.scrollLeft += tab.left - rail.left;
        if (tab.right > rail.right) pageNav.scrollLeft += tab.right - rail.right;
      }
    });
  }

  window.showCafeteriaPasswordSetup = () => {
    document.querySelectorAll(".nav-item[data-view]").forEach(item => {
      const cafeteria = item.dataset.view === "cafeteria";
      item.classList.toggle("hidden", !cafeteria);
      item.classList.toggle("active", cafeteria);
    });
    document.querySelectorAll(".view").forEach(view => {
      view.classList.toggle("active", view.id === "view-cafeteria");
    });
    document.querySelector("#cafeteria-toolbar").classList.add("hidden");
    content.innerHTML = '<p>请先设置个人密码，再使用食堂管理。</p>' + button("设置密码", "data-set-password");
    content.querySelector("[data-set-password]").onclick = () => show("设置个人密码", formHtml(
      field("新密码", "password", "password", 'required minlength=8 maxlength=128 autocomplete="new-password"') +
      field("确认新密码", "confirm", "password", 'required minlength=8 maxlength=128 autocomplete="new-password"') +
      submitButton("保存密码")), async fields => {
      const password = fields.get("password");
      if (password !== fields.get("confirm")) throw new Error("两次输入的密码不一致");
      const result = await api("password", { scope: "", data: { password } });
      sessionStorage.setItem("boyuan_current_user", JSON.stringify(result.user));
      window.location.reload();
    });
  };

  window.refreshCafeteriaNav = async () => {
    try {
      const result = await api("access", { scope: "" });
      document.querySelector("#cafeteria-nav").classList.toggle("hidden", !result.sites.length);
    } catch {
      // Keep the permissions provided by the login session if the refresh fails.
    }
  };

  window.loadCafeteria = async () => {
    if (currentUser?.mustSetPassword) return;
    try {
      const previous = site.value;
      ({ sites: access } = await api("access", { scope: "" }));
      site.innerHTML = options(access.map(entry => [entry.id, entry.name]));
      if (access.some(entry => entry.id === previous)) site.value = previous;
      choosePage();
      await refresh();
    } catch (error) {
      report(error);
    }
  };
  site.onchange = () => { documentStatus = ""; choosePage(); refresh(); };
  function switchSection(section) {
    if (!section || section === currentSection) return;
    currentSection = section;
    highlightPage();
    currentPage = 1;
    refresh();
  }
  sectionSelect.onchange = () => switchSection(sectionSelect.value);
  pageNav.addEventListener("click", event => {
    switchSection(event.target.closest("[data-section]")?.dataset.section);
  });
  document.querySelector("#cafeteria-refresh").onclick = refresh;
  document.querySelector("[data-caf-close]").onclick = () => dialog.close();
})();
