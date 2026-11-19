"""Site-scoped roles stored in the application's existing role tables."""

from sqlalchemy.orm.attributes import set_committed_value

SITES = {"jiyang": "济阳", "yucheng": "禹城"}
LOCAL_ROLES = {"supervisor": "食堂主管", "buyer": "采购员", "store": "验收／仓管员", "kitchen": "厨房／领用人"}
DELEGATED_ROLES = frozenset({"buyer", "store", "kitchen"})
CAFETERIA_ROLES = {
    f"cafeteria_{site}_{job}": (site, job, f"食堂 · {label} · {title}")
    for site, label in SITES.items()
    for job, title in LOCAL_ROLES.items()
}
CAFETERIA_ROLES.update({
    "cafeteria_manager": (None, "manager", "食堂 · 公司管理负责人"),
    "cafeteria_finance": (None, "finance", "食堂 · 财务只读"),
    "cafeteria_admin": (None, "admin", "食堂 · 系统管理员"),
})
ALL_CAFETERIA_JOBS = frozenset(job for _, job, _ in CAFETERIA_ROLES.values())


def cafeteria_jobs(user, site):
    if site not in SITES:
        return set()
    if any(role.deleted_at is None and role.name == "admin" for role in user.roles):
        return ALL_CAFETERIA_JOBS
    return {
        job
        for role in user.roles
        if role.deleted_at is None and role.name in CAFETERIA_ROLES
        for scope, job, _ in (CAFETERIA_ROLES[role.name],)
        if scope is None or scope == site
    }


def has_cafeteria_access(user):
    return any(cafeteria_jobs(user, site) for site in SITES)


def refresh_locked_roles(db, user):
    from app.db.models.user import Role, user_roles

    roles = db.query(Role).join(user_roles, user_roles.c.role_id == Role.id).filter(
        user_roles.c.user_id == user.id,
    ).with_for_update().all()
    set_committed_value(user, "roles", roles)
