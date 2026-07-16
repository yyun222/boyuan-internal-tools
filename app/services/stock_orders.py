"""Business rules and serialization for stock-order tracking."""

from __future__ import annotations

from datetime import datetime, timedelta

from app.auth import utcnow
from app.config import settings
from app.db.models import StockOrder, StockOrderFieldUpdate, StockOrderWarning, User


FIELD_META = {
    "internal_name": ("基础信息", "内部简称", "sales"),
    "cas": ("基础信息", "CAS", "sales"),
    "quantity": ("基础信息", "数量", "sales"),
    "order_type": ("销售部", "订单类型", "sales"),
    "salesperson": ("销售部", "业务员", "sales"),
    "demand_date": ("销售部", "提需求日期", "sales"),
    "customer_name": ("销售部", "客户名称", "sales"),
    "order_situation": ("销售部", "订单情况", "sales"),
    "quality_requirement": ("销售部", "质量要求", "sales"),
    "delivery_requirement": ("销售部", "交货期需求", "sales"),
    "sales_note": ("销售部", "销售其他说明", "sales"),
    "purchase_material": ("采购部", "需采购原料", "purchase"),
    "purchase_quantity": ("采购部", "采购数量", "purchase"),
    "purchase_not_required": ("采购部", "无需采购", "purchase"),
    "purchase_items": ("采购部", "采购原料明细", "purchase"),
    "purchase_date": ("采购部", "采购日期", "purchase"),
    "arrival_date": ("采购部", "预计到货时间", "purchase"),
    "purchase_note": ("采购部", "采购其他说明", "purchase"),
    "purchase_owner": ("采购部", "采购负责人", "purchase"),
    "production_not_required": ("生产部", "无需生产", "production"),
    "production_form_date": ("生产部", "填表日期", "production"),
    "production_status": ("生产部", "评估当前状态", "production"),
    "expected_delivery_date": ("生产部", "预计完成时间", "production"),
    "production_note": ("生产部", "生产其他说明", "production"),
    "qc_not_required": ("质量部", "无需检测", "qc"),
    "coa_time": ("质量部", "预计完成时间", "qc"),
    "qc_note": ("质量部", "QC备注", "qc"),
    "qc_owner": ("质量部", "QC负责人", "qc"),
    "actual_delivery": ("实际交货", "实际交货", "sales"),
}

BOOLEAN_FIELDS = {"purchase_not_required", "production_not_required", "qc_not_required"}
MODULES = {
    "purchase": ("arrival_date", "purchase_completed_at", "purchase_not_required", "采购预计到货"),
    "production": ("expected_delivery_date", "production_completed_at", "production_not_required", "生产预计完成"),
    "qc": ("coa_time", "qc_completed_at", "qc_not_required", "QC预计完成"),
}
DEPARTMENT_MODULE = {"销售部": "sales", "采购部": "purchase", "生产部": "production", "质量部": "qc", "QC/质检部": "qc"}


def business_date(value: datetime | None = None) -> str:
    """Return the China business date for naive UTC timestamps used by the app."""
    return ((value or utcnow()) + timedelta(hours=settings.business_utc_offset_hours)).date().isoformat()


def business_datetime(value: datetime | None) -> str:
    """Serialize a naive UTC database timestamp as Beijing/business time."""
    if value is None:
        return ""
    return (value + timedelta(hours=settings.business_utc_offset_hours)).isoformat()


def module_status(order: StockOrder, module: str) -> str:
    """Return the three-state form status shown in the tracking table."""
    done_key = "sales_completed_at" if module == "sales" else MODULES[module][1]
    if getattr(order, done_key):
        return "已完成"
    values = [getattr(order, key) for key, meta in FIELD_META.items() if meta[2] == module]
    return "进行中" if any(value not in (None, "", False, "[]") for value in values) else "未填写"


def user_modules(user: User) -> set[str]:
    if any(role.deleted_at is None and role.name == "admin" for role in user.roles):
        return {"sales", "purchase", "production", "qc"}
    return {
        DEPARTMENT_MODULE[role.department]
        for role in user.roles
        if role.deleted_at is None and role.department in DEPARTMENT_MODULE
    }


def can_edit_module(user: User, module: str) -> bool:
    return module in user_modules(user)


def is_admin(user: User) -> bool:
    return any(role.deleted_at is None and role.name == "admin" for role in user.roles)


def clean_fields(raw: dict) -> dict:
    result = {}
    for key, value in raw.items():
        if key not in FIELD_META:
            continue
        if key in BOOLEAN_FIELDS:
            result[key] = value is True or str(value).lower() in {"1", "true", "yes", "on"}
        else:
            result[key] = str(value or "").strip()
    return result


def field_locks(db, order: StockOrder) -> dict[str, bool]:
    today = business_date()
    updates = {row.field_key: row.updated_date for row in db.query(StockOrderFieldUpdate).filter_by(order_id=order.id).all()}
    fallback = business_date(order.updated_at or order.created_at)
    return {key: bool(getattr(order, key) not in (None, "", False) and updates.get(key, fallback) < today) for key in FIELD_META}


def overdue(order: StockOrder) -> dict[str, str]:
    if order.archive_status == "已取消" or order.order_type == "现货留货":
        return {}
    today = business_date()
    result = {}
    for module, (due_key, done_key, skip_key, label) in MODULES.items():
        if getattr(order, skip_key):
            continue
        due = getattr(order, due_key) or ""
        done = getattr(order, done_key)
        if due and not done and due < today:
            result[module] = f"{label}已逾期"
        elif due and done and done.date().isoformat() > due:
            result[module] = f"{label}逾期完成"
    return result


def sync_order_warnings(
    db,
    order: StockOrder,
    now: datetime | None = None,
    existing_types: set[str] | None = None,
) -> None:
    """Materialize each warning once so later performance exports remain auditable."""
    if order.archive_status == "已取消" or order.order_type == "现货留货":
        return
    now = now or utcnow()
    existing = existing_types if existing_types is not None else {
        row.warning_type for row in db.query(StockOrderWarning).filter_by(order_id=order.id).all()
    }

    def add(kind: str, department: str, message: str, threshold: datetime | None, detail: str = "") -> None:
        if kind in existing:
            return
        db.add(StockOrderWarning(
            order_id=order.id, order_no=order.order_no, department=department,
            warning_type=kind, message=message, threshold_at=threshold,
            occurred_at=now, detail=detail,
        ))
        existing.add(kind)

    if order.sales_completed_at:
        deadline = order.sales_completed_at + timedelta(hours=24)
        for module, department, responded in (
            ("purchase", "采购部", order.purchase_responded_at),
            ("production", "生产部", order.production_responded_at),
        ):
            if (responded and responded > deadline) or (not responded and now > deadline):
                add(f"{module}_response_24h", department, f"{department}未完成(24h)", deadline)

    if order.purchase_responded_at and order.production_responded_at:
        qc_start = max(order.purchase_responded_at, order.production_responded_at)
        deadline = qc_start + timedelta(hours=12)
        if (order.qc_responded_at and order.qc_responded_at > deadline) or (not order.qc_responded_at and now > deadline):
            add("qc_response_12h", "质量部", "质量部未完成(12h)", deadline)

    date_checks = (
        ("sales_delivery_late", "销售部", order.actual_delivery, order.delivery_requirement, True, "交货超时"),
        ("purchase_schedule_overdue", "采购部", business_date(order.purchase_completed_at) if order.purchase_completed_at else "", order.arrival_date, bool(order.purchase_completed_at), "采购超过预计到货时间"),
        ("production_schedule_overdue", "生产部", business_date(order.production_completed_at) if order.production_completed_at else "", order.expected_delivery_date, bool(order.production_completed_at), "生产超过预计完成时间"),
        ("qc_schedule_overdue", "质量部", business_date(order.qc_completed_at) if order.qc_completed_at else "", order.coa_time, bool(order.qc_completed_at), "QC超过预计完成时间"),
    )
    for kind, department, actual, due, finished, message in date_checks:
        is_late = bool(actual and due and actual > due)
        is_pending_overdue = bool(due and not finished and business_date(now) > due and department != "销售部")
        if is_late or is_pending_overdue:
            detail = f"要求：{due}；实际：{actual or '尚未完成'}"
            add(kind, department, message, datetime.fromisoformat(due), detail)


def order_payload(
    db,
    order: StockOrder,
    include_locks: bool = False,
    warning_rows: list[StockOrderWarning] | None = None,
) -> dict:
    data = {key: getattr(order, key) for key in FIELD_META}
    for key in BOOLEAN_FIELDS:
        data[key] = bool(data[key])
    data.update({
        "id": order.id,
        "order_no": order.order_no,
        "archive_status": order.archive_status,
        "sales_completed_at": business_datetime(order.sales_completed_at),
        "purchase_completed_at": business_datetime(order.purchase_completed_at),
        "production_completed_at": business_datetime(order.production_completed_at),
        "qc_completed_at": business_datetime(order.qc_completed_at),
        "cancelled_at": business_datetime(order.cancelled_at),
        "cancelled_reason": order.cancelled_reason or "",
        "created_at": business_datetime(order.created_at),
        "updated_at": business_datetime(order.updated_at),
        "module_statuses": {module: module_status(order, module) for module in ("sales", *MODULES)},
        "overdue": overdue(order),
        "warnings": [] if order.archive_status == "已取消" else [{
            "department": row.department, "type": row.warning_type,
            "message": row.message, "occurredAt": business_datetime(row.occurred_at),
        } for row in (
            warning_rows if warning_rows is not None
            else db.query(StockOrderWarning).filter_by(order_id=order.id).order_by(StockOrderWarning.occurred_at).all()
        )],
    })
    if include_locks:
        data["locks"] = field_locks(db, order)
    return data
