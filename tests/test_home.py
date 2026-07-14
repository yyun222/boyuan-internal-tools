"""Regression tests for homepage calendar information."""

from __future__ import annotations

import os
import unittest
from datetime import date

os.environ.setdefault("BOYUAN_DATABASE_URL", "sqlite:///:memory:")
os.environ.setdefault("BOYUAN_SESSION_SECRET", "unit-test-secret")

from app.main import _next_statutory_holiday


class HomeRegressionTests(unittest.TestCase):
    def test_next_statutory_holiday_uses_beijing_calendar_date(self) -> None:
        rows = [{"date": "2026-09-25", "name": "中秋节", "isOffDay": True}]
        holiday = _next_statutory_holiday(date(2026, 7, 14), rows)
        self.assertEqual(holiday, {"name": "中秋节", "date": "2026-09-25", "days": 73})

    def test_holiday_countdown_is_zero_during_holiday(self) -> None:
        rows = [{"date": "2026-10-03", "name": "国庆节", "isOffDay": True}]
        holiday = _next_statutory_holiday(date(2026, 10, 3), rows)
        self.assertEqual(holiday, {"name": "国庆节", "date": "2026-10-03", "days": 0})


if __name__ == "__main__":
    unittest.main()
