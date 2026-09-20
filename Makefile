# Convenience wrappers (00_GIT_DOCKER_DELIVERY_RULES §11). ไม่มี make (Windows) ใช้คำสั่ง docker compose ตรง ๆ ที่อยู่ในแต่ละ target ได้เลย
COMPOSE_DEV = docker compose -f compose.yaml -f compose.dev.yaml
COMPOSE     = docker compose -f compose.yaml

.PHONY: help core up down ps logs compose-validate lint typecheck test-unit test-contract test-integration test-e2e \
        contracts-install contracts-lint contracts-generate contracts-verify api-shell api-migrate

help:            ## แสดง target ทั้งหมด
	@grep -E '^[a-zA-Z_-]+:.*?## ' $(MAKEFILE_LIST) | awk 'BEGIN {FS = ":.*?## "}; {printf "  %-18s %s\n", $$1, $$2}'

core:            ## เปิดเฉพาะ infra กลาง (postgres redis qdrant keycloak) แบบ dev
	$(COMPOSE_DEV) up -d --wait

up:              ## เปิดทุกอย่าง (core + app) แบบ dev
	$(COMPOSE_DEV) --profile app up -d --build

down:            ## ปิดทุกกล่อง (ข้อมูลใน volume ยังอยู่)
	$(COMPOSE_DEV) --profile app down

ps:              ## สถานะกล่อง
	$(COMPOSE_DEV) ps

logs:            ## ดู log: make logs S=api
	$(COMPOSE_DEV) logs -f --tail=200 $(S)

compose-validate: ## ตรวจไฟล์ compose อ่านได้
	$(COMPOSE_DEV) --profile app config > /dev/null && echo "compose OK"

# --- ด้านล่างนี้แต่ละ module เติมคำสั่งของตัวเองใน PR (ตอนนี้ยังไม่มี service จริง) ---
lint:            ## lint ทุก service
	$(MAKE) contracts-lint
	cd services/api && uv run ruff check . && uv run ruff format --check .
	@echo "TODO: pnpm --filter web lint ; module อื่นเติม ruff ของตัวเองที่นี่"

typecheck:       ## typecheck ทุก service
	cd packages/contracts && npm run --silent typecheck
	cd services/api && uv run mypy app
	@echo "TODO: pnpm --filter web typecheck ; module อื่นเติม mypy ของตัวเองที่นี่"

test-unit:       ## unit tests (ไม่แตะ Docker)
	cd services/api && uv run pytest -m "not integration"
	@echo "TODO: pnpm --filter web test ; module อื่นเติม pytest ของตัวเองที่นี่"

test-contract:   ## contract tests (tests/contract + packages/contracts)
	cd packages/contracts && npm run --silent check
	uv run --project tests/contract pytest tests/contract

contracts-install: ## ติดตั้ง tooling ของ packages/contracts (ครั้งแรก/หลังแก้ package.json)
	cd packages/contracts && npm ci

contracts-lint:  ## lint OpenAPI + validate JSON Schema/examples
	cd packages/contracts && npm run --silent lint && npm run --silent validate:schemas && npm run --silent validate:examples

contracts-generate: ## regenerate bundled OpenAPI + TS/Python clients (ต้องมี uv)
	cd packages/contracts && npm run --silent generate

contracts-verify: ## regenerate แล้ว fail ถ้า working tree เปลี่ยน (สิ่งที่ CI ตรวจ)
	cd packages/contracts && ./scripts/check-generated-clean.sh

test-integration: ## integration smoke (ต้องมี Docker; Testcontainers จะ pull image เอง)
	cd services/api && uv run pytest -m integration
	@echo "TODO: tests/integration/ เมื่อมีหลาย service ให้เชื่อมกัน"

api-shell:       ## เปิด shell ในกล่อง api
	$(COMPOSE_DEV) --profile core --profile app exec api sh

api-migrate:     ## รัน alembic upgrade head ในกล่อง api
	$(COMPOSE_DEV) --profile core --profile app run --rm api alembic upgrade head

test-e2e:        ## Playwright E2E (tests/e2e)
	@echo "TODO"
