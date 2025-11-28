# OCSF Schema Compiler
This is a Python library and command-line tool for compiling the Open Cybersecurity Schema Framework (OCSF) schema, specifically the schema at https://github.com/ocsf/ocsf-schema.

## Getting started
There are three ways to use the OCSF Schema Compiler:
1. As a command-line tool, installed from PyPI.
2. As a library, installed from PyPI.
3. As a developer working on this project.

Python version 3.14 or later is required.

## Using `ocsf-schema-compiler` as a command-line tool
Create a virtual environment then install with `pip`. For example:
```shell
python3 -m venv .venv
source ./.venv/bin/activate
python -m pip install ocsf-schema-compiler
```

Running from this environment is now a matter of calling `ocsf-schema-compiler`:
```shell
ocsf-schema-compiler -h
```

The basic usage is passing the base directory of a schema to the compiler and capturing the output to a file.
```shell
ocsf-schema-compiler path/to/ocsf-schema > schema.json
```

## Using `ocsf-schema-compiler` as a library
Create a virtual environment then install with `pip`. For example:
```shell
python3 -m venv .venv
source ./.venv/bin/activate
pip install ocsf-schema-compiler
```

The compiler is implemented in the `SchemaCompiler` class. The class constructor the same options as the command-line tool. The class's `compile` method does the heavy lifting, returning a `dict` containing the compiled schema. More specifically, `compiler` returns an `ocsf_schema_compiler.jsonish.JObject`, which is a type alias for JSON-compatible `dict`.
```python
from pathlib import Path

from ocsf_schema_compiler.compiler import SchemaCompiler


compiler = SchemaCompiler(Path("path/to/ocsf-schema"))
output = compiler.compile()
```

See `ocsf_schema_compiler.__main__` for a working example.

## Developing `ocsf-schema-compiler`
The recommended way to work on OCSF projects is via a fork into your own GitHub profile or organization. Create your fork of [this repo](https://github.com/ocsf/ocsf-schema-compiler) with the [GitHub CLI](https://cli.github.com/) tool (or, more painfully, manually).

This project requires Python 3.14 or later, and otherwise has no runtime dependencies. This mean you can run it directly from a cloned repo's `src` directory without creating a virtual environment.

```shell
cd path/to/ocsf-schema-compiler
cd src
python3 -m ocsf_schema_compiler ~/path/to/ocsf-schema > ~/path/to/output/schema.json
```

This project has regression tests in the `tests` directory built using the `unittest` library. These also can be run without a virtual environment. The tests can be run with the `Makefile` target `tests`.
```shell
make tests
```

This project uses [Ruff](https://docs.astral.sh/ruff/) for linting and code formatting and [basedpyright](https://docs.basedpyright.com) for type checking. Ruff's formatting is very similar to Black with some minor differences (improvements, in my opinion). These require a virtual environment with both installed. With the virtual environment activated the linting and formatting can be run with the `Makefile` target `lint`.

This project's `.gitignore` assumes the virtual environment is at `.venv`.

```shell
# A standard Python virtual environment works fine
python3 -m venv .venv
source ./.venv/bin/activate

# Install the tools
pip install ruff basedpyright

# Now the lint target will work
make lint
```

Also with a virtual environment, a local install can be used to run the compiler.
```shell
# A standard Python virtual environment works fine
python3 -m venv .venv
source ./.venv/bin/activate

pip install -e .
```

Integrating Ruff with your editor is recommended. See [Editor integration | Ruff](https://docs.astral.sh/ruff/editors/).

## Publishing
This project follows the publishing approach described by this tutorial: [How to Publish an Open-Source Python Package to PyPI — Real Python](https://realpython.com/pypi-publish-python-package/), including use of the [Build](https://pypa-build.readthedocs.io/) and [Twine](https://twine.readthedocs.io/) tools. The [BumpVer](https://pypi.org/project/bumpver/) tool is also used to increment versions and keep the various mentions of the version in sync.

## Copyright
Copyright © OCSF a Series of LF Projects, LLC. See [NOTICE](https://github.com/ocsf/ocsf-schema-compiler/blob/main/NOTICE) for details.

## License
This project is distributed under the Apache License Version 2.0. See [LICENSE](https://github.com/ocsf/ocsf-schema-compiler/blob/main/LICENSE) for details.
