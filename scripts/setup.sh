#!/bin/bash

# Setup script for FastAPI application

set -e

echo "Setting up FastAPI Clean Architecture Application..."

# Check if UV is installed
if ! command -v uv &> /dev/null; then
    echo "UV is not installed. Please install UV first."
    echo "Visit: https://github.com/astral-sh/uv"
    exit 1
fi

# Create virtual environment
echo "Creating virtual environment with UV..."
uv venv

# Activate virtual environment
source .venv/bin/activate

# Install dependencies
echo "Installing dependencies..."
uv pip install -e .
uv pip install -e ".[dev]"

# Copy environment file
if [ ! -f ".env" ]; then
    echo "Creating .env file from .env.example..."
    cp .env.example .env
    echo "Please update .env with your configuration."
fi

echo ""
echo "Setup complete!"
echo ""
echo "Next steps:"
echo "1. Update .env with your database credentials"
echo "2. Create your PostgreSQL database"
echo "3. Run: alembic upgrade head"
echo "4. Run: ./scripts/start.sh"
