.PHONY: smoke-celebrity

smoke-celebrity:
	docker compose up -d --no-build api worker
	python3 scripts/smoke_celebrity.py
