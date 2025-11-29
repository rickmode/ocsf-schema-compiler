# OCSF Schema Compiler
This is a Python library and command-line tool for compiling the Open Cybersecurity Schema Framework (OCSF) schema, specifically the schema at https://github.com/ocsf/ocsf-schema.

This project published to PyPI: [ocsf-schema-compiler · PyPI](https://pypi.org/project/ocsf-schema-compiler/)

## Getting started
There are three ways to use the OCSF Schema Compiler:
1. As a command-line tool, installed from PyPI.
2. As a library, installed from PyPI.
3. As a developer working on this project.

Python version 3.14 or later is required. The core project code does not require any dependencies, though optional developer dependencies are used (see below).

## Using `ocsf-schema-compiler` as a command-line tool
Create a virtual environment then install with `pip`. For example:
```shell
python3 -m venv .venv
source ./.venv/bin/activate
pip install ocsf-schema-compiler
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

See [`ocsf_schema_compiler.__main__`](https://github.com/ocsf/ocsf-schema-compiler/blob/main/src/ocsf_schema_compiler/__main__.py) for a working example.

## Developing `ocsf-schema-compiler`
The recommended way to work on OCSF projects is via a fork into your own GitHub profile or organization. Create your fork of [this repo](https://github.com/ocsf/ocsf-schema-compiler) with the [GitHub CLI](https://cli.github.com/) tool (or, more painfully, manually).

This project requires Python 3.14 or later, and otherwise has no runtime dependencies. This mean you can run it directly from a cloned repo's `src` directory without creating a virtual environment.

```shell
cd path/to/ocsf-schema-compiler
cd src
python3 -m ocsf_schema_compiler ~/path/to/ocsf-schema > ~/path/to/output/schema.json
```

This project has regression tests in the `tests` directory built using the `unittest` library. These also can be run without a virtual environment so long `python3` refers to Python 3.14 or later. The tests can be run with the [`Makefile`](https://github.com/ocsf/ocsf-schema-compiler/blob/main/Makefile) target `tests`.
```shell
make tests
```

This project uses [basedpyright](https://docs.basedpyright.com/latest/) for type checking and [Ruff](https://docs.astral.sh/ruff/) for linting and code formatting.

Basedpyright was picked this as an alternative to Pylance because I'm using the open-source and telemetry-free [VSCodium](https://vscodium.com/) variation of VS Code, and the Microsoft proprietary Pylance extension (part of the Python extension) does not work in VSCodium by design. Basedpyright also offers other benefits: it is strict by default and includes additional type checking rules. Extensions are available for both VSCodium and VS Code; in both cases look for "BasedPyright" by detachhead. Use in VS Code does take a little more work. I hope Pyright fans and especially VS Code users will find this workable, and perhaps consider using the privacy-focused VSCodium themselves.

The choice of Ruff should be less controversial: it is the current favorite for Python linting and code formatting. The formatting is very similar to [Black](https://black.readthedocs.io/en/stable/) with some minor differences (improvements, in my opinion).

Use of these tools require a virtual environment. With the virtual environment activated, the linting and formatting can be run with the [`Makefile`](https://github.com/ocsf/ocsf-schema-compiler/blob/main/Makefile) target `lint`.

Integrating basedpyright and Ruff with your editor is recommended. In both cases, these tools will pick up the configuration in this project's [`pyproject.toml` file](https://github.com/ocsf/ocsf-schema-compiler/blob/main/pyproject.toml).
* [Editor integration | Ruff](https://docs.astral.sh/ruff/editors/)
* [IDEs - basedpyright](https://docs.basedpyright.com/latest/installation/ides/)

This

This project's `.gitignore` assumes the virtual environment is at `.venv`.

```shell
# A standard Python virtual environment works fine
python3 -m venv .venv
source ./.venv/bin/activate

# Install the tools
pip install basedpyright ruff

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

## Continuous integration
The continuous integration is done via GitHub action in [`.github/workflows/ci.yaml`](https://github.com/ocsf/ocsf-schema-compiler/blob/main/.github/workflows/ci.yaml). This action uses the [`Makefile`](https://github.com/ocsf/ocsf-schema-compiler/blob/main/Makefile) and runs the `test`, `lint-github`, and `build-check` targets. The `build-check` target is described below. The `lint-github` is a minor variation of the `lint` target with Ruff's GitHub output format option.

## Publishing
This project is published using [Flit](https://flit.pypa.io/). Publishing it done via GitHub releases.

Much of the publishing is based on the tutorial [How to Publish an Open-Source Python Package to PyPI — Real Python](https://realpython.com/pypi-publish-python-package/), though using Flit as suggested later in the article.

The publishing flow requires the project's version to be bumped up, and a git tag created with the same version, though with a "v" prefix. Publishing uses GitHub's Releases mechanism, which fires the publish or test-publish GitHub actions defined in this project. These actions ensure that the version has been changed and the related git tag exists.

### Publishing step 1: update project version
The version is defined in the `__version__` variable in [`src/ocsf_schema_compiler/__init__.py`](https://github.com/ocsf/ocsf-schema-compiler/blob/main/src/ocsf_schema_compiler/__init__.py).

Updating the version requires a normal pull request.

### Publishing step 2 (optional): create git tag
A git tag must be created with the same version with a "v" prefix. This can be created during a release or beforehand via `git` on the command-line or with a draft release.

Creating a tag before release can be used to manually publish to TestPyPI at [ocsf-schema-compiler · TestPyPI](https://test.pypi.org/project/ocsf-schema-compiler/) using this repo's "Test publish package to TestPyPI" GitHub action defined in [`.github/workflows/test-publish.yaml`](https://github.com/ocsf/ocsf-schema-compiler/blob/main/.github/workflows/test-publish.yaml).

To create a new tag on the command line, go to a local cloned of this repo's `main` branch (not a fork), the use command similar to the following example for version 1.0.0.
```shell
# Create a nice annotated tag with a message
git tag v1.0.0 -a -m "Release version 1.0.0"
# Or just create the tag
git tag v1.0.0

# Push the tag - this does not require a pull request
git push origin v1.0.0

# Alternately all tags can be pushed
git push origin --tags
```

To create draft release with a new tag, go to this repo's [Releases](https://github.com/ocsf/ocsf-schema-compiler/releases) page, clicking "Create a new release", putting the new tag in the "Select tag" box, and finally clicking "Save draft" (rather than "Publish release").

### Publishing step 3: release
Create a new release with a tag or select a draft release on the [Releases](https://github.com/ocsf/ocsf-schema-compiler/releases) page from a tag then click "Publish release". This will trigger the GitHub action in [`.github/workflows/publish.yaml`](https://github.com/ocsf/ocsf-schema-compiler/blob/main/.github/workflows/publish.yaml) that publishes the package to PyPI.

### Optional: manually check everything
These steps are optional. The continuous integration and publish actions have this covered. But for the paranoid we can manually double-check everything locally.

```shell
# If in a virtual environment
deactivate
# Clean up everything, including .venv
make clean-up

# Create fresh virtual environment
python3 -m venv .venv
source ./.venv/bin/activate

# Code does not have any dependencies
# Running tests before installing anything ensure this remains true
make tests

pip install basedpyright ruff flit
make lint
make build-check
```

The pre-publishing checks require the project's version to be updated, and the related git tag to exist. The check is run with the `pre-publish-check` target in the [`Makefile`](https://github.com/ocsf/ocsf-schema-compiler/blob/main/Makefile). This target runs the [`scripts/pre-publish-check.sh`](https://github.com/ocsf/ocsf-schema-compiler/blob/main/scripts/pre-publish-check.sh) script. This requires a virtual environment.

This check downloads the latest release of ocsf-schema-compiler from PyPI, and so you will probably to remove the virtual environment. afterwards.

```shell
# Create virtual environment if it doesn't already exist
python3 -m venv .venv
source ./.venv/bin/activate

# Run the check
make pre-publish-check
# Alternately run `pre-test-publish-check` to verify against TestPyPI
make pre-test-publish-check

# This virtual environment now oddly includes ocsf-schema-compiler itself
# Best to clean up and start over
deactivate
make clean-all
```

If everything works, the actual publishing should work.

## Copyright
Copyright © OCSF a Series of LF Projects, LLC. See [NOTICE](https://github.com/ocsf/ocsf-schema-compiler/blob/main/NOTICE) for details.

## License
This project is distributed under the Apache License Version 2.0. See [LICENSE](https://github.com/ocsf/ocsf-schema-compiler/blob/main/LICENSE) for details.
