.PHONY: install prepull picks precompute fixtures smoke api backend verify clean-data reset-news

install:
	.venv/bin/pip install -r requirements.txt

prepull:
	.venv/bin/python scripts/prepull.py --mode=demo

picks:
	.venv/bin/python scripts/pick_demo_day.py

precompute:
	.venv/bin/python scripts/precompute_breakdowns.py --all

fixtures:
	.venv/bin/python scripts/record_fixtures.py

smoke:
	.venv/bin/python -m pytest tests/ -v -x --ignore=tests/integration

api backend:
	.venv/bin/uvicorn backend.main:app --port 8000 --reload

verify: smoke
	.venv/bin/python -m pytest tests/integration -v

clean-data:
	find data/cache -mindepth 1 -not -name '.gitkeep' -delete
	find data/llm_fixtures -mindepth 1 -not -name '.gitkeep' -delete
	find data/templates -mindepth 1 -not -name '.gitkeep' -delete

reset-news:
	curl -X POST http://localhost:8000/admin/reset_news_cooldowns

# ----- Frontend -----
.PHONY: frontend-install frontend-dev frontend-build frontend-test-unit frontend-test-e2e

frontend-install:
	cd frontend && npm install

frontend-dev:
	cd frontend && npm run dev

frontend-build:
	cd frontend && npm run build

frontend-test-unit:
	cd frontend && npx vitest run lib

frontend-test-e2e:
	cd frontend && npx playwright test
