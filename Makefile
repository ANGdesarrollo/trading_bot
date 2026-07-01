.PHONY: up down logs ps build operator-local reconciler-local

up:
	docker compose up -d --build

down:
	docker compose down

logs:
	docker compose logs -f

ps:
	docker compose ps

build:
	docker compose build

operator-local:
	PYTHONPATH=src .venv/bin/python3 src/__main__.py

reconciler-local:
	PYTHONPATH=src .venv/bin/python3 src/reconciler.py
