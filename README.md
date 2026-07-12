# boyuan-internal-tools

Internal FastAPI tools for Boyuan operations.

## Project Structure

```text
app/
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
