"""FastAPI application: Boyuan Internal Tools."""

from __future__ import annotations

import os
import json
import secrets
from pathlib import Path

from datetime import datetime
from urllib.parse import quote

from fastapi import FastAPI, File, HTTPException, Request, UploadFile
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse, RedirectResponse, Response
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel
from starlette.middleware.sessions import SessionMiddleware

from app.services.export import build_workbook
from app.services.reconcile import reconcile

APP_DIR = Path(__file__).resolve().parent
PROJECT_DIR = APP_DIR.parent
STATIC_DIR = APP_DIR / "static"
ASSET_LEDGER_HTML = STATIC_DIR / "asset-ledger.html"
ASSET_LEDGER_STATE = PROJECT_DIR / "data" / "ledger-state.json"

# In production, set BOYUAN_SESSION_SECRET via env. For local dev a random
# per-process key is fine — sessions just don't survive a server restart.
SESSION_SECRET = os.environ.get("BOYUAN_SESSION_SECRET") or secrets.token_urlsafe(32)

# Single hard-coded user for now. Replace with a real user store later.
USERS = {"root": "123123"}

app = FastAPI(title="Boyuan Internal Tools")
app.add_middleware(
    SessionMiddleware,
    secret_key=SESSION_SECRET,
    session_cookie="boyuan_session",
    same_site="lax",
    https_only=False,  # set True behind HTTPS
)


def _current_user(request: Request) -> str | None:
    return request.session.get("user")


class LoginPayload(BaseModel):
    username: str
    password: str


def _read_asset_ledger_state() -> dict:
    if not ASSET_LEDGER_STATE.exists():
        return {"assets": [], "logs": []}
    try:
        return json.loads(ASSET_LEDGER_STATE.read_text(encoding="utf-8"))
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"固定资产台账数据读取失败：{exc}") from exc


def _write_asset_ledger_state(state: dict) -> None:
    safe_state = {
        "importKey": str(state.get("importKey", "")),
        "assets": state.get("assets") if isinstance(state.get("assets"), list) else [],
        "logs": state.get("logs") if isinstance(state.get("logs"), list) else [],
    }
    ASSET_LEDGER_STATE.parent.mkdir(parents=True, exist_ok=True)
    tmp = ASSET_LEDGER_STATE.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(safe_state, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp.replace(ASSET_LEDGER_STATE)


@app.post("/api/login")
async def api_login(payload: LoginPayload, request: Request):
    expected = USERS.get(payload.username)
    if expected is None or expected != payload.password:
        raise HTTPException(status_code=401, detail="用户名或密码错误")
    request.session["user"] = payload.username
    return {"ok": True, "user": payload.username}


@app.post("/api/logout")
async def api_logout(request: Request):
    request.session.clear()
    return {"ok": True}


@app.get("/api/me")
async def api_me(request: Request):
    user = _current_user(request)
    if not user:
        raise HTTPException(status_code=401, detail="未登录")
    return {"user": user}


@app.post("/api/reconcile")
async def api_reconcile(
    request: Request,
    warehouse: UploadFile = File(..., description="仓库原料库余额表 (.xls)"),
    mapping: UploadFile = File(..., description="代码对应表 (.xlsx)"),
    finance: UploadFile = File(..., description="财务系统原料库库存 (.xlsx)"),
):
    if not _current_user(request):
        raise HTTPException(status_code=401, detail="未登录")

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

    return JSONResponse(result)


@app.post("/api/export")
async def api_export(request: Request):
    if not _current_user(request):
        raise HTTPException(status_code=401, detail="未登录")
    try:
        result = await request.json()
    except Exception as exc:
        raise HTTPException(status_code=400, detail=f"无效的 JSON：{exc}") from exc
    if not isinstance(result, dict) or "summary" not in result:
        raise HTTPException(status_code=400, detail="缺少对账结果数据")

    xlsx_bytes = build_workbook(result)
    fname = f"对账结果_{datetime.now():%Y%m%d_%H%M%S}.xlsx"
    return Response(
        content=xlsx_bytes,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={
            "Content-Disposition": f"attachment; filename*=UTF-8''{quote(fname)}",
        },
    )


@app.get("/api/asset-ledger/state")
async def api_asset_ledger_state(request: Request):
    if not _current_user(request):
        raise HTTPException(status_code=401, detail="未登录")
    return JSONResponse(_read_asset_ledger_state())


@app.post("/api/asset-ledger/state")
async def api_asset_ledger_state_save(request: Request):
    if not _current_user(request):
        raise HTTPException(status_code=401, detail="未登录")
    try:
        state = await request.json()
    except Exception as exc:
        raise HTTPException(status_code=400, detail=f"无效的 JSON：{exc}") from exc
    if not isinstance(state, dict):
        raise HTTPException(status_code=400, detail="固定资产台账数据格式错误")
    _write_asset_ledger_state(state)
    return {"ok": True}


_NO_STORE = {"Cache-Control": "no-store, no-cache, must-revalidate", "Pragma": "no-cache"}


@app.get("/login")
async def page_login(request: Request):
    if _current_user(request):
        return RedirectResponse(url="/", status_code=302, headers=_NO_STORE)
    return FileResponse(STATIC_DIR / "login.html", headers=_NO_STORE)


@app.get("/")
async def page_index(request: Request):
    if not _current_user(request):
        return RedirectResponse(url="/login", status_code=302, headers=_NO_STORE)
    return FileResponse(STATIC_DIR / "index.html", headers=_NO_STORE)


@app.get("/asset-ledger/")
async def page_asset_ledger(request: Request):
    if not _current_user(request):
        return RedirectResponse(url="/login", status_code=302, headers=_NO_STORE)
    html = ASSET_LEDGER_HTML.read_text(encoding="utf-8")
    state = json.dumps(_read_asset_ledger_state(), ensure_ascii=False).replace("<", "\\u003c")
    html = html.replace(
        '<script src="/static/asset_data.js"></script>',
        (
            "<script>"
            "window.SERVER_MODE=true;"
            "window.STATE_API_PATH='/api/asset-ledger/state';"
            f"window.SERVER_STATE={state};"
            "</script>\n  <script src=\"/static/asset_data.js\"></script>"
        ),
    )
    return HTMLResponse(html, headers=_NO_STORE)


app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")
