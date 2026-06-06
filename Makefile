.PHONY: api worker web test

api:
	uvicorn services.api.app.main:app --reload --port 8000

worker:
	python -m services.worker.rq_worker

web:
	cd apps/web && npm run dev

test:
	pytest -q
