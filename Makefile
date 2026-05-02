# ============================================================================
# Project shortcuts. Run `make help` to see all targets.
# ============================================================================
.PHONY: help dev down logs ps clean build \
        backend-shell frontend-shell db-shell \
        migrate migrate-create migrate-prod \
        prod-up prod-down \
        test fmt lint

COMPOSE_DEV  := docker compose -f infra/docker-compose.yml
COMPOSE_PROD := docker compose -f infra/docker-compose.yml -f infra/docker-compose.prod.yml

help:                         ## Show this help
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) | awk 'BEGIN {FS = ":.*?## "}; {printf "  \033[36m%-20s\033[0m %s\n", $$1, $$2}'

# ---------------------------------------------------------------------------
# Local dev
# ---------------------------------------------------------------------------
dev:                          ## Start dev stack (postgres, ollama, backend, frontend)
	$(COMPOSE_DEV) up -d --build
	@echo ""
	@echo "  Backend  -> http://localhost:8000"
	@echo "  Frontend -> http://localhost:8501"
	@echo "  Docs     -> http://localhost:8000/docs"
	@echo ""
	@echo "  Tail logs:  make logs"

down:                         ## Stop dev stack (keeps data)
	$(COMPOSE_DEV) down

clean:                        ## Stop dev stack AND wipe volumes (data loss!)
	$(COMPOSE_DEV) down -v

logs:                         ## Tail logs from all services
	$(COMPOSE_DEV) logs -f --tail=200

ps:                           ## List running containers
	$(COMPOSE_DEV) ps

build:                        ## Rebuild images without starting
	$(COMPOSE_DEV) build

backend-shell:                ## Open a shell in the backend container
	$(COMPOSE_DEV) exec backend bash

frontend-shell:               ## Open a shell in the frontend container
	$(COMPOSE_DEV) exec frontend bash

db-shell:                     ## Open psql against the dev DB
	$(COMPOSE_DEV) exec postgres psql -U postgres -d aiassistant

# ---------------------------------------------------------------------------
# Migrations
# ---------------------------------------------------------------------------
migrate:                      ## Apply all migrations to the dev DB
	$(COMPOSE_DEV) exec backend alembic upgrade head

migrate-create:               ## Create a new migration. Usage: make migrate-create m="add foo"
	$(COMPOSE_DEV) exec backend alembic revision --autogenerate -m "$(m)"

migrate-prod:                 ## Apply migrations to PRODUCTION DB (RDS). Use carefully!
	$(COMPOSE_PROD) run --rm backend alembic upgrade head

# ---------------------------------------------------------------------------
# Production
# ---------------------------------------------------------------------------
prod-up:                      ## Start production stack on EC2
	$(COMPOSE_PROD) up -d --build

prod-down:                    ## Stop production stack
	$(COMPOSE_PROD) down

# ---------------------------------------------------------------------------
# Code quality
# ---------------------------------------------------------------------------
test:                         ## Run pytest in the backend container
	$(COMPOSE_DEV) exec backend pytest -v

fmt:                          ## Format code with ruff
	cd backend && ruff format app/
	cd frontend && ruff format .

lint:                         ## Lint with ruff
	cd backend && ruff check app/
	cd frontend && ruff check .