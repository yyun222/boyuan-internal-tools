"""Business rules and serialization for stock-order tracking."""

from __future__ import annotations

from datetime import datetime

from app.db.models import StockOrder, StockOrderFieldUpdate, User


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
    "sales_owner": ("销售部", "销售负责人", "sales"),
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


def user_modules(user: User) -> set[str]:
    if any(role.deleted_at is None and role.name == "admin" for role in user.roles):
        return {"sales", "purchase", "production", "qc"}
    return {
        DEPARTMENT_MODULE[role.department]
        for role in user.roles
        if role.deleted_at is None and role.department in DEPARTMENT_MODULE
    }


def can_edit_module(user: User, module: str) -> bool:
    # Current rollout policy: every authenticated role with feature access may
    # update every department section. Keep this helper as the single policy
    # switch for a future return to department-scoped editing.
    return module in {"sales", "purchase", "production", "qc"}


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
    today = datetime.utcnow().date().isoformat()
    updates = {row.field_key: row.updated_date for row in db.query(StockOrderFieldUpdate).filter_by(order_id=order.id).all()}
    return {key: bool(getattr(order, key) not in (None, "", False) and updates.get(key, today) < today) for key in FIELD_META}


def overdue(order: StockOrder) -> dict[str, str]:
    if order.archive_status == "已取消" or order.order_type == "留货订单":
        return {}
    today = datetime.utcnow().date().isoformat()
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


def order_payload(db, order: StockOrder, include_locks: bool = False) -> dict:
    data = {key: getattr(order, key) for key in FIELD_META}
    for key in BOOLEAN_FIELDS:
        data[key] = bool(data[key])
    data.update({
        "id": order.id,
        "order_no": order.order_no,
        "archive_status": order.archive_status,
        "purchase_completed_at": order.purchase_completed_at.isoformat() if order.purchase_completed_at else "",
        "production_completed_at": order.production_completed_at.isoformat() if order.production_completed_at else "",
        "qc_completed_at": order.qc_completed_at.isoformat() if order.qc_completed_at else "",
        "created_at": order.created_at.isoformat() if order.created_at else "",
        "updated_at": order.updated_at.isoformat() if order.updated_at else "",
        "overdue": overdue(order),
    })
    if include_locks:
        data["locks"] = field_locks(db, order)
    return data
