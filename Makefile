.PHONY: install test lint run login plugin-install plugin-build

install:
	python -m pip install -e '.[dev]'

test:
	pytest -q

lint:
	ruff check app tests

run:
	TG_MOCK=true TG_SGK_API_KEY=dev-secret-key uvicorn app.main:app --reload

login:
	python -m app.login

plugin-install:
	cd openclaw-plugin && npm install

plugin-build:
	cd openclaw-plugin && npm run build
