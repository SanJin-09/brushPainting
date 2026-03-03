.PHONY: api worker web test

api:
	uvicorn services.api.app.main:app --reload --port 8000

worker:
	celery -A services.worker.celery_app.celery_app worker -Q default --loglevel=info

web:
	cd apps/web && npm run dev

test:
	pytest -q
