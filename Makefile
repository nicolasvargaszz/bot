# Common developer entry points. `make help` lists them.

.PHONY: help install test lint buffer report stack stack-down

help:
	@grep -E '^[a-z-]+:.*## ' $(MAKEFILE_LIST) | awk -F':.*## ' '{printf "  %-12s %s\n", $$1, $$2}'

install: ## Create/refresh the virtualenv dependencies
	pip install -r requirements.txt

test: ## Run the pytest suite
	pytest

lint: ## Run ruff over src and tests
	ruff check src tests

buffer: ## Run the message buffer service locally with reload
	PYTHONPATH=src uvicorn autobots.services.message_buffer.app:app --host 0.0.0.0 --port 8081 --reload

report: ## Pilot report for INSTANCE (make report INSTANCE=cliente-main DAYS=7)
	PYTHONPATH=src python -m autobots.reporting.pilot_report --instance $(INSTANCE) --days $(or $(DAYS),7)

stack: ## Start the full local stack (postgres, redis, evolution, n8n, buffer)
	docker compose up -d

stack-down: ## Stop the local stack
	docker compose down
