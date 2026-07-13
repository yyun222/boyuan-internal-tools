"""Stock-order tracking models."""

from sqlalchemy import Boolean, Column, DateTime, ForeignKey, Integer, String, Text, UniqueConstraint

from app.auth import utcnow
from app.db.base import Base


class StockOrder(Base):
    __tablename__ = "stock_orders"
    id = Column(Integer, primary_key=True)
    order_no = Column(String(40), nullable=False, unique=True, index=True)
    internal_name = Column(String(255), nullable=False, default="")
    cas = Column(String(120), nullable=False, default="")
    quantity = Column(String(120), nullable=False, default="")
    order_type = Column(String(40), nullable=False, default="备货订单", index=True)
    salesperson = Column(String(120), nullable=False, default="")
    demand_date = Column(String(40), nullable=False, default="")
    customer_name = Column(String(255), nullable=False, default="", index=True)
    order_situation = Column(Text, nullable=False, default="")
    quality_requirement = Column(Text, nullable=False, default="")
    delivery_requirement = Column(String(40), nullable=False, default="")
    sales_note = Column(Text, nullable=False, default="")
    sales_owner = Column(String(120), nullable=False, default="")
    purchase_material = Column(Text, nullable=False, default="")
    purchase_quantity = Column(String(120), nullable=False, default="")
    purchase_not_required = Column(Boolean, nullable=False, default=False)
    purchase_items = Column(Text, nullable=False, default="")
    purchase_date = Column(String(40), nullable=False, default="")
    arrival_date = Column(String(40), nullable=False, default="")
    purchase_note = Column(Text, nullable=False, default="")
    purchase_owner = Column(String(120), nullable=False, default="")
    production_not_required = Column(Boolean, nullable=False, default=False)
    production_form_date = Column(String(40), nullable=False, default="")
    production_status = Column(Text, nullable=False, default="")
    expected_delivery_date = Column(String(40), nullable=False, default="")
    production_note = Column(Text, nullable=False, default="")
    qc_not_required = Column(Boolean, nullable=False, default=False)
    coa_time = Column(String(40), nullable=False, default="")
    qc_note = Column(Text, nullable=False, default="")
    qc_owner = Column(String(120), nullable=False, default="")
    actual_delivery = Column(String(40), nullable=False, default="")
    sales_completed_at = Column(DateTime)
    purchase_completed_at = Column(DateTime)
    production_completed_at = Column(DateTime)
    qc_completed_at = Column(DateTime)
    purchase_responded_at = Column(DateTime)
    production_responded_at = Column(DateTime)
    qc_responded_at = Column(DateTime)
    archive_status = Column(String(40), nullable=False, default="未归档", index=True)
    cancelled_at = Column(DateTime)
    cancelled_reason = Column(Text, nullable=False, default="")
    created_by_user_id = Column(Integer, ForeignKey("users.id", ondelete="SET NULL"), index=True)
    updated_by_user_id = Column(Integer, ForeignKey("users.id", ondelete="SET NULL"), index=True)
    created_at = Column(DateTime, nullable=False, default=utcnow)
    updated_at = Column(DateTime, nullable=False, default=utcnow, onupdate=utcnow, index=True)
    deleted_at = Column(DateTime)


class StockOrderFieldUpdate(Base):
    __tablename__ = "stock_order_field_updates"
    __table_args__ = (UniqueConstraint("order_id", "field_key", name="uq_stock_field_order_key"),)
    id = Column(Integer, primary_key=True)
    order_id = Column(Integer, ForeignKey("stock_orders.id", ondelete="CASCADE"), nullable=False, index=True)
    field_key = Column(String(80), nullable=False)
    updated_date = Column(String(10), nullable=False)
    updated_by_user_id = Column(Integer, ForeignKey("users.id", ondelete="SET NULL"), index=True)
    created_at = Column(DateTime, nullable=False, default=utcnow)
    updated_at = Column(DateTime, nullable=False, default=utcnow, onupdate=utcnow)


class StockOrderChangeLog(Base):
    __tablename__ = "stock_order_change_logs"
    id = Column(Integer, primary_key=True)
    order_id = Column(Integer, ForeignKey("stock_orders.id", ondelete="CASCADE"), nullable=False, index=True)
    order_no = Column(String(40), nullable=False, index=True)
    module = Column(String(40), nullable=False, index=True)
    action = Column(String(40), nullable=False)
    field_key = Column(String(80), nullable=False, default="")
    field_label = Column(String(120), nullable=False, default="")
    old_value = Column(Text, nullable=False, default="")
    new_value = Column(Text, nullable=False, default="")
    operator_id = Column(Integer, ForeignKey("users.id", ondelete="SET NULL"), index=True)
    operator_name = Column(String(255), nullable=False)
    operated_at = Column(DateTime, nullable=False, default=utcnow, index=True)
    reason = Column(Text, nullable=False, default="")


class StockOrderWarning(Base):
    __tablename__ = "stock_order_warnings"
    __table_args__ = (UniqueConstraint("order_id", "warning_type", name="uq_stock_warning_order_type"),)
    id = Column(Integer, primary_key=True)
    order_id = Column(Integer, ForeignKey("stock_orders.id", ondelete="CASCADE"), nullable=False, index=True)
    order_no = Column(String(40), nullable=False, index=True)
    department = Column(String(40), nullable=False, index=True)
    warning_type = Column(String(80), nullable=False, index=True)
    message = Column(String(255), nullable=False)
    threshold_at = Column(DateTime)
    occurred_at = Column(DateTime, nullable=False, default=utcnow, index=True)
    detail = Column(Text, nullable=False, default="")
