import json
import logging
import unittest
from compression import zstd
from pathlib import Path
from sys import stderr
from typing import override

from diff import (  # pyright: ignore[reportImplicitRelativeImport]
    diff_objects,
    formatted_diffs,
    DiffValue,
    DiffDictKeys,
    MISSING,
)
from ocsf_schema_compiler.compiler import SchemaCompiler
from ocsf_schema_compiler.jsonish import JObject
from ocsf_schema_compiler.structured_read import read_json_object_file

BASE_DIR = Path(__file__).parent


class TestRegressions(unittest.TestCase):
    @classmethod
    @override
    def setUpClass(cls):
        logging.basicConfig(
            format="%(levelname)s: %(message)s", style="%", stream=stderr, level="INFO"
        )

    @override
    def setUp(self):
        print(file=stderr)  # so logs start on new line

    def test_v1_6_0(self):
        compiler = SchemaCompiler(
            Path(BASE_DIR, "uncompiled-schemas/ocsf-schema-v1.6.0")
        )
        schema = compiler.compile()
        baseline_schema = read_json_object_file(
            Path(BASE_DIR, "compiled-baselines/schema-v1.6.0.json")
        )
        ok, diffs = diff_objects(schema, baseline_schema)
        self.assertTrue(ok, f"schema should match baseline:\n{formatted_diffs(diffs)}")
        # To make sure diff_objects is implemented correctly, also check with Python
        # equality
        self.assertEqual(schema, baseline_schema, "schema should match baseline")

    def test_v1_6_0_browser_mode(self):
        compiler = SchemaCompiler(
            Path(BASE_DIR, "uncompiled-schemas/ocsf-schema-v1.6.0"), browser_mode=True
        )
        schema = compiler.compile()

        p = Path(BASE_DIR, "compiled-baselines/browser-schema-v1.6.0.zst")
        with zstd.open(p) as f:
            baseline_schema = json.load(f)

        ok, diffs = diff_objects(schema, baseline_schema)
        self.assertTrue(ok, f"schema should match baseline:\n{formatted_diffs(diffs)}")
        # To make sure diff_objects is implemented correctly, also check with Python
        # equality
        self.assertEqual(schema, baseline_schema, "schema should match baseline")

    def test_v1_6_0_with_aws_v1_0_0(self):
        compiler = SchemaCompiler(
            Path(BASE_DIR, "uncompiled-schemas/ocsf-schema-v1.6.0"),
            extensions_paths=[Path(BASE_DIR, "uncompiled-schemas/aws-v1.0.0")],
        )
        schema = compiler.compile()
        baseline_schema = read_json_object_file(
            Path(BASE_DIR, "compiled-baselines/schema-v1.6.0-aws-v1.0.0.json")
        )
        ok, diffs = diff_objects(schema, baseline_schema)
        self.assertTrue(ok, f"schema should match baseline:\n{formatted_diffs(diffs)}")
        # To make sure diff_objects is implemented correctly, also check with Python
        # equality
        self.assertEqual(schema, baseline_schema, "schema should match baseline")

    def test_v1_0_0_rc_2_with_splunk_v1_16_2(self):
        compiler = SchemaCompiler(
            Path(BASE_DIR, "uncompiled-schemas/ocsf-schema-v1.0.0-rc.2"),
            ignore_platform_extensions=True,
            extensions_paths=[Path(BASE_DIR, "uncompiled-schemas/splunk-v1.16.2")],
        )
        schema = compiler.compile()
        baseline_schema = read_json_object_file(
            Path(BASE_DIR, "compiled-baselines/schema-v1.0.0-rc.2-splunk-v1.16.2.json")
        )
        ok, diffs = diff_objects(schema, baseline_schema)
        self.assertTrue(ok, f"schema should match baseline:\n{formatted_diffs(diffs)}")
        # To make sure diff_objects is implemented correctly, also check with Python
        # equality
        self.assertEqual(schema, baseline_schema, "schema should match baseline")

    def test_legacy_v1_6_0_with_aws_v1_0_0(self):
        # The legacy schema export, even with v3 fixes, changes a slightly different
        # schema, however these differences are not material differences in actual
        # usage. The test uses a diff callback to ensure these differences are ones we
        # expect.

        # Compile using legacy mode with scoped keys to minimize the differences.
        compiler = SchemaCompiler(
            Path(BASE_DIR, "uncompiled-schemas/ocsf-schema-v1.6.0"),
            extensions_paths=[Path(BASE_DIR, "uncompiled-schemas/aws-v1.0.0")],
            legacy_mode=True,
            scope_extension_keys=True,
        )
        schema = compiler.compile()
        baseline_schema = read_json_object_file(
            Path(BASE_DIR, "compiled-baselines/server-v3-schema-v1.6.0-aws-v1.0.0.json")
        )
        ok, diffs = diff_objects(
            schema, baseline_schema, diff_callback=legacy_aws_diff_callback
        )
        self.assertTrue(ok, f"schema should match baseline:\n{formatted_diffs(diffs)}")
        # print("Diffs are all expected")
        # for diff in diffs:
        #     print(diff.formatted_string())


def legacy_aws_diff_callback(
    key: str,
    path: list[str],
    left: JObject,
    right: JObject,
    left_diff: DiffValue,
    right_diff: DiffValue,
) -> bool:
    # Legacy compiler add _both_ aws/last_used_time and last_used_time
    # This compiler overwrites last_used_time, and then the scope_extension_keys option
    # it to aws/last_user_time
    if (
        key == "dictionary_attributes"
        and isinstance(left_diff, DiffDictKeys)
        and left_diff.keys == []
        and isinstance(right_diff, DiffDictKeys)
        and right_diff.keys == ["last_used_time", "last_used_time_dt"]
    ):
        return True

    if (
        path == ["dictionary_attributes", "last_used_time"]
        or path == ["dictionary_attributes", "last_used_time_dt"]
    ) and left_diff == MISSING:
        # These will be missing with this compiler and scope_extension_keys (left value)
        return True

    if (
        len(path) == 2
        and path[0] == "objects"
        and isinstance(left_diff, DiffDictKeys)
        and left_diff.keys == []
        and isinstance(right_diff, DiffDictKeys)
        and right_diff.keys == ["profiles"]
    ):
        # This compiler does not needlessly set object and class "profiles" to null.
        return True

    if (
        key == "profiles"
        and len(path) == 3
        and path[0] == "objects"
        and left_diff == MISSING
        and right_diff is None
    ):
        # Same as above but now we are at the "objects.<object-name>.profiles" level
        return True

    if (
        key in ["last_used_time", "last_used_time_dt"]
        and len(path) > 2
        and path[-2] == "attributes"
        and isinstance(left_diff, DiffDictKeys)
        and left_diff.keys == ["extension", "extension_id"]
        and isinstance(right_diff, DiffDictKeys)
        and right_diff.keys == []
    ):
        # This compiler overwrites the one last_user_time (which is carried over to
        # last_user_time_dt) and so class and object attributes using it will have
        # "extension" and "extension_id"
        return True

    if (
        key in ["extension", "extension_id"]
        and len(path) > 3
        and path[-3] == "attributes"
        and path[-2] in ["last_used_time", "last_used_time_dt"]
        and left_diff != MISSING
        and right_diff == MISSING
    ):
        # Same as above, though here we are at the attribute property level
        return True

    if (
        key == "caption"
        and len(path) > 3
        and path[-3] == "attributes"
        and path[-2] in ["last_used_time", "last_used_time_dt"]
        and left_diff == "Last Used time"
        and right_diff == "Last Used Time"
    ):
        # Because this compiler overwrite the actual dictionary attribute
        # last_used_time, the caption in object attributes (and class attributes if
        # that happened) becomes the one from the AWS extension.
        return True

    return False


if __name__ == "__main__":
    unittest.main()
