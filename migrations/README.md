# Alembic migrations

Migrations live under this package (`migrations/`, see `script_location` in `alembic.ini`).

## Sync database URL

The FastAPI app uses **asyncpg** (`postgresql+asyncpg://...`). Alembic uses a **sync** SQLAlchemy engine (`psycopg2-binary`).

`migrations/env.py` reads `DATABASE_URL` from settings and strips `+asyncpg` automatically. Use a standard URL in `.env`, for example:

```env
DATABASE_URL=postgresql://user:password@localhost:5432/ulalo
```

If you use `postgresql+asyncpg://` for the app, the same value works: Alembic normalizes it for offline/online runs.

## New migration filenames

`alembic.ini` sets `file_template` so new scripts are named like
`YYYYMMDD_HHMMSS_<revision_id>_<slug>.py` (UTC/local per machine clock when you run the command).

## Commands

From the project root (with venv activated and Postgres running):

```bash
alembic upgrade head
alembic revision --autogenerate -m "describe change"
```

After autogenerate, review the generated file before applying.
