"""Regression coverage for username-only invitations and credential resets."""

import asyncio
import os
import unittest

os.environ.setdefault("BOYUAN_DATABASE_URL", "sqlite:///:memory:")

from fastapi import HTTPException
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from starlette.requests import Request

from app.auth import CAFETERIA_DEFAULT_PASSWORD, utcnow
from app.cafeteria import StaffInvitation
from app.config import settings
from app.db import init_database
from app.db.models import Role, User
from app.main import (
    CafeteriaPasswordPayload, InvitePayload, LoginPayload, _require_user, api_cafeteria_password,
    api_invite, api_login, api_me, api_reset_user_password, api_users, app,
)


class CafeteriaPasswordTests(unittest.TestCase):
    def setUp(self):
        engine = create_engine("sqlite:///:memory:")
        self.addCleanup(engine.dispose)
        sessions = sessionmaker(bind=engine)
        init_database(engine, sessions)
        self.db = sessions()
        self.addCleanup(self.db.close)
        supervisor = User(email="supervisor@boyuanpharm.com", display_name="Supervisor",
                          roles=[self.db.query(Role).filter_by(name="cafeteria_jiyang_supervisor").one()])
        self.db.add(supervisor)
        self.db.commit()
        admin = self.db.query(User).filter_by(email=settings.initial_admin_email).one()
        self.admin = self.request(admin.id)
        self.supervisor = self.request(supervisor.id)
        self.invite = next(route.endpoint for route in app.routes
                           if getattr(route, "path", None) == "/api/cafeteria/{site}/invitations")

    @staticmethod
    def request(user_id=None):
        session = {"user_id": user_id, "authenticated_at": utcnow().isoformat()} if user_id else {}
        return Request({"type": "http", "headers": [], "session": session})

    def assert_http(self, status, call, *args):
        with self.assertRaises(HTTPException) as error:
            call(*args)
        self.assertEqual(error.exception.status_code, status)

    def login(self, username, password, request):
        return asyncio.run(api_login(LoginPayload(username=username, password=password), request, self.db))

    def test_username_password_setup_and_reset_invalidate_earlier_sessions(self):
        invitation = StaffInvitation(username="Kitchen_01", roles=["cafeteria_jiyang_kitchen"])
        result = self.invite("jiyang", invitation, self.supervisor, self.db)
        self.assertEqual(result["username"], "kitchen_01")
        self.assert_http(409, self.invite, "jiyang", invitation, self.supervisor, self.db)
        account = self.db.query(User).filter_by(username="kitchen_01").one()
        self.assertIsNone(account.email)
        self.assertIn(account.id, {row["id"] for row in asyncio.run(api_users(self.admin, self.db))["users"]})

        first = self.request()
        another = self.request()
        self.assertTrue(self.login("Kitchen_01", CAFETERIA_DEFAULT_PASSWORD, first)["user"]["mustSetPassword"])
        self.login("kitchen_01", CAFETERIA_DEFAULT_PASSWORD, another)
        self.assert_http(403, _require_user, first, self.db)
        self.assert_http(400, lambda: asyncio.run(api_cafeteria_password(
            CafeteriaPasswordPayload(password=CAFETERIA_DEFAULT_PASSWORD), first, self.db)))

        personal = "my-private-password"
        result = asyncio.run(api_cafeteria_password(CafeteriaPasswordPayload(password=personal), first, self.db))
        self.assertFalse(result["user"]["mustSetPassword"])
        self.assertEqual(_require_user(first, self.db).id, account.id)
        self.assert_http(401, _require_user, another, self.db)
        self.assert_http(401, self.login, "kitchen_01", CAFETERIA_DEFAULT_PASSWORD, self.request())

        self.assert_http(403, lambda: asyncio.run(api_reset_user_password(account.id, self.supervisor, self.db)))
        result = asyncio.run(api_reset_user_password(account.id, self.admin, self.db))
        self.assertTrue(result["mustSetPassword"])
        self.assert_http(401, lambda: asyncio.run(api_me(first, self.db)))
        self.assert_http(401, self.login, "kitchen_01", personal, self.request())
        self.assertTrue(self.login("kitchen_01", CAFETERIA_DEFAULT_PASSWORD, self.request())["user"]["mustSetPassword"])

    def test_username_invitation_requires_cafeteria_scope(self):
        self.assert_http(400, lambda: asyncio.run(api_invite(
            InvitePayload(email="no-company-email", roles=["cafeteria_jiyang_kitchen"]), self.admin, self.db)))
        self.assert_http(403, self.invite, "yucheng",
                         StaffInvitation(username="kitchen_02", roles=["cafeteria_yucheng_kitchen"]),
                         self.supervisor, self.db)
        self.assert_http(400, self.invite, "jiyang",
                         StaffInvitation(username="kitchen_02", roles=["admin"]), self.supervisor, self.db)

    def test_username_invitations_reject_non_ascii_and_punctuation(self):
        for username in ("厨房01", "kitchen.01", "kitchen-01", " kitchen01", "kitchen 01"):
            with self.subTest(username=username):
                self.assert_http(400, self.invite, "jiyang",
                                 StaffInvitation(username=username, roles=["cafeteria_jiyang_kitchen"]),
                                 self.supervisor, self.db)
