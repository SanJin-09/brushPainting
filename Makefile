.PHONY: api worker web test

api:
	uvicorn services.api.app.main:app --reload --host $${API_BIND_HOST:-127.0.0.1} --port 8000

worker:
	python -m services.worker.rq_worker

web:
	cd apps/web && npm run dev -- --host $${WEB_BIND_HOST:-127.0.0.1}

test:
	pytest -q
