"""Regression tests for homepage joke selection and session stability."""

from __future__ import annotations

import asyncio
import os
import unittest
from datetime import date
from unittest.mock import patch

os.environ.setdefault("BOYUAN_DATABASE_URL", "sqlite:///:memory:")
os.environ.setdefault("BOYUAN_SESSION_SECRET", "unit-test-secret")

from starlette.requests import Request

from app.auth import utcnow
from app.db.models import User
from app.main import (
    SessionLocal, _extract_cfun_jokes, _extract_cfun_range, _new_home_jokes, _next_statutory_holiday,
    api_home_jokes,
)


def authenticated_request(user_id: int, jokes: list[str]) -> Request:
    return Request({
        "type": "http",
        "headers": [],
        "session": {
            "user_id": user_id,
            "authenticated_at": utcnow().isoformat(),
            "home_jokes": jokes,
            "home_jokes_version": 2,
        },
    })


class HomeRegressionTests(unittest.TestCase):
    def setUp(self) -> None:
        self.db = SessionLocal()
        self.admin = self.db.query(User).filter_by(email="root@boyuanpharm.com").one()

    def tearDown(self) -> None:
        self.db.rollback()
        self.db.close()

    def test_extracts_jokes_from_cfun_rows(self) -> None:
        payload = {"rows": [
            {"row": {"instruction": "请分析以下文字幽默的原因", "input": "标题：第一条测试笑话", "output": "这个笑话的幽默之处在于……"}},
            {"row": {"instruction": "请生成一个中文笑话", "input": "", "output": "第二条测试笑话"}},
        ]}
        self.assertEqual(_extract_cfun_jokes(payload), ["第一条测试笑话", "第二条测试笑话"])

    def test_extracts_complete_rows_from_raw_json_range(self) -> None:
        chunk = (
            b'partial prefix},\n'
            b'{"instruction":"generate joke","input":"","output":"range joke one"},\n'
            b'{"instruction":"generate joke","input":"","output":"range joke two"},\n'
            b'{"instruction":"incomplete"'
        )
        rows = _extract_cfun_range(chunk)
        self.assertEqual([item["row"]["output"] for item in rows], ["range joke one", "range joke two"])

    def test_home_jokes_remain_stable_in_same_session(self) -> None:
        jokes = [f"会话笑话{index}" for index in range(10)]
        request = authenticated_request(self.admin.id, jokes)

        first = asyncio.run(api_home_jokes(request, self.db))
        second = asyncio.run(api_home_jokes(request, self.db))

        self.assertEqual(first["jokes"], jokes)
        self.assertEqual(second["jokes"], jokes)

    def test_fallback_avoids_previous_login_jokes(self) -> None:
        previous = ["我给闹钟放了一天假，结果第二天我们两个都迟到了。", "医生让我少熬夜，我听进去了，所以改成了通宵。"]
        with patch("app.main._fetch_cfun_jokes", side_effect=RuntimeError("offline")):
            current = asyncio.run(_new_home_jokes(previous))
        self.assertEqual(len(current), 10)
        self.assertTrue(set(current).isdisjoint(previous))

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
