import json
from copy import deepcopy
from dataclasses import dataclass
from typing import Callable

from ocsf_schema_compiler.jsonish import JObject, JValue


class Missing:
    pass


MISSING = Missing()


@dataclass
class DiffDictKeys:
    keys: list[str]


type DiffValue = Missing | DiffDictKeys | JValue


@dataclass
class Difference:
    is_expected: bool
    key: str
    path: list[str]
    value1: DiffValue
    value2: DiffValue

    def formatted_string(self) -> str:
        if self.is_expected:
            kind = "expected"
        else:
            kind = "unexpected"
        return (
            f'Diff at "{_path_to_string(self.path)}" ({kind}):'
            f"\n    left value  : {_diff_value_to_string(self.value1)}"
            f"\n    right value : {_diff_value_to_string(self.value2)}"
        )


def formatted_diffs(diffs: list[Difference]) -> str:
    # Show unexpected before expected
    unexpected_diffs: list[str] = []
    expected_diffs: list[str] = []
    for diff in diffs:
        if diff.is_expected:
            expected_diffs.append(diff.formatted_string())
        else:
            unexpected_diffs.append(diff.formatted_string())
    return "\n".join(unexpected_diffs + expected_diffs)


type DiffCallback = Callable[
    [str, list[str], JObject, JObject, DiffValue, DiffValue], bool
]


def diff_objects(
    obj1: JObject, obj2: JObject, diff_callback: DiffCallback | None = None
) -> tuple[bool, list[Difference]]:
    diffs: list[Difference] = []
    _diff_objects(obj1, obj2, diff_callback, [], diffs)
    ok = True
    for diff in diffs:
        if not diff.is_expected:
            ok = False
            break
    return ok, diffs


def _diff_objects(
    obj1: JObject,
    obj2: JObject,
    diff_callback: DiffCallback | None,
    base_path: list[str],
    diffs: list[Difference],
) -> None:
    for key in sorted(set(obj1.keys()) | set(obj2.keys())):
        path = deepcopy(base_path)
        path.append(key)
        v1 = _diff_get(obj1, key)
        v2 = _diff_get(obj2, key)
        is_equal, dv1, dv2 = _is_diff_equal_shallow(v1, v2)
        if not is_equal:
            if diff_callback:
                is_expected = diff_callback(key, path, obj1, obj2, dv1, dv2)
                diffs.append(Difference(is_expected, key, path, dv1, dv2))
            else:
                diffs.append(Difference(False, key, path, dv1, dv2))
        if isinstance(v1, dict) and isinstance(v2, dict):
            _diff_objects(v1, v2, diff_callback, path, diffs)


def _is_diff_equal_shallow(
    v1: DiffValue, v2: DiffValue
) -> tuple[bool, DiffValue, DiffValue]:
    if isinstance(v1, dict) and isinstance(v2, dict):
        v1keys = set(v1.keys())
        v2keys = set(v2.keys())
        if v1keys == v2keys:
            return True, None, None
        else:
            return (
                False,
                DiffDictKeys(sorted(v1keys - v2keys)),
                DiffDictKeys(sorted(v2keys - v1keys)),
            )
    return v1 == v2, v1, v2


def _diff_get(o: JObject, k: str) -> DiffValue:
    if k in o:
        return o[k]
    return MISSING


def _path_to_string(path: list[str]) -> str:
    return ".".join(path)


def _diff_value_to_string(dv: DiffValue) -> str:
    if isinstance(dv, Missing):
        return "missing"
    if isinstance(dv, DiffDictKeys):
        if dv.keys:
            return f"key(s) not in other object: {', '.join(dv.keys)}"
        else:
            return "key(s) not in other object: none"
    return json.dumps(dv, sort_keys=True)
