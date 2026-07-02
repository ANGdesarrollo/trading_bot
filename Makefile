.DEFAULT_GOAL := help
.PHONY: help up down logs ps build operator-local reconciler-local api-local frontend test postgres api frontend-detached

help: ## Show this help
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) | \
		sort | \
		awk 'BEGIN {FS = ":.*?## "}; {printf "  \033[36m%-18s\033[0m %s\n", $$1, $$2}'

up: ## Build and start all services (postgres, ingestion, operator, reconciler, api)
	docker compose up -d --build

postgres: ## Start only the postgres service (detached)
	docker compose up -d postgres

api: ## Start only the api service in docker (detached, starts postgres if needed)
	docker compose up -d --build api

frontend-detached: ## Start the candle viewer dev server in the background (logs to frontend/dev.log)
	cd frontend && nohup pnpm dev > dev.log 2>&1 &

down: ## Stop and remove all services
	docker compose down

logs: ## Follow logs from all services
	docker compose logs -f

ps: ## Show status of all services
	docker compose ps

build: ## Build all service images without starting them
	docker compose build

operator-local: ## Run the trading loop locally (no docker)
	PYTHONPATH=src .venv/bin/python3 src/__main__.py

reconciler-local: ## Run the reconciler locally (no docker)
	PYTHONPATH=src .venv/bin/python3 src/reconciler.py

api-local: ## Run the candle HTTP API locally on port 8001 (no docker)
	PYTHONPATH=src .venv/bin/python3 src/api.py

ingestion-polygon-local: ## Run the Polygon candle ingestion locally (no docker)
	PYTHONPATH=src .venv/bin/python3 src/ingestion_polygon.py

frontend: ## Run the candle viewer dev server on port 5173
	cd frontend && pnpm dev

test: ## Run the test suite
	uv run python -m pytest
