"""Database connection setup."""

from __future__ import annotations

import os

from sqlalchemy import create_engine, text
from sqlalchemy.engine import make_url
from sqlalchemy.orm import sessionmaker

DEFAULT_DATABASE_URL = "mysql+pymysql://root:123123@127.0.0.1:3306/boyuan_internal_tools"
DATABASE_URL = os.environ.get("BOYUAN_DATABASE_URL", DEFAULT_DATABASE_URL)


def _create_database_if_needed(database_url: str) -> None:
    url = make_url(database_url)
    if not url.database:
        return
    server_url = url.set(database=None)
    engine = create_engine(server_url, future=True, pool_pre_ping=True)
    db_name = url.database.replace("`", "``")
    with engine.begin() as conn:
        conn.execute(text(f"CREATE DATABASE IF NOT EXISTS `{db_name}` CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci"))
    engine.dispose()


def _make_engine():
    _create_database_if_needed(DATABASE_URL)
    return create_engine(DATABASE_URL, future=True, pool_pre_ping=True)


engine = _make_engine()
SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False, future=True)


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
