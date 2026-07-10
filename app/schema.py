"""Database table definitions and seed data."""

from __future__ import annotations

from sqlalchemy import Boolean, Column, DateTime, ForeignKey, Integer, String, Table, Text, UniqueConstraint, text
from sqlalchemy.orm import DeclarativeBase, relationship

from app.auth import hash_password, utcnow


class Base(DeclarativeBase):
    pass


user_roles = Table(
    "user_roles",
    Base.metadata,
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
    can_view_activity_logs = Column(Boolean, nullable=False, default=False)
    can_manage_users = Column(Boolean, nullable=False, default=False)
    created_at = Column(DateTime, nullable=False, default=utcnow)
    updated_at = Column(DateTime, nullable=False, default=utcnow, onupdate=utcnow)
    deleted_at = Column(DateTime)

    users = relationship("User", secondary=user_roles, back_populates="roles")


class ActivityLog(Base):
    __tablename__ = "activity_logs"

    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, ForeignKey("users.id", ondelete="SET NULL"), index=True)
    activity_time = Column(DateTime, nullable=False, default=utcnow, index=True)
    action = Column(String(80), nullable=False)
    target = Column(String(120), nullable=False)
    detail = Column(Text, nullable=False)
    created_at = Column(DateTime, nullable=False, default=utcnow)
    updated_at = Column(DateTime, nullable=False, default=utcnow, onupdate=utcnow)
    deleted_at = Column(DateTime)

    user = relationship("User")


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


DEPARTMENT_ROLES = [
    ("dept01", "工程部", "工程部"),
    ("dept02", "行政后勤", "行政后勤"),
    ("dept03", "仓储部", "仓储部"),
    ("dept04", "销售部", "销售部"),
    ("dept05", "生产部", "生产部"),
    ("dept06", "质量部", "质量部"),
    ("dept07", "EHS", "EHS"),
    ("dept08", "济阳厂区", "济阳厂区"),
    ("dept09", "采购部", "采购部"),
    ("dept10", "建筑路墙", "建筑路墙"),
    ("dept12", "公共区", "公共区"),
    ("dept13", "动力车间", "动力车间"),
]


def _upsert_role(db, name: str, display_name: str, **values) -> Role:
    role = db.query(Role).filter(Role.name == name).one_or_none()
    if role is None:
        role = Role(name=name, display_name=display_name, **values)
        db.add(role)
    else:
        role.display_name = display_name
        role.deleted_at = None
        for key, value in values.items():
            setattr(role, key, value)
    return role


def _mysql_columns(conn, table_name: str) -> set[str]:
    rows = conn.execute(text(f"SHOW COLUMNS FROM `{table_name}`")).mappings()
    return {row["Field"] for row in rows}


def _mysql_primary_key_columns(conn, table_name: str) -> list[str]:
    rows = conn.execute(text(f"SHOW KEYS FROM `{table_name}` WHERE Key_name = 'PRIMARY'")).mappings()
    return [row["Column_name"] for row in rows]


def _mysql_index_names(conn, table_name: str) -> set[str]:
    rows = conn.execute(text(f"SHOW INDEX FROM `{table_name}`")).mappings()
    return {row["Key_name"] for row in rows}


def _add_column_if_missing(conn, table_name: str, column_name: str, definition: str) -> None:
    if column_name not in _mysql_columns(conn, table_name):
        conn.execute(text(f"ALTER TABLE `{table_name}` ADD COLUMN `{column_name}` {definition}"))


def _ensure_audit_columns(engine) -> None:
    if engine.dialect.name != "mysql":
        return
    with engine.begin() as conn:
        if "id" not in _mysql_columns(conn, "user_roles"):
            primary_key_columns = _mysql_primary_key_columns(conn, "user_roles")
            if primary_key_columns:
                index_names = _mysql_index_names(conn, "user_roles")
                if "ix_user_roles_user_id" not in index_names:
                    conn.execute(text("ALTER TABLE `user_roles` ADD INDEX `ix_user_roles_user_id` (`user_id`)"))
                if "ix_user_roles_role_id" not in index_names:
                    conn.execute(text("ALTER TABLE `user_roles` ADD INDEX `ix_user_roles_role_id` (`role_id`)"))
                conn.execute(text("ALTER TABLE `user_roles` DROP PRIMARY KEY"))
            conn.execute(text("ALTER TABLE `user_roles` ADD COLUMN `id` INT NOT NULL AUTO_INCREMENT PRIMARY KEY FIRST"))
        if "uq_user_roles_user_id_role_id" not in _mysql_index_names(conn, "user_roles"):
            conn.execute(text("ALTER TABLE `user_roles` ADD UNIQUE KEY `uq_user_roles_user_id_role_id` (`user_id`, `role_id`)"))

        table_columns = {
            "users": {"deleted_at": "DATETIME NULL"},
            "roles": {"updated_at": "DATETIME NULL", "deleted_at": "DATETIME NULL"},
            "activity_logs": {
                "created_at": "DATETIME NULL",
                "updated_at": "DATETIME NULL",
                "deleted_at": "DATETIME NULL",
            },
            "user_roles": {
                "created_at": "DATETIME NULL",
                "updated_at": "DATETIME NULL",
                "deleted_at": "DATETIME NULL",
            },
        }
        for table_name, columns in table_columns.items():
            for column_name, definition in columns.items():
                _add_column_if_missing(conn, table_name, column_name, definition)


def init_database(engine, session_factory) -> None:
    Base.metadata.create_all(bind=engine)
    _ensure_audit_columns(engine)
    with session_factory() as db:
        admin = _upsert_role(
            db,
            "admin",
            "系统管理员",
            scope="all",
            department=None,
            can_view_reconcile=True,
            can_update_reconcile=True,
            can_view_asset_ledger=True,
            can_update_asset_ledger=True,
            can_view_activity_logs=True,
            can_manage_users=True,
        )
        _upsert_role(
            db,
            "finance",
            "财务",
            scope="all",
            department=None,
            can_view_reconcile=True,
            can_update_reconcile=True,
            can_view_asset_ledger=True,
            can_update_asset_ledger=True,
        )
        _upsert_role(
            db,
            "inventory",
            "盘点",
            scope="all",
            department=None,
            can_view_asset_ledger=True,
            can_update_asset_ledger=True,
        )
        for role_name, display_name, department in DEPARTMENT_ROLES:
            _upsert_role(
                db,
                role_name,
                f"{display_name}部门",
                scope="department",
                department=department,
                can_view_asset_ledger=True,
                can_update_asset_ledger=True,
            )

        root = db.query(User).filter(User.email == "root@boyuanpharm.com").one_or_none()
        if root is None:
            root = User(
                email="root@boyuanpharm.com",
                username="root",
                display_name="Root Admin",
                password_hash=hash_password("123123"),
                is_active=True,
                password_set_at=utcnow(),
                last_activity_at=utcnow(),
                roles=[admin],
            )
            db.add(root)
        elif admin not in root.roles:
            root.roles.append(admin)
        if root.deleted_at is not None:
            root.deleted_at = None
            root.is_active = True
        db.commit()
