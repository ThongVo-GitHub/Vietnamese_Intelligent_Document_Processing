.PHONY: install test run check compose-up compose-down compose-ps compose-logs

install:
	python -m pip install -e "./backend[dev]"

test:
	python -m pytest backend/tests -q

run:
	python -m uvicorn app.main:app --app-dir backend --reload --host 0.0.0.0 --port 8000

check:
	python -m pytest backend/tests -q
	docker compose config --quiet

compose-up:
	docker compose up -d --build

compose-down:
	docker compose down

compose-ps:
	docker compose ps

compose-logs:
	docker compose logs --tail=100 -f