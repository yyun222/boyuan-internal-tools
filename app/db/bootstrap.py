"""Schema compatibility checks and initial role/user seed data."""

from sqlalchemy import text

from app.auth import hash_password, utcnow
from app.config import settings
from app.db.models import Base, Role, User

DEPARTMENT_ROLES = [
    ("dept01", "工程部", "工程部"), ("dept02", "行政后勤", "行政后勤"),
    ("dept03", "仓储部", "仓储部"), ("dept04", "销售部", "销售部"),
    ("dept05", "生产部", "生产部"), ("dept06", "质量部", "质量部"),
    ("dept07", "EHS", "EHS"), ("dept08", "济阳厂区", "济阳厂区"),
    ("dept09", "采购部", "采购部"), ("dept10", "建筑路墙", "建筑路墙"),
    ("dept12", "公共区", "公共区"), ("dept13", "动力车间", "动力车间"),
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
    return {row["Field"] for row in conn.execute(text(f"SHOW COLUMNS FROM `{table_name}`")).mappings()}


def _mysql_primary_key_columns(conn, table_name: str) -> list[str]:
    return [row["Column_name"] for row in conn.execute(text(f"SHOW KEYS FROM `{table_name}` WHERE Key_name = 'PRIMARY'")).mappings()]


def _mysql_index_names(conn, table_name: str) -> set[str]:
    return {row["Key_name"] for row in conn.execute(text(f"SHOW INDEX FROM `{table_name}`")).mappings()}


def _add_column_if_missing(conn, table_name: str, column_name: str, definition: str) -> None:
    if column_name not in _mysql_columns(conn, table_name):
        conn.execute(text(f"ALTER TABLE `{table_name}` ADD COLUMN `{column_name}` {definition}"))


def _ensure_legacy_columns(engine) -> None:
    if engine.dialect.name != "mysql":
        return
    with engine.begin() as conn:
        if "id" not in _mysql_columns(conn, "user_roles"):
            if _mysql_primary_key_columns(conn, "user_roles"):
                indexes = _mysql_index_names(conn, "user_roles")
                if "ix_user_roles_user_id" not in indexes:
                    conn.execute(text("ALTER TABLE `user_roles` ADD INDEX `ix_user_roles_user_id` (`user_id`)"))
                if "ix_user_roles_role_id" not in indexes:
                    conn.execute(text("ALTER TABLE `user_roles` ADD INDEX `ix_user_roles_role_id` (`role_id`)"))
                conn.execute(text("ALTER TABLE `user_roles` DROP PRIMARY KEY"))
            conn.execute(text("ALTER TABLE `user_roles` ADD COLUMN `id` INT NOT NULL AUTO_INCREMENT PRIMARY KEY FIRST"))
        if "uq_user_roles_user_id_role_id" not in _mysql_index_names(conn, "user_roles"):
            conn.execute(text("ALTER TABLE `user_roles` ADD UNIQUE KEY `uq_user_roles_user_id_role_id` (`user_id`, `role_id`)"))
        columns = {
            "users": {"deleted_at": "DATETIME NULL"},
            "roles": {"updated_at": "DATETIME NULL", "deleted_at": "DATETIME NULL", "can_view_stock_orders": "BOOLEAN NOT NULL DEFAULT TRUE", "can_update_stock_orders": "BOOLEAN NOT NULL DEFAULT TRUE"},
            "activity_logs": {"created_at": "DATETIME NULL", "updated_at": "DATETIME NULL", "deleted_at": "DATETIME NULL"},
            "user_roles": {"created_at": "DATETIME NULL", "updated_at": "DATETIME NULL", "deleted_at": "DATETIME NULL"},
            "stock_orders": {
                "delivery_items": "TEXT NOT NULL",
                "purchase_arrival_items": "TEXT NOT NULL",
                "production_expected_items": "TEXT NOT NULL",
                "production_actual_items": "TEXT NOT NULL",
                "qc_expected_items": "TEXT NOT NULL",
                "qc_actual_items": "TEXT NOT NULL",
                "sales_completed_at": "DATETIME NULL",
                "purchase_responded_at": "DATETIME NULL",
                "production_responded_at": "DATETIME NULL",
                "qc_responded_at": "DATETIME NULL",
                "cancelled_at": "DATETIME NULL",
                "cancelled_reason": "TEXT NOT NULL",
            },
        }
        for table_name, definitions in columns.items():
            for column_name, definition in definitions.items():
                _add_column_if_missing(conn, table_name, column_name, definition)
        stock_columns = _mysql_columns(conn, "stock_orders")
        legacy_delivery_columns = {"delivery_quantity", "delivery_note"} & stock_columns
        if legacy_delivery_columns:
            quantity = "COALESCE(`delivery_quantity`, '')" if "delivery_quantity" in stock_columns else "''"
            note = "COALESCE(`delivery_note`, '')" if "delivery_note" in stock_columns else "''"
            conn.execute(text(
                "UPDATE `stock_orders` SET `delivery_items` = "
                f"JSON_ARRAY(JSON_OBJECT('quantity', {quantity}, 'note', {note})) "
                f"WHERE COALESCE(`delivery_items`, '') = '' AND ({quantity} <> '' OR {note} <> '')"
            ))
            for column_name in sorted(legacy_delivery_columns):
                conn.execute(text(f"ALTER TABLE `stock_orders` DROP COLUMN `{column_name}`"))
        stock_columns = _mysql_columns(conn, "stock_orders")
        legacy_purchase_columns = {"purchase_material", "purchase_quantity"} & stock_columns
        if legacy_purchase_columns:
            material = "COALESCE(`purchase_material`, '')" if "purchase_material" in stock_columns else "''"
            quantity = "COALESCE(`purchase_quantity`, '')" if "purchase_quantity" in stock_columns else "''"
            conn.execute(text(
                "UPDATE `stock_orders` SET `purchase_items` = "
                f"JSON_ARRAY(JSON_OBJECT('arrival_date', COALESCE(`arrival_date`, ''), 'material', {material}, 'quantity', {quantity})) "
                f"WHERE COALESCE(`purchase_items`, '') IN ('', '[]') AND ({material} <> '' OR {quantity} <> '')"
            ))
            for column_name in sorted(legacy_purchase_columns):
                conn.execute(text(f"ALTER TABLE `stock_orders` DROP COLUMN `{column_name}`"))
        if "sales_owner" in _mysql_columns(conn, "stock_orders"):
            conn.execute(text("ALTER TABLE `stock_orders` DROP COLUMN `sales_owner`"))


def init_database(engine, session_factory) -> None:
    Base.metadata.create_all(bind=engine)
    _ensure_legacy_columns(engine)
    with session_factory() as db:
        admin = _upsert_role(db, "admin", "系统管理员", scope="all", department=None, can_view_reconcile=True, can_update_reconcile=True, can_view_asset_ledger=True, can_update_asset_ledger=True, can_view_activity_logs=True, can_manage_users=True)
        _upsert_role(db, "finance", "财务", scope="all", department=None, can_view_reconcile=True, can_update_reconcile=True, can_view_asset_ledger=True, can_update_asset_ledger=True)
        _upsert_role(db, "inventory", "盘点", scope="all", department=None, can_view_asset_ledger=True, can_update_asset_ledger=True)
        for role_name, display_name, department in DEPARTMENT_ROLES:
            _upsert_role(db, role_name, display_name, scope="department", department=department, can_view_asset_ledger=True, can_update_asset_ledger=True)
        for role in db.query(Role).filter(Role.deleted_at.is_(None)).all():
            role.can_view_stock_orders = True
            role.can_update_stock_orders = True
        root = db.query(User).filter(User.email == settings.initial_admin_email).one_or_none()
        if root is None:
            root = User(email=settings.initial_admin_email, username="root", display_name="Root Admin", password_hash=hash_password(settings.initial_admin_password), is_active=True, password_set_at=utcnow(), last_activity_at=utcnow(), roles=[admin])
            db.add(root)
        elif admin not in root.roles:
            root.roles.append(admin)
        if root.deleted_at is not None:
            root.deleted_at = None
            root.is_active = True
        db.commit()
