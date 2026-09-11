"""Regression coverage for the logout control and endpoint."""

from __future__ import annotations

import asyncio
import os
import unittest
from pathlib import Path

os.environ.setdefault("BOYUAN_DATABASE_URL", "sqlite:///:memory:")
os.environ.setdefault("BOYUAN_SESSION_SECRET", "unit-test-secret")

from starlette.requests import Request

from app.main import SessionLocal, api_logout


class LogoutRegressionTests(unittest.TestCase):
    def test_logout_endpoint_clears_session(self) -> None:
        request = Request({
            "type": "http",
            "headers": [],
            "session": {"user_id": 999999, "authenticated_at": "2026-08-05T00:00:00"},
        })
        db = SessionLocal()
        try:
            result = asyncio.run(api_logout(request, db))
        finally:
            db.close()

        self.assertEqual(result, {"ok": True})
        self.assertEqual(dict(request.session), {})

    def test_logout_button_posts_then_redirects(self) -> None:
        static_dir = Path(__file__).parents[1] / "app" / "static"
        html = (static_dir / "index.html").read_text(encoding="utf-8")
        javascript = (static_dir / "app.js").read_text(encoding="utf-8")

        self.assertIn('id="logout-btn"', html)
        self.assertIn('fetch("/api/logout", { method: "POST" })', javascript)
        self.assertIn('sessionStorage.removeItem("boyuan_current_user")', javascript)
        self.assertIn('window.location.replace("/login")', javascript)


if __name__ == "__main__":
    unittest.main()
