"""Build an .xlsx report from a reconciliation result dict."""

from __future__ import annotations

from io import BytesIO

from openpyxl import Workbook
from openpyxl.styles import Alignment, Font, PatternFill
from openpyxl.utils import get_column_letter

HEADER_FONT = Font(bold=True, color="1D1D1F")
HEADER_FILL = PatternFill("solid", fgColor="F5F5F7")
NAME_MISMATCH_FILL = PatternFill("solid", fgColor="FFF1F0")
SUMMARY_LABEL_FONT = Font(bold=True)
LEFT = Alignment(horizontal="left", vertical="center")
RIGHT = Alignment(horizontal="right", vertical="center")


# Sheet name -> (result key, columns: list of (header, row_key, "num"|"text"))
SHEETS = [
    ("数量差异", "mismatches", [
        ("财务编号", "fin_code", "text"),
        ("财务描述", "fin_desc", "text"),
        ("仓库代码", "wh_code", "text"),
        ("仓库名称", "wh_name", "text"),
        ("财务数量", "fin_qty", "num"),
        ("仓库数量", "wh_qty", "num"),
        ("差额", "diff", "num"),
    ]),
    ("已映射但仓库无余额", "mapped_no_wh_balance", [
        ("财务编号", "fin_code", "text"),
        ("财务描述", "fin_desc", "text"),
        ("对应仓库代码", "wh_code", "text"),
        ("对应表中名称", "wh_name_in_mapping", "text"),
        ("财务数量", "fin_qty", "num"),
    ]),
    ("财务无映射", "fin_no_mapping", [
        ("财务编号", "fin_code", "text"),
        ("描述", "fin_desc", "text"),
        ("仓库", "warehouse", "text"),
        ("单位", "unit", "text"),
        ("财务数量", "fin_qty", "num"),
    ]),
    ("仅在仓库", "wh_only", [
        ("仓库代码", "wh_code", "text"),
        ("仓库名称", "wh_name", "text"),
        ("仓库数量", "wh_qty", "num"),
    ]),
    ("完全匹配", "matches", [
        ("财务编号", "fin_code", "text"),
        ("财务描述", "fin_desc", "text"),
        ("仓库代码", "wh_code", "text"),
        ("仓库名称", "wh_name", "text"),
        ("数量", "fin_qty", "num"),
    ]),
]


def _autosize(ws, ncols: int) -> None:
    """Approximate auto-fit for column widths based on content."""
    for c in range(1, ncols + 1):
        max_len = 0
        for row in ws.iter_rows(min_col=c, max_col=c, values_only=True):
            v = row[0]
            if v is None:
                continue
            # CJK chars count as ~2; rough approximation
            length = sum(2 if ord(ch) > 127 else 1 for ch in str(v))
            if length > max_len:
                max_len = length
        ws.column_dimensions[get_column_letter(c)].width = min(max(max_len + 2, 10), 60)


def _write_summary(wb: Workbook, summary: dict) -> None:
    ws = wb.create_sheet("汇总", 0)
    rows = [
        ("财务系统物料数", summary.get("fin_total")),
        ("仓库物料数", summary.get("wh_total")),
        ("完全匹配", summary.get("matches")),
        ("数量差异", summary.get("mismatches")),
        ("其中名称疑似不一致", summary.get("name_mismatches")),
        ("已映射但仓库无余额", summary.get("mapped_no_wh_balance")),
        ("财务无映射", summary.get("fin_no_mapping")),
        ("仅在仓库", summary.get("wh_only")),
    ]
    ws.cell(row=1, column=1, value="指标").font = HEADER_FONT
    ws.cell(row=1, column=1).fill = HEADER_FILL
    ws.cell(row=1, column=2, value="数值").font = HEADER_FONT
    ws.cell(row=1, column=2).fill = HEADER_FILL
    for i, (label, value) in enumerate(rows, start=2):
        ws.cell(row=i, column=1, value=label).font = SUMMARY_LABEL_FONT
        ws.cell(row=i, column=2, value=value).alignment = RIGHT
    ws.freeze_panes = "A2"
    _autosize(ws, 2)


def _write_table(wb: Workbook, sheet_name: str, columns: list[tuple], rows: list[dict]) -> None:
    ws = wb.create_sheet(sheet_name)
    headers = [h for h, _, _ in columns]
    for c, h in enumerate(headers, start=1):
        cell = ws.cell(row=1, column=c, value=h)
        cell.font = HEADER_FONT
        cell.fill = HEADER_FILL
        cell.alignment = LEFT
    for r, row in enumerate(rows, start=2):
        for c, (_, key, kind) in enumerate(columns, start=1):
            v = row.get(key)
            if kind == "num" and v is not None:
                try:
                    v = float(v)
                except (TypeError, ValueError):
                    pass
            cell = ws.cell(row=r, column=c, value=v)
            cell.alignment = RIGHT if kind == "num" else LEFT
        # Highlight name mismatches in the 数量差异 sheet
        if sheet_name == "数量差异" and row.get("name_match") is False:
            for c in range(1, len(columns) + 1):
                ws.cell(row=r, column=c).fill = NAME_MISMATCH_FILL
    ws.freeze_panes = "A2"
    _autosize(ws, len(columns))


def build_workbook(result: dict) -> bytes:
    wb = Workbook()
    # remove default sheet (we'll add named ones)
    default = wb.active
    wb.remove(default)

    _write_summary(wb, result.get("summary", {}))
    for sheet_name, key, columns in SHEETS:
        _write_table(wb, sheet_name, columns, result.get(key, []) or [])

    buf = BytesIO()
    wb.save(buf)
    return buf.getvalue()
