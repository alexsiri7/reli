.PHONY: test test-backend install install-backend build dev

test: test-backend

test-backend:
	uv run pytest backend/tests/

install: install-backend

install-backend:
	uv sync --frozen

build:
	docker compose build

dev:
	uvicorn backend.main:app --reload --port 8000
