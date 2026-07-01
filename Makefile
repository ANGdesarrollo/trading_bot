.PHONY: up down logs operator reconciler

up:
	docker compose up -d

down:
	docker compose down

logs:
	docker compose logs -f

operator:
	PYTHONPATH=src .venv/bin/python3 src/__main__.py

reconciler:
	PYTHONPATH=src .venv/bin/python3 src/reconciler.py
