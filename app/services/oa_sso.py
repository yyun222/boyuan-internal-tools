"""OA signature verification and credential privacy."""

from __future__ import annotations

import base64
import binascii
import hashlib
import hmac
import json
import re
import time
from dataclasses import dataclass
from urllib.parse import parse_qs

from app.config import Settings

PHONE_RE = re.compile(r"1[3-9][0-9]{9}")
TOKEN_RE = re.compile(r"[A-Za-z0-9_-]+")
OA_HEADERS = {"Cache-Control": "no-store, no-cache, must-revalidate", "Pragma": "no-cache", "Referrer-Policy": "no-referrer"}


class OaSsoError(ValueError):
    pass


@dataclass(frozen=True)
class OaCredential:
    phone: str
    nonce_hash: str
    expires_at: int
    next_path: str = "/?view=stock-orders"


class OaEntryPrivacyMiddleware:
    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] == "http" and scope.get("path", "").rstrip("/") == "/auth/oa":
            # 保留给验签入口，避免应用访问日志输出手机号及凭证。
            scope["oa_query_string"] = scope.get("query_string", b"")
            scope["query_string"] = b""
        await self.app(scope, receive, send)


def normalize_oa_phone(value: str | None) -> str | None:
    phone = (value or "").strip()
    if not phone:
        return None
    if not PHONE_RE.fullmatch(phone):
        raise OaSsoError("请输入中国大陆 11 位手机号")
    return phone


def masked_phone(phone: str | None) -> str:
    return f"{phone[:3]}****{phone[-4:]}" if phone else "未配置"


def _decode(value: str) -> bytes:
    if not TOKEN_RE.fullmatch(value) or len(value) % 4 == 1:
        raise OaSsoError("身份凭证无效，请从 OA 重新进入")
    return base64.b64decode(value + "=" * (-len(value) % 4), altchars=b"-_", validate=True)


def verify_oa_query(query: bytes, settings: Settings, *, now: int | None = None) -> OaCredential:
    if not settings.oa_sso_enabled or len(settings.oa_sso_secret.encode("utf-8")) < 32 or not settings.oa_sso_audience or settings.oa_sso_max_age_seconds <= 0:
        raise OaSsoError("OA 登录暂不可用，请使用账号密码登录或联系管理员")
    invalid = "身份凭证无效，请从 OA 重新进入"
    try:
        if len(query) > 4096:
            raise ValueError()
        params = parse_qs(query.decode("ascii"), keep_blank_values=True, strict_parsing=True, max_num_fields=2)
        if set(params) != {"payload", "signature"} or any(len(values) != 1 for values in params.values()):
            raise ValueError()
        payload, signature = params["payload"][0], params["signature"][0]
        supplied = _decode(signature)
        expected = hmac.digest(settings.oa_sso_secret.encode("utf-8"), payload.encode("ascii"), "sha256")
        if not hmac.compare_digest(supplied, expected):
            raise ValueError()
        data = json.loads(_decode(payload).decode("utf-8"))
        if not isinstance(data, dict) or set(data) not in (
            {"v", "phone", "iat", "exp", "nonce", "aud"},
            {"v", "phone", "iat", "exp", "nonce", "aud", "next"},
        ) or type(data.get("v")) is not int or data["v"] != 1 or data.get("aud") != settings.oa_sso_audience:
            raise ValueError()
        phone, nonce = data.get("phone"), data.get("nonce")
        if not isinstance(phone, str) or not PHONE_RE.fullmatch(phone):
            raise ValueError()
        if not isinstance(nonce, str) or not re.fullmatch(r"[0-9a-f]{32}", nonce):
            raise ValueError()
        issued, expires = data.get("iat"), data.get("exp")
        if type(issued) is not int or type(expires) is not int:
            raise ValueError()
        current = int(time.time()) if now is None else now
        if issued > current + 30 or issued < 0 or expires <= issued or expires - issued > settings.oa_sso_max_age_seconds:
            raise ValueError()
        if expires <= current:
            raise OaSsoError("登录链接已失效，请回到 OA 重新点击")
        next_path = "/?view=stock-orders"
        if "next" in data:
            candidate = data["next"]
            if not isinstance(candidate, str) or not re.fullmatch(
                r"/\?view=stock-orders&stockOrder=[1-9][0-9]{0,9}&stockOrderMode=edit", candidate
            ):
                raise ValueError()
            next_path = candidate
        return OaCredential(phone, hashlib.sha256(nonce.encode("ascii")).hexdigest(), expires, next_path)
    except OaSsoError:
        raise
    except (ValueError, TypeError, UnicodeError, binascii.Error, OverflowError):
        raise OaSsoError(invalid) from None
