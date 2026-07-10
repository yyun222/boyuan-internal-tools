"""Reconciliation logic for the three Excel files.

Inputs (as raw bytes):
    warehouse_xls  仓库原料库余额表 (.xls)  - cols: 科目编码 | 科目名称 | 期末借方余额数量
    mapping_xlsx   代码对应表       (.xlsx) - cols: 财务编号 | 物料描述 | 仓库代码 | 仓库名称
    finance_xlsx   财务系统原料库库存 (.xlsx) - cols: 货品编码 | 描述 | 单位 | Warehouse | 结存数量
"""

from __future__ import annotations

from io import BytesIO
from typing import Any

import xlrd
from openpyxl import load_workbook

QTY_TOL = 1e-6


def _to_str(v: Any) -> str:
    if v is None:
        return ""
    if isinstance(v, float) and v.is_integer():
        v = int(v)
    return str(v).strip()


def _to_qty(v: Any) -> float | None:
    if v is None or v == "":
        return None
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def _parse_warehouse(xls_bytes: bytes) -> dict[str, dict]:
    """Return {wh_code: {name, qty}} excluding category-level rows (codes <= 5 chars)."""
    book = xlrd.open_workbook(file_contents=xls_bytes)
    sheet = book.sheets()[0]
    out: dict[str, dict] = {}
    for r in range(1, sheet.nrows):
        code = _to_str(sheet.cell_value(r, 0))
        name = _to_str(sheet.cell_value(r, 1))
        qty = _to_qty(sheet.cell_value(r, 2))
        if not code or len(code) <= 5:
            continue
        out[code] = {"name": name, "qty": qty if qty is not None else 0.0}
    return out


def _parse_mapping(xlsx_bytes: bytes) -> tuple[dict[str, dict], dict[str, list[dict]]]:
    """Return (fin_to_wh, wh_to_fins).

    fin_to_wh: {fin_code: {wh_code, wh_name, fin_desc}} (only rows with non-empty fin_code)
    wh_to_fins: {wh_code: [{fin_code, wh_name, fin_desc}, ...]}
    """
    wb = load_workbook(BytesIO(xlsx_bytes), data_only=True, read_only=True)
    ws = wb[wb.sheetnames[0]]
    fin_to_wh: dict[str, dict] = {}
    wh_to_fins: dict[str, list[dict]] = {}
    for i, row in enumerate(ws.iter_rows(values_only=True)):
        if i == 0:
            continue
        cells = list(row) + [None] * 4
        fin = _to_str(cells[0])
        desc = _to_str(cells[1])
        wh_code = _to_str(cells[2])
        wh_name = _to_str(cells[3])
        if fin:
            fin_to_wh[fin] = {
                "wh_code": wh_code,
                "wh_name": wh_name,
                "fin_desc": desc,
            }
        if wh_code:
            wh_to_fins.setdefault(wh_code, []).append({
                "fin_code": fin,
                "wh_name": wh_name,
                "fin_desc": desc,
            })
    return fin_to_wh, wh_to_fins


def _parse_finance(xlsx_bytes: bytes) -> dict[str, dict]:
    """Return {fin_code: {desc, unit, warehouse, qty}}."""
    wb = load_workbook(BytesIO(xlsx_bytes), data_only=True, read_only=True)
    ws = wb[wb.sheetnames[0]]
    out: dict[str, dict] = {}
    for i, row in enumerate(ws.iter_rows(values_only=True)):
        if i == 0:
            continue
        cells = list(row) + [None] * 5
        code = _to_str(cells[0])
        desc = _to_str(cells[1])
        unit = _to_str(cells[2])
        warehouse = _to_str(cells[3])
        qty = _to_qty(cells[4])
        if not code:
            continue
        out[code] = {
            "desc": desc,
            "unit": unit,
            "warehouse": warehouse,
            "qty": qty if qty is not None else 0.0,
        }
    return out


def _name_match(a: str, b: str) -> bool:
    """Loose name match: ignore separators/punctuation, lowercase. Used to flag
    suspicious mapping rows where the two systems' names disagree."""
    if not a or not b:
        return True  # don't flag if either side is missing
    drop = " :,，：、-_/()（）.．。+"
    norm = lambda s: "".join(ch for ch in s.lower() if ch not in drop)
    na, nb = norm(a), norm(b)
    if not na or not nb:
        return True
    return na in nb or nb in na


def reconcile(
    warehouse_xls: bytes,
    mapping_xlsx: bytes,
    finance_xlsx: bytes,
) -> dict:
    wh = _parse_warehouse(warehouse_xls)
    fin_to_wh, wh_to_fins = _parse_mapping(mapping_xlsx)
    fin = _parse_finance(finance_xlsx)

    matches: list[dict] = []
    mismatches: list[dict] = []
    mapped_no_wh_balance: list[dict] = []
    fin_no_mapping: list[dict] = []

    for fin_code, fin_row in fin.items():
        mapping = fin_to_wh.get(fin_code)
        if not mapping or not mapping["wh_code"]:
            fin_no_mapping.append({
                "fin_code": fin_code,
                "fin_desc": fin_row["desc"],
                "fin_qty": fin_row["qty"],
                "unit": fin_row["unit"],
                "warehouse": fin_row["warehouse"],
            })
            continue
        wh_code = mapping["wh_code"]
        wh_row = wh.get(wh_code)
        if wh_row is None:
            mapped_no_wh_balance.append({
                "fin_code": fin_code,
                "fin_desc": fin_row["desc"],
                "fin_qty": fin_row["qty"],
                "wh_code": wh_code,
                "wh_name_in_mapping": mapping["wh_name"],
            })
            continue
        f_q = float(fin_row["qty"])
        w_q = float(wh_row["qty"])
        diff = round(f_q - w_q, 6)
        name_ok = _name_match(fin_row["desc"], wh_row["name"])
        item = {
            "fin_code": fin_code,
            "fin_desc": fin_row["desc"],
            "wh_code": wh_code,
            "wh_name": wh_row["name"],
            "fin_qty": f_q,
            "wh_qty": w_q,
            "diff": diff,
            "name_match": name_ok,
        }
        if abs(diff) < QTY_TOL:
            matches.append(item)
        else:
            mismatches.append(item)

    # Warehouse-only: items that have no finance counterpart at all
    wh_only: list[dict] = []
    for wh_code, wh_row in wh.items():
        fin_links = wh_to_fins.get(wh_code, [])
        any_in_fin = any(link["fin_code"] and link["fin_code"] in fin for link in fin_links)
        if not any_in_fin:
            wh_only.append({
                "wh_code": wh_code,
                "wh_name": wh_row["name"],
                "wh_qty": float(wh_row["qty"]),
            })

    # Sort every table by the absolute value of the implied difference, descending.
    # When the counterpart is missing, the implied diff equals the present-side quantity.
    mismatches.sort(key=lambda x: abs(x["diff"]), reverse=True)
    mapped_no_wh_balance.sort(key=lambda x: abs(float(x["fin_qty"])), reverse=True)
    fin_no_mapping.sort(key=lambda x: abs(float(x["fin_qty"])), reverse=True)
    wh_only.sort(key=lambda x: abs(float(x["wh_qty"])), reverse=True)
    matches.sort(key=lambda x: abs(float(x["fin_qty"])), reverse=True)

    return {
        "summary": {
            "fin_total": len(fin),
            "wh_total": len(wh),
            "matches": len(matches),
            "mismatches": len(mismatches),
            "mapped_no_wh_balance": len(mapped_no_wh_balance),
            "fin_no_mapping": len(fin_no_mapping),
            "wh_only": len(wh_only),
            "name_mismatches": sum(1 for m in mismatches if not m["name_match"]),
        },
        "mismatches": mismatches,
        "mapped_no_wh_balance": mapped_no_wh_balance,
        "fin_no_mapping": fin_no_mapping,
        "wh_only": wh_only,
        "matches": matches,
    }
