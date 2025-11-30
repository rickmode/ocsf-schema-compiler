#!/bin/bash

set -e

test_mode=0
while [ "$1" != "" ]; do
    case $1 in
        --test)
            test_mode=1
            ;;
        *)
            echo "Invalid option: $1"
            exit 1
    esac
    shift
done

# Get the current version in from source code
code_version=$(python -c 'from src.ocsf_schema_compiler.__init__ import __version__ ; print(__version__)')

# Install the current package and get its version
if [ $test_mode -eq 1 ]; then
    echo "Installing ocsf-schema-compiler from TestPyPI"
    python -m pip install -i https://test.pypi.org/simple ocsf-schema-compiler
else
    echo "Installing ocsf-schema-compiler from PyPI"
    python -m pip install ocsf-schema-compiler
fi
last_published_version=$(ocsf-schema-compiler -v | cut -d ' ' -f 2)

# Compare the current version in code against the last published version and make sure they are different
if [ "${code_version}" == "${last_published_version}" ]; then
    echo "Current code version is unchanged from the last published version ${last_published_version}"
    echo "The value of __version__ in src/ocsf_schema_compiler/__init__.py must be updated"
    # The git tag checking will likely incorrectly succeed if we continue, so fail now
    exit 1
else
    echo "Current code version ${code_version} is different from the last published version ${last_published_version}, as expected"
fi

# Compare current version against the latest tag
# Tags have leading have "v" prefix, e.g., "v1.0.0"
latest_tag=$(git describe --abbrev=0 --tags)
if [ "v${code_version}" == "${latest_tag}" ]; then
    echo "Current code version ${code_version} matches the latest tag ${latest_tag}, as expected"
else
    echo "Current code version ${code_version} does not match latest git tag ${latest_tag}"
    echo "The git tag v${code_version} must be created"
    exit 1
fi

if [ $test_mode -eq 1 ]; then
    echo "Pre-test-publish check successful"
else
    echo "Pre-publish check successful"
fi
