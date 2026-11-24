"""OA authentication and administrator phone binding integration tests."""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import os
import re
import secrets
import shutil
import subprocess
import tempfile
import time
import unittest
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from pathlib import Path
from unittest.mock import MagicMock, patch

os.environ.setdefault("BOYUAN_DATABASE_URL", "sqlite:///:memory:")
os.environ.setdefault("BOYUAN_SESSION_SECRET", "unit-test-secret")

from fastapi.testclient import TestClient
from sqlalchemy import create_engine, inspect
from sqlalchemy.orm import sessionmaker

from app.auth import hash_password, utcnow
from app.config import settings
from app.db import get_db
from app.db.bootstrap import init_database
from app.db.models import ActivityLog, Base, OaSsoCredential, Role, User
from app.main import app
from app.services.oa_sso import OaSsoError, verify_oa_query

SECRET = "test-only-oa-key-0123456789abcdef0123456789"
CONFIG = replace(settings, oa_sso_enabled=True, oa_sso_secret=SECRET)
PHONE = "13800138000"


def signed_query(**changes) -> str:
    now = int(time.time())
    data = {"v": 1, "phone": PHONE, "iat": now, "exp": now + 60,
            "nonce": secrets.token_hex(16), "aud": CONFIG.oa_sso_audience}
    data.update(changes)
    payload = base64.urlsafe_b64encode(json.dumps(data, separators=(",", ":")).encode()).decode().rstrip("=")
    signature = base64.urlsafe_b64encode(hmac.digest(SECRET.encode(), payload.encode(), "sha256")).decode().rstrip("=")
    return f"payload={payload}&signature={signature}"


class OaSignatureTests(unittest.TestCase):
    def test_signed_fields_and_time_constraints(self):
        now = int(time.time())
        for change in ({"v": True}, {"v": 2}, {"aud": "other-system"}, {"phone": " 13800138000"},
                       {"nonce": "short"}, {"iat": True}, {"exp": "123"}, {"iat": now + 31},
                       {"iat": now, "exp": now + 61}, {"exp": now}, {"iat": -1}, {"exp": now - 10}):
            with self.subTest(change=change), self.assertRaises(OaSsoError):
                verify_oa_query(signed_query(**change).encode(), CONFIG, now=now)
        self.assertEqual(verify_oa_query(signed_query().encode(), CONFIG).phone, PHONE)
        self.assertEqual(verify_oa_query(signed_query(next="/?view=stock-orders&stockOrder=123&stockOrderMode=edit").encode(), CONFIG).next_path,
                         "/?view=stock-orders&stockOrder=123&stockOrderMode=edit")
        for next_path in ("https://example.com", "//example.com", "/?view=stock-orders&stockOrder=0&stockOrderMode=edit",
                          "/?view=stock-orders&stockOrder=12&stockOrderMode=view"):
            with self.subTest(next_path=next_path), self.assertRaises(OaSsoError):
                verify_oa_query(signed_query(next=next_path).encode(), CONFIG)

    def test_configuration_and_malformed_query(self):
        query = signed_query().encode()
        for config in (replace(CONFIG, oa_sso_enabled=False), replace(CONFIG, oa_sso_secret="short"),
                       replace(CONFIG, oa_sso_audience=""), replace(CONFIG, oa_sso_max_age_seconds=0)):
            with self.assertRaises(OaSsoError):
                verify_oa_query(query, config)
        for value in (b"", b"payload=x&signature=x", query + b"&payload=x", query + b"&extra=x",
                      query.replace(b"signature=", b"signature=bad"), b"x=" + b"a" * 5000, b"\xff"):
            with self.subTest(value=value[:30]), self.assertRaises(OaSsoError):
                verify_oa_query(value, CONFIG)

    @unittest.skipUnless(shutil.which("javac") and shutil.which("java"), "JDK not installed")
    def test_java_jsp_signature_matches_python(self):
        jsp = (Path(__file__).parents[1] / "integrations/oa/OA点击打开内部工具.jsp").read_text(encoding="utf-8")
        declarations = re.search(r"<%!([\s\S]*?)%>", jsp).group(1)
        now = int(time.time())
        java = "public class OaVector {" + declarations + '''
            public static void main(String[] args) throws Exception {
                String next = args.length > 5 ? args[5] : null;
                System.out.print(boyuanSignedQuery(args[0], args[1], args[2], Long.parseLong(args[3]), 60, args[4], next));
            }
        }'''
        with tempfile.TemporaryDirectory() as folder:
            source = Path(folder) / "OaVector.java"
            source.write_text(java, encoding="utf-8")
            subprocess.run(["javac", "-source", "1.7", "-target", "1.7", "-encoding", "UTF-8", str(source)], check=True, capture_output=True)
            result = subprocess.run(["java", "-cp", folder, "OaVector", PHONE, SECRET, CONFIG.oa_sso_audience,
                                     str(now), "0" * 32], check=True, capture_output=True)
            credential = verify_oa_query(result.stdout, CONFIG, now=now)
            self.assertEqual(credential.phone, PHONE)
            self.assertEqual(credential.nonce_hash, hashlib.sha256(b"0" * 32).hexdigest())
            destination = "/?view=stock-orders&stockOrder=123&stockOrderMode=edit"
            deep_link_result = subprocess.run(
                ["java", "-cp", folder, "OaVector", PHONE, SECRET, CONFIG.oa_sso_audience,
                 str(now), "1" * 32, destination], check=True, capture_output=True,
            )
            deep_link = verify_oa_query(deep_link_result.stdout, CONFIG, now=now)
            self.assertEqual(deep_link.next_path, destination)


class OaManualMigrationTests(unittest.TestCase):
    def test_missing_mysql_structure_fails_before_automatic_ddl(self):
        for missing in ("users", "phone", "unique", "consumption", "nonce-primary-key"):
            with self.subTest(missing=missing):
                schema = MagicMock()
                schema.has_table.side_effect = lambda name: name != ({"users": "users", "consumption": "oa_sso_credentials"}.get(missing))
                schema.get_columns.side_effect = lambda name: (
                    [] if name == "users" and missing == "phone" else
                    [{"name": "oa_login_phone"}] if name == "users" else
                    [{"name": value} for value in ("nonce_hash", "expires_at", "consumed_at")]
                )
                schema.get_unique_constraints.return_value = [] if missing == "unique" else [{"column_names": ["oa_login_phone"]}]
                schema.get_pk_constraint.return_value = {"constrained_columns": [] if missing == "nonce-primary-key" else ["nonce_hash"]}
                mysql = MagicMock()
                mysql.dialect.name = "mysql"
                with patch("app.db.bootstrap.inspect", return_value=schema), patch.object(Base.metadata, "create_all") as create:
                    with self.assertRaisesRegex(RuntimeError, "手工执行"):
                        init_database(mysql, MagicMock())
                    create.assert_not_called()

    def test_complete_mysql_structure_passes_preflight(self):
        schema = MagicMock()
        schema.has_table.return_value = True
        schema.get_columns.side_effect = lambda name: [{"name": "oa_login_phone"}] if name == "users" else [
            {"name": name} for name in ("nonce_hash", "expires_at", "consumed_at")
        ]
        schema.get_unique_constraints.return_value = [{"column_names": ["oa_login_phone"]}]
        schema.get_pk_constraint.return_value = {"constrained_columns": ["nonce_hash"]}
        mysql = MagicMock()
        mysql.dialect.name = "mysql"
        with patch("app.db.bootstrap.inspect", return_value=schema), patch.object(Base.metadata, "create_all") as create, patch("app.db.bootstrap._ensure_legacy_columns"):
            init_database(mysql, MagicMock())
            create.assert_called_once_with(bind=mysql)


class OaEndpointTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.engine = create_engine("sqlite:///" + str(Path(self.temp.name) / "oa.db"), connect_args={"check_same_thread": False})
        Base.metadata.create_all(self.engine)
        self.sessions = sessionmaker(self.engine)
        with self.sessions() as db:
            admin_role = Role(name="admin", display_name="管理员", can_manage_users=True, can_view_stock_orders=True)
            member_role = Role(name="member", display_name="成员", can_view_stock_orders=True)
            self.password = "test-password"
            password_hash = hash_password(self.password)
            admin = User(email="oa-admin@boyuanpharm.com", username="oa-admin", display_name="Admin",
                         password_hash=password_hash, password_set_at=utcnow(), roles=[admin_role])
            user = User(email="oa-member@boyuanpharm.com", username="oa-member", display_name="Member",
                        password_hash=password_hash, password_set_at=utcnow(), oa_login_phone=PHONE, roles=[member_role])
            db.add_all([admin, user])
            db.commit()
            self.admin_id, self.user_id = admin.id, user.id

        def database():
            with self.sessions() as db:
                yield db

        self.previous_overrides = app.dependency_overrides.copy()
        app.dependency_overrides[get_db] = database
        self.settings_patch = patch("app.main.settings", CONFIG)
        self.settings_patch.start()
        self.client = TestClient(app, follow_redirects=False)

    def tearDown(self):
        self.client.close()
        self.settings_patch.stop()
        app.dependency_overrides.clear()
        app.dependency_overrides.update(self.previous_overrides)
        self.engine.dispose()
        self.temp.cleanup()

    def login_admin(self):
        response = self.client.post("/api/login", json={"username": "oa-admin", "password": self.password})
        self.assertEqual(response.status_code, 200)

    def test_login_switches_account_and_records_log_without_credentials(self):
        self.login_admin()
        response = self.client.get("/auth/oa?" + signed_query())
        self.assertEqual(response.status_code, 303)
        self.assertEqual(response.headers["location"], "/auth/oa/complete")
        self.assertIn("no-store", response.headers["cache-control"])
        self.assertEqual(response.headers["referrer-policy"], "no-referrer")
        complete = self.client.get(response.headers["location"])
        self.assertIn('sessionStorage.removeItem("boyuan_current_user")', complete.text)
        self.assertNotIn(PHONE, complete.text)
        self.assertIn("nonce-", complete.headers["content-security-policy"])
        self.assertEqual(self.client.get("/api/me").json()["user"]["id"], self.user_id)
        with self.sessions() as db:
            log = db.query(ActivityLog).filter_by(action="oa_login").one()
            self.assertEqual(log.user_id, self.user_id)
            self.assertNotIn(PHONE, log.detail)
            self.assertEqual(db.query(OaSsoCredential).count(), 1)

    def test_oa_entry_rotates_existing_cafeteria_session(self):
        with self.sessions() as db:
            role = Role(name="cafeteria_jiyang_kitchen", display_name="Kitchen")
            db.add(User(email=None, username="kitchen-oa", display_name="Kitchen",
                        password_hash=hash_password(self.password), password_set_at=utcnow(),
                        roles=[role]))
            db.commit()
        for valid in (True, False):
            with self.subTest(valid=valid):
                response = self.client.post("/api/login", json={
                    "username": "kitchen-oa", "password": self.password,
                })
                self.assertEqual(response.status_code, 200)
                query = signed_query() if valid else "payload=bad&signature=bad"
                response = self.client.get("/auth/oa?" + query)
                self.assertEqual(response.status_code, 303 if valid else 400)
                if valid:
                    complete = self.client.get(response.headers["location"])
                    self.assertEqual(complete.status_code, 200)
                    self.assertEqual(self.client.get("/api/me").json()["user"]["id"], self.user_id)
                else:
                    self.assertEqual(self.client.get("/api/me").status_code, 401)

    def test_login_completion_preserves_valid_order_edit_destination(self):
        destination = "/?view=stock-orders&stockOrder=123&stockOrderMode=edit"
        response = self.client.get("/auth/oa?" + signed_query(next=destination))
        self.assertEqual(response.status_code, 303)
        complete = self.client.get(response.headers["location"])
        self.assertIn('window.location.replace("' + destination + '")', complete.text)

    def test_unknown_pending_disabled_deleted_and_incomplete_users(self):
        for change, message in (({"oa_login_phone": None}, "未关联"), ({"password_hash": None}, "注册"),
                                ({"password_set_at": None}, "注册"), ({"is_active": False}, "不可用"),
                                ({"deleted_at": utcnow()}, "不可用")):
            with self.subTest(change=change):
                with self.sessions() as db:
                    user = db.get(User, self.user_id)
                    original = {key: getattr(user, key) for key in change}
                    for key, value in change.items():
                        setattr(user, key, value)
                    db.commit()
                response = self.client.get("/auth/oa?" + signed_query())
                self.assertEqual(response.status_code, 403)
                self.assertIn(message, response.text)
                self.assertEqual(self.client.get("/api/me").status_code, 401)
                with self.sessions() as db:
                    user = db.get(User, self.user_id)
                    for key, value in original.items():
                        setattr(user, key, value)
                    db.commit()

    def test_failure_clears_previous_login_and_never_grants_access(self):
        self.login_admin()
        response = self.client.get("/auth/oa?payload=bad&signature=bad")
        self.assertEqual(response.status_code, 400)
        self.assertEqual(self.client.get("/api/me").status_code, 401)
        self.assertEqual(self.client.get("/auth/oa/complete").status_code, 400)

    def test_replay_rejected_across_clients_and_new_database_connections(self):
        query = signed_query()
        self.assertEqual(self.client.get("/auth/oa?" + query).status_code, 303)
        self.client.close()
        self.engine.dispose()
        with TestClient(app, follow_redirects=False) as restarted_client:
            self.assertEqual(restarted_client.get("/auth/oa?" + query).status_code, 400)

    def test_concurrent_credential_consumption_succeeds_only_once(self):
        query = signed_query()

        def login():
            with TestClient(app, follow_redirects=False) as client:
                return client.get("/auth/oa?" + query).status_code

        with ThreadPoolExecutor(max_workers=2) as pool:
            statuses = list(pool.map(lambda _: login(), range(2)))
        self.assertEqual(sorted(statuses), [303, 400])
        with self.sessions() as db:
            self.assertEqual(db.query(ActivityLog).filter_by(action="oa_login").count(), 1)

    def test_phone_admin_update_clear_uniqueness_and_audit(self):
        self.login_admin()
        endpoint = f"/api/users/{self.user_id}/oa-phone"
        response = self.client.put(endpoint, json={"oa_login_phone": " 13900139000 "})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["oaLoginPhone"], "13900139000")
        with self.sessions() as db:
            log = db.query(ActivityLog).filter_by(action="update_oa_phone").one()
            self.assertNotIn("13900139000", log.detail)
            self.assertIn("139****9000", log.detail)
            duplicate = User(email="oa-deleted@boyuanpharm.com", display_name="Deleted", oa_login_phone=PHONE, deleted_at=utcnow())
            db.add(duplicate)
            db.commit()
        self.assertEqual(self.client.put(endpoint, json={"oa_login_phone": PHONE}).status_code, 409)
        self.assertEqual(self.client.put(endpoint, json={"oa_login_phone": "invalid"}).status_code, 400)
        self.assertEqual(self.client.put(endpoint, json={"oa_login_phone": " "}).status_code, 200)
        self.assertIsNone(next(user for user in self.client.get("/api/users").json()["users"] if user["id"] == self.user_id)["oaLoginPhone"])
        with self.sessions() as db:
            db.add(User(email="oa-empty@boyuanpharm.com", display_name="Empty"))
            db.commit()
        unique = inspect(self.engine).get_unique_constraints("users")
        self.assertTrue(any(item["column_names"] == ["oa_login_phone"] for item in unique))

    def test_phone_update_requires_manage_users_permission(self):
        endpoint = f"/api/users/{self.user_id}/oa-phone"
        self.assertEqual(self.client.put(endpoint, json={"oa_login_phone": None}).status_code, 401)
        self.client.post("/api/login", json={"username": "oa-member", "password": self.password})
        self.assertEqual(self.client.put(endpoint, json={"oa_login_phone": None}).status_code, 403)
        self.assertEqual(self.client.get("/api/users").status_code, 403)

    def test_oa_session_expires_and_logout_still_clears_session(self):
        self.client.get("/auth/oa?" + signed_query())
        with patch("app.main.settings", replace(CONFIG, session_max_age_seconds=0)):
            self.assertEqual(self.client.get("/api/me").status_code, 401)
        self.client.get("/auth/oa?" + signed_query())
        self.assertEqual(self.client.post("/api/logout").status_code, 200)
        self.assertEqual(self.client.get("/api/me").status_code, 401)


if __name__ == "__main__":
    unittest.main()
