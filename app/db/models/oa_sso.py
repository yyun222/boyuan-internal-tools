"""Consumed OA credentials, shared across application workers."""

from sqlalchemy import Column, DateTime, String

from app.auth import utcnow
from app.db.base import Base


class OaSsoCredential(Base):
    __tablename__ = "oa_sso_credentials"

    nonce_hash = Column(String(64), primary_key=True)
    expires_at = Column(DateTime, nullable=False, index=True)
    consumed_at = Column(DateTime, nullable=False, default=utcnow)
