#!/bin/bash

# Start script for FastAPI application

set -e

echo "Starting FastAPI Clean Architecture Application..."

# Activate virtual environment if it exists
if [ -d ".venv" ]; then
    source .venv/bin/activate
fi

# Run migrations
echo "Running database migrations..."
alembic upgrade head

# Start the application
echo "Starting uvicorn server..."
uvicorn src.main:app --host 0.0.0.0 --port 8000 --reload
