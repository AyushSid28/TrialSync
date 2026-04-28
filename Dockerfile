# Layer with Python and some shared environment variables
FROM python:3.13.9-slim AS build 
ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1

# Layer for installing Python dependencies
FROM build AS dependencies
ENV PIP_DISABLE_PIP_VERSION_CHECK=1

# uv sync ignores VIRTUAL_ENV; without this, the venv is created as ./.venv and /opt/venv never exists
ENV UV_PROJECT_ENVIRONMENT=/opt/venv
ENV VIRTUAL_ENV=/opt/venv
ENV PATH="/opt/venv/bin:$PATH"

# Static uv binary (install.sh puts uv in ~/.local/bin, which is not on PATH here)
COPY --from=ghcr.io/astral-sh/uv:latest /uv /usr/local/bin/uv

# Install build-essential for building Python wheels
RUN --mount=type=cache,target=/var/cache/apt,sharing=locked --mount=type=cache,target=/var/lib/apt,sharing=locked \
    apt-get update --fix-missing && \
    apt-get install --no-install-recommends -y \
    build-essential \
    ca-certificates

# README.md required by pyproject.toml (hatchling metadata) during editable/sync resolution
COPY pyproject.toml uv.lock README.md ./
RUN uv sync --frozen --no-dev --no-editable
# Layer for production
FROM dependencies AS production
WORKDIR /app

COPY --from=dependencies /opt/venv /opt/venv
COPY . .
ENV VIRTUAL_ENV=/opt/venv
ENV PATH="/opt/venv/bin:$PATH"

EXPOSE 8000

CMD ["uvicorn", "src.main:app", "--host", "0.0.0.0", "--port", "8000"]