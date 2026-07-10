# boyuan-internal-tools

Internal FastAPI tools for Boyuan operations.

## Project Structure

```text
app/
  main.py              FastAPI routes and session handling
  services/           Reconciliation and Excel export logic
  static/             Browser UI assets
data/
  ledger-state.json   Local/runtime asset ledger state
samples/
  test_data.js        Imported sample asset data
assets/
  logo-original.png   Source logo asset
```

## Run Locally

```bash
pip install -r requirements.txt
uvicorn app.main:app --reload
```

The app listens on `http://127.0.0.1:8000`.
