.PHONY: tests
tests:
	cd src && python3 -m unittest discover -v -s ../tests

lint:
	# Requires ruff and basedpyright: python -m pip install ruff basedpyright
	ruff check
	basedpyright
	ruff format --check --diff

lint-github:
	# Requires ruff and basedpyright: python -m pip install ruff basedpyright
	ruff check --output-format=github
	basedpyright
	ruff format --check --diff

dist-check:
	# Requires build and twine: python -m pip install build twine
	python -m build
	twine check dist/*

clean-dist:
	rm -rf dist
	rm -rf src/ocsf_schema_compiler.egg-info

clean: clean-dist
	rm -rf .ruff_cache
	find src tests \
		-type d -name __pycache__ -delete \
		-or -type f -name '*.py[cod]' -delete \
		-or -type f -name '*$py.class' -delete

clean-all: clean
	rm -rf .venv

cloc:
	cloc --exclude-dir=.venv,.idea .
