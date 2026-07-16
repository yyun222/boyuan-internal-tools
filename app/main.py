"""FastAPI application: Boyuan Internal Tools."""

from __future__ import annotations

import asyncio
import json
import logging
import secrets
import csv
import io
from html import escape
from pathlib import Path
from typing import Literal, Optional

from datetime import date, datetime, timedelta
from urllib.parse import quote, urlencode
from urllib.request import Request as UrlRequest, urlopen

from fastapi import Depends, FastAPI, File, HTTPException, Request, UploadFile
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse, RedirectResponse, Response
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field
from sqlalchemy import Numeric, and_, case, cast, or_
from sqlalchemy.orm import Session
from starlette.middleware.sessions import SessionMiddleware

from app.auth import (
    hash_password,
    is_allowed_email,
    utcnow,
    verify_password,
)
from app.config import settings
from app.db import SessionLocal, engine, get_db, init_database
from app.db.models import (
    ActivityLog, AssetLedgerAsset, AssetLedgerLog, Role, StockOrder,
    StockOrderChangeLog, StockOrderFieldUpdate, StockOrderWarning, User,
)
from app.services.stock_orders import (
    FIELD_META, MODULES, business_date, business_datetime, can_edit_module, clean_fields, field_locks, is_admin,
    order_payload, sync_order_warnings, user_modules,
)
from app.services.export import build_workbook
from app.services.reconcile import reconcile

APP_DIR = Path(__file__).resolve().parent
PROJECT_DIR = APP_DIR.parent
STATIC_DIR = APP_DIR / "static"

HOLIDAY_API = "https://api.jiejiariapi.com/v1/holidays/{year}"
FUN_FACTS_API = "https://factfacts.com/api.php?count=10"
TRANSLATION_API = "https://apis.uctb.cn/api/qqfy"

logger = logging.getLogger(__name__)

app = FastAPI(title="Boyuan Internal Tools")
app.add_middleware(
    SessionMiddleware,
    secret_key=settings.session_secret,
    session_cookie="boyuan_session",
    same_site="lax",
    https_only=settings.session_cookie_secure,
    max_age=settings.session_max_age_seconds,
)
init_database(engine, SessionLocal)


def _wants_json(request: Request) -> bool:
    accept = request.headers.get("accept", "")
    return request.url.path.startswith("/api/") or "application/json" in accept and "text/html" not in accept


def _error_title(status_code: int) -> str:
    return {
        400: "请求无效",
        401: "需要登录",
        403: "没有权限",
        404: "页面不存在",
        500: "服务器错误",
    }.get(status_code, "发生错误")


def _error_page(status_code: int, detail: str) -> str:
    title = _error_title(status_code)
    safe_title = escape(title)
    safe_detail = escape(detail or title)
    return f"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
  <meta charset="UTF-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1.0" />
  <title>{status_code} · Boyuan Internal Tools</title>
  <link rel="stylesheet" href="/static/style.css" />
</head>
<body class="error-body">
  <main class="error-card">
    <div class="error-code">{status_code}</div>
    <h1>{safe_title}</h1>
    <p>{safe_detail}</p>
    <div class="error-actions">
      <a href="/login?force=1">重新登录</a>
    </div>
  </main>
</body>
</html>"""


@app.exception_handler(HTTPException)
async def http_exception_handler(request: Request, exc: HTTPException):
    if _wants_json(request):
        return JSONResponse({"detail": exc.detail}, status_code=exc.status_code, headers=exc.headers)
    return HTMLResponse(_error_page(exc.status_code, str(exc.detail)), status_code=exc.status_code, headers=exc.headers)


@app.exception_handler(404)
async def not_found_handler(request: Request, exc):
    if _wants_json(request):
        return JSONResponse({"detail": "Not Found"}, status_code=404)
    return HTMLResponse(_error_page(404, "你访问的页面不存在或已经移动。"), status_code=404)


@app.exception_handler(500)
async def internal_error_handler(request: Request, exc):
    if _wants_json(request):
        return JSONResponse({"detail": "Internal Server Error"}, status_code=500)
    return HTMLResponse(_error_page(500, "服务器处理请求时遇到问题，请稍后再试。"), status_code=500)


def _role_names(user: User) -> list[str]:
    return [role.name for role in user.roles if role.deleted_at is None]


def _role_display_names(user: User) -> list[str]:
    return [role.display_name for role in user.roles if role.deleted_at is None]


def _role_departments(user: User) -> list[str]:
    return sorted({role.department for role in user.roles if role.deleted_at is None and role.scope == "department" and role.department})


def _has_permission(user: User, permission: str) -> bool:
    return any(role.deleted_at is None and bool(getattr(role, permission, False)) for role in user.roles)


def _has_all_asset_access(user: User) -> bool:
    return any(role.deleted_at is None and role.scope == "all" and role.can_view_asset_ledger for role in user.roles)


def _allowed_asset_departments(user: User) -> set[str]:
    return {role.department for role in user.roles if role.deleted_at is None and role.scope == "department" and role.department}


def _user_payload(user: User) -> dict:
    roles = _role_names(user)
    departments = _role_departments(user)
    all_asset_access = _has_all_asset_access(user)
    return {
        "id": user.id,
        "email": user.email,
        "username": user.username,
        "displayName": user.display_name,
        "roles": roles,
        "role": "admin" if "admin" in roles else (roles[0] if roles else ""),
        "department": "全部" if all_asset_access else (departments[0] if departments else ""),
        "departments": departments,
        "scope": "all" if all_asset_access else "department",
        "permissions": {
            "viewReconcile": _has_permission(user, "can_view_reconcile"),
            "updateReconcile": _has_permission(user, "can_update_reconcile"),
            "viewAssetLedger": _has_permission(user, "can_view_asset_ledger"),
            "updateAssetLedger": _has_permission(user, "can_update_asset_ledger"),
            "viewStockOrders": _has_permission(user, "can_view_stock_orders"),
            "updateStockOrders": _has_permission(user, "can_update_stock_orders"),
            "viewActivityLogs": _has_permission(user, "can_view_activity_logs"),
            "manageUsers": _has_permission(user, "can_manage_users"),
        },
        "lastActivityAt": business_datetime(user.last_activity_at) or None,
    }


def _current_user(db: Session, request: Request) -> Optional[User]:
    user_id = request.session.get("user_id")
    authenticated_at = request.session.get("authenticated_at")
    if not user_id or not authenticated_at:
        return None
    try:
        login_time = datetime.fromisoformat(authenticated_at)
    except (TypeError, ValueError):
        request.session.clear()
        return None
    if utcnow() - login_time >= timedelta(seconds=settings.session_max_age_seconds):
        request.session.clear()
        return None
    user = db.get(User, user_id)
    if not user or not user.is_active or user.deleted_at is not None:
        request.session.clear()
        return None
    return user


def _require_user(request: Request, db: Session) -> User:
    user = _current_user(db, request)
    if not user:
        raise HTTPException(status_code=401, detail="未登录")
    return user


def _require_permission(request: Request, db: Session, permission: str) -> User:
    user = _require_user(request, db)
    if not _has_permission(user, permission):
        raise HTTPException(status_code=403, detail="当前账号没有权限")
    return user


def _log_activity(db: Session, user: User, action: str, target: str, detail: str) -> None:
    user.last_activity_at = utcnow()
    db.add(ActivityLog(user_id=user.id, action=action, target=target, detail=detail))
    db.commit()


class LoginPayload(BaseModel):
    username: str
    password: str


def _fetch_holiday_year(year: int) -> list[dict]:
    request = UrlRequest(HOLIDAY_API.format(year=year), headers={"User-Agent": "boyuan-internal-tools/1.0"})
    with urlopen(request, timeout=3) as response:
        payload = json.load(response)
    if not isinstance(payload, dict):
        raise ValueError("节假日 API 返回格式无效")
    return [row for row in payload.values() if isinstance(row, dict) and row.get("isOffDay") is True]


async def _holiday_rows(year: int) -> list[dict]:
    try:
        return await asyncio.to_thread(_fetch_holiday_year, year)
    except Exception:
        return []


def _next_statutory_holiday(today: date, rows: list[dict]) -> dict | None:
    candidates = []
    for row in rows:
        try:
            holiday_date = date.fromisoformat(str(row.get("date") or ""))
        except ValueError:
            continue
        if row.get("isOffDay") is True and holiday_date >= today:
            candidates.append((holiday_date, str(row.get("name") or "法定节假日")))
    if not candidates:
        return None
    holiday_date, name = min(candidates)
    return {"name": name, "date": holiday_date.isoformat(), "days": (holiday_date - today).days}


class InvitePayload(BaseModel):
    email: str
    roles: list[str]
    display_name: Optional[str] = None


class SignupPayload(BaseModel):
    email: str
    password: str
    display_name: Optional[str] = None


class UserStatusPayload(BaseModel):
    is_active: bool


class UserRolesPayload(BaseModel):
    roles: list[str]


class StockOrderPayload(BaseModel):
    fields: dict[str, object]
    reason: str = ""


class StockCompletePayload(BaseModel):
    module: Literal["sales", "purchase", "production", "qc"]
    fields: dict[str, object] = Field(default_factory=dict)


class StockCancelPayload(BaseModel):
    reason: str


ASSET_FIELD_MAP = {
    "assetNo": "asset_no",
    "name": "name",
    "model": "model",
    "site": "site",
    "department": "department",
    "useDepartment": "use_department",
    "location": "location",
    "startDate": "start_date",
    "manager": "manager",
    "admin": "admin",
    "owner": "owner",
    "status": "status",
    "checkResult": "check_result",
    "lastCheckDate": "last_check_date",
    "actualLocation": "actual_location",
    "remark": "remark",
    "sourceRow": "source_row",
}
ASSET_DB_FIELDS = set(ASSET_FIELD_MAP)

LOG_FIELD_MAP = {
    "date": "event_date",
    "action": "action",
    "assetNo": "asset_no",
    "assetName": "asset_name",
    "department": "department",
    "detail": "detail",
}
LOG_DB_FIELDS = set(LOG_FIELD_MAP)


def _asset_client_id(asset: dict) -> str:
    raw_id = asset.get("id")
    if raw_id is None or str(raw_id).strip() == "":
        return "FA-" + secrets.token_urlsafe(12)
    return str(raw_id)


def _log_client_id(log: dict) -> str:
    raw_id = log.get("id")
    if raw_id is None or str(raw_id).strip() == "":
        return "LOG-" + secrets.token_urlsafe(12)
    return str(raw_id)


def _asset_payload(row: AssetLedgerAsset) -> dict:
    payload = {
        "id": row.client_id,
        "assetNo": row.asset_no,
        "name": row.name,
        "model": row.model or "",
        "site": row.site or "",
        "department": row.department or "",
        "useDepartment": row.use_department or "",
        "location": row.location or "",
        "startDate": row.start_date or "",
        "manager": row.manager or "",
        "admin": row.admin or "",
        "owner": row.owner or "",
        "status": row.status or "",
        "checkResult": row.check_result or "",
        "lastCheckDate": row.last_check_date or "",
        "actualLocation": row.actual_location or "",
        "remark": row.remark or "",
        "sourceRow": row.source_row,
        "createdAt": row.created_at.date().isoformat() if row.created_at else "",
        "updatedAt": row.updated_at.date().isoformat() if row.updated_at else "",
    }
    if row.extra_data:
        try:
            payload.update(json.loads(row.extra_data))
        except ValueError:
            pass
    return payload


def _log_payload(row: AssetLedgerLog) -> dict:
    payload = {
        "id": row.client_id,
        "date": row.event_date,
        "action": row.action,
        "assetNo": row.asset_no or "",
        "assetName": row.asset_name or "",
        "department": row.department or "",
        "detail": row.detail,
        "createdAt": row.created_at.date().isoformat() if row.created_at else "",
        "updatedAt": row.updated_at.date().isoformat() if row.updated_at else "",
    }
    if row.extra_data:
        try:
            payload.update(json.loads(row.extra_data))
        except ValueError:
            pass
    return payload


def _upsert_asset_row(db: Session, asset: dict) -> AssetLedgerAsset:
    client_id = _asset_client_id(asset)
    row = db.query(AssetLedgerAsset).filter(AssetLedgerAsset.client_id == client_id).one_or_none()
    if row is None:
        row = AssetLedgerAsset(client_id=client_id)
        db.add(row)
    row.deleted_at = None
    row.updated_at = utcnow()
    for api_field, db_field in ASSET_FIELD_MAP.items():
        value = asset.get(api_field)
        if db_field == "source_row":
            try:
                value = int(value) if value not in (None, "") else None
            except (TypeError, ValueError):
                value = None
        elif value is not None:
            value = str(value)
        setattr(row, db_field, value)
    row.asset_no = row.asset_no or client_id
    row.name = row.name or row.asset_no
    extra = {key: value for key, value in asset.items() if key not in ASSET_DB_FIELDS and key != "id"}
    row.extra_data = json.dumps(extra, ensure_ascii=False) if extra else None
    return row


def _upsert_log_row(db: Session, log: dict) -> AssetLedgerLog:
    client_id = _log_client_id(log)
    row = db.query(AssetLedgerLog).filter(AssetLedgerLog.client_id == client_id).one_or_none()
    if row is None:
        row = AssetLedgerLog(client_id=client_id)
        db.add(row)
    row.deleted_at = None
    row.updated_at = utcnow()
    for api_field, db_field in LOG_FIELD_MAP.items():
        value = log.get(api_field)
        if value is not None:
            value = str(value)
        setattr(row, db_field, value)
    row.event_date = row.event_date or utcnow().date().isoformat()
    row.action = row.action or "记录"
    row.detail = row.detail or ""
    extra = {key: value for key, value in log.items() if key not in LOG_DB_FIELDS and key != "id"}
    row.extra_data = json.dumps(extra, ensure_ascii=False) if extra else None
    return row


def _asset_query_for_user(db: Session, user: User):
    query = db.query(AssetLedgerAsset).filter(AssetLedgerAsset.deleted_at.is_(None))
    if _has_all_asset_access(user):
        return query
    allowed_departments = _allowed_asset_departments(user)
    return query.filter(AssetLedgerAsset.department.in_(allowed_departments or {""}))


def _log_query_for_user(db: Session, user: User):
    query = db.query(AssetLedgerLog).filter(AssetLedgerLog.deleted_at.is_(None))
    if _has_all_asset_access(user):
        return query
    allowed_departments = _allowed_asset_departments(user)
    return query.filter(AssetLedgerLog.department.in_(allowed_departments or {""}))


def _visible_asset_ledger_state_for_user(db: Session, user: User) -> dict:
    return {
        "importKey": "",
        "assets": [_asset_payload(row) for row in _asset_query_for_user(db, user).order_by(AssetLedgerAsset.id.desc()).all()],
        "logs": [_log_payload(row) for row in _log_query_for_user(db, user).order_by(AssetLedgerLog.id.desc()).all()],
    }


def _save_asset_ledger_state_for_user(db: Session, user: User, state: dict) -> dict:
    submitted_assets = state.get("assets") if isinstance(state.get("assets"), list) else []
    submitted_logs = state.get("logs") if isinstance(state.get("logs"), list) else []
    allowed_departments = _allowed_asset_departments(user)

    if _has_all_asset_access(user):
        assets_to_save = [asset for asset in submitted_assets if isinstance(asset, dict)]
        logs_to_save = [log for log in submitted_logs if isinstance(log, dict)]
        asset_scope_query = db.query(AssetLedgerAsset).filter(AssetLedgerAsset.deleted_at.is_(None))
        log_scope_query = db.query(AssetLedgerLog).filter(AssetLedgerLog.deleted_at.is_(None))
    else:
        assets_to_save = [
            asset for asset in submitted_assets
            if isinstance(asset, dict) and asset.get("department") in allowed_departments
        ]
        logs_to_save = [
            log for log in submitted_logs
            if isinstance(log, dict) and log.get("department") in allowed_departments
        ]
        asset_scope_query = db.query(AssetLedgerAsset).filter(
            AssetLedgerAsset.deleted_at.is_(None),
            AssetLedgerAsset.department.in_(allowed_departments or {""}),
        )
        log_scope_query = db.query(AssetLedgerLog).filter(
            AssetLedgerLog.deleted_at.is_(None),
            AssetLedgerLog.department.in_(allowed_departments or {""}),
        )

    saved_asset_ids = {_asset_client_id(asset) for asset in assets_to_save}
    saved_log_ids = {_log_client_id(log) for log in logs_to_save}
    for row in asset_scope_query.all():
        if row.client_id not in saved_asset_ids:
            row.deleted_at = utcnow()
            row.updated_at = utcnow()
    for row in log_scope_query.all():
        if row.client_id not in saved_log_ids:
            row.deleted_at = utcnow()
            row.updated_at = utcnow()
    for asset in assets_to_save:
        _upsert_asset_row(db, asset)
    for log in logs_to_save:
        _upsert_log_row(db, log)
    db.commit()
    return {"assets": assets_to_save, "logs": logs_to_save}


@app.post("/api/login")
async def api_login(payload: LoginPayload, request: Request, db: Session = Depends(get_db)):
    login = payload.username.strip().lower()
    user = db.query(User).filter(
        or_(User.email == login, User.username == payload.username.strip()),
        User.deleted_at.is_(None),
        User.is_active.is_(True),
    ).one_or_none()
    if user is None or not verify_password(payload.password, user.password_hash):
        raise HTTPException(status_code=401, detail="用户名或密码错误")
    user.last_activity_at = utcnow()
    request.session["user_id"] = user.id
    request.session["authenticated_at"] = utcnow().isoformat()
    _log_activity(db, user, "login", "auth", "用户登录")
    return {"ok": True, "user": _user_payload(user)}


@app.post("/api/logout")
async def api_logout(request: Request, db: Session = Depends(get_db)):
    user = _current_user(db, request)
    if user:
        _log_activity(db, user, "logout", "auth", "用户退出登录")
    request.session.clear()
    return {"ok": True}


@app.get("/api/me")
async def api_me(request: Request, db: Session = Depends(get_db)):
    user = _require_user(request, db)
    return {"user": _user_payload(user)}


def _fetch_fun_facts() -> list[dict]:
    request = UrlRequest(FUN_FACTS_API, headers={"User-Agent": "boyuan-internal-tools/1.0"})
    with urlopen(request, timeout=10) as response:
        payload = json.load(response)
    facts = payload.get("facts", []) if isinstance(payload, dict) else []
    if payload.get("ok") is not True or not isinstance(facts, list) or not facts:
        raise ValueError("FactFacts API returned no facts")
    return [fact for fact in facts if isinstance(fact, dict) and fact.get("text")][:10]


def _translate_fun_fact(text: str) -> str:
    query = urlencode({
        "ckey": settings.translation_api_key,
        "encoding": "json",
        "text": text,
    })
    request = UrlRequest(
        f"{TRANSLATION_API}?{query}",
        headers={"User-Agent": "boyuan-internal-tools/1.0"},
    )
    with urlopen(request, timeout=10) as response:
        payload = json.load(response)
    data = payload.get("data", {}) if isinstance(payload, dict) else {}
    result = data.get("result") if isinstance(data, dict) else None
    if payload.get("code") != 200 or not result:
        raise ValueError("Translation API returned no result")
    return str(result)


@app.get("/api/fun-facts")
async def api_fun_facts(request: Request, db: Session = Depends(get_db)):
    _require_user(request, db)
    try:
        facts = await asyncio.to_thread(_fetch_fun_facts)
        translations = await asyncio.gather(*(
            asyncio.to_thread(_translate_fun_fact, str(fact["text"])) for fact in facts
        ))
        return {"facts": [
            {
                "english": str(fact["text"]),
                "chinese": translated,
                "category": str(fact.get("category") or ""),
            }
            for fact, translated in zip(facts, translations)
        ]}
    except Exception as exc:
        logger.warning("Unable to fetch or translate fun facts: %s", exc)
        raise HTTPException(503, "暂时无法获取趣味知识") from exc


@app.get("/api/next-holiday")
async def api_next_holiday(request: Request, db: Session = Depends(get_db)):
    _require_user(request, db)
    today = date.fromisoformat(business_date())
    holiday = _next_statutory_holiday(today, await _holiday_rows(today.year))
    if holiday is None:
        raise HTTPException(503, "暂时无法获取下一法定节假日")
    return {"holiday": holiday}


@app.get("/api/roles")
async def api_roles(request: Request, db: Session = Depends(get_db)):
    _require_permission(request, db, "can_manage_users")
    roles = db.query(Role).filter(Role.deleted_at.is_(None)).order_by(Role.name).all()
    return {
        "roles": [
            {
                "name": role.name,
                "displayName": role.display_name,
                "scope": role.scope,
                "department": role.department,
            }
            for role in roles
        ]
    }


@app.get("/api/users")
async def api_users(request: Request, db: Session = Depends(get_db)):
    _require_permission(request, db, "can_manage_users")
    users = db.query(User).filter(
        User.deleted_at.is_(None),
        User.email != settings.initial_admin_email,
    ).order_by(User.created_at.desc()).all()
    return {
        "users": [
            {
                "id": user.id,
                "email": user.email,
                "displayName": user.display_name,
                "roles": _role_names(user),
                "roleDisplayNames": _role_display_names(user),
                "status": "active" if user.is_active and user.password_hash else "pending",
                "isActive": user.is_active,
                "hasPassword": bool(user.password_hash),
                "invitedAt": business_datetime(user.invited_at) or None,
                "passwordSetAt": business_datetime(user.password_set_at) or None,
                "lastActivityAt": business_datetime(user.last_activity_at) or None,
            }
            for user in users
        ]
    }


@app.post("/api/users/{user_id}/reset-password")
async def api_reset_user_password(user_id: int, request: Request, db: Session = Depends(get_db)):
    admin = _require_permission(request, db, "can_manage_users")
    user = db.query(User).filter(
        User.id == user_id,
        User.deleted_at.is_(None),
        User.email != settings.initial_admin_email,
    ).one_or_none()
    if not user:
        raise HTTPException(status_code=404, detail="用户不存在")
    if user.id == admin.id:
        raise HTTPException(status_code=400, detail="不能重置当前登录账号的密码")

    user.password_hash = None
    user.password_set_at = None
    user.is_active = False
    user.invited_at = utcnow()
    user.invited_by_user_id = admin.id
    user.updated_at = utcnow()
    db.commit()
    signup_url = str(request.url_for("page_signup")) + f"?email={quote(user.email)}"
    _log_activity(db, admin, "reset_password", "users", f"重置 {user.email} 的密码")
    return {"ok": True, "email": user.email, "signupUrl": signup_url}


@app.put("/api/users/{user_id}/status")
async def api_update_user_status(
    user_id: int,
    payload: UserStatusPayload,
    request: Request,
    db: Session = Depends(get_db),
):
    admin = _require_permission(request, db, "can_manage_users")
    user = db.query(User).filter(
        User.id == user_id,
        User.deleted_at.is_(None),
        User.email != settings.initial_admin_email,
    ).one_or_none()
    if not user:
        raise HTTPException(status_code=404, detail="用户不存在")
    if user.id == admin.id:
        raise HTTPException(status_code=400, detail="不能停用当前登录账号")
    if user.is_active == payload.is_active:
        return {"ok": True, "isActive": user.is_active}

    user.is_active = payload.is_active
    user.updated_at = utcnow()
    db.commit()
    action = "启用" if payload.is_active else "停用"
    _log_activity(db, admin, "update_user_status", "users", f"{action}用户 {user.email}")
    return {"ok": True, "isActive": user.is_active}


@app.put("/api/users/{user_id}/roles")
async def api_update_user_roles(
    user_id: int,
    payload: UserRolesPayload,
    request: Request,
    db: Session = Depends(get_db),
):
    admin = _require_permission(request, db, "can_manage_users")
    user = db.query(User).filter(
        User.id == user_id,
        User.deleted_at.is_(None),
        User.email != settings.initial_admin_email,
    ).one_or_none()
    if not user:
        raise HTTPException(status_code=404, detail="用户不存在")
    role_names = list(dict.fromkeys(payload.roles))
    if not role_names:
        raise HTTPException(status_code=400, detail="请至少选择一个角色")
    roles = db.query(Role).filter(Role.name.in_(role_names), Role.deleted_at.is_(None)).all()
    if len(roles) != len(role_names):
        raise HTTPException(status_code=400, detail="包含无效角色")
    if user.id == admin.id and not any(role.can_manage_users for role in roles):
        raise HTTPException(status_code=400, detail="不能移除当前登录账号的用户管理权限")
    old_role_names = sorted(_role_names(user))
    old_names = sorted(_role_display_names(user))
    new_role_names = sorted(role.name for role in roles)
    new_names = sorted(role.display_name for role in roles)
    if old_role_names == new_role_names:
        return {"ok": True, "roles": _role_names(user), "roleDisplayNames": old_names}
    user.roles = roles
    user.updated_at = utcnow()
    _log_activity(
        db, admin, "update_user_roles", "users",
        f"更新 {user.email} 权限：{'、'.join(old_names) or '无'} → {'、'.join(new_names)}",
    )
    return {"ok": True, "roles": new_role_names, "roleDisplayNames": new_names}


@app.post("/api/invitations")
async def api_invite(payload: InvitePayload, request: Request, db: Session = Depends(get_db)):
    admin = _require_permission(request, db, "can_manage_users")
    email = payload.email.strip().lower()
    if not is_allowed_email(email):
        raise HTTPException(status_code=400, detail="只允许 boyuanpharm.com 邮箱")
    if not payload.roles:
        raise HTTPException(status_code=400, detail="请至少选择一个角色")
    roles = db.query(Role).filter(Role.name.in_(payload.roles), Role.deleted_at.is_(None)).all()
    if len(roles) != len(set(payload.roles)):
        raise HTTPException(status_code=400, detail="包含无效角色")
    user = db.query(User).filter(User.email == email).one_or_none()
    if user and user.deleted_at is not None:
        raise HTTPException(status_code=400, detail="该邮箱对应用户已删除")
    if user and user.password_hash:
        raise HTTPException(status_code=400, detail="该用户已经完成注册")
    if user is None:
        user = User(
            email=email,
            username=email,
            display_name=payload.display_name or email.split("@", 1)[0],
            is_active=False,
            invited_at=utcnow(),
            invited_by_user_id=admin.id,
        )
        db.add(user)
    user.roles = roles
    user.is_active = False
    user.display_name = payload.display_name or user.display_name or email.split("@", 1)[0]
    user.invited_at = utcnow()
    user.invited_by_user_id = admin.id
    user.updated_at = utcnow()
    db.commit()
    signup_url = str(request.url_for("page_signup")) + f"?email={quote(email)}"
    _log_activity(db, admin, "invite_user", "users", f"邀请 {email}，角色：{', '.join(payload.roles)}")
    return {"ok": True, "email": email, "signupUrl": signup_url}


@app.post("/api/signup")
async def api_signup(payload: SignupPayload, request: Request, db: Session = Depends(get_db)):
    email = payload.email.strip().lower()
    if not is_allowed_email(email):
        raise HTTPException(status_code=400, detail="只允许 boyuanpharm.com 邮箱")
    if len(payload.password) < 8:
        raise HTTPException(status_code=400, detail="密码至少 8 位")
    user = db.query(User).filter(
        User.email == email,
        User.deleted_at.is_(None),
        User.is_active.is_(False),
        User.password_hash.is_(None),
    ).one_or_none()
    if not user:
        raise HTTPException(status_code=400, detail="该邮箱没有有效邀请，或账号已完成注册")
    user.password_hash = hash_password(payload.password)
    user.display_name = payload.display_name or user.display_name or email.split("@", 1)[0]
    user.is_active = True
    user.password_set_at = utcnow()
    user.last_activity_at = utcnow()
    request.session["user_id"] = user.id
    request.session["authenticated_at"] = utcnow().isoformat()
    _log_activity(db, user, "signup", "auth", "用户完成注册并设置密码")
    return {"ok": True, "user": _user_payload(user)}


@app.get("/api/activity-logs")
async def api_activity_logs(request: Request, db: Session = Depends(get_db)):
    _require_permission(request, db, "can_view_activity_logs")
    logs = db.query(ActivityLog).order_by(ActivityLog.activity_time.desc()).limit(200).all()
    return {
        "logs": [
            {
                "id": log.id,
                "userId": log.user_id,
                "userEmail": log.user.email if log.user else "",
                "activityTime": business_datetime(log.activity_time),
                "action": log.action,
                "target": log.target,
                "detail": log.detail,
            }
            for log in logs
        ]
    }


@app.post("/api/reconcile")
async def api_reconcile(
    request: Request,
    db: Session = Depends(get_db),
    warehouse: UploadFile = File(..., description="仓库原料库余额表 (.xls)"),
    mapping: UploadFile = File(..., description="代码对应表 (.xlsx)"),
    finance: UploadFile = File(..., description="财务系统原料库库存 (.xlsx)"),
):
    user = _require_permission(request, db, "can_update_reconcile")

    try:
        wh_bytes = await warehouse.read()
        mp_bytes = await mapping.read()
        fn_bytes = await finance.read()
    except Exception as exc:
        raise HTTPException(status_code=400, detail=f"文件读取失败：{exc}") from exc

    if not wh_bytes or not mp_bytes or not fn_bytes:
        raise HTTPException(status_code=400, detail="请上传全部三个文件")

    try:
        result = reconcile(wh_bytes, mp_bytes, fn_bytes)
    except Exception as exc:
        raise HTTPException(status_code=400, detail=f"解析或对账失败：{exc}") from exc

    _log_activity(db, user, "reconcile", "reconcile", "上传三份文件并完成原料库存对账")
    return JSONResponse(result)


@app.post("/api/export")
async def api_export(request: Request, db: Session = Depends(get_db)):
    user = _require_permission(request, db, "can_update_reconcile")
    try:
        result = await request.json()
    except Exception as exc:
        raise HTTPException(status_code=400, detail=f"无效的 JSON：{exc}") from exc
    if not isinstance(result, dict) or "summary" not in result:
        raise HTTPException(status_code=400, detail="缺少对账结果数据")

    xlsx_bytes = build_workbook(result)
    fname = f"对账结果_{datetime.now():%Y%m%d_%H%M%S}.xlsx"
    _log_activity(db, user, "export_reconcile", "reconcile", "导出对账结果 Excel")
    return Response(
        content=xlsx_bytes,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={
            "Content-Disposition": f"attachment; filename*=UTF-8''{quote(fname)}",
        },
    )


def _next_stock_order_no(db: Session) -> str:
    prefix = "BH" + business_date().replace("-", "")
    latest = db.query(StockOrder).filter(StockOrder.order_no.like(prefix + "-%")).order_by(StockOrder.order_no.desc()).first()
    number = int(latest.order_no.rsplit("-", 1)[-1]) + 1 if latest else 1
    return f"{prefix}-{number:04d}"


def _stock_log(db: Session, order: StockOrder, user: User, module: str, action: str,
               label: str, old_value: str = "", new_value: str = "", reason: str = "") -> None:
    db.add(StockOrderChangeLog(
        order_id=order.id, order_no=order.order_no, module=module, action=action,
        field_key=f"__{action}__", field_label=label, old_value=old_value,
        new_value=new_value, operator_id=user.id,
        operator_name=user.display_name or user.email, reason=reason,
    ))


def _sync_stock_warnings(db: Session, orders: list[StockOrder]) -> dict[int, list[StockOrderWarning]]:
    """Refresh warnings for many orders with a constant number of queries."""
    if not orders:
        return {}
    order_ids = [order.id for order in orders]
    existing_rows = db.query(StockOrderWarning).filter(StockOrderWarning.order_id.in_(order_ids)).all()
    existing_types: dict[int, set[str]] = {order_id: set() for order_id in order_ids}
    for row in existing_rows:
        existing_types[row.order_id].add(row.warning_type)
    for order in orders:
        sync_order_warnings(db, order, existing_types=existing_types[order.id])
    db.flush()
    rows = db.query(StockOrderWarning).filter(StockOrderWarning.order_id.in_(order_ids)).order_by(StockOrderWarning.occurred_at).all()
    grouped: dict[int, list[StockOrderWarning]] = {order_id: [] for order_id in order_ids}
    for row in rows:
        grouped[row.order_id].append(row)
    return grouped


@app.get("/api/stock-orders")
async def api_stock_orders(request: Request, q: str = "", order_type: str = "", incomplete: str = "",
                           date_from: str = "", date_to: str = "", page: int = 1,
                           page_size: int = 10, sort_by: str = "", sort_order: str = "asc",
                           db: Session = Depends(get_db)):
    _require_permission(request, db, "can_view_stock_orders")
    if bool(date_from) != bool(date_to):
        raise HTTPException(400, "开始日期和结束日期必须同时选择")
    query = db.query(StockOrder).filter(StockOrder.deleted_at.is_(None))
    if q.strip():
        like = f"%{q.strip()}%"
        query = query.filter(or_(StockOrder.order_no.like(like), StockOrder.customer_name.like(like),
                                 StockOrder.salesperson.like(like), StockOrder.cas.like(like), StockOrder.internal_name.like(like)))
    if order_type:
        query = query.filter(StockOrder.order_type == order_type)
    if date_from:
        query = query.filter(StockOrder.created_at >= datetime.fromisoformat(date_from) - timedelta(hours=settings.business_utc_offset_hours))
    if date_to:
        query = query.filter(StockOrder.created_at < datetime.fromisoformat(date_to) + timedelta(days=1) - timedelta(hours=settings.business_utc_offset_hours))
    if incomplete:
        key = incomplete.lower()
        query = query.filter(StockOrder.archive_status != "已取消")
        incomplete_filters = {
            "purchase": and_(
                StockOrder.purchase_completed_at.is_(None),
                StockOrder.purchase_not_required.is_(False),
                StockOrder.order_type != "现货留货",
            ),
            "采购": and_(
                StockOrder.purchase_completed_at.is_(None),
                StockOrder.purchase_not_required.is_(False),
                StockOrder.order_type != "现货留货",
            ),
            "production": and_(
                StockOrder.production_completed_at.is_(None),
                StockOrder.production_not_required.is_(False),
                StockOrder.order_type != "现货留货",
            ),
            "生产": and_(
                StockOrder.production_completed_at.is_(None),
                StockOrder.production_not_required.is_(False),
                StockOrder.order_type != "现货留货",
            ),
            "qc": and_(
                StockOrder.qc_completed_at.is_(None),
                StockOrder.qc_not_required.is_(False),
                StockOrder.order_type != "现货留货",
            ),
            "质量": and_(
                StockOrder.qc_completed_at.is_(None),
                StockOrder.qc_not_required.is_(False),
                StockOrder.order_type != "现货留货",
            ),
            "sales": StockOrder.actual_delivery == "",
            "销售": StockOrder.actual_delivery == "",
        }
        if key in incomplete_filters:
            query = query.filter(incomplete_filters[key])
    page = max(page, 1)
    page_size = page_size if page_size in {10, 20, 50, 100} else 10
    total = query.count()
    total_pages = max(1, (total + page_size - 1) // page_size)
    page = min(page, total_pages)
    sort_columns = {
        "quantity": cast(StockOrder.quantity, Numeric(20, 4)),
        "actual_delivery": case((StockOrder.actual_delivery == "", ""), else_=StockOrder.actual_delivery),
        "created_at": StockOrder.created_at,
        "updated_at": StockOrder.updated_at,
    }
    if sort_by in sort_columns:
        sort_column = sort_columns[sort_by]
        direction = sort_column.desc() if sort_order.lower() == "desc" else sort_column.asc()
        query = query.order_by(direction, StockOrder.id.desc())
    else:
        query = query.order_by(StockOrder.updated_at.desc(), StockOrder.id.desc())
    rows = query.offset((page - 1) * page_size).limit(page_size).all()
    warnings_by_order = _sync_stock_warnings(db, rows)
    payloads = [order_payload(db, row, warning_rows=warnings_by_order[row.id]) for row in rows]
    db.commit()
    return {"orders": payloads, "pagination": {"page": page, "pageSize": page_size, "total": total, "totalPages": total_pages}}


@app.get("/api/stock-orders/{order_id}")
async def api_stock_order(order_id: int, request: Request, db: Session = Depends(get_db)):
    user = _require_permission(request, db, "can_view_stock_orders")
    order = db.query(StockOrder).filter_by(id=order_id, deleted_at=None).one_or_none()
    if not order:
        raise HTTPException(404, "订单不存在")
    sync_order_warnings(db, order)
    db.flush()
    data = order_payload(db, order, include_locks=True)
    data["editableModules"] = sorted({module for module in {meta[2] for meta in FIELD_META.values()} if can_edit_module(user, module)})
    data["isAdmin"] = is_admin(user)
    db.commit()
    return {"order": data}


def _save_stock_order(db: Session, user: User, payload: StockOrderPayload, order: Optional[StockOrder] = None) -> StockOrder:
    fields = clean_fields(payload.fields)
    if not fields:
        raise HTTPException(400, "没有可保存的字段")
    is_new = order is None
    if is_new:
        if not (is_admin(user) or "sales" in user_modules(user)):
            raise HTTPException(403, "只有销售部门可以新建订单")
        order = StockOrder(order_no=_next_stock_order_no(db), created_by_user_id=user.id, updated_by_user_id=user.id)
        db.add(order)
        db.flush()
    elif order.archive_status == "已取消":
        raise HTTPException(400, "已取消订单不能修改")
    locks = field_locks(db, order)
    changes = []
    changed_modules = set()
    today = business_date()
    for key, value in fields.items():
        module = FIELD_META[key][2]
        old = getattr(order, key)
        # Full-form and older cached clients may include unchanged fields from
        # completed or unrelated modules. Only enforce module rules when the
        # submitted value would actually change persisted data.
        if old == value:
            continue
        if not can_edit_module(user, module):
            raise HTTPException(403, f"当前角色不能修改{FIELD_META[key][0]}字段")
        if order.order_type == "现货留货" and module in {"purchase", "production", "qc"}:
            raise HTTPException(400, "现货留货无需采购、生产和QC填写")
        done_key = "sales_completed_at" if module == "sales" else next((values[1] for name, values in MODULES.items() if name == module), None)
        if done_key and getattr(order, done_key) and not is_admin(user):
            raise HTTPException(403, f"{FIELD_META[key][0]}已完成确认")
        if locks.get(key) and not is_admin(user):
            raise HTTPException(403, f"{FIELD_META[key][1]}已跨日锁定")
        if locks.get(key) and is_admin(user) and not payload.reason.strip():
            raise HTTPException(400, "管理员修改跨日锁定字段必须填写修正原因")
        setattr(order, key, value)
        changed_modules.add(module)
        changes.append(f"{FIELD_META[key][1]}：{old or '空'} → {value or '空'}")
        update = db.query(StockOrderFieldUpdate).filter_by(order_id=order.id, field_key=key).one_or_none()
        if update is None:
            update = StockOrderFieldUpdate(order_id=order.id, field_key=key)
            db.add(update)
        update.updated_date = today
        update.updated_by_user_id = user.id
    responded_fields = {
        "purchase": "purchase_responded_at", "production": "production_responded_at", "qc": "qc_responded_at",
    }
    for module, timestamp_field in responded_fields.items():
        module_values = [getattr(order, key) for key, meta in FIELD_META.items() if meta[2] == module]
        has_meaningful_value = any(value not in (None, "", False, "[]") for value in module_values)
        if module in changed_modules and has_meaningful_value and not getattr(order, timestamp_field):
            setattr(order, timestamp_field, utcnow())
    if "actual_delivery" in fields and order.actual_delivery and not order.sales_completed_at:
        order.sales_completed_at = utcnow()
        _stock_log(db, order, user, "sales", "complete", "完成确认", new_value="已填写实际交货时间")
    if changes:
        order.updated_by_user_id = user.id
        order.updated_at = utcnow()
        _stock_log(db, order, user, "all", "create" if is_new else "save", "新建订单" if is_new else "保存更新",
                   new_value="\n".join(changes), reason=payload.reason.strip())
    sync_order_warnings(db, order)
    db.flush()
    db.refresh(order)
    return order


@app.post("/api/stock-orders")
async def api_create_stock_order(payload: StockOrderPayload, request: Request, db: Session = Depends(get_db)):
    user = _require_permission(request, db, "can_update_stock_orders")
    order = _save_stock_order(db, user, payload)
    _log_activity(db, user, "create_stock_order", "stock-orders", order.order_no)
    return {"ok": True, "order": order_payload(db, order, True)}


@app.put("/api/stock-orders/{order_id}")
async def api_update_stock_order(order_id: int, payload: StockOrderPayload, request: Request, db: Session = Depends(get_db)):
    user = _require_permission(request, db, "can_update_stock_orders")
    order = db.query(StockOrder).filter_by(id=order_id, deleted_at=None).one_or_none()
    if not order:
        raise HTTPException(404, "订单不存在")
    order = _save_stock_order(db, user, payload, order)
    _log_activity(db, user, "update_stock_order", "stock-orders", order.order_no)
    return {"ok": True, "order": order_payload(db, order, True)}


@app.post("/api/stock-orders/{order_id}/complete")
async def api_complete_stock_order(order_id: int, payload: StockCompletePayload, request: Request, db: Session = Depends(get_db)):
    user = _require_permission(request, db, "can_update_stock_orders")
    if payload.module not in {*MODULES, "sales"}:
        raise HTTPException(400, "完成模块无效")
    if not can_edit_module(user, payload.module):
        raise HTTPException(403, "当前角色不能完成该模块")
    order = db.query(StockOrder).filter_by(id=order_id, deleted_at=None).one_or_none()
    if not order:
        raise HTTPException(404, "订单不存在")
    if order.archive_status == "已取消" or (order.order_type == "现货留货" and payload.module != "sales"):
        raise HTTPException(400, "该订单不能完成此模块")
    if payload.module == "sales":
        due_key, done_key, skip_key, label = "", "sales_completed_at", "", "销售填写完成"
    else:
        due_key, done_key, skip_key, label = MODULES[payload.module]
    if getattr(order, done_key):
        raise HTTPException(400, "该模块已经完成")
    module_fields = {k: v for k, v in payload.fields.items() if k in FIELD_META and FIELD_META[k][2] == payload.module}
    if module_fields:
        _save_stock_order(db, user, StockOrderPayload(fields=module_fields), order)
    if due_key and not getattr(order, due_key) and not getattr(order, skip_key):
        raise HTTPException(400, "请先填写预计日期或勾选无需处理")
    setattr(order, done_key, utcnow())
    order.updated_at = utcnow()
    order.updated_by_user_id = user.id
    responded_field = {"purchase": "purchase_responded_at", "production": "production_responded_at", "qc": "qc_responded_at"}.get(payload.module)
    if responded_field and not getattr(order, responded_field):
        setattr(order, responded_field, utcnow())
    _stock_log(db, order, user, payload.module, "complete", "完成确认", new_value=label)
    sync_order_warnings(db, order)
    _log_activity(db, user, "complete_stock_order", "stock-orders", f"{order.order_no} · {label}")
    return {"ok": True, "order": order_payload(db, order, True)}


@app.post("/api/stock-orders/{order_id}/cancel")
async def api_cancel_stock_order(order_id: int, payload: StockCancelPayload, request: Request, db: Session = Depends(get_db)):
    user = _require_permission(request, db, "can_update_stock_orders")
    if not is_admin(user):
        raise HTTPException(403, "只有管理员可以取消订单")
    if not payload.reason.strip():
        raise HTTPException(400, "请填写取消原因")
    order = db.query(StockOrder).filter_by(id=order_id, deleted_at=None).one_or_none()
    if not order:
        raise HTTPException(404, "订单不存在")
    order.archive_status = "已取消"
    order.cancelled_at = utcnow()
    order.cancelled_reason = payload.reason.strip()
    order.updated_at = utcnow()
    _stock_log(db, order, user, "all", "cancel", "取消订单", "未归档", "已取消", payload.reason.strip())
    _log_activity(db, user, "cancel_stock_order", "stock-orders", order.order_no)
    return {"ok": True}


def _stock_month_range(month: str) -> tuple[datetime, datetime]:
    try:
        local_start = datetime.strptime(month, "%Y-%m")
    except ValueError as exc:
        raise HTTPException(400, "月份格式无效") from exc
    local_end = (local_start.replace(day=28) + timedelta(days=4)).replace(day=1)
    offset = timedelta(hours=settings.business_utc_offset_hours)
    return local_start - offset, local_end - offset


@app.get("/api/stock-orders-history")
async def api_stock_order_history(request: Request, order: str = "", operator: str = "", month: str = "", db: Session = Depends(get_db)):
    user = _require_permission(request, db, "can_view_stock_orders")
    if month and not is_admin(user):
        raise HTTPException(403, "只有管理员可以按月查询订单")
    query = db.query(StockOrderChangeLog)
    if order:
        query = query.filter(StockOrderChangeLog.order_no.like(f"%{order}%"))
    if operator:
        query = query.filter(StockOrderChangeLog.operator_name.like(f"%{operator}%"))
    if month:
        start, end = _stock_month_range(month)
        query = query.join(StockOrder, StockOrder.id == StockOrderChangeLog.order_id).filter(StockOrder.created_at >= start, StockOrder.created_at < end)
    logs = query.order_by(StockOrderChangeLog.operated_at.desc()).limit(1000).all()
    return {"logs": [{
        "id": row.id, "orderNo": row.order_no, "module": row.module, "action": row.action,
        "label": row.field_label, "oldValue": row.old_value, "newValue": row.new_value,
        "operator": row.operator_name, "operatedAt": business_datetime(row.operated_at), "reason": row.reason,
    } for row in logs]}


def _stock_export_orders(db: Session, order: str, operator: str, month: str):
    query = db.query(StockOrder).filter(StockOrder.deleted_at.is_(None))
    if order:
        query = query.filter(StockOrder.order_no.like(f"%{order}%"))
    if operator:
        ids = db.query(StockOrderChangeLog.order_id).filter(StockOrderChangeLog.operator_name.like(f"%{operator}%")).distinct()
        query = query.filter(StockOrder.id.in_(ids))
    if month:
        start, end = _stock_month_range(month)
        query = query.filter(StockOrder.created_at >= start, StockOrder.created_at < end)
    return query.order_by(StockOrder.created_at.desc()).all()


def _csv_download(filename: str, rows: list[list]) -> Response:
    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerows(rows)
    return Response(
        content="\ufeff" + output.getvalue(), media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": f"attachment; filename*=UTF-8''{quote(filename)}"},
    )


@app.get("/api/stock-orders-export/{kind}")
async def api_stock_order_export(kind: str, request: Request, order: str = "", operator: str = "", month: str = "", db: Session = Depends(get_db)):
    user = _require_permission(request, db, "can_view_stock_orders")
    if not is_admin(user):
        raise HTTPException(403, "只有管理员可以导出备货订单数据")
    orders = _stock_export_orders(db, order, operator, month)
    _sync_stock_warnings(db, orders)
    order_ids = [item.id for item in orders]
    if kind == "orders":
        rows = [["订单号","订单类型","创建时间","内部简称","CAS","数量","业务员","客户名称","提需求日期","交货期需求","实际交货","采购明细","采购预计到货","生产预计完成","QC预计完成","销售完成","采购完成","生产完成","QC完成","订单状态","取消原因"]]
        for item in orders:
            rows.append([item.order_no,item.order_type,business_datetime(item.created_at),item.internal_name,item.cas,item.quantity,item.salesperson,item.customer_name,item.demand_date,item.delivery_requirement,item.actual_delivery,item.purchase_items,item.arrival_date,item.expected_delivery_date,item.coa_time,business_datetime(item.sales_completed_at),business_datetime(item.purchase_completed_at),business_datetime(item.production_completed_at),business_datetime(item.qc_completed_at),item.archive_status,item.cancelled_reason])
        filename = "备货订单.csv"
    elif kind == "performance":
        warnings = db.query(StockOrderWarning).filter(StockOrderWarning.order_id.in_(order_ids or [-1])).order_by(StockOrderWarning.occurred_at).all()
        rows = [["订单号","责任部门","预警类型","预警内容","截止时间","预警时间","详情"], *[[w.order_no,w.department,w.warning_type,w.message,business_datetime(w.threshold_at),business_datetime(w.occurred_at),w.detail] for w in warnings]]
        filename = "备货订单绩效.csv"
    elif kind == "changes":
        query = db.query(StockOrderChangeLog).filter(StockOrderChangeLog.order_id.in_(order_ids or [-1]))
        if operator:
            query = query.filter(StockOrderChangeLog.operator_name.like(f"%{operator}%"))
        logs = query.order_by(StockOrderChangeLog.operated_at).all()
        rows = [["时间","订单号","模块","动作","字段","原内容","新内容","操作人","修改说明"], *[[business_datetime(x.operated_at),x.order_no,x.module,x.action,x.field_label,x.old_value,x.new_value,x.operator_name,x.reason] for x in logs]]
        filename = "备货订单修改记录.csv"
    else:
        raise HTTPException(404, "导出类型不存在")
    _log_activity(db, user, f"export_stock_{kind}", "stock-orders", f"导出 {len(orders)} 个订单")
    return _csv_download(filename, rows)


@app.get("/api/asset-ledger/state")
async def api_asset_ledger_state(request: Request, db: Session = Depends(get_db)):
    user = _require_permission(request, db, "can_view_asset_ledger")
    return JSONResponse(_visible_asset_ledger_state_for_user(db, user))


@app.post("/api/asset-ledger/state")
async def api_asset_ledger_state_save(request: Request, db: Session = Depends(get_db)):
    user = _require_permission(request, db, "can_update_asset_ledger")
    try:
        state = await request.json()
    except Exception as exc:
        raise HTTPException(status_code=400, detail=f"无效的 JSON：{exc}") from exc
    if not isinstance(state, dict):
        raise HTTPException(status_code=400, detail="固定资产台账数据格式错误")
    saved = _save_asset_ledger_state_for_user(db, user, state)
    _log_activity(
        db,
        user,
        "update_asset_ledger",
        "asset-ledger",
        f"保存固定资产台账：assets={len(saved['assets'])}, logs={len(saved['logs'])}",
    )
    return {"ok": True}


_NO_STORE = {"Cache-Control": "no-store, no-cache, must-revalidate", "Pragma": "no-cache"}


@app.get("/login")
async def page_login(request: Request, db: Session = Depends(get_db)):
    if request.query_params.get("force") == "1":
        request.session.clear()
        return FileResponse(STATIC_DIR / "login.html", headers=_NO_STORE)
    if _current_user(db, request):
        return RedirectResponse(url="/", status_code=302, headers=_NO_STORE)
    return FileResponse(STATIC_DIR / "login.html", headers=_NO_STORE)


@app.get("/signup")
async def page_signup(request: Request, db: Session = Depends(get_db)):
    if _current_user(db, request):
        return RedirectResponse(url="/", status_code=302, headers=_NO_STORE)
    return FileResponse(STATIC_DIR / "signup.html", headers=_NO_STORE)


@app.get("/")
async def page_index(request: Request, db: Session = Depends(get_db)):
    user = _current_user(db, request)
    if not user:
        return RedirectResponse(url="/login", status_code=302, headers=_NO_STORE)
    if not (
        _has_permission(user, "can_view_reconcile")
        or _has_permission(user, "can_view_asset_ledger")
        or _has_permission(user, "can_manage_users")
        or _has_permission(user, "can_view_activity_logs")
        or _has_permission(user, "can_view_stock_orders")
    ):
        raise HTTPException(status_code=403, detail="当前账号没有权限")
    return FileResponse(STATIC_DIR / "index.html", headers=_NO_STORE)


@app.get("/asset-ledger/")
async def page_asset_ledger(request: Request, db: Session = Depends(get_db)):
    if not _current_user(db, request):
        return RedirectResponse(url="/login", status_code=302, headers=_NO_STORE)
    return RedirectResponse(url="/", status_code=302, headers=_NO_STORE)


app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")
