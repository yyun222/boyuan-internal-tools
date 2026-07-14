"""Focused regression tests for stock-order business rules."""

from __future__ import annotations

import os
import unittest
from datetime import datetime, timedelta

os.environ.setdefault("BOYUAN_DATABASE_URL", "sqlite:///:memory:")
os.environ.setdefault("BOYUAN_SESSION_SECRET", "unit-test-secret")

from sqlalchemy import event

from app.auth import utcnow
from app.db.models import Role, StockOrder, StockOrderWarning, User
from app.main import SessionLocal, StockOrderPayload, _save_stock_order, _sync_stock_warnings, engine
from app.services.stock_orders import business_datetime, module_status, sync_order_warnings


class StockOrderRegressionTests(unittest.TestCase):
    def setUp(self) -> None:
        self.db = SessionLocal()
        self.admin = self.db.query(User).filter_by(email="root@boyuanpharm.com").one()

    def tearDown(self) -> None:
        self.db.rollback()
        self.db.close()

    def test_save_is_rollback_safe_until_route_commits(self) -> None:
        order = _save_stock_order(self.db, self.admin, StockOrderPayload(fields={
            "internal_name": "事务测试",
            "order_type": "备货订单",
        }))
        order_id = order.id
        self.db.rollback()
        self.assertIsNone(self.db.get(StockOrder, order_id))

    def test_completed_module_does_not_block_other_module(self) -> None:
        sales = self.db.query(Role).filter_by(name="dept04").one()
        purchase = self.db.query(Role).filter_by(name="dept09").one()
        user = User(
            email="multi-test@boyuanpharm.com", username="multi-test",
            display_name="multi-test", is_active=True, roles=[sales, purchase],
        )
        self.db.add(user)
        self.db.flush()
        order = StockOrder(
            order_no="TEST-CROSS-MODULE", internal_name="产品A",
            order_type="备货订单", sales_completed_at=utcnow(),
            created_by_user_id=user.id,
        )
        self.db.add(order)
        self.db.flush()

        saved = _save_stock_order(self.db, user, StockOrderPayload(fields={
            "internal_name": "产品A",
            "arrival_date": "2026-07-20",
        }), order)
        self.assertEqual(saved.arrival_date, "2026-07-20")

    def test_hold_order_ignores_unchanged_other_module_defaults(self) -> None:
        order = _save_stock_order(self.db, self.admin, StockOrderPayload(fields={
            "order_type": "留货订单",
            "internal_name": "留货产品",
            "purchase_note": "",
            "production_note": "",
            "qc_note": "",
        }))
        self.assertEqual(order.order_type, "留货订单")

    def test_warning_refresh_uses_constant_query_count(self) -> None:
        orders = [
            StockOrder(order_no=f"TEST-WARNING-{index}", sales_completed_at=utcnow() - timedelta(hours=25))
            for index in range(3)
        ]
        self.db.add_all(orders)
        self.db.flush()
        warning_selects = 0

        def count_warning_selects(_conn, _cursor, statement, _parameters, _context, _executemany):
            nonlocal warning_selects
            if statement.lstrip().upper().startswith("SELECT") and "stock_order_warnings" in statement:
                warning_selects += 1

        event.listen(engine, "before_cursor_execute", count_warning_selects)
        try:
            grouped = _sync_stock_warnings(self.db, orders)
        finally:
            event.remove(engine, "before_cursor_execute", count_warning_selects)

        self.assertEqual(warning_selects, 2)
        self.assertTrue(all(len(grouped[order.id]) == 2 for order in orders))
        self.assertEqual(self.db.query(StockOrderWarning).count(), 6)

    def test_business_timestamps_are_serialized_as_beijing_time(self) -> None:
        self.assertEqual(business_datetime(datetime(2026, 7, 13, 20, 30)), "2026-07-14T04:30:00")

    def test_module_status_distinguishes_unfilled_in_progress_and_complete(self) -> None:
        order = StockOrder(order_no="TEST-THREE-STATES")
        self.assertEqual(module_status(order, "purchase"), "未填写")
        order.purchase_note = "已开始填写"
        self.assertEqual(module_status(order, "purchase"), "进行中")
        order.purchase_completed_at = utcnow()
        self.assertEqual(module_status(order, "purchase"), "已完成")

    def test_late_actual_delivery_creates_sales_warning(self) -> None:
        order = StockOrder(
            order_no="TEST-LATE-DELIVERY", order_type="备货订单",
            delivery_requirement="2026-07-10", actual_delivery="2026-07-11",
        )
        self.db.add(order)
        self.db.flush()
        sync_order_warnings(self.db, order, existing_types=set())
        self.db.flush()
        warning = self.db.query(StockOrderWarning).filter_by(order_id=order.id, warning_type="sales_delivery_late").one()
        self.assertEqual(warning.department, "销售部")


if __name__ == "__main__":
    unittest.main()
