all: tests lint build-check

.PHONY: tests
tests:
	cd src && python3 -m unittest discover -v -s ../tests

lint:
	# Requires ruff and basedpyright: python -m pip install basedpyright ruff
	ruff check
	basedpyright
	ruff format --check --diff

lint-github:
	# Requires ruff and basedpyright: python -m pip install basedpyright ruff
	ruff check --output-format=github
	basedpyright
	ruff format --check --diff

build-check:
	# Requires Flit: python -m pip install flit
	# Build, install locally, and attempt to run
	flit build
	flit install
	ocsf-schema-compiler -h

pre-publish-check:
	./scripts/pre-publish-check.sh

pre-test-publish-check:
	./scripts/pre-publish-check.sh --test

clean:
	rm -rf dist
	rm -rf .ruff_cache
	find src tests \
		-type d -name __pycache__ -delete \
		-or -type f -name '*.py[cod]' -delete \
		-or -type f -name '*$py.class' -delete

clean-all: clean
	rm -rf .venv

cloc:
	cloc --exclude-dir=.venv,.idea .
