const $ = (s) => document.querySelector(s);
const form = $("#upload-form");
const submitBtn = $("#submit-btn");
const statusEl = $("#status");
const resultsEl = $("#results");

let lastResult = null;

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
    if (d && d.user) $("#current-user").textContent = d.user;
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
