"""FastAPI application: Boyuan Internal Tools."""

from __future__ import annotations

import os
import json
import secrets
from html import escape
from pathlib import Path
from typing import Optional

from datetime import datetime
from urllib.parse import quote

from fastapi import Depends, FastAPI, File, HTTPException, Request, UploadFile
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse, RedirectResponse, Response
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel
from sqlalchemy import or_
from sqlalchemy.orm import Session
from starlette.middleware.sessions import SessionMiddleware

from app.auth import (
    hash_password,
    is_allowed_email,
    utcnow,
    verify_password,
)
from app.database import SessionLocal, engine, get_db
from app.schema import ActivityLog, AssetLedgerAsset, AssetLedgerLog, Role, User, init_database
from app.services.export import build_workbook
from app.services.reconcile import reconcile

APP_DIR = Path(__file__).resolve().parent
PROJECT_DIR = APP_DIR.parent
STATIC_DIR = APP_DIR / "static"

# In production, set BOYUAN_SESSION_SECRET via env. For local dev a random
# per-process key is fine — sessions just don't survive a server restart.
SESSION_SECRET = os.environ.get("BOYUAN_SESSION_SECRET") or secrets.token_urlsafe(32)

app = FastAPI(title="Boyuan Internal Tools")
app.add_middleware(
    SessionMiddleware,
    secret_key=SESSION_SECRET,
    session_cookie="boyuan_session",
    same_site="lax",
    https_only=False,  # set True behind HTTPS
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
            "viewActivityLogs": _has_permission(user, "can_view_activity_logs"),
            "manageUsers": _has_permission(user, "can_manage_users"),
        },
        "lastActivityAt": user.last_activity_at.isoformat() if user.last_activity_at else None,
    }


def _current_user(db: Session, request: Request) -> Optional[User]:
    user_id = request.session.get("user_id")
    if not user_id:
        return None
    user = db.get(User, user_id)
    if not user or not user.is_active or user.deleted_at is not None:
        request.session.clear()
        return None
    user.last_activity_at = utcnow()
    db.commit()
    db.refresh(user)
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


class InvitePayload(BaseModel):
    email: str
    roles: list[str]
    display_name: Optional[str] = None


class SignupPayload(BaseModel):
    email: str
    password: str
    display_name: Optional[str] = None


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
    ).one_or_none()
    if user is None or not user.is_active or not verify_password(payload.password, user.password_hash):
        raise HTTPException(status_code=401, detail="用户名或密码错误")
    user.last_activity_at = utcnow()
    request.session["user_id"] = user.id
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
                "activityTime": log.activity_time.isoformat(),
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
    ):
        raise HTTPException(status_code=403, detail="当前账号没有权限")
    return FileResponse(STATIC_DIR / "index.html", headers=_NO_STORE)


@app.get("/asset-ledger/")
async def page_asset_ledger(request: Request, db: Session = Depends(get_db)):
    if not _current_user(db, request):
        return RedirectResponse(url="/login", status_code=302, headers=_NO_STORE)
    return RedirectResponse(url="/", status_code=302, headers=_NO_STORE)


app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")
