from ocsf_schema_compiler.jsonish import JObject, j_object


def to_extension_scoped_name(name: str, item: JObject) -> str:
    if "extension" in item:
        return f"{item['extension']}/{name}"
    return name


def add_extension_scope_to_attribute_object_type(
    attribute: JObject,
    objects: JObject,
) -> None:
    if "object_type" in attribute:
        obj_name = attribute["object_type"]
        if obj_name in objects:
            obj = j_object(objects[obj_name])
            if "extension" in obj:
                attribute["object_type"] = (
                    f"{obj['extension']}/{attribute['object_type']}"
                )


def add_extension_scope_to_items(items: JObject, objects: JObject) -> JObject:
    scoped_items: JObject = {}
    for item_name, item in items.items():
        item = j_object(item)
        scoped_items[to_extension_scoped_name(item_name, item)] = item
        if "attributes" in item:
            for attribute in j_object(item["attributes"]).values():
                attribute = j_object(attribute)
                add_extension_scope_to_attribute_object_type(attribute, objects)
    return scoped_items


def add_extension_scope_to_dictionary(dictionary: JObject, objects: JObject) -> None:
    scoped_attributes = {}
    for attribute_name, attribute in j_object(dictionary["attributes"]).items():
        attribute = j_object(attribute)
        add_extension_scope_to_attribute_object_type(attribute, objects)
        scoped_attributes[to_extension_scoped_name(attribute_name, attribute)] = (
            attribute
        )
    dictionary["attributes"] = scoped_attributes
