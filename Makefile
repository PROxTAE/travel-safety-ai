# Convenience wrappers (00_GIT_DOCKER_DELIVERY_RULES §11). ไม่มี make (Windows) ใช้คำสั่ง docker compose ตรง ๆ ที่อยู่ในแต่ละ target ได้เลย
COMPOSE_DEV = docker compose -f compose.yaml -f compose.dev.yaml
COMPOSE     = docker compose -f compose.yaml

.PHONY: help core up down ps logs compose-validate lint typecheck test-unit test-contract test-integration test-e2e

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
	@echo "TODO: pnpm --filter web lint ; docker compose run --rm <svc> uv run ruff check ."

typecheck:       ## typecheck ทุก service
	@echo "TODO: pnpm --filter web typecheck ; docker compose run --rm <svc> uv run mypy app"

test-unit:       ## unit tests
	@echo "TODO: pnpm --filter web test ; docker compose run --rm <svc> uv run pytest -q"

test-contract:   ## contract tests (tests/contract)
	@echo "TODO"

test-integration: ## integration smoke (tests/integration)
	@echo "TODO"

test-e2e:        ## Playwright E2E (tests/e2e)
	@echo "TODO"
