.PHONY: install format lint typecheck test check run pre-commit-install

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
	uv run uvicorn app.main:app --reload

pre-commit-install:
	uv run pre-commit install
