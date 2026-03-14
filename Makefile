.PHONY: test test-backend test-frontend install install-backend install-frontend

test: test-backend test-frontend

test-backend:
	cd backend && pip install -q -r requirements.txt -r requirements-dev.txt && pytest tests/ -v

test-frontend:
	cd frontend && npm install --silent && npm run test -- --run

install: install-backend install-frontend

install-backend:
	pip install -r backend/requirements.txt -r backend/requirements-dev.txt

install-frontend:
	cd frontend && npm install
