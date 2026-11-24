"""OA todo configuration and submission tests."""

from __future__ import annotations

import json
import os
import tempfile
import unittest
from dataclasses import replace
from pathlib import Path
from unittest.mock import MagicMock, patch

os.environ.setdefault("BOYUAN_DATABASE_URL", "sqlite:///:memory:")
os.environ.setdefault("BOYUAN_SESSION_SECRET", "unit-test-secret")

from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.auth import hash_password
from app.config import settings
from app.db import get_db
from app.db.models import Base, Role, User
from app.main import app
from app.services.oa_todo import send_todo


class OaTodoApiTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.engine = create_engine("sqlite:///" + str(Path(self.temp.name) / "todos.db"), connect_args={"check_same_thread": False})
        Base.metadata.create_all(self.engine)
        self.sessions = sessionmaker(self.engine)
        with self.sessions() as db:
            admin_role = Role(name="admin", display_name="Admin", can_manage_users=True, can_view_stock_orders=True, can_update_stock_orders=True)
            self.password = "test-password"
            admin = User(email="todo-admin@example.com", username="todo-admin", display_name="Admin",
                         password_hash=hash_password(self.password), is_active=True, roles=[admin_role])
            receivers = [
                User(email="purchase@example.com", username="purchase", display_name="采购员", oa_login_phone="13800138001", is_active=True),
                User(email="production@example.com", username="production", display_name="生产员", oa_login_phone="13800138002", is_active=True),
                User(email="qc@example.com", username="qc", display_name="质检员", oa_login_phone="13800138003", is_active=True),
            ]
            db.add_all([admin, *receivers])
            db.commit()
            self.receiver_ids = [user.id for user in receivers]

        def database():
            with self.sessions() as db:
                yield db

        self.previous_overrides = app.dependency_overrides.copy()
        app.dependency_overrides[get_db] = database
        self.settings_patch = patch("app.main.settings", replace(settings, oa_todo_username="todo-user", oa_todo_password="todo-pass"))
        self.settings_patch.start()
        self.client = TestClient(app)
        response = self.client.post("/api/login", json={"username": "todo-admin", "password": self.password})
        self.assertEqual(response.status_code, 200)

    def tearDown(self):
        self.client.close()
        self.settings_patch.stop()
        app.dependency_overrides.clear()
        app.dependency_overrides.update(self.previous_overrides)
        self.engine.dispose()
        self.temp.cleanup()

    def config_payload(self):
        return {"departments": {
            "purchase": {"user_ids": [self.receiver_ids[0]], "subject": "采购 {order_no}", "link": "/?view=stock-orders&stockOrder={order_id}"},
            "production": {"user_ids": [self.receiver_ids[1]], "subject": "生产 {order_no}", "link": "/?view=stock-orders&stockOrder={order_id}"},
            "qc": {"user_ids": [self.receiver_ids[2]], "subject": "质量 {order_no}", "link": "/?view=stock-orders&stockOrder={order_id}"},
        }}

    def order_payload(self):
        return {"fields": {"internal_name": "产品A", "quantity": "10 kg", "order_type": "备货订单", "salesperson": "销售员"}}

    def test_regular_save_never_sends_oa_todos(self):
        with patch("app.main.send_todo") as send:
            response = self.client.post("/api/stock-orders", json=self.order_payload())
        self.assertEqual(response.status_code, 200)
        send.assert_not_called()

    def test_submit_sends_three_department_todos_with_login_names(self):
        config_response = self.client.put("/api/admin/oa-todo-config", json=self.config_payload())
        self.assertEqual(config_response.status_code, 200, config_response.text)
        with patch("app.main.send_todo", return_value={"returnState": 2, "message": "ok"}) as send:
            response = self.client.post("/api/stock-orders/submit-and-notify", json=self.order_payload())
        self.assertEqual(response.status_code, 200, response.text)
        self.assertTrue(response.json()["ok"])
        self.assertEqual([item["success"] for item in response.json()["notifications"]], [True, True, True])
        self.assertEqual(send.call_count, 3)
        contexts = [call.args[0] for call in send.call_args_list]
        self.assertEqual({context["subject"] for context in contexts}, {
            f"采购 {response.json()['order']['order_no']}",
            f"生产 {response.json()['order']['order_no']}",
            f"质量 {response.json()['order']['order_no']}",
        })
        self.assertEqual({context["modelName"] for context in contexts}, {"备货订单"})
        target_sets = {tuple(json.loads(context["targets"])[0].values()) for context in contexts}
        self.assertEqual(target_sets, {("13800138001",), ("13800138002",), ("13800138003",)})

    def test_configuration_rejects_user_without_oa_phone(self):
        payload = self.config_payload()
        payload["departments"]["purchase"]["user_ids"] = [99999]
        response = self.client.put("/api/admin/oa-todo-config", json=payload)
        self.assertEqual(response.status_code, 400)

    def test_retry_endpoint_sends_only_requested_department(self):
        self.assertEqual(self.client.put("/api/admin/oa-todo-config", json=self.config_payload()).status_code, 200)
        created = self.client.post("/api/stock-orders", json=self.order_payload()).json()["order"]
        with patch("app.main.send_todo", return_value={"returnState": 2, "message": "ok"}) as send:
            response = self.client.post(
                f"/api/stock-orders/{created['id']}/notify-retry", json={"departments": ["purchase"]},
            )
        self.assertEqual(response.status_code, 200, response.text)
        self.assertTrue(response.json()["ok"])
        self.assertEqual([item["departmentKey"] for item in response.json()["notifications"]], ["purchase"])
        send.assert_called_once()

    def test_non_admin_cannot_retry_all_departments(self):
        self.assertEqual(self.client.put("/api/admin/oa-todo-config", json=self.config_payload()).status_code, 200)
        created = self.client.post("/api/stock-orders", json=self.order_payload()).json()["order"]
        self.client.post("/api/logout")
        with self.sessions() as db:
            member_role = Role(name="todo-editor", display_name="订单编辑", can_view_stock_orders=True, can_update_stock_orders=True)
            member = User(email="todo-editor@example.com", username="todo-editor", display_name="订单编辑",
                          password_hash=hash_password(self.password), is_active=True, roles=[member_role])
            db.add(member)
            db.commit()
        self.client.post("/api/login", json={"username": "todo-editor", "password": self.password})
        with patch("app.main.send_todo") as send:
            response = self.client.post(
                f"/api/stock-orders/{created['id']}/notify-retry",
                json={"departments": ["purchase", "production", "qc"]},
            )
        self.assertEqual(response.status_code, 403)
        send.assert_not_called()

    def test_non_admin_cannot_read_todo_configuration(self):
        self.client.post("/api/logout")
        with self.sessions() as db:
            member_role = Role(name="member-todo", display_name="Member", can_view_stock_orders=True)
            member = User(email="member-todo@example.com", username="member-todo", display_name="Member",
                          password_hash=hash_password(self.password), is_active=True, roles=[member_role])
            db.add(member)
            db.commit()
        self.client.post("/api/login", json={"username": "member-todo", "password": self.password})
        response = self.client.get("/api/admin/oa-todo-config")
        self.assertEqual(response.status_code, 403)

    def test_oa_client_posts_basic_auth_json_to_send_todo(self):
        config = replace(settings, oa_todo_base_url="http://oa.example:3551/", oa_todo_username="api-user",
                         oa_todo_password="api-pass", oa_todo_service_path="/ekp/api/sys-notify/sysNotifyTodoRestService")
        response = MagicMock()
        response.__enter__.return_value.read.return_value = b'{"returnState":2,"message":"ok"}'
        with patch("app.services.oa_todo.urlopen", return_value=response) as open_url:
            result = send_todo({"subject": "test"}, config)
        request = open_url.call_args.args[0]
        self.assertEqual(request.full_url, "http://oa.example:3551/ekp/api/sys-notify/sysNotifyTodoRestService/sendTodo")
        self.assertTrue(request.get_header("Authorization").startswith("Basic "))
        self.assertEqual(json.loads(request.data), {"subject": "test"})
        self.assertEqual(result["returnState"], 2)


if __name__ == "__main__":
    unittest.main()
