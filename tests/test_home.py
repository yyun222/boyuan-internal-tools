"""Regression tests for homepage content."""

from __future__ import annotations

import asyncio
import os
import unittest
from datetime import date
from unittest.mock import patch

os.environ.setdefault("BOYUAN_DATABASE_URL", "sqlite:///:memory:")
os.environ.setdefault("BOYUAN_SESSION_SECRET", "unit-test-secret")

from app.main import _next_statutory_holiday, api_fun_facts
from app.services.home_facts import FACTS


class HomeRegressionTests(unittest.TestCase):
    def test_local_catalog_contains_458_unique_bilingual_facts(self) -> None:
        self.assertEqual(len(FACTS), 458)
        self.assertTrue(all(fact["english"] and fact["chinese"] and fact["category"] for fact in FACTS))
        self.assertEqual(len({fact["english"] for fact in FACTS}), len(FACTS))
        self.assertEqual(len({fact["chinese"] for fact in FACTS}), len(FACTS))

    def test_fun_facts_remain_bilingual_without_external_services(self) -> None:
        with patch("app.main._require_user"), patch("app.main.urlopen", side_effect=OSError("offline")):
            facts = asyncio.run(api_fun_facts(None, None))["facts"]
        self.assertEqual(len(facts), 10)
        self.assertEqual(len({fact["english"] for fact in facts}), 10)
        self.assertTrue(all(fact["english"] and fact["chinese"] and fact["category"] for fact in facts))

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
