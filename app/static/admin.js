let managedRoles = [];
let managedUsers = [];
let oaTodoUsers = [];
let oaTodoSelections = {};
const oaTodoDepartments = [["purchase", "采购部"], ["production", "生产部"], ["qc", "质量部"]];

function renderOaTodoOptions(key, query = "") {
  const target = document.querySelector(`[data-oa-todo-options="${key}"]`);
  if (!target) return;
  const needle = query.trim().toLocaleLowerCase();
  const matches = oaTodoUsers.filter(user => `${user.displayName} ${user.oaLoginPhone}`.toLocaleLowerCase().includes(needle));
  const selected = oaTodoSelections[key] || new Set();
  const options = matches.slice(0, 50);
  target.innerHTML = options.length ? options.map(user => `
    <label class="oa-todo-option"><input type="checkbox" name="${key}-users" value="${user.id}" ${selected.has(user.id) ? "checked" : ""}>
      <span>${escapeHtml(user.displayName)} · ${escapeHtml(user.oaLoginPhone)}</span></label>
  `).join("") : '<span class="muted oa-todo-empty">没有匹配的用户</span>';
  const count = document.querySelector(`[data-oa-todo-count="${key}"]`);
  if (count) count.textContent = `匹配 ${matches.length} 人${matches.length > 50 ? "，当前显示前 50 人" : ""}`;
}

function renderOaTodoSelection(key) {
  const selected = oaTodoSelections[key] || new Set();
  const users = [...selected].map(id => oaTodoUsers.find(user => user.id === id)).filter(Boolean);
  const summary = document.querySelector(`[data-oa-todo-summary="${key}"]`);
  const preview = document.querySelector(`[data-oa-todo-selected="${key}"]`);
  if (summary) summary.textContent = users.length ? `已选 ${users.length} 人` : "选择接收人";
  if (preview) {
    const visible = users.slice(0, 3);
    preview.innerHTML = `${visible.map(user => `<span class="oa-todo-chip">${escapeHtml(user.displayName)}<button type="button" data-oa-todo-remove="${key}" data-user-id="${user.id}" aria-label="移除 ${escapeHtml(user.displayName)}">×</button></span>`).join("")}${users.length > visible.length ? `<span class="oa-todo-more">另有 ${users.length - visible.length} 人</span>` : ""}`;
  }
}

async function loadOaTodoConfig() {
  const status = $("#oa-todo-config-status");
  try {
    const response = await fetch("/api/admin/oa-todo-config", { cache: "no-store" });
    const data = await response.json().catch(() => ({}));
    if (!response.ok) throw new Error(data.detail || "OA 待办配置加载失败");
    oaTodoUsers = data.users || [];
    oaTodoSelections = Object.fromEntries(oaTodoDepartments.map(([key]) => [key, new Set(data.departments[key].userIds || [])]));
    $("#oa-todo-config-connection").textContent = data.oaConfigured ? "OA 接口凭证已配置" : "OA 接口凭证未配置，请在服务端环境变量中设置";
    $("#oa-todo-departments").innerHTML = oaTodoDepartments.map(([key, label]) => {
      const config = data.departments[key];
      return `<fieldset class="oa-todo-department"><legend>${label}</legend>
          <div class="oa-todo-fields"><label><span>待办标题</span><input name="${key}-subject" maxlength="255" required value="${escapeHtml(config.subject)}"></label>
        <label><span>目标链接</span><input name="${key}-link" maxlength="2000" required value="${escapeHtml(config.link)}"></label></div><p class="muted">标题支持 {order_no}、{internal_name}；链接支持 {order_no}、{order_id}。默认链接会打开对应订单。</p>
        <div class="admin-label">接收人</div><div class="oa-todo-recipient" data-oa-todo-recipient="${key}"><details class="oa-todo-picker">
          <summary><span data-oa-todo-summary="${key}">选择接收人</span><span class="oa-todo-chevron" aria-hidden="true">⌄</span></summary>
          <div class="oa-todo-picker-menu"><input type="search" class="oa-todo-search" data-oa-todo-search="${key}" placeholder="搜索姓名或手机号" autocomplete="off"><div class="oa-todo-option-list" data-oa-todo-options="${key}" role="group" aria-label="${label}接收人"></div><span class="muted oa-todo-count" data-oa-todo-count="${key}"></span></div>
        </details><div class="oa-todo-selected" data-oa-todo-selected="${key}"></div></div>
      </fieldset>`;
    }).join("");
    oaTodoDepartments.forEach(([key]) => {
      renderOaTodoOptions(key);
      renderOaTodoSelection(key);
    });
    status.textContent = "";
    status.className = "status";
  } catch (error) {
    status.textContent = error.message || String(error);
    status.className = "status error";
  }
}

$("#refresh-oa-todo-config")?.addEventListener("click", loadOaTodoConfig);
$("#oa-todo-departments")?.addEventListener("input", event => {
  const search = event.target.closest("[data-oa-todo-search]");
  if (search) renderOaTodoOptions(search.dataset.oaTodoSearch, search.value);
});
$("#oa-todo-departments")?.addEventListener("change", event => {
  const checkbox = event.target.closest('input[name$="-users"]');
  if (!checkbox) return;
  const key = checkbox.name.slice(0, -6);
  const selected = oaTodoSelections[key] || new Set();
  if (checkbox.checked) selected.add(Number(checkbox.value));
  else selected.delete(Number(checkbox.value));
  oaTodoSelections[key] = selected;
  renderOaTodoSelection(key);
});
$("#oa-todo-departments")?.addEventListener("click", event => {
  const remove = event.target.closest("[data-oa-todo-remove]");
  if (!remove) return;
  const key = remove.dataset.oaTodoRemove;
  oaTodoSelections[key]?.delete(Number(remove.dataset.userId));
  const checkbox = document.querySelector(`input[name="${key}-users"][value="${remove.dataset.userId}"]`);
  if (checkbox) checkbox.checked = false;
  renderOaTodoSelection(key);
});
$("#oa-todo-config-form")?.addEventListener("submit", async event => {
  event.preventDefault();
  const form = event.currentTarget;
  const submit = $("#save-oa-todo-config");
  const status = $("#oa-todo-config-status");
  const departments = Object.fromEntries(oaTodoDepartments.map(([key]) => [key, {
    user_ids: [...(oaTodoSelections[key] || new Set())],
    subject: form.elements[`${key}-subject`].value,
    link: form.elements[`${key}-link`].value,
  }]));
  submit.disabled = true;
  status.textContent = "正在保存…";
  status.className = "status";
  try {
    const response = await fetch("/api/admin/oa-todo-config", { method: "PUT", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ departments }) });
    const data = await response.json().catch(() => ({}));
    if (!response.ok) throw new Error(data.detail || "OA 待办配置保存失败");
    status.textContent = "配置已保存";
    status.className = "status success";
    await loadOaTodoConfig();
  } catch (error) {
    status.textContent = error.message || String(error);
    status.className = "status error";
  } finally {
    submit.disabled = false;
  }
});

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
      <thead><tr><th>用户</th><th>OA 登录手机号</th><th>角色</th><th>状态</th><th>邀请时间</th><th>密码设置时间</th><th>最近活动</th><th>操作</th></tr></thead>
      <tbody>${data.users.map((user) => `
        <tr>
          <td>${escapeHtml(user.displayName || "")}<br><span class="muted">${escapeHtml(user.email || user.username || "")}</span></td>
          <td><div class="user-oa-phone-cell"><span class="user-oa-phone-value${user.oaLoginPhone ? "" : " is-empty"}">${escapeHtml(user.oaLoginPhone || "未配置")}</span><button type="button" class="user-oa-phone-btn" data-user-id="${user.id}" aria-label="编辑 ${escapeHtml(user.displayName || user.email)} 的 OA 登录手机号">编辑</button></div></td>
          <td>${escapeHtml((user.roleDisplayNames || user.roles || []).join("、") || "—")}</td>
          <td><span class="user-state ${!user.hasPassword ? "pending" : (user.isActive ? "active" : "inactive")}">${!user.hasPassword ? "已邀请" : (user.isActive ? (user.mustSetPassword ? "待设置密码" : "正常") : "已停用")}</span></td>
          <td>${formatDateTime(user.invitedAt)}</td>
          <td>${formatDateTime(user.passwordSetAt)}</td>
          <td>${formatDateTime(user.lastActivityAt)}</td>
          <td><div class="user-row-actions"><button type="button" class="user-permission-btn" data-user-id="${user.id}">更新权限</button><button type="button" class="user-status-btn ${user.isActive ? "deactivate" : "activate"}" data-user-id="${user.id}" data-user-email="${escapeHtml(user.email || user.username || "")}" data-user-active="${user.isActive}" ${!user.hasPassword ? "disabled" : ""}>${user.isActive ? "停用" : "启用"}</button><button type="button" class="user-reset-btn" data-user-id="${user.id}" data-user-email="${escapeHtml(user.email || user.username || "")}" ${!user.hasPassword ? "disabled" : ""}>重置密码</button></div></td>
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
  const phoneBtn = event.target.closest(".user-oa-phone-btn");
  if (phoneBtn) {
    const user = managedUsers.find((item) => item.id === Number(phoneBtn.dataset.userId));
    if (!user) return;
    $("#user-oa-phone-title").textContent = `OA 登录手机号 · ${user.displayName || user.email}`;
    $("#user-oa-phone-id").value = String(user.id);
    $("#user-oa-phone-input").value = user.oaLoginPhone || "";
    $("#user-oa-phone-status").textContent = "";
    $("#user-oa-phone-mask").classList.add("active");
    $("#user-oa-phone-input").focus();
    return;
  }
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
    await Promise.all([loadUsers(), loadActivityLogs()]);
    status.textContent = data.mustSetPassword
      ? `已重置 ${data.username} 的密码。请使用默认密码登录后设置个人密码。`
      : `密码已重置。新密码设置链接：${data.signupUrl}`;
    status.className = "status success";
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
  $("#user-permission-title").textContent = `更新权限 · ${user.displayName || user.email || user.username}`;
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
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ roles }),
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

function closeOaPhoneEditor() {
  $("#user-oa-phone-mask").classList.remove("active");
}
document.querySelectorAll("[data-user-oa-phone-close]").forEach((button) => button.addEventListener("click", closeOaPhoneEditor));
$("#user-oa-phone-mask")?.addEventListener("click", (event) => {
  if (event.target.id === "user-oa-phone-mask") closeOaPhoneEditor();
});
$("#user-oa-phone-form")?.addEventListener("submit", async (event) => {
  event.preventDefault();
  const phone = $("#user-oa-phone-input").value.trim();
  const status = $("#user-oa-phone-status");
  status.className = "status error";
  if (phone && !/^1[3-9][0-9]{9}$/.test(phone)) {
    status.textContent = "请输入中国大陆 11 位手机号";
    return;
  }
  const submit = $("#user-oa-phone-submit");
  submit.disabled = true;
  status.textContent = "正在保存…";
  status.className = "status";
  try {
    const response = await fetch(`/api/users/${$("#user-oa-phone-id").value}/oa-phone`, {
      method: "PUT", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ oa_login_phone: phone || null }),
    });
    const data = await response.json().catch(() => ({}));
    if (!response.ok) throw new Error(data.detail || "手机号保存失败");
    await Promise.all([loadUsers(), loadActivityLogs()]);
    closeOaPhoneEditor();
    $("#user-status").textContent = phone ? "OA 登录手机号已更新" : "OA 登录手机号已清空";
    $("#user-status").className = "status success";
  } catch (error) {
    status.textContent = error.message || "手机号保存失败";
    status.className = "status error";
  } finally {
    submit.disabled = false;
  }
});

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

