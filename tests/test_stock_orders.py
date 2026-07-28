"""Focused regression tests for stock-order business rules."""

from __future__ import annotations

import os
import json
import unittest
from datetime import datetime, timedelta

os.environ.setdefault("BOYUAN_DATABASE_URL", "sqlite:///:memory:")
os.environ.setdefault("BOYUAN_SESSION_SECRET", "unit-test-secret")

from sqlalchemy import event

from app.auth import utcnow
from app.db.models import Role, StockOrder, StockOrderWarning, User
from app.main import SessionLocal, StockOrderPayload, _save_stock_order, _stock_month_range, _sync_stock_warnings, _validate_stock_completion_quantities, engine
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
            "order_type": "现货留货",
            "internal_name": "留货产品",
            "purchase_note": "",
            "production_note": "",
            "qc_note": "",
        }))
        self.assertEqual(order.order_type, "现货留货")

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

    def test_stock_month_range_uses_complete_beijing_month(self) -> None:
        start, end = _stock_month_range("2026-07")
        self.assertEqual(start, datetime(2026, 6, 30, 16))
        self.assertEqual(end, datetime(2026, 7, 31, 16))

    def test_module_status_distinguishes_unfilled_in_progress_and_complete(self) -> None:
        order = StockOrder(order_no="TEST-THREE-STATES")
        self.assertEqual(module_status(order, "purchase"), "未填写")
        order.purchase_note = "已开始填写"
        self.assertEqual(module_status(order, "purchase"), "进行中")
        order.purchase_completed_at = utcnow()
        self.assertEqual(module_status(order, "purchase"), "已完成")

    def test_sales_completion_requires_matching_delivery_total(self) -> None:
        order = StockOrder(
            order_no="TEST-COMPLETE-SALES", internal_name="产品A", quantity="1 kg",
            order_type="备货订单", created_by_user_id=self.admin.id,
        )
        self.db.add(order)
        self.db.flush()

        saved = _save_stock_order(self.db, self.admin, StockOrderPayload(fields={
            "delivery_items": '[{"date":"2026-07-20","quantity":"1000 g","note":"一次性交付"}]',
        }), order)

        self.assertEqual(saved.actual_delivery, "2026-07-20")
        self.assertIsNone(saved.sales_completed_at)
        _validate_stock_completion_quantities(saved, "sales")

        saved.delivery_items = '[{"quantity":"999 g","note":"数量不足"}]'
        with self.assertRaisesRegex(Exception, "总数量"):
            _validate_stock_completion_quantities(saved, "sales")

    def test_delivery_fields_must_be_all_filled_or_all_empty(self) -> None:
        order = StockOrder(order_no="TEST-DELIVERY-VALIDATION", order_type="备货订单")
        self.db.add(order)
        self.db.flush()

        with self.assertRaisesRegex(Exception, "必须填写"):
            _save_stock_order(self.db, self.admin, StockOrderPayload(fields={
                "delivery_items": '[{"date":"2026-07-20","quantity":"10 kg","note":""}]',
            }), order)

    def test_latest_delivery_item_date_becomes_actual_delivery(self) -> None:
        order = StockOrder(
            order_no="TEST-LATEST-DELIVERY", order_type="备货订单",
            delivery_requirement="2026-07-21",
        )
        self.db.add(order)
        self.db.flush()

        saved = _save_stock_order(self.db, self.admin, StockOrderPayload(fields={
            "delivery_items": '[{"date":"2026-07-22","quantity":"1 kg","note":"第二批"},{"date":"2026-07-20","quantity":"1 kg","note":"第一批"}]',
        }), order)

        self.assertEqual(saved.actual_delivery, "2026-07-22")
        delivery_items = json.loads(saved.delivery_items)
        self.assertEqual([item["id"] for item in delivery_items], [1, 2])
        warning = self.db.query(StockOrderWarning).filter_by(
            order_id=saved.id, warning_type="sales_delivery_late"
        ).one()
        self.assertIn("2026-07-22", warning.detail)

    def test_received_purchase_item_cannot_be_modified_or_deleted(self) -> None:
        order = StockOrder(
            order_no="TEST-RECEIVED-LOCK", order_type="备货订单",
            purchase_items='[{"id":1,"arrival_date":"2026-07-20","material":"原料A","quantity":"10 kg","received":true}]',
        )
        self.db.add(order)
        self.db.flush()

        with self.assertRaisesRegex(Exception, "不能修改或删除"):
            _save_stock_order(self.db, self.admin, StockOrderPayload(fields={
                "purchase_items": '[]',
            }), order)

    def test_purchase_completion_requires_received_date_and_all_items_received(self) -> None:
        order = StockOrder(order_no="TEST-PURCHASE-COMPLETE", order_type="备货订单")
        with self.assertRaisesRegex(Exception, "实际全部到货时间"):
            _validate_stock_completion_quantities(order, "purchase")
        order.purchase_received_at = "2026-07-21"
        order.purchase_items = '[{"id":1,"arrival_date":"2026-07-20","material":"原料A","quantity":"1 kg","received":false}]'
        with self.assertRaisesRegex(Exception, "均已勾选已到货"):
            _validate_stock_completion_quantities(order, "purchase")
        order.purchase_items = '[{"id":1,"arrival_date":"2026-07-20","material":"原料A","quantity":"1 kg","received":true}]'
        _validate_stock_completion_quantities(order, "purchase")

    def test_purchase_items_require_expected_arrival_date(self) -> None:
        order = StockOrder(order_no="TEST-PURCHASE-ITEM-VALIDATION", order_type="备货订单")
        self.db.add(order)
        self.db.flush()

        with self.assertRaisesRegex(Exception, "预计到货时间"):
            _save_stock_order(self.db, self.admin, StockOrderPayload(fields={
                "purchase_items": '[{"arrival_date":"","material":"原料A","quantity":"10 kg"}]',
            }), order)

    def test_production_items_require_complete_rows(self) -> None:
        order = StockOrder(order_no="TEST-PRODUCTION-ITEM-VALIDATION", order_type="备货订单")
        self.db.add(order)
        self.db.flush()

        with self.assertRaisesRegex(Exception, "生产数量和备注"):
            _save_stock_order(self.db, self.admin, StockOrderPayload(fields={
                "production_actual_items": '[{"date":"2026-07-20","quantity":"10 kg","note":""}]',
            }), order)

    def test_item_ids_are_persisted_and_sorted(self) -> None:
        order = StockOrder(order_no="TEST-ITEM-IDS", order_type="备货订单")
        self.db.add(order)
        self.db.flush()

        saved = _save_stock_order(self.db, self.admin, StockOrderPayload(fields={
            "production_expected_items": '[{"id":2,"date":"2026-07-21","quantity":"2 kg","note":"二"},{"id":1,"date":"2026-07-20","quantity":"1 kg","note":"一"}]',
            "production_actual_items": '[{"date":"2026-07-20","quantity":"1 kg","note":"一"},{"date":"2026-07-21","quantity":"2 kg","note":"二"}]',
        }), order)

        self.assertEqual([item["id"] for item in json.loads(saved.production_expected_items)], [1, 2])
        self.assertEqual([item["id"] for item in json.loads(saved.production_actual_items)], [1, 2])

    def test_qc_items_require_complete_rows(self) -> None:
        order = StockOrder(order_no="TEST-QC-ITEM-VALIDATION", order_type="备货订单")
        self.db.add(order)
        self.db.flush()

        with self.assertRaisesRegex(Exception, "日期和备注"):
            _save_stock_order(self.db, self.admin, StockOrderPayload(fields={
                "qc_expected_items": '[{"date":"2026-07-20","note":""}]',
            }), order)

    def test_qc_items_do_not_require_quantity(self) -> None:
        order = StockOrder(order_no="TEST-QC-NO-QUANTITY", order_type="备货订单")
        self.db.add(order)
        self.db.flush()

        saved = _save_stock_order(self.db, self.admin, StockOrderPayload(fields={
            "qc_expected_items": '[{"date":"2026-07-20","note":"预计检测"}]',
            "qc_actual_items": '[{"date":"2026-07-21","note":"检测完成"}]',
        }), order)

        _validate_stock_completion_quantities(saved, "qc")

    def test_qc_completion_only_requires_matching_item_counts(self) -> None:
        order = StockOrder(
            order_no="TEST-QC-ITEM-COUNT", order_type="备货订单",
            qc_expected_items='[{"date":"2026-07-20","note":"一"},{"date":"2026-07-21","note":"二"}]',
            qc_actual_items='[{"date":"2026-07-22","note":"完成"}]',
        )

        with self.assertRaisesRegex(Exception, "明细条数"):
            _validate_stock_completion_quantities(order, "qc")

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

    def test_schedule_warning_compares_item_dates_not_confirmation_time(self) -> None:
        order = StockOrder(
            order_no="TEST-ITEM-DATE-WARNING", order_type="备货订单",
            production_expected_items='[{"date":"2026-07-20","quantity":"1 kg","note":"预计"}]',
            production_actual_items='[{"date":"2026-07-21","quantity":"1 kg","note":"实际"}]',
            production_completed_at=datetime(2026, 7, 19),
        )
        self.db.add(order)
        self.db.flush()

        sync_order_warnings(self.db, order, now=datetime(2026, 7, 21), existing_types=set())
        self.db.flush()

        warning = self.db.query(StockOrderWarning).filter_by(
            order_id=order.id, warning_type="production_schedule_overdue"
        ).one()
        self.assertIn("第1项", warning.detail)
        self.assertIn("实际 2026-07-21", warning.detail)

    def test_purchase_warning_compares_received_date_to_latest_expected_item(self) -> None:
        order = StockOrder(
            order_no="TEST-PURCHASE-DATE-WARNING", order_type="备货订单",
            purchase_items='[{"arrival_date":"2026-07-20","material":"A","quantity":"1 kg"},{"arrival_date":"2026-07-22","material":"B","quantity":"1 kg"}]',
            purchase_received_at="2026-07-23",
        )
        self.db.add(order)
        self.db.flush()
        sync_order_warnings(self.db, order, now=datetime(2026, 7, 23), existing_types=set())
        self.db.flush()
        warning = self.db.query(StockOrderWarning).filter_by(
            order_id=order.id, warning_type="purchase_schedule_overdue"
        ).one()
        self.assertIn("最晚预计：2026-07-22", warning.detail)
        self.assertIn("实际全部到货：2026-07-23", warning.detail)


if __name__ == "__main__":
    unittest.main()
