.PHONY: tests
tests:
	cd src && python3 -m unittest discover -v -s ../tests

lint:
	# Requires ruff and pyright: python -m pip install build twine
	ruff check
	pyright
	ruff format --check --diff

lint-github:
	# Requires ruff and pyright: python -m pip install build twine
	ruff check --output-format=github
	pyright
	ruff format --check --diff

dist-check:
	# Requires build and twine: python -m pip install build twine
	python -m build
	twine check dist/*

clean:
	rm -rf dist
	rm -rf src/ocsf_schema_compiler.egg-info
	rm -rf .ruff_cache
	find src tests \
		-type d -name __pycache__ -delete \
		-or -type f -name '*.py[cod]' -delete \
		-or -type f -name '*$py.class' -delete

cloc:
	cloc --exclude-dir=.venv,.idea .
