"""Central runtime configuration loaded from environment variables."""

from __future__ import annotations

import os
import secrets
from dataclasses import dataclass


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
    business_utc_offset_hours: int = int(os.environ.get("BOYUAN_BUSINESS_UTC_OFFSET", "8"))
    translation_api_key: str = os.environ.get("BOYUAN_TRANSLATION_API_KEY", "KVLWMD6PW85MV9421AKS")
    initial_admin_email: str = os.environ.get("BOYUAN_INITIAL_ADMIN_EMAIL", "root@boyuanpharm.com")
    initial_admin_password: str = os.environ.get(
        "BOYUAN_INITIAL_ADMIN_PASSWORD",
        os.environ.get("BOYUAN_ROOT_PASSWORD", "123123"),
    )


settings = Settings()
