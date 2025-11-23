import json
from typing import Any
from copy import deepcopy

from ocsf_schema_compiler.exceptions import SchemaException
from ocsf_schema_compiler.jsonish import JValue, JObject, JArray


def deep_copy_j_object(obj: JObject) -> JObject:
    """JObject typed flavor of copy.deepcopy. Returns deep copy of obj."""
    return deepcopy(obj)


def deep_copy_j_array(array: JArray) -> JArray:
    """JArray typed flavor of copy.deepcopy. Returns deep copy of array."""
    return deepcopy(array)


def deep_merge(dest: JObject, source: JObject) -> None:
    """
    In-place merge a source dictionary into a destination dictionary, modifying the
    destination dictionary.

    Note: this merge does not merge lists or deep merge dictionaries inside lists. List
    values are simply overwritten.
    """

    for source_key, source_value in source.items():
        if source_key in dest:
            dest_value = dest[source_key]
            if isinstance(dest_value, dict) and isinstance(source_value, dict):
                deep_merge(dest_value, source_value)
            else:
                # This replaces dest[source_key] with source_value
                dest[source_key] = source_value
        else:
            dest[source_key] = source_value


def put_non_none(d: JObject, k: str, v: JValue) -> None:
    if v is not None:
        d[k] = v


def is_hidden_class(cls_name: str, cls: JObject) -> bool:
    return cls_name != "base_event" and "uid" not in cls


def is_hidden_object(obj_name: str) -> bool:
    return obj_name.startswith("_")


def extension_scoped_category_uid(extension_uid: int, category_uid: int) -> int:
    """Return an extension-specific category UID."""
    assert category_uid < 100, (
        f"category_uid {category_uid} should be less than 100"
        " (not yet extension UID scoped)"
    )
    return extension_uid * 100 + category_uid


def category_scoped_class_uid(category_uid: int, cls_uid: int) -> int:
    """Return a category-specific class UID."""
    assert cls_uid < 1000, (
        f"class UID {cls_uid} should be less than 1000 (not yet category UID scoped)"
    )
    return category_uid * 1000 + cls_uid


def class_uid_scoped_type_uid(cls_uid: int, type_uid: int) -> int:
    """Return a class-specific type UID."""
    assert type_uid < 100, (
        f"type_uid {type_uid} should be less than 1000 (not class UID scoped)"
    )
    return cls_uid * 100 + type_uid


def pretty_json_encode(v: Any) -> str:  # pyright: ignore[reportAny, reportExplicitAny]
    return json.dumps(v, indent=4, sort_keys=True)


def quote_string(s: str | None) -> str | None:
    if s:
        return f'"{s}"'
    return None


def requirement_to_rank(requirement: str | None) -> int:
    if requirement == "required":
        return 3
    if requirement == "recommended":
        return 2
    if requirement == "optional":
        return 1
    if requirement is None:
        return 0
    raise SchemaException(f'Unknown requirement: "{requirement}"')


def rank_to_requirement(rank: int) -> str | None:
    if rank == 3:
        return "required"
    if rank == 2:
        return "recommended"
    if rank == 1:
        return "optional"
    if rank == 0:
        return None
    raise SchemaException(f"Unknown rank: {rank}")
