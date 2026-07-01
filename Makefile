.PHONY: up down logs operator reconciler

up:
	docker compose up -d

down:
	docker compose down

logs:
	docker compose logs -f

operator:
	cd src && ../.venv/bin/python3 -m src

reconciler:
	cd src && ../.venv/bin/python3 -m reconciler
