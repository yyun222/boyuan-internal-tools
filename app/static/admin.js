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

