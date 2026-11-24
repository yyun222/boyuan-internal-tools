"""OA todo REST client."""

from __future__ import annotations

import base64
import json
from datetime import datetime, timedelta, timezone
from urllib.error import HTTPError, URLError
from urllib.parse import quote
from urllib.request import Request, urlopen

from app.config import Settings


class OaTodoError(RuntimeError):
    pass


def build_todo_context(order, department: str, config: dict, settings: Settings, phones: list[str]) -> dict:
    subject = config["subject"].replace("{order_no}", order.order_no).replace("{internal_name}", order.internal_name)
    link = config["link"].replace("{order_id}", str(order.id)).replace("{order_no}", quote(order.order_no))
    targets = [{"LoginName": phone} for phone in phones]
    return {
        "appName": "Boyuan Internal Tools",
        "modelName": "备货订单",
        "modelId": order.order_no,
        "subject": subject,
        "link": link,
        "mobileLink": link,
        "padLink": link,
        "type": 2,
        "key": f"stock_order_{department}",
        "targets": json.dumps(targets, ensure_ascii=False, separators=(",", ":")),
        "createTime": (datetime.now(timezone.utc) + timedelta(hours=settings.business_utc_offset_hours)).strftime("%Y-%m-%d %H:%M:%S"),
        "level": 3,
    }


def send_todo(context: dict, settings: Settings) -> dict:
    if not settings.oa_todo_username or not settings.oa_todo_password:
        raise OaTodoError("OA 待办 Basic Auth 凭证未配置")
    base_url = settings.oa_todo_base_url.rstrip("/")
    service_path = "/" + settings.oa_todo_service_path.strip("/")
    url = f"{base_url}{service_path}/sendTodo"
    token = base64.b64encode(f"{settings.oa_todo_username}:{settings.oa_todo_password}".encode()).decode("ascii")
    request = Request(
        url,
        data=json.dumps(context, ensure_ascii=False).encode("utf-8"),
        headers={"Authorization": f"Basic {token}", "Content-Type": "application/json; charset=utf-8"},
        method="POST",
    )
    try:
        with urlopen(request, timeout=10) as response:
            result = json.loads(response.read().decode("utf-8"))
    except HTTPError as exc:
        raise OaTodoError(f"OA 返回 HTTP {exc.code}") from None
    except (URLError, TimeoutError, OSError, UnicodeError, json.JSONDecodeError):
        raise OaTodoError("OA 待办请求失败或返回格式无效") from None
    if not isinstance(result, dict) or result.get("returnState") != 2:
        message = result.get("message", "OA 未确认待办发送成功") if isinstance(result, dict) else "OA 返回格式无效"
        raise OaTodoError(str(message)[:300])
    return result
