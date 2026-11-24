"""Run an isolated OA flow in a real browser without using deployment databases."""

from __future__ import annotations

import base64
import hmac
import json
import os
from pathlib import Path
import secrets
import socket
import subprocess
import sys
import tempfile
import time
from urllib.request import urlopen

from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def run():
    with tempfile.TemporaryDirectory(prefix="boyuan-oa-browser-") as folder:
        secret = "browser-test-key-0123456789abcdef0123456789"
        os.environ.update(
            BOYUAN_DATABASE_URL="sqlite:///" + str(Path(folder) / "browser.db"),
            BOYUAN_SESSION_SECRET="browser-test-session-secret",
            BOYUAN_SESSION_COOKIE_SECURE="false",
            BOYUAN_INITIAL_ADMIN_EMAIL="root@boyuanpharm.com",
            BOYUAN_INITIAL_ADMIN_PASSWORD="browser-test-password",
            BOYUAN_OA_SSO_ENABLED="true", BOYUAN_OA_SSO_SECRET=secret,
            BOYUAN_OA_SSO_AUDIENCE="boyuan-internal-tools", BOYUAN_OA_SSO_MAX_AGE="60",
        )
        from app.main import SessionLocal, engine
        from app.auth import hash_password, utcnow
        from app.db.models import Role, User

        with socket.socket() as listener:
            listener.bind(("127.0.0.1", 0))
            port = listener.getsockname()[1]
        base = f"http://127.0.0.1:{port}"
        log_path = Path(folder) / "uvicorn.log"
        with log_path.open("w", encoding="utf-8") as log:
            process = subprocess.Popen([sys.executable, "-m", "uvicorn", "app.main:app", "--host", "127.0.0.1", "--port", str(port)],
                                       cwd=ROOT, env=os.environ.copy(), stdout=log, stderr=subprocess.STDOUT)
            try:
                for _ in range(100):
                    try:
                        with urlopen(base + "/login", timeout=1):
                            break
                    except OSError:
                        if process.poll() is not None:
                            raise RuntimeError("Isolated application failed to start")
                        time.sleep(.1)
                else:
                    raise RuntimeError("Isolated application startup timed out")

                with SessionLocal() as db:
                    password_hash = hash_password("browser-test-password")
                    sales = db.query(Role).filter_by(name="dept04").one()
                    home_role = Role(name="oa-home-only", display_name="首页测试", can_view_reconcile=True,
                                     can_view_stock_orders=False, can_update_stock_orders=False)
                    db.add_all([
                        User(email="ui-member@boyuanpharm.com", display_name="测试成员", password_hash=password_hash,
                             password_set_at=utcnow(), is_active=True, roles=[sales]),
                        User(email="ui-home@boyuanpharm.com", display_name="首页成员", password_hash=password_hash,
                             password_set_at=utcnow(), is_active=True, oa_login_phone="13900139000", roles=[home_role]),
                        User(email="ui-pending@boyuanpharm.com", display_name="待注册成员", is_active=False,
                             oa_login_phone="13700137000", roles=[sales]),
                    ])
                    db.commit()

                def link(phone):
                    now = int(time.time())
                    data = {"v": 1, "phone": phone, "iat": now, "exp": now + 60,
                            "nonce": secrets.token_hex(16), "aud": "boyuan-internal-tools"}
                    payload = base64.urlsafe_b64encode(json.dumps(data).encode()).decode().rstrip("=")
                    signature = base64.urlsafe_b64encode(hmac.digest(secret.encode(), payload.encode(), "sha256")).decode().rstrip("=")
                    return base + f"/auth/oa?payload={payload}&signature={signature}"

                with sync_playwright() as playwright:
                    browser = playwright.chromium.launch(channel="msedge", headless=True)
                    page = browser.new_page(viewport={"width": 1440, "height": 1000})
                    errors = []
                    page.on("pageerror", lambda error: errors.append(str(error)))
                    page.route("**/api/fun-facts", lambda route: route.fulfill(json={"facts": []}))
                    page.route("**/api/next-holiday", lambda route: route.fulfill(status=503, json={"detail": "browser test"}))
                    page.goto(base + "/login")
                    page.locator("#username").fill("root@boyuanpharm.com")
                    page.locator("#password").fill("browser-test-password")
                    page.locator("#login-btn").click()
                    page.wait_for_url(base + "/")
                    page.locator('[data-view="admin"]').click()
                    member = page.locator("#user-table tbody tr").filter(has_text="ui-member@boyuanpharm.com")
                    member.locator(".user-oa-phone-btn").click()
                    page.locator("#user-oa-phone-input").fill("13800138000")
                    page.locator("#user-oa-phone-submit").click()
                    page.locator("#user-oa-phone-mask").wait_for(state="hidden")
                    assert "13800138000" in member.inner_text()

                    home = page.locator("#user-table tbody tr").filter(has_text="ui-home@boyuanpharm.com")
                    home.locator(".user-oa-phone-btn").click()
                    page.locator("#user-oa-phone-input").fill("13800138000")
                    page.locator("#user-oa-phone-submit").click()
                    page.get_by_text("该 OA 登录手机号已被其他账号占用，请核对绑定关系", exact=True).wait_for()
                    page.locator("[data-user-oa-phone-close]").click()

                    member.locator(".user-oa-phone-btn").click()
                    page.locator("#user-oa-phone-input").fill("")
                    page.locator("#user-oa-phone-submit").click()
                    page.locator("#user-oa-phone-mask").wait_for(state="hidden")
                    assert "未配置" in member.inner_text()
                    member.locator(".user-oa-phone-btn").click()
                    page.locator("#user-oa-phone-input").fill("13800138000")
                    page.locator("#user-oa-phone-submit").click()
                    page.locator("#user-oa-phone-mask").wait_for(state="hidden")
                    print("PASS: browser admin phone bind, duplicate rejection, clear and rebind")

                    oa_link = link("13800138000")
                    page.goto(oa_link)
                    page.wait_for_url(base + "/?view=stock-orders")
                    page.locator("#view-stock-orders.active").wait_for()
                    assert page.locator("#current-user").inner_text() == "ui-member@boyuanpharm.com"
                    assert page.evaluate("JSON.parse(sessionStorage.getItem('boyuan_current_user')).email") == "ui-member@boyuanpharm.com"
                    assert "payload=" not in page.url
                    print("PASS: browser OA account switch, cache refresh, clean URL and stock menu")

                    page.goto(oa_link)
                    page.get_by_text("登录链接已失效，请回到 OA 重新点击", exact=True).wait_for()
                    assert page.request.get(base + "/api/me").status == 401
                    page.goto(link("13700137000"))
                    page.get_by_text("请先完成本系统注册，再从 OA 登录", exact=True).wait_for()
                    print("PASS: browser replay rejection, old session cleared, pending signup rejected")

                    page.goto(link("13900139000"))
                    page.wait_for_url(base + "/?view=stock-orders")
                    page.locator("#view-home.active").wait_for()
                    assert "hidden" in page.locator("#stock-orders-nav").get_attribute("class")
                    assert page.locator("#current-user").inner_text() == "ui-home@boyuanpharm.com"
                    page.locator("#logout-btn").click()
                    page.wait_for_url(base + "/login")
                    assert not errors, errors
                    print("PASS: browser no-stock-permission fallback, logout; no JavaScript errors")
                    browser.close()
            finally:
                process.terminate()
                process.wait(timeout=10)
                engine.dispose()
        log_text = log_path.read_text(encoding="utf-8")
        assert "payload=" not in log_text and "signature=" not in log_text and "13800138000" not in log_text
        print("PASS: real Uvicorn access log contains no raw credential or phone")


if __name__ == "__main__":
    run()
