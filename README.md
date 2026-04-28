# Ulalo Backend

FastAPI service for Ulalo: REST API, agents, and PostgreSQL via SQLAlchemy (async). Dependencies are managed with [uv](https://docs.astral.sh/uv/).

## Prerequisites

- Python 3.11 or newer
- [uv](https://docs.astral.sh/uv/getting-started/installation/) installed
- PostgreSQL (local or remote) for full functionality

## Quick start (local)

```bash
cd ulalo-backend

# Install dependencies into a project virtualenv (creates .venv by default)
uv sync

# Environment
cp .env.example .env
# Edit .env: set DATABASE_URL, SECRET_KEY, and any other required values.

# Apply database migrations
uv run alembic upgrade head

# Run the API (development, with reload)
uv run uvicorn src.main:app --reload --host 0.0.0.0 --port 8000
```

Open [http://localhost:8000/docs](http://localhost:8000/docs) for Swagger UI.

## Quick start (Docker)

```bash
cp .env.example .env   # configure DATABASE_URL and secrets for your environment

docker compose build
docker compose up api
```

The API listens on port **8000** (mapped to the host in `docker-compose.yml`). Ensure `DATABASE_URL` in `.env` is reachable from the container (e.g. `host.docker.internal` on Docker Desktop, or your DB service name on Compose networks).

## Project layout

| Path | Purpose |
|------|---------|
| `src/main.py` | FastAPI application entry |
| `src/api/` | Routes and HTTP API |
| `src/core/` | Settings, logging |
| `src/db/` | SQLAlchemy models and session |
| `src/agents/` | Agent workflows and prompts |
| `src/repository/` | Data access helpers |
| `src/schemas/` | Pydantic schemas |
| `migrations/` | Alembic migration scripts |
| `tests/` | Pytest suite |

## Common commands

```bash
# Run tests
uv run pytest

# Format / lint (after installing dev deps: uv sync --all-extras or dev group as needed)
uv run ruff check .
uv run black .

# New migration (after model changes)
uv run alembic revision --autogenerate -m "describe change"
uv run alembic upgrade head
```

## Configuration

See `.env.example` for variables: database URL, JWT settings, CORS, Logfire, etc.

## Production notes

- Set `DEBUG=False` and use a strong `SECRET_KEY`.
- Run behind a reverse proxy with TLS; tune `WORKERS` and pooling for your load.
- Prefer `uv sync --frozen` in CI/Docker (lockfile pinned in `uv.lock`).
