.PHONY: up down test batch openapi samples
up:        ## start API + MinIO
	cp -n .env.example .env || true
	docker compose up --build
down:
	docker compose down
test:      ## unit + API + end-to-end tests, no API keys needed
	cp -n .env.example .env || true
	docker compose run --rm --no-deps -e STORAGE_BACKEND=local api pytest -q
batch:     ## run samples/ against the running service, write results/
	docker compose run --rm --no-deps api python -m cli.batch_runner --api http://api:8000 --input samples --out /data/results
openapi:
	python scripts/export_openapi.py
samples:
	python scripts/make_samples.py
