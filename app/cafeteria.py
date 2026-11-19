"""Cafeteria routes using the site's account and invitation services."""

import re

from fastapi import Depends, HTTPException, Request
from pydantic import BaseModel, Field
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.auth import CAFETERIA_DEFAULT_PASSWORD, hash_password, utcnow
from app.db import get_db
from app.db.models import Role, User
from app.services.cafeteria_access import (
    CAFETERIA_ROLES, DELEGATED_ROLES, SITES, cafeteria_jobs, refresh_locked_roles,
)


class StaffRoles(BaseModel):
    roles: list[str]


class StaffInvitation(StaffRoles):
    email: str | None = Field(default=None, max_length=255)
    username: str | None = Field(default=None, max_length=40)
    display_name: str | None = Field(default=None, max_length=120)


def site_roles(site, *, delegated=False):
    return {
        name: title for name, (scope, job, title) in CAFETERIA_ROLES.items()
        if scope == site and (not delegated or job in DELEGATED_ROLES)
    }


def register_cafeteria(app, require_user, invite_user, log_activity):
    def supervisor(site, request, db):
        user = require_user(request, db)
        if site not in SITES or "supervisor" not in cafeteria_jobs(user, site):
            raise HTTPException(403, "没有此食堂的人员管理权限")
        return user

    @app.get("/api/cafeteria/access")
    def access(request: Request, db: Session = Depends(get_db)):
        user = require_user(request, db)
        return {
            "sites": [
                {"id": site, "name": label, "jobs": sorted(jobs), "manageStaff": "supervisor" in jobs}
                for site, label in SITES.items() if (jobs := cafeteria_jobs(user, site))
            ],
        }

    @app.get("/api/cafeteria/{site}/staff")
    def staff(site: str, request: Request, db: Session = Depends(get_db)):
        supervisor(site, request, db)
        editable = site_roles(site, delegated=True)
        local = site_roles(site)
        users = db.query(User).filter(
            User.deleted_at.is_(None),
            User.roles.any(Role.name.in_(local) & Role.deleted_at.is_(None)),
        ).order_by(User.display_name, User.id).all()
        return {"roles": editable, "users": [
            {
                "id": user.id, "email": user.email, "username": user.username, "displayName": user.display_name,
                "mustSetPassword": user.email is None and user.password_set_at is None,
                "roles": [r.name for r in user.roles if not r.deleted_at and r.name in editable],
                "roleDisplayNames": [local[r.name] for r in user.roles if not r.deleted_at and r.name in local],
                "pending": not bool(user.password_hash),
            }
            for user in users
        ]}

    @app.post("/api/cafeteria/{site}/invitations")
    def invite(site: str, payload: StaffInvitation, request: Request, db: Session = Depends(get_db)):
        actor = supervisor(site, request, db)
        if not payload.roles or not set(payload.roles) <= site_roles(site, delegated=True).keys():
            raise HTTPException(400, "请选择本食堂可分配的岗位")
        email = (payload.email or "").strip()
        username = payload.username or ""
        if bool(email) == bool(username):
            raise HTTPException(400, "请选择邮箱邀请或用户名邀请")
        if email:
            return invite_user(payload, request, db, actor, new_only=True)
        if not re.fullmatch(r"[A-Za-z0-9_]{3,40}", username):
            raise HTTPException(400, "用户名须为 3–40 位英文字母、数字或下划线")
        username = username.lower()
        roles = db.query(Role).filter(Role.name.in_(payload.roles), Role.deleted_at.is_(None)).all()
        if len(roles) != len(set(payload.roles)):
            raise HTTPException(400, "包含无效岗位")
        user = User(email=None, username=username, display_name=(payload.display_name or "").strip() or username,
                    password_hash=hash_password(CAFETERIA_DEFAULT_PASSWORD), is_active=True,
                    invited_at=utcnow(), invited_by_user_id=actor.id, roles=roles)
        try:
            db.add(user)
            db.flush()
        except IntegrityError:
            db.rollback()
            raise HTTPException(409, "该用户名已被使用") from None
        log_activity(db, actor, "invite_cafeteria_username", "users", f"{SITES[site]} · 邀请 {username}")
        return {"ok": True, "username": username, "mustSetPassword": True}

    @app.put("/api/cafeteria/{site}/staff/{user_id}/roles")
    def update_roles(site: str, user_id: int, payload: StaffRoles, request: Request, db: Session = Depends(get_db)):
        actor = supervisor(site, request, db)
        editable = site_roles(site, delegated=True)
        if not set(payload.roles) <= editable.keys():
            raise HTTPException(400, "包含不可分配的岗位")
        user = db.query(User).filter(User.id == user_id, User.deleted_at.is_(None)).with_for_update().one_or_none()
        local = site_roles(site)
        if user is not None:
            refresh_locked_roles(db, user)
        if user is None or not any(not r.deleted_at and r.name in local for r in user.roles):
            raise HTTPException(404, "该人员不属于本食堂，请联系网站管理员")
        roles = db.query(Role).filter(Role.name.in_(payload.roles), Role.deleted_at.is_(None)).all()
        if len(roles) != len(set(payload.roles)):
            raise HTTPException(400, "包含无效岗位")
        user.roles = [role for role in user.roles if role.name not in editable] + roles
        user.updated_at = utcnow()
        log_activity(db, actor, "update_cafeteria_roles", "users",
                     f"{SITES[site]} · {user.email or user.username} · {', '.join(payload.roles) or '撤销普通岗位'}")
        return {"ok": True}
