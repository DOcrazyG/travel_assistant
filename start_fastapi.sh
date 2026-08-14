#!/bin/sh

set -eu

project_root=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
cd "$project_root"

uv run alembic upgrade head
uv run python scripts/setup_langgraph_checkpoints.py

exec uv run python -m app.main
