"""Fixed-asset ledger models."""

from sqlalchemy import Column, DateTime, Integer, String, Text

from app.auth import utcnow
from app.db.base import Base


class AssetLedgerAsset(Base):
    __tablename__ = "asset_ledger_assets"
    id = Column(Integer, primary_key=True)
    client_id = Column(String(80), nullable=False, unique=True, index=True)
    asset_no = Column(String(120), nullable=False, index=True)
    name = Column(String(255), nullable=False)
    model = Column(String(255))
    site = Column(String(120), index=True)
    department = Column(String(120), index=True)
    use_department = Column(String(120))
    location = Column(String(255))
    start_date = Column(String(40))
    manager = Column(String(120))
    admin = Column(String(120))
    owner = Column(String(120))
    status = Column(String(80), index=True)
    check_result = Column(String(80), index=True)
    last_check_date = Column(String(40))
    actual_location = Column(String(255))
    remark = Column(Text)
    source_row = Column(Integer)
    extra_data = Column(Text)
    created_at = Column(DateTime, nullable=False, default=utcnow)
    updated_at = Column(DateTime, nullable=False, default=utcnow, onupdate=utcnow)
    deleted_at = Column(DateTime)


class AssetLedgerLog(Base):
    __tablename__ = "asset_ledger_logs"
    id = Column(Integer, primary_key=True)
    client_id = Column(String(80), nullable=False, unique=True, index=True)
    event_date = Column(String(40), nullable=False, index=True)
    action = Column(String(120), nullable=False)
    asset_no = Column(String(120), index=True)
    asset_name = Column(String(255))
    department = Column(String(120), index=True)
    detail = Column(Text, nullable=False)
    extra_data = Column(Text)
    created_at = Column(DateTime, nullable=False, default=utcnow)
    updated_at = Column(DateTime, nullable=False, default=utcnow, onupdate=utcnow)
    deleted_at = Column(DateTime)
