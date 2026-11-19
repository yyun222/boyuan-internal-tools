"""Regression coverage for site-scoped cafeteria permissions."""

import asyncio
import os
import unittest

os.environ.setdefault("BOYUAN_DATABASE_URL", "sqlite:///:memory:")

from fastapi import HTTPException
from starlette.requests import Request

from app.auth import utcnow
from app.db.models import Role, User
from app.main import SessionLocal, _user_payload, app, page_index


class CafeteriaAccessTests(unittest.TestCase):
    def setUp(self):
        self.db = SessionLocal()
        self.addCleanup(self.db.close)
        self.addCleanup(self.db.rollback)

    def user(self, name, *roles):
        user = User(email=f"{name}@boyuanpharm.com", display_name=name,
                    roles=self.db.query(Role).filter(Role.name.in_(roles)).all())
        self.db.add(user)
        self.db.flush()
        return user

    def request(self, user):
        return Request({
            "type": "http",
            "headers": [],
            "session": {"user_id": user.id, "authenticated_at": utcnow().isoformat()},
        })

    def endpoint(self, path, method):
        return next(route.endpoint for route in app.routes
                    if getattr(route, "path", None) == path and method in route.methods)

    def test_cafeteria_only_user_can_open_home(self):
        user = self.user("cafeteria-only", "cafeteria_jiyang_store")
        permissions = _user_payload(user)["permissions"]
        self.assertTrue(permissions["viewCafeteria"])
        self.assertFalse(permissions["viewStockOrders"])
        response = asyncio.run(page_index(self.request(user), self.db))
        self.assertEqual(response.status_code, 200)

    def test_staff_listing_requires_supervisor_for_the_selected_site(self):
        supervisor = self.user("cafeteria-supervisor", "cafeteria_jiyang_supervisor")
        included = self.user("cafeteria-local", "cafeteria_jiyang_store", "dept09")
        excluded = self.user("cafeteria-other", "cafeteria_yucheng_store")
        endpoint = self.endpoint("/api/cafeteria/{site}/staff", "GET")
        users = {user["id"]: user for user in endpoint("jiyang", self.request(supervisor), self.db)["users"]}
        self.assertEqual(users[included.id]["roles"], ["cafeteria_jiyang_store"])
        self.assertNotIn(excluded.id, users)
        with self.assertRaises(HTTPException) as error:
            endpoint("yucheng", self.request(supervisor), self.db)
        self.assertEqual(error.exception.status_code, 403)
