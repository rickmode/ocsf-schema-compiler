# Baseline compiled schemas
This directory holds compiled schemas used for regression tests, and should be updated as compiler output changes.

Here are example of how these can be created from the command-line. Run these from the base of the repo.
```shell
python3 -m venv .venv
source ./.venv/bin/activate
pip install -e .

ocsf-schema-compiler tests/uncompiled-schemas/ocsf-schema-v1.6.0 | jq -S > tests/compiled-baselines/schema-v1.6.0.json

# Using jq with the browser mode variation leads to a file that exceeds GitHub 100MB limit.
# Also compress with zstd (available on Mac with Homebrew) to get below GitHub's LFS warning.
# Browser schema tests will look for compressed JSON *.zst files instead plain *.json files.
ocsf-schema-compiler tests/uncompiled-schemas/ocsf-schema-v1.6.0 -b | zstd > tests/compiled-baselines/browser-schema-v1.6.0.zst

ocsf-schema-compiler tests/uncompiled-schemas/ocsf-schema-v1.6.0 -e tests/uncompiled-schemas/aws-v1.0.0 | jq -S > tests/compiled-baselines/browser-schema-v1.6.0-aws-v1.0.0.json

ocsf-schema-compiler tests/uncompiled-schemas/ocsf-schema-v1.0.0-rc.2 -i -e tests/uncompiled-schemas/splunk-v1.16.2 | jq -S > ../tests/compiled-baselines/schema-v1.0.0-rc.2-splunk-v1.16.2.json
```

The use of `jq -S` is not required but can be helpful when using other diff tools like the one in Visual Studio Code.

Schemas with filenames starting with `server-v3` were created via schema export of the v3 (older) Elixir OCSF Server using the `/export/schema` API.