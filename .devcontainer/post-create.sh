#!/bin/bash
set -e

echo "Setting up development environment..."

# Create virtual environment with uv
uv venv --clear /workspaces/climate_group_helper/.venv
source /workspaces/climate_group_helper/.venv/bin/activate

# Install dependencies from pyproject.toml
uv pip install ".[dev]"

echo "Development environment ready!"
echo ""
echo "To run tests:  pytest"
echo "To lint:       ruff check ."
echo "To format:     ruff format ."
