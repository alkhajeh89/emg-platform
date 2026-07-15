.PHONY: bootstrap up down logs lint fmt test pre-commit new-service branch-protection

bootstrap: ## One-time local setup: pre-commit hooks + local infra
	@echo "==> Installing pre-commit hooks"
	pip install --quiet pre-commit || true
	pre-commit install
	@echo "==> Bootstrapping local infrastructure"
	$(MAKE) up
	@echo "==> Bootstrap complete. See docs/engineering/onboarding.md"

up: ## Start local orchestration (Postgres, Redis, Keycloak, Neo4j, Qdrant)
	docker compose -f docker-compose.yml up -d

down: ## Stop local orchestration
	docker compose -f docker-compose.yml down

logs: ## Tail local orchestration logs
	docker compose -f docker-compose.yml logs -f

lint: ## Run lint/static analysis across all workspace packages
	./tools/scripts/run-lint.sh

fmt: ## Auto-format all workspace packages
	./tools/scripts/run-fmt.sh

test: ## Run unit tests across all workspace packages
	./tools/scripts/run-tests.sh

pre-commit: ## Run pre-commit hooks against all files
	pre-commit run --all-files

new-service: ## Scaffold a new backend service: make new-service NAME=identity
	./tools/scripts/new-service.sh $(NAME)

branch-protection: ## Apply branch protection rules via GitHub API (requires gh auth)
	./tools/scripts/configure-branch-protection.sh
