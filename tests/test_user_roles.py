"""Regression tests for administrator-managed user roles."""

from __future__ import annotations

import asyncio
import os
import unittest

os.environ.setdefault("BOYUAN_DATABASE_URL", "sqlite:///:memory:")
os.environ.setdefault("BOYUAN_SESSION_SECRET", "unit-test-secret")

from fastapi import HTTPException
from starlette.requests import Request

from app.auth import utcnow
from app.db.models import Role, User
from app.main import SessionLocal, UserRolesPayload, api_update_user_roles


def authenticated_request(user_id: int) -> Request:
    return Request({
        "type": "http",
        "headers": [],
        "session": {"user_id": user_id, "authenticated_at": utcnow().isoformat()},
    })


class UserRoleUpdateTests(unittest.TestCase):
    def setUp(self) -> None:
        self.db = SessionLocal()
        self.root = self.db.query(User).filter_by(email="root@boyuanpharm.com").one()
        self.sales = self.db.query(Role).filter_by(name="dept04").one()
        self.purchase = self.db.query(Role).filter_by(name="dept09").one()

    def tearDown(self) -> None:
        self.db.rollback()
        self.db.close()

    def test_admin_can_replace_user_roles(self) -> None:
        user = User(
            email="role-target@boyuanpharm.com", username="role-target",
            display_name="Role Target", is_active=True, roles=[self.sales],
        )
        self.db.add(user)
        self.db.commit()

        result = asyncio.run(api_update_user_roles(
            user.id,
            UserRolesPayload(roles=["dept09"]),
            authenticated_request(self.root.id),
            self.db,
        ))
        self.assertTrue(result["ok"])
        self.assertEqual(result["roles"], ["dept09"])
        self.assertEqual({role.name for role in user.roles}, {"dept09"})

    def test_admin_cannot_remove_own_manage_users_permission(self) -> None:
        admin_role = self.db.query(Role).filter_by(name="admin").one()
        user = User(
            email="role-admin@boyuanpharm.com", username="role-admin",
            display_name="Role Admin", is_active=True, roles=[admin_role],
        )
        self.db.add(user)
        self.db.commit()

        with self.assertRaises(HTTPException) as raised:
            asyncio.run(api_update_user_roles(
                user.id,
                UserRolesPayload(roles=["dept04"]),
                authenticated_request(user.id),
                self.db,
            ))
        self.assertEqual(raised.exception.status_code, 400)


if __name__ == "__main__":
    unittest.main()
