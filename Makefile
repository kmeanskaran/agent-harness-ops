.PHONY: up down fresh logs restart

# Start all services (uses cache)
up:
	docker compose up --build

# Fresh rebuild — no cache, then start
fresh:
	docker compose down
	docker compose build --no-cache
	docker compose up

# Stop and remove containers
down:
	docker compose down

# Tail logs for all services
logs:
	docker compose logs -f

# Restart a specific service: make restart s=worker
restart:
	docker compose restart $(s)
