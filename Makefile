.PHONY: build deploy-ui test evals local

build:
	sh build.sh

deploy-ui:
	sh deploy-ui.sh

test:
	python -m unittest discover -s tests

evals:
	python evals/run_evals.py

local:
	python -m src.dev_server
