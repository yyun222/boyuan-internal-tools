# boyuan-internal-tools

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

```bash
pip install -r requirements.txt
uvicorn app.main:app --reload
```

The app listens on `http://127.0.0.1:8000`.

By default the app connects to MySQL at:

```text
mysql+pymysql://root:123123@127.0.0.1:3306/boyuan_internal_tools
```

Override it with `BOYUAN_DATABASE_URL` if needed. On first startup the app creates the database tables and bootstraps `root@boyuanpharm.com` with password `123123`.
The fixed-asset ledger is stored in MySQL tables.

## Configuration

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

The insecure database and administrator defaults are intended for local development only.

## Tests

The core stock-order regression suite uses an in-memory SQLite database:

```bash
BOYUAN_DATABASE_URL=sqlite:///:memory: python -m unittest discover -s tests -v
```
