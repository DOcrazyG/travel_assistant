.PHONY: install format lint typecheck test check run migrate revision up down pre-commit-install

install:
	uv sync --all-groups

format:
	uv run ruff format .

lint:
	uv run ruff check .

typecheck:
	uv run pyright

test:
	uv run pytest

check: lint typecheck test

run:
	uv run alembic upgrade head
	uv run uvicorn app.main:app --reload

migrate:
	uv run alembic upgrade head

revision:
	uv run alembic revision --autogenerate -m "$(message)"

up:
	docker compose up -d postgres valkey

down:
	docker compose down

pre-commit-install:
	uv run pre-commit install
