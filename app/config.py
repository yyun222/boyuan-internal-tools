"""Central runtime configuration loaded from environment variables."""

from __future__ import annotations

import os
import secrets
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv


load_dotenv(Path(__file__).resolve().parent.parent / ".env", override=False, encoding="utf-8-sig")


def _env_bool(name: str, default: bool) -> bool:
    raw = os.environ.get(name)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


@dataclass(frozen=True)
class Settings:
    database_url: str = os.environ.get(
        "BOYUAN_DATABASE_URL",
        "mysql+pymysql://localdbuser:localdbpassword@127.0.0.1:3306/boyuan_internal_tools",
    )
    session_secret: str = os.environ.get("BOYUAN_SESSION_SECRET") or secrets.token_urlsafe(32)
    session_max_age_seconds: int = int(os.environ.get("BOYUAN_SESSION_MAX_AGE", str(8 * 60 * 60)))
    session_cookie_secure: bool = _env_bool("BOYUAN_SESSION_COOKIE_SECURE", False)
    oa_sso_enabled: bool = _env_bool("BOYUAN_OA_SSO_ENABLED", False)
    oa_sso_secret: str = os.environ.get("BOYUAN_OA_SSO_SECRET", "")
    oa_sso_audience: str = os.environ.get("BOYUAN_OA_SSO_AUDIENCE", "boyuan-internal-tools")
    oa_sso_max_age_seconds: int = int(os.environ.get("BOYUAN_OA_SSO_MAX_AGE", "60"))
    oa_todo_base_url: str = os.environ.get("BOYUAN_OA_TODO_BASE_URL", "http://36.139.172.238:3551")
    oa_todo_username: str = os.environ.get("BOYUAN_OA_TODO_USERNAME", "")
    oa_todo_password: str = os.environ.get("BOYUAN_OA_TODO_PASSWORD", "")
    oa_todo_service_path: str = os.environ.get(
        "BOYUAN_OA_TODO_SERVICE_PATH", "/ekp/api/sys-notify/sysNotifyTodoRestService"
    )
    business_utc_offset_hours: int = int(os.environ.get("BOYUAN_BUSINESS_UTC_OFFSET", "8"))
    initial_admin_email: str = os.environ.get("BOYUAN_INITIAL_ADMIN_EMAIL", "root@boyuanpharm.com")
    initial_admin_password: str = os.environ.get(
        "BOYUAN_INITIAL_ADMIN_PASSWORD",
        os.environ.get("BOYUAN_ROOT_PASSWORD", "123123"),
    )


settings = Settings()
