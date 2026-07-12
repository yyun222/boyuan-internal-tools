"""User, role, and role-assignment models."""

from sqlalchemy import Boolean, Column, DateTime, ForeignKey, Integer, String, Table, UniqueConstraint
from sqlalchemy.orm import relationship

from app.auth import utcnow
from app.db.base import Base

user_roles = Table(
    "user_roles", Base.metadata,
    Column("id", Integer, primary_key=True),
    Column("user_id", ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
    Column("role_id", ForeignKey("roles.id", ondelete="CASCADE"), nullable=False),
    Column("created_at", DateTime, nullable=False, default=utcnow),
    Column("updated_at", DateTime, nullable=False, default=utcnow, onupdate=utcnow),
    Column("deleted_at", DateTime),
    UniqueConstraint("user_id", "role_id", name="uq_user_roles_user_id_role_id"),
)


class User(Base):
    __tablename__ = "users"
    id = Column(Integer, primary_key=True)
    email = Column(String(255), nullable=False, unique=True, index=True)
    username = Column(String(255), unique=True, index=True)
    display_name = Column(String(120), nullable=False)
    password_hash = Column(String(255))
    is_active = Column(Boolean, nullable=False, default=True)
    invited_at = Column(DateTime)
    invited_by_user_id = Column(Integer, ForeignKey("users.id"))
    password_set_at = Column(DateTime)
    last_activity_at = Column(DateTime)
    created_at = Column(DateTime, nullable=False, default=utcnow)
    updated_at = Column(DateTime, nullable=False, default=utcnow, onupdate=utcnow)
    deleted_at = Column(DateTime)
    roles = relationship("Role", secondary=user_roles, back_populates="users")


class Role(Base):
    __tablename__ = "roles"
    id = Column(Integer, primary_key=True)
    name = Column(String(80), nullable=False, unique=True, index=True)
    display_name = Column(String(120), nullable=False)
    scope = Column(String(40), nullable=False, default="all")
    department = Column(String(120))
    can_view_reconcile = Column(Boolean, nullable=False, default=False)
    can_update_reconcile = Column(Boolean, nullable=False, default=False)
    can_view_asset_ledger = Column(Boolean, nullable=False, default=False)
    can_update_asset_ledger = Column(Boolean, nullable=False, default=False)
    can_view_stock_orders = Column(Boolean, nullable=False, default=True)
    can_update_stock_orders = Column(Boolean, nullable=False, default=True)
    can_view_activity_logs = Column(Boolean, nullable=False, default=False)
    can_manage_users = Column(Boolean, nullable=False, default=False)
    created_at = Column(DateTime, nullable=False, default=utcnow)
    updated_at = Column(DateTime, nullable=False, default=utcnow, onupdate=utcnow)
    deleted_at = Column(DateTime)
    users = relationship("User", secondary=user_roles, back_populates="roles")
