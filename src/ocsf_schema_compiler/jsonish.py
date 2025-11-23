# Type aliases for JSON-compatible types. See https://json.org.
# Yes, these are circular, and Python is OK with that.
# As with all Python type hints, these improve code readability and help IDEs identify
# type mismatches.

# JValue is type alias for types compatible with JSON values.
type JValue = JObject | JArray | str | int | float | bool | None
# JObject is a type alias for dictionary compatible with a JSON object.
type JObject = dict[str, JValue]
# JArray is a type alias for types compatible with a JSON array.
type JArray = list[JValue]  # TODO | tuple[JValue]


def json_type_from_value(value: object) -> str:
    """
    Return JSON type for a Python value. See https://json.org.
    This is intended for error messages.
    """
    if isinstance(value, dict):
        return "object"
    if isinstance(value, list):
        return "array"
    if isinstance(value, str):
        return "string"
    if isinstance(value, int):
        return "number (integer)"
    if isinstance(value, float):
        return "number (float)"
    if isinstance(value, bool):
        if value:
            return "true"
        return "false"
    if value is None:
        return "null"
    return f"non-JSON type: {type(value).__name__}"


# These j_* function are for type safety. They keep pyright happy.
# The assertion error messages are given in terms of JSON types, mostly.
# JSON does not have a integer type, though we have j_integer rather than a more
# general j_number.


def j_object(v: JValue) -> JObject:
    """Ensures value v is a JObject (dict) and returns it."""
    assert isinstance(v, dict), (
        f"j_object: expected object but got {json_type_from_value(v)}: {v}"
    )
    return v


def j_object_optional(v: JValue) -> JObject | None:
    """Ensures value v is a JObject (dict) or None and returns it."""
    assert v is None or isinstance(v, dict), (
        f"j_object: expected object or null but got {json_type_from_value(v)}: {v}"
    )
    return v


# TODO
# def j_array(v: JValue) -> JArray:
#     """Ensures value v is a JArray (list or tuple) and returns it."""
#     assert isinstance(v, list) or isinstance(v, tuple), (
#         f"j_array: expected array but got {json_type_from_value(v)}: {v}"
#     )
#     return v


# TODO
# def j_array_optional(v: JValue) -> JArray | None:
#     """Ensures value v is a JArray (list or tuple) or None and returns it."""
#     assert v is None or isinstance(v, list) or isinstance(v, tuple), (
#         f"j_array: expected array or null but got {json_type_from_value(v)}: {v}"
#     )
#     return v


def j_array(v: JValue) -> JArray:
    """Ensures value v is a JArray (list) and returns it."""
    assert isinstance(v, list), (
        f"j_array: expected array but got {json_type_from_value(v)}: {v}"
    )
    return v


def j_array_optional(v: JValue) -> JArray | None:
    """Ensures value v is a JArray (list) or None and returns it."""
    assert v is None or isinstance(v, list), (
        f"j_array: expected array or null but got {json_type_from_value(v)}: {v}"
    )
    return v


def j_string(v: JValue) -> str:
    """Ensures value v is a string and returns it."""
    assert isinstance(v, str), (
        f"j_string: expected string but got {json_type_from_value(v)}: {v}"
    )
    return v


def j_string_optional(v: JValue) -> str | None:
    """Ensures value v is a string or None and returns it."""
    assert v is None or isinstance(v, str), (
        f"j_string: expected string or null but got {json_type_from_value(v)}: {v}"
    )
    return v


def j_integer(v: JValue) -> int:
    """Ensures value v is an integer and returns it."""
    assert isinstance(v, int), (
        f"j_integer: expected integer number but got {json_type_from_value(v)}: {v}"
    )
    return v
