"""Parse the existing daily CSV and monthly Excel formats without evaluating formulas."""

import csv
import io
import re
import zipfile
from datetime import date
from decimal import Decimal, InvalidOperation

import xlrd
from openpyxl import load_workbook

from app.services.cafeteria_inventory import require

PRICES = {"早餐": 4, "午餐": 8, "晚餐": 6}


def csv_rows(content):
    try:
        data = content.decode("utf-8-sig")
    except UnicodeDecodeError:
        data = content.decode("gb18030")
    return list(csv.reader(io.StringIO(data), strict=True))


def excel_rows(name, content):
    if name.endswith(".xls"):
        workbook = xlrd.open_workbook(file_contents=content, on_demand=True)
        try:
            for sheet in workbook.sheets()[:20]:
                yield [sheet.row_values(index, end_colx=50) for index in range(min(sheet.nrows, 3000))]
        finally:
            workbook.release_resources()
    else:
        with zipfile.ZipFile(io.BytesIO(content)) as archive:
            require(sum(info.file_size for info in archive.infolist()) <= 64 * 1024 * 1024, "Excel 解压后过大")
        workbook = load_workbook(io.BytesIO(content), read_only=True, data_only=True, keep_links=False)
        try:
            for sheet in workbook.worksheets[:20]:
                yield list(sheet.iter_rows(max_row=min(sheet.max_row or 3000, 3000), max_col=50, values_only=True))
        finally:
            workbook.close()


def meal_row(meal, count, price, service_date=None, source_amount=None):
    meal = "午餐" if meal == "中餐" else meal
    require(meal in PRICES, "餐次无效")
    count = Decimal(str(count))
    require(count.is_finite() and 0 <= count <= 10**9 and count == int(count), "人次必须为非负整数")
    price = Decimal(str(price))
    require(price.is_finite() and 0 < price <= 10**6 and price == price.quantize(Decimal(".0001")),
            "餐费单价无效")
    return {"date": service_date, "meal": meal, "count": int(count), "price": str(price),
            "source_amount": str(source_amount) if isinstance(source_amount, (int, float)) else None}


def parse(name, content):
    try:
        if name.lower().endswith(".csv"):
            source = csv_rows(content)
            require(source and source[0] == ["日期", "餐次", "人次"], "CSV 表头应为 日期,餐次,人次")
            rows = [meal_row(meal, count, PRICES.get(meal), date.fromisoformat(day).isoformat())
                    for day, meal, count in (r for r in source[1:] if any(r))]
            mode = "daily"
        else:
            require(name.lower().endswith((".xlsx", ".xls")), "请上传 XLS、XLSX 或 CSV 文件")
            rows = []
            mode = "summary"
            for sheet in excel_rows(name.lower(), content):
                for index, header in enumerate(sheet):
                    if "合计人次" not in header or "餐别" not in header:
                        continue
                    require("餐费标准" in header, "原表缺少餐费标准")
                    meal_index, count_index, price_index = map(header.index, ("餐别", "合计人次", "餐费标准"))
                    amount_index = header.index("金额（元）") if "金额（元）" in header else None
                    for source in sheet[index + 1:]:
                        meal = str(source[meal_index] or "").strip() if meal_index < len(source) else ""
                        if meal not in {*PRICES, "中餐"}:
                            continue
                        price = source[price_index] if price_index < len(source) else None
                        if isinstance(price, str):
                            match = re.search(r"([\d.]+)\s*元", price)
                            price = match.group(1) if match else price
                        rows.append(meal_row(meal, source[count_index], price,
                                             source_amount=source[amount_index] if amount_index is not None and amount_index < len(source) else None))
                    break
                if rows:
                    break
    except (ValueError, TypeError, InvalidOperation, IndexError, KeyError, csv.Error, zipfile.BadZipFile, xlrd.XLRDError):
        require(False, "文件格式、日期、人数或单价无效，请核对原文件")
    require(0 < len(rows) <= 1000, "未识别到有效餐次，或数据超过 1000 行")
    require(len({(row["date"], row["meal"]) for row in rows}) == len(rows), "同日或整期同餐次重复")
    return mode, rows
