"""Cafeteria records and stock posting ledger."""

from sqlalchemy.dialects.mysql import MEDIUMBLOB
from sqlalchemy import LargeBinary, JSON, Column, Date, DateTime, ForeignKey, Integer, Numeric, String, UniqueConstraint

from app.auth import utcnow
from app.db.base import Base


class CafeteriaSite(Base):
    __tablename__ = "cafeteria_sites"
    code = Column(String(24), primary_key=True)
    name = Column(String(40), nullable=False)


class CafeteriaItem(Base):
    __tablename__ = "cafeteria_items"
    __table_args__ = (UniqueConstraint("name", "unit", "spec"),)
    id = Column(Integer, primary_key=True)
    name = Column(String(120), nullable=False)
    unit = Column(String(20), nullable=False)
    spec = Column(String(120), nullable=False, default="")
    category = Column(String(40), nullable=False, default="其他食品类")


class CafeteriaSupplier(Base):
    __tablename__ = "cafeteria_suppliers"
    id = Column(Integer, primary_key=True)
    name = Column(String(120), nullable=False)
    source_type = Column(String(40), nullable=False)
    location = Column(String(120), nullable=False, default="")
    contact = Column(String(120), nullable=False, default="")


class CafeteriaDocument(Base):
    __tablename__ = "cafeteria_documents"
    id = Column(Integer, primary_key=True)
    site = Column(ForeignKey("cafeteria_sites.code"), nullable=False, index=True)
    destination = Column(ForeignKey("cafeteria_sites.code"))
    parent_id = Column(ForeignKey("cafeteria_documents.id"), index=True)
    original_id = Column(ForeignKey("cafeteria_documents.id"), index=True)
    kind = Column(String(24), nullable=False)
    status = Column(String(24), nullable=False)
    business_date = Column(Date, nullable=False)
    created_by = Column(ForeignKey("users.id"), nullable=False)
    buyer_id = Column(ForeignKey("users.id"))
    receiver_id = Column(ForeignKey("users.id"))
    target_id = Column(ForeignKey("users.id"))
    purchase_method = Column(String(24))
    note = Column(String(1000), nullable=False, default="")
    version = Column(Integer, nullable=False, default=1)
    created_at = Column(DateTime, nullable=False, default=utcnow)


class CafeteriaLine(Base):
    __tablename__ = "cafeteria_document_lines"
    id = Column(Integer, primary_key=True)
    document_id = Column(ForeignKey("cafeteria_documents.id"), nullable=False, index=True)
    item_id = Column(ForeignKey("cafeteria_items.id"), nullable=False)
    request_line_id = Column(ForeignKey("cafeteria_document_lines.id"))
    name = Column(String(120), nullable=False)
    unit = Column(String(20), nullable=False)
    spec = Column(String(120), nullable=False, default="")
    quantity = Column(Numeric(18, 4), nullable=False)
    accepted = Column(Numeric(18, 4))
    book = Column(Numeric(18, 4))
    closed_quantity = Column(Numeric(18, 4), nullable=False, default=0)
    price = Column(Numeric(18, 4))
    supplier_id = Column(ForeignKey("cafeteria_suppliers.id"))
    expiry = Column(Date)
    voucher = Column(String(1000), nullable=False, default="")


class CafeteriaLot(Base):
    __tablename__ = "cafeteria_stock_lots"
    id = Column(Integer, primary_key=True)
    site = Column(ForeignKey("cafeteria_sites.code"), nullable=False, index=True)
    item_id = Column(ForeignKey("cafeteria_items.id"), nullable=False, index=True)
    source_line_id = Column(ForeignKey("cafeteria_document_lines.id"), nullable=False)
    source_lot_id = Column(ForeignKey("cafeteria_stock_lots.id"))
    expiry = Column(Date)
    quantity = Column(Numeric(18, 4), nullable=False)


class CafeteriaMovement(Base):
    __tablename__ = "cafeteria_stock_movements"
    id = Column(Integer, primary_key=True)
    line_id = Column(ForeignKey("cafeteria_document_lines.id"), nullable=False, index=True)
    lot_id = Column(ForeignKey("cafeteria_stock_lots.id"), nullable=False, index=True)
    quantity = Column(Numeric(18, 4), nullable=False)
    value = Column(Numeric(24, 8), nullable=False)
    reverses_id = Column(ForeignKey("cafeteria_stock_movements.id"), unique=True)
    actor_id = Column(ForeignKey("users.id"), nullable=False)
    created_at = Column(DateTime, nullable=False, default=utcnow)


class CafeteriaEvent(Base):
    __tablename__ = "cafeteria_events"
    id = Column(Integer, primary_key=True)
    document_id = Column(ForeignKey("cafeteria_documents.id"), nullable=False, index=True)
    actor_id = Column(ForeignKey("users.id"), nullable=False)
    action = Column(String(40), nullable=False)
    detail = Column(String(1000), nullable=False, default="")
    created_at = Column(DateTime, nullable=False, default=utcnow)


class CafeteriaRequest(Base):
    __tablename__ = "cafeteria_idempotency_keys"
    user_id = Column(ForeignKey("users.id"), primary_key=True)
    key = Column(String(100), primary_key=True)
    digest = Column(String(64), nullable=False)
    response = Column(JSON, nullable=False)
    created_at = Column(DateTime, nullable=False, default=utcnow)


class CafeteriaFile(Base):
    __tablename__ = "cafeteria_files"
    id = Column(Integer, primary_key=True)
    site = Column(ForeignKey("cafeteria_sites.code"), nullable=False)
    document_id = Column(ForeignKey("cafeteria_documents.id"), index=True)
    uploader_id = Column(ForeignKey("users.id"), nullable=False)
    name = Column(String(200), nullable=False)
    content_type = Column(String(100), nullable=False)
    content = Column(LargeBinary().with_variant(MEDIUMBLOB(), "mysql"), nullable=False)
    created_at = Column(DateTime, nullable=False, default=utcnow)


class CafeteriaMeal(Base):
    __tablename__ = "cafeteria_meal_versions"
    __table_args__ = (UniqueConstraint("site", "month", "version"), UniqueConstraint("site", "month", "digest"))
    id = Column(Integer, primary_key=True)
    site = Column(ForeignKey("cafeteria_sites.code"), nullable=False)
    month = Column(String(7), nullable=False)
    version = Column(Integer, nullable=False)
    period_start = Column(Date, nullable=False)
    period_end = Column(Date, nullable=False)
    mode = Column(String(12), nullable=False)
    digest = Column(String(64), nullable=False)
    comment = Column(String(1000), nullable=False)
    rows = Column(JSON, nullable=False)
    file_id = Column(ForeignKey("cafeteria_files.id"), nullable=False)
    created_by = Column(ForeignKey("users.id"), nullable=False)
    locked_by = Column(ForeignKey("users.id"))
    locked_at = Column(DateTime)
    created_at = Column(DateTime, nullable=False, default=utcnow)
