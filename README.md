# boyuan-internal-tools

<!--
Author: liuzhiwei_jn
Date: 2026-11-24
Version: v1.1.1
-->

Internal FastAPI tools for Boyuan operations.

## Project Structure

```text
app/
  config.py            Environment-backed runtime settings
  main.py              FastAPI routes and session handling
  db/                  Database sessions, models, and seed/bootstrap logic
  services/           Reconciliation and Excel export logic
  static/             Browser UI assets
assets/
  logo-original.png   Source logo asset
```

## Run Locally

Copy `.env.example` to `.env` in the project root (PowerShell: `Copy-Item .env.example .env`, only if `.env` does not already exist). Edit `BOYUAN_DATABASE_URL` with your local database username and password, then run:

```bash
pip install -r requirements.txt
uvicorn app.main:app --reload
```

The app listens on `http://127.0.0.1:8000`.

By default the app connects to MySQL at:

```text
mysql+pymysql://localdbuser:localdbpassword@127.0.0.1:3306/boyuan_internal_tools
```

Override it with `BOYUAN_DATABASE_URL` if needed. On first startup the app creates the database tables and bootstraps `root@boyuanpharm.com` with password `123123`.
The fixed-asset ledger is stored in MySQL tables.

## Configuration

The app automatically loads the project-root `.env` file regardless of the working directory. Existing environment variables take precedence over `.env`, followed by code defaults. Restart the app after editing `.env`. The local `.env` is ignored by Git; commit only `.env.example`.

Database URL format: `mysql+pymysql://username:password@host:port/database`. URL-encode special characters in the username or password, such as `@`, `#`, and `/`.

Docker Compose also reads `.env`. When connecting from Docker Desktop to MySQL on the host, use `host.docker.internal` instead of `127.0.0.1`.

Production deployments should set these values in `.env`:

```text
BOYUAN_DATABASE_URL=mysql+pymysql://user:password@host:3306/boyuan_internal_tools
BOYUAN_SESSION_SECRET=<random-long-secret>
BOYUAN_SESSION_MAX_AGE=28800
BOYUAN_SESSION_COOKIE_SECURE=true
BOYUAN_BUSINESS_UTC_OFFSET=8
BOYUAN_INITIAL_ADMIN_EMAIL=root@boyuanpharm.com
BOYUAN_INITIAL_ADMIN_PASSWORD=<strong-initial-password>
```

`BOYUAN_ROOT_PASSWORD` remains supported as a backward-compatible alias for the initial administrator password. The insecure database and administrator defaults are intended for local development only.

## Tests

The core stock-order regression suite uses an in-memory SQLite database:

```bash
BOYUAN_DATABASE_URL=sqlite:///:memory: python -m unittest discover -s tests -v
```

## OA integration

Before starting this version against an existing MySQL database, manually apply `sql/2026-11-18_oa_sso.sql`. Startup checks require the OA phone column and credential table. Configure OA login and notification settings using `.env.example`; restart the application after changes. The existing cafeteria features remain available.
