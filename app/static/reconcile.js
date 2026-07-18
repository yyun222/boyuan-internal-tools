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
