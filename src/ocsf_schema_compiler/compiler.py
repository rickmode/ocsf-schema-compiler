import logging
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

from ocsf_schema_compiler.exceptions import SchemaException
from ocsf_schema_compiler.jsonish import (
    JValue,
    JObject,
    JArray,
    j_object,
    j_object_optional,
    j_array,
    j_array_optional,
    j_string,
    j_string_optional,
    j_integer,
    json_type_from_value,
)
from ocsf_schema_compiler.legacy_mode import (
    add_extension_scope_to_items,
    add_extension_scope_to_dictionary,
)
from ocsf_schema_compiler.structured_read import (
    read_json_object_file,
    read_structured_items,
    read_patchable_structured_items,
)
from ocsf_schema_compiler.utils import (
    deep_copy_j_object,
    deep_copy_j_array,
    deep_merge,
    put_non_none,
    is_hidden_class,
    is_hidden_object,
    extension_scoped_category_uid,
    category_scoped_class_uid,
    class_uid_scoped_type_uid,
    pretty_json_encode,
    quote_string,
    requirement_to_rank,
    rank_to_requirement,
)

logger = logging.getLogger(__name__)


@dataclass
class Extension:
    base_path: Path
    uid: int
    name: str
    is_platform_extension: bool
    caption: str | None
    description: str | None
    version: str
    categories: JObject
    classes: JObject
    class_patches: JObject
    objects: JObject
    object_patches: JObject
    dictionary: JObject
    profiles: JObject


@dataclass
class ProfileInfo:
    is_extension_profile: bool
    extension_name: str | None
    caption: str


# Type alias for dictionary from patch item name to a list of patch objects.
# The value is list since different extensions can patch the same thing.
type PatchList = list[JObject]  # list of patches for an item name
type PatchDict = dict[str, PatchList]  # dict of item name to list of patches


class SchemaCompiler:
    def __init__(
        self,
        schema_path: Path,
        ignore_platform_extensions: bool = False,
        extensions_paths: list[Path] | None = None,
        browser_mode: bool = False,
        legacy_mode: bool = False,
        scope_extension_keys: bool = False,
    ) -> None:
        if browser_mode and legacy_mode:
            raise SchemaException("Browser mode and legacy mode are mutually exclusive")
        if scope_extension_keys and not legacy_mode:
            raise SchemaException(
                "Scope extension keys option is only supported in legacy mode"
            )

        self.schema_path: Path = schema_path
        self.ignore_platform_extensions: bool = ignore_platform_extensions
        self.extensions_paths: list[Path] | None = extensions_paths
        self.browser_mode: bool = browser_mode
        self.legacy_mode: bool = legacy_mode
        self.scope_extension_keys: bool = scope_extension_keys

        logger.info("Schema path: %s", self.schema_path)
        if self.ignore_platform_extensions:
            logger.info(
                "Ignoring platform extensions (if any) at path: %s",
                self.schema_path / "extensions",
            )
        else:
            logger.info(
                "Including platform extensions (if any) at path: %s",
                self.schema_path / "extensions",
            )
        if self.extensions_paths:
            logger.info(
                "Including extensions path(s): %s",
                ", ".join(list(map(str, self.extensions_paths))),
            )
        if self.browser_mode:
            logger.info(
                "Browser mode enabled."
                " Including extra information needed by the schema browser (the OCSF"
                " Server)."
            )
        if self.legacy_mode:
            logger.info(
                "Legacy mode enabled. Compiled output will be in legacy schema export"
                " layout."
            )
            if self.scope_extension_keys:
                logger.info(
                    "Creating extension scoped keys similar to the legacy compiler."
                    "\n    Note 1:"
                    "\n    Extension scoped keys are not necessary. Scoped extension"
                    " keys make diffs against the legacy schema export identical for"
                    " many cases (see Note 2)."
                    "\n    Note 2:"
                    "\n    Differences occur for extensions with dictionary and"
                    " category attributes that overwrite existing attributes, and are"
                    " due to compiler implementation differences. These difference do"
                    " not affect base schema compilations."
                    "\n    Note 3:"
                    "\n    Profiles defined in extensions are always scoped by"
                    " extension."
                )

        self._is_compiled: bool = False
        self._error_count: int = 0
        self._warning_count: int = 0
        self._version: str = "0.0.0-undefined"
        self._categories: JObject = {}
        self._dictionary: JObject = {}
        self._classes: JObject = {}
        # class patches consolidated from all extensions
        self._class_patches: PatchDict = {}
        self._objects: JObject = {}
        # object patches consolidated from all extensions
        self._object_patches: PatchDict = {}
        # Profiles from the base schema
        self._base_profiles: JObject = {}
        # Profiles from all extensions - profile names (keys) are extension-scoped
        self._extension_profiles: JObject = {}
        # All profiles used for collision detection, mapping from unscoped profile name
        # to a ProfileInfo instance
        self._unscoped_profiles_info: dict[str, ProfileInfo] = {}
        # The extensions here are just the extension information as used by the schema
        # browser, not the complete data used during schema compilation. The values in
        # this JObject are thus a subset of the information in the Extension dataclass.
        self._extensions: JObject = {}

        self._include_cache: dict[Path, JObject] = {}
        # Observable type_id values extracted from all observable sources
        # Used to detect collisions and populate the observable object's type_id enum
        self._observable_type_id_dict: JObject = {}
        # Slice of classes before removing "hidden" / abstract classes
        self._all_classes: JObject = {}
        # Slice of objects before removing "hidden" / abstract objects
        self._all_objects: JObject = {}

    def compile(self) -> JObject:
        if self._is_compiled:
            raise SchemaException(
                "Schema already compiled (compile can only be run once)"
            )
        self._is_compiled = True

        logger.info("Compiling schema")

        if not self.schema_path.is_dir():
            raise FileNotFoundError(f"Schema path does not exist: {self.schema_path}")

        self._read_base_schema()
        self._read_and_merge_extensions()

        self._enrich_dictionary_object_types()

        self._process_classes()
        self._process_objects()

        self._enrich_and_validate_dictionary()
        self._observables_from_dictionary()

        self._validate_object_profiles_and_add_links()
        if self.browser_mode:
            self._add_object_links()
        self._update_observable_enum()
        self._consolidate_object_profiles()
        self._verify_object_attributes_and_add_datetime()

        self._validate_class_profiles_and_add_links()
        self._consolidate_class_profiles()
        self._verify_class_attributes_and_add_datetime()

        self._ensure_attributes_have_requirement()

        self._finish_attributes()

        output = self._create_compile_output()

        if self._error_count and self._warning_count:
            logger.error(
                "Compile completed with %d error(s) and %d warning(s)",
                self._error_count,
                self._warning_count,
            )
        elif self._error_count and not self._warning_count:
            logger.error(
                "Compile completed with %d (tolerated) error(s)", self._error_count
            )
        elif self._warning_count:
            logger.warning("Compile completed with %d warnings(s)", self._warning_count)
        else:
            logger.info("Compile completed successfully")

        logger.info("Compiled schema base version: %s", self._version)
        if self._extensions:
            logger.info(
                "Compiled schema includes the following extension(s):\n%s",
                pretty_json_encode(self._extensions),
            )

        return output

    def _warning(self, message: str, *args: JValue | Path) -> None:
        self._warning_count += 1
        logger.warning(message, *args)

    def _read_base_schema(self) -> None:
        self._read_version()
        self._categories = read_json_object_file(self.schema_path / "categories.json")
        self._dictionary = read_json_object_file(self.schema_path / "dictionary.json")
        self._classes = read_structured_items(
            self.schema_path,
            "events",
            item_callback_fn=self._upgrade_attribute_profiles,
        )
        self._objects = read_structured_items(
            self.schema_path,
            "objects",
            item_callback_fn=self._upgrade_attribute_profiles,
        )
        self._base_profiles = read_structured_items(
            self.schema_path, "profiles", item_callback_fn=self._cache_profile
        )
        self._validate_base_profiles()

        self._resolve_includes()

    def _read_version(self) -> None:
        version_path = self.schema_path / "version.json"
        try:
            obj = read_json_object_file(version_path)
            self._version = j_string(obj["version"])
        except FileNotFoundError as e:
            raise SchemaException(
                "Schema version file does not exist (is this a schema directory?):"
                f" {version_path}"
            ) from e
        except KeyError as e:
            raise SchemaException(
                'The "version" key is missing in the schema version file:'
                f" {version_path}"
            ) from e

    def _upgrade_attribute_profiles(self, path: Path, item: JObject) -> None:
        if not self.legacy_mode:
            # Upgrading class and object attributes with profile properties before
            # processing any "$include" pulling in profiles.
            # (Attributes in profiles cannot use "$include".)
            attributes = j_object(item.get("attributes", {}))
            for attribute_name, attribute in attributes.items():
                if attribute_name != "$include":
                    attribute = j_object(attribute)
                    if "profiles" in attribute:
                        # This is a processing bug. The metaschema does not
                        # allow "profiles" in attributes.
                        raise SchemaException(
                            'Unexpectedly found "profiles" in attribute'
                            f" {attribute_name}: {path}"
                        )
                    if "profile" in attribute:
                        profile = attribute["profile"]
                        if profile is None:
                            attribute["profiles"] = None
                        else:
                            profile = j_string(profile)
                            attribute["profiles"] = [profile]
                        del attribute["profile"]

    def _cache_profile(self, path: Path, profile: JObject) -> None:
        self._include_cache[path] = profile

    def _validate_base_profiles(self) -> None:
        # Before potentially resolving includes of profiles and then later finding
        # issues we will validate profiles early to identify the source of problems.
        dictionary_attributes = j_object(self._dictionary.get("attributes", {}))
        for profile_name, profile in self._base_profiles.items():
            profile = j_object(profile)
            profile_attributes = j_object(profile.get("attributes", {}))
            for attribute_name in profile_attributes.keys():
                if attribute_name not in dictionary_attributes:
                    raise SchemaException(
                        f'Attribute "{attribute_name}" in base schema profile'
                        f' "{profile_name}" is not a defined dictionary attribute'
                    )

    @staticmethod
    def _add_attribute_annotations(annotations: JObject, attribute: JObject) -> None:
        for key, value in annotations.items():
            if key == "profiles":
                # This isn't covered by metaschema, but could cause trouble for
                # compilation.
                raise SchemaException(
                    'Unexpectedly found "profiles" in attribute annotations'
                )
            # Only add annotation mappings that do no exist already in annotation
            if key not in attribute:
                attribute[key] = value

    def _read_and_merge_extensions(self) -> None:
        extensions: list[Extension] = self._read_extensions()

        self._validate_extension_profiles(extensions)

        self._resolve_extension_includes(extensions)

        for extension in extensions:
            self._fix_extension_profile_uses(extension)

        self._merge_categories_from_extensions(extensions)
        self._merge_classes_from_extensions(extensions)
        self._merge_objects_from_extensions(extensions)
        self._merge_dictionary_from_extensions(extensions)
        self._merge_profiles_from_extensions(extensions)
        self._consolidate_extension_patches(extensions)

        # Create extension information. This information is needed for the
        # self._browser_mode output format, as well as the final information log showing
        # what was included in the compilation.
        for extension in extensions:
            self._extensions[extension.name] = {
                "uid": extension.uid,
                "name": extension.name,
                "platform_extension?": extension.is_platform_extension,
                "caption": extension.caption,
                "description": extension.description,
                "version": extension.version,
            }

    def _read_extensions(self) -> list[Extension]:
        extensions: list[Extension] = []
        if not self.ignore_platform_extensions:
            self._read_extensions_in_path(
                extensions, self.schema_path / "extensions", is_platform_extension=True
            )
        if self.extensions_paths:
            for extensions_path in self.extensions_paths:
                self._read_extensions_in_path(
                    extensions, extensions_path, is_platform_extension=False
                )

        self._enrich_extension_items(extensions)
        return extensions

    def _read_extensions_in_path(
        self, extensions: list[Extension], base_path: Path, is_platform_extension: bool
    ) -> None:
        for dir_path, _dir_names, file_names in os.walk(base_path, topdown=False):
            for file_name in file_names:
                if file_name == "extension.json":
                    # we found an extension at dir_path
                    extension = self._read_extension(
                        Path(dir_path), is_platform_extension
                    )
                    extensions.append(extension)
                    if is_platform_extension:
                        logger.info(
                            'Read platform extension "%s" from directory: %s',
                            extension.name,
                            dir_path,
                        )
                    else:
                        logger.info(
                            'Read extension "%s" from directory: %s',
                            extension.name,
                            dir_path,
                        )

    def _read_extension(
        self, base_path: Path, is_platform_extension: bool
    ) -> Extension:
        if is_platform_extension:
            logger.info("Reading platform extension directory: %s", base_path)
        else:
            logger.info("Reading extension directory: %s", base_path)
        # This should only be called after we know that extension.json exists in
        # base_path, so there's no need for extra error handling.
        extension_info_path = base_path / "extension.json"
        info = read_json_object_file(extension_info_path)

        uid = info.get("uid")
        name = info.get("name")
        if not isinstance(uid, int):
            t = json_type_from_value(uid)
            raise SchemaException(
                f'The extension "uid" must be an integer but got {t}:'
                " {extension_info_path}"
            )
        if not isinstance(name, str):
            t = json_type_from_value(name)
            raise SchemaException(
                f'The extension "name" must be a string but got {t}:'
                f" {extension_info_path}"
            )

        categories_path = base_path / "categories.json"
        if categories_path.is_file():
            categories = read_json_object_file(categories_path)
        else:
            categories = {}

        classes, class_patches = read_patchable_structured_items(
            base_path, "events", item_callback_fn=self._upgrade_attribute_profiles
        )
        objects, object_patches = read_patchable_structured_items(
            base_path, "objects", item_callback_fn=self._upgrade_attribute_profiles
        )

        dictionary_path = base_path / "dictionary.json"
        if dictionary_path.is_file():
            dictionary = read_json_object_file(base_path / "dictionary.json")
        else:
            dictionary = {}

        profiles = read_structured_items(
            base_path, "profiles", item_callback_fn=self._cache_profile
        )

        if is_platform_extension and "version" not in info:
            # Fall back to overall schema version for platform extensions that do not
            # specify their own version
            version = self._version
        elif "version" in info:
            version = info["version"]
        else:
            raise SchemaException(
                f'Extension extension.json file is missing "version":'
                f" {extension_info_path}"
            )

        return Extension(
            base_path=base_path,
            uid=uid,
            name=name,
            is_platform_extension=is_platform_extension,
            caption=j_string_optional(info.get("caption")),
            description=j_string_optional(info.get("description")),
            version=j_string(version),
            categories=categories,
            classes=classes,
            class_patches=class_patches,
            objects=objects,
            object_patches=object_patches,
            dictionary=dictionary,
            profiles=profiles,
        )

    @staticmethod
    def _enrich_extension_items(extensions: list[Extension]) -> None:
        for extension in extensions:
            try:
                for category_detail in j_object(
                    extension.categories.setdefault("attributes", {})
                ).values():
                    category_detail = j_object(category_detail)
                    category_detail["uid"] = extension_scoped_category_uid(
                        extension.uid, j_integer(category_detail["uid"])
                    )
                    category_detail["extension"] = extension.name
                    category_detail["extension_id"] = extension.uid
            except KeyError as e:
                raise SchemaException(
                    f'Malformed category in extension "{extension.name}" - missing {e}'
                ) from e

            for cls in extension.classes.values():
                cls = j_object(cls)
                cls["extension"] = extension.name
                cls["extension_id"] = extension.uid

            for cls_patch in extension.class_patches.values():
                cls_patch = j_object(cls_patch)
                cls_patch["extension"] = extension.name
                cls_patch["extension_id"] = extension.uid

            for obj in extension.objects.values():
                obj = j_object(obj)
                obj["extension"] = extension.name
                obj["extension_id"] = extension.uid

            for obj_patch in extension.object_patches.values():
                obj_patch = j_object(obj_patch)
                obj_patch["extension"] = extension.name
                obj_patch["extension_id"] = extension.uid

            for dictionary_attribute in j_object(
                extension.dictionary.setdefault("attributes", {})
            ).values():
                dictionary_attribute = j_object(dictionary_attribute)
                dictionary_attribute["extension"] = extension.name
                dictionary_attribute["extension_id"] = extension.uid

            dictionary_types = j_object(extension.dictionary.setdefault("types", {}))
            dictionary_types_attributes = j_object(
                dictionary_types.setdefault("attributes", {})
            )
            for dictionary_type in dictionary_types_attributes.values():
                dictionary_type = j_object(dictionary_type)
                dictionary_type["extension"] = extension.name
                dictionary_type["extension_id"] = extension.uid

            for profile in extension.profiles.values():
                profile = j_object(profile)
                profile["extension"] = extension.name
                profile["extension_id"] = extension.uid

    def _validate_extension_profiles(self, extensions: list[Extension]) -> None:
        # Instead of resolving includes of profiles and then later finding issues, we
        # will validate profiles early so help identify the source of problems.
        base_dictionary_attributes = j_object(self._dictionary.get("attributes", {}))
        for extension in extensions:
            ext_dictionary_attributes = j_object(
                extension.dictionary.get("attributes", {})
            )
            for profile_name, profile in extension.profiles.items():
                profile = j_object(profile)
                profile_attributes = j_object(profile.get("attributes", {}))
                for attribute_name in profile_attributes.keys():
                    if (
                        attribute_name not in base_dictionary_attributes
                        and attribute_name not in ext_dictionary_attributes
                    ):
                        if (
                            extension.name == "splunk"
                            and profile_name == "splunk"
                            and self._version == "1.0.0-rc.2"
                        ):
                            # This is a known issue with the 1.0.0-rc.2 with "splunk"
                            # extension compilation, so we will log this specific case.
                            # TODO: Remove the unused splunk extension from the splunk
                            #       extension. After this is fixed we can remove this
                            #       special-case.
                            self._warning(
                                'Ignoring know issue with "splunk" extension: attribute'
                                ' "%s" in profile "splunk" is not a defined dictionary'
                                " attribute.\n\n    PLEASE FIX by removing the unused"
                                ' "splunk" profile.\n',
                                attribute_name,
                            )
                        else:
                            raise SchemaException(
                                f'Attribute "{attribute_name}" in extension'
                                f' "{extension.name}" profile "{profile_name}" is not a'
                                " defined dictionary attribute"
                            )

    def _fix_extension_profile_uses(self, extension: Extension) -> None:
        self._fix_extension_profile_uses_in_items(extension, extension.classes, "class")
        self._fix_extension_profile_uses_in_items(
            extension, extension.class_patches, "class patch"
        )
        self._fix_extension_profile_uses_in_items(
            extension, extension.objects, "object"
        )
        self._fix_extension_profile_uses_in_items(
            extension, extension.object_patches, "object patch"
        )

    def _fix_extension_profile_uses_in_items(
        self, extension: Extension, items: JObject, kind: str
    ) -> None:
        # Structured items can be classes, objects, class patches, or object patches
        for item_name, item in items.items():
            item_context = f'Extension "{extension.name}" {kind} "{item_name}"'
            item = j_object(item)
            item_profiles = j_array_optional(item.get("profiles"))
            if item_profiles:
                profiles_context = f'{item_context} "profiles"'
                fixed_item_profiles: JArray = []
                for profile_name in item_profiles:
                    fixed_item_profiles.append(
                        self._fix_extension_profile(
                            extension, j_string(profile_name), profiles_context
                        )
                    )
                item["profiles"] = fixed_item_profiles

            item_attributes = j_object(item.setdefault("attributes", {}))
            for attribute_name, attribute in item_attributes.items():
                attribute = j_object(attribute)
                if self.legacy_mode:
                    profile_name = j_string_optional(attribute.get("profile"))
                    if profile_name:
                        attribute_context = (
                            f'{item_context} attribute "{attribute_name}"'
                        )
                        attribute["profile"] = self._fix_extension_profile(
                            extension, profile_name, attribute_context
                        )
                else:
                    attribute_profiles = j_array_optional(attribute.get("profiles"))
                    if attribute_profiles:
                        attribute_context = (
                            f'{item_context} attribute "{attribute_name}"'
                        )
                        fixed_attribute_profiles: JArray = []
                        for profile_name in attribute_profiles:
                            fixed_attribute_profiles.append(
                                self._fix_extension_profile(
                                    extension, j_string(profile_name), attribute_context
                                )
                            )
                        attribute["profiles"] = fixed_attribute_profiles

    def _fix_extension_profile(
        self, extension: Extension, profile_name: str, context: str
    ) -> str:
        """
        Validates a profile reference used in an extension. Raises a SchemaException
        if validation fails.
        Returns fixed profile name, adding extension-scope to name if not already
        scoped.
        """
        if "/" in profile_name:
            split = profile_name.split("/")
            extension_name = split[0]
            if extension_name != extension.name:
                raise SchemaException(
                    f'{context} references profile "{profile_name}" that is scoped'
                    f' to a different extension: "{extension_name}"'
                )
            unscoped_profile_name = split[1]
            if unscoped_profile_name in extension.profiles:
                logger.debug('%s uses scoped profile "%s"', context, profile_name)
            else:
                raise SchemaException(
                    f'{context} references profile "{profile_name}" that is'
                    f" undefined in this extension and is not a platform extension"
                )
        else:
            if profile_name in extension.profiles:
                # This is normal - an extension's use of its own profiles are not
                # scoped. We will add the scope for the compiled schema.
                scoped_profile_name = f"{extension.name}/{profile_name}"
                logger.debug(
                    '%s references this extension\'s own profile "%s"; changing to'
                    ' "%s".',
                    context,
                    profile_name,
                    scoped_profile_name,
                )
                return scoped_profile_name

            elif profile_name in self._base_profiles:
                # This is fine
                logger.debug('%s uses base schema profile "%s"', context, profile_name)
            else:
                raise SchemaException(
                    f'{context} references profile "{profile_name}" that is not'
                    " defined in this extension or the base schema"
                )
        return profile_name

    def _resolve_includes(self) -> None:
        for cls in self._classes.values():
            cls = j_object(cls)
            self._resolve_item_includes(
                cls,
                f'class "{cls.get("name")}"',
                self._resolver_include_path,
            )
        for obj in self._objects.values():
            obj = j_object(obj)
            self._resolve_item_includes(
                obj,
                f'object "{obj.get("name")}"',
                self._resolver_include_path,
            )

    def _resolver_include_path(self, file_name: str) -> Path:
        return self.schema_path / file_name

    def _resolve_extension_includes(self, extensions: list[Extension]) -> None:
        for extension in extensions:

            def path_resolver(file_name: str) -> Path:
                return self._resolve_extension_include_path(extension, file_name)

            for cls in extension.classes.values():
                cls = j_object(cls)
                context = f'extension "{extension.name}" class "{cls.get("name")}"'
                self._resolve_item_includes(cls, context, path_resolver)

            for cls_patch in extension.class_patches.values():
                cls_patch = j_object(cls_patch)
                context = (
                    f'extension "{extension.name}" class patch'
                    f' "{cls_patch.get("name")}"'
                )
                self._resolve_item_includes(cls_patch, context, path_resolver)

            for obj in extension.objects.values():
                obj = j_object(obj)
                context = f'extension "{extension.name}" object "{obj.get("name")}"'
                self._resolve_item_includes(obj, context, path_resolver)

            for obj_patch in extension.object_patches.values():
                obj_patch = j_object(obj_patch)
                context = (
                    f'extension "{extension.name}" object patch'
                    f' "{obj_patch.get("name")}"'
                )
                self._resolve_item_includes(obj_patch, context, path_resolver)

    def _resolve_extension_include_path(
        self, extension: Extension, file_name: str
    ) -> Path:
        extension_path = extension.base_path / file_name
        if extension_path.is_file():
            return extension_path
        path = self.schema_path / file_name
        if path.is_file():
            return path
        raise FileNotFoundError(
            f'Extension "{extension.name}" "$include" {file_name} not found in'
            f" extension directory {extension.base_path} or schema directory"
            f" {self.schema_path}"
        )

    def _resolve_item_includes(
        self,
        item: JObject,
        context: str,
        path_resolver: Callable[[str], Path],
    ) -> None:
        item_attributes = j_object(item.setdefault("attributes", {}))

        # First, resolve $include at "attributes" level. These are commonly used for
        # profiles. An include at this level has the common item JSON object structure
        # with keys like "name", "caption", "description", and "attributes". Of these,
        # only the "attributes" are merged.
        #
        # This value of the "$include" key can be single string or an array of strings.
        # Each string is a path relative to the base directory of the schema, or for
        # extensions, the base directory of the extension OR the schema.
        #
        # The merge prefers existing values. The existing attributes details (if any)
        # are merged on top of (a copy of) the include contents.
        #
        # This example shows the array form of an $include:
        # {
        #    "name": "foo",
        #    ... other item details
        #    "attributes": {
        #       "$include": [
        #         "profiles/bar.json",
        #         "profiles/baz.json",
        #       ]
        #       "qux": {
        #          ... attribute details
        #       },
        #       ... other attributes
        #    }
        # }
        if "$include" in item_attributes:
            sub_context = f"{context} attributes.$include"
            # Get $include value and remove it from item attributes
            include_value = item_attributes.pop("$include")
            if isinstance(include_value, str):
                include_path = path_resolver(include_value)
                self._merge_attributes_include(item, sub_context, include_path)
            elif isinstance(include_value, list):
                for include_file_name in include_value:
                    include_path = path_resolver(j_string(include_file_name))
                    self._merge_attributes_include(item, sub_context, include_path)
            else:
                raise TypeError(
                    f"Illegal {sub_context} value type:"
                    f" expected string or array (list), but got"
                    f" {json_type_from_value(include_value)}"
                )

        # TODO: This is can easily overwrite existing information.
        #       Consider carefully determining if include is overwriting anything,
        #       perhaps with a new overwrite flag to utils.deep_merge.
        # Second, resolve $include in attribute details. An include at this level is a
        # JSON object containing exactly the information to merge in. These are (or
        # were) used to extract common enum values. The merge prefers existing values.
        # The existing attributes details (if any) are merged on top of the base.
        #
        # The value of the "$include" key must be a single string. The string is a path
        # relative to the base of the schema, or for extensions, the base directory of
        # the extension OR the schema.
        #
        # The merge prefers existing values. The existing attributes details (if any)
        # are merged on top of (a copy of) the include contents.
        #
        # Example:
        # {
        #    "name": "foo",
        #    ... other item details
        #    "attributes": {
        #       "baz_id": {
        #          "$include": "enum/baz.json"
        #           ... other attribute details (if any)
        #       },
        #       ... other attributes
        #    }
        # }
        #
        # attributes may have been modified, so we need to get them again, though now
        # we know they exist
        item_attributes = j_object(item["attributes"])
        for attribute_name, attribute in item_attributes.items():
            if isinstance(attribute, dict) and "$include" in attribute:
                sub_context = f"{context} attributes.{attribute_name}.$include"
                # Get $include value and remove it from attribute
                include_value = attribute.pop("$include")
                if isinstance(include_value, str):
                    include_path = path_resolver(include_value)
                    self._merge_attribute_detail_include(
                        item_attributes,
                        attribute_name,
                        attribute,
                        sub_context,
                        include_path,
                    )
                else:
                    raise TypeError(
                        f"Illegal {sub_context} value type: expected string,"
                        f" but got {json_type_from_value(include_value)}"
                    )

    def _merge_attributes_include(
        self, item: JObject, context: str, include_path: Path
    ) -> None:
        include_item = self._get_include_contents(context, include_path)

        # Include file content should always have "attributes", but we will be
        # defensive.
        if "attributes" not in include_item:
            self._warning(
                "Include file suspiciously has no attributes: %s", include_path
            )
            # Nothing to merge. This should never happen (because it does nothing),
            # but is possible.
            return

        # Create merged attributes by merging item's attributes on top of included
        # attributes resulting in merge with base of included attributes, overridden by
        # item's.

        attributes = deep_copy_j_object(j_object(include_item["attributes"]))

        # First do profile-specific enrichment if include is a profile, and annotation
        # enrichment for all include cases (even though currently only profiles use
        # attributes includes)

        if include_item.get("meta") == "profile":
            if "name" not in include_item:
                raise SchemaException(f'Profile "name" is missing in {context}')
            profile_name = include_item["name"]
            for attribute_name, attribute in attributes.items():
                attribute = j_object(attribute)
                if "profile" in attribute:
                    raise SchemaException(
                        f'Profile "{profile_name}" attribute "{attribute_name}"'
                        f' unexpectedly has a "profile"'
                    )
                if self.legacy_mode:
                    attribute["profile"] = profile_name
                else:
                    attribute["profiles"] = [profile_name]

        if "annotations" in include_item:
            annotations = j_object(include_item["annotations"])
            for attribute in attributes.values():
                self._add_attribute_annotations(annotations, j_object(attribute))

        # item["attributes"] should exist at this point, so no need to double-check
        # Merge item's attributes on top of the copy of the include attribute,
        # preferring item's data
        self._merge_attributes(attributes, j_object(item["attributes"]), context)

        # replace item "attributes" with merged / resolved include attributes
        item["attributes"] = attributes

    def _merge_attribute_detail_include(
        self,
        attributes: JObject,
        attribute_name: str,
        attribute: JObject,
        context: str,
        include_path: Path,
    ) -> None:
        include_attribute = self._get_include_contents(context, include_path)

        # Create merged attribute detail for attributes.{attribute_name} by merging item
        # attribute's details on top of included attribute details resulting in merge
        # with base of included details overridden by item's.

        new_attribute = deep_copy_j_object(include_attribute)

        # Merge original attribute detail on top of the copy of the included
        # attribute_detail, preferring the original
        deep_merge(new_attribute, attribute)

        # replace existing attribute detail with the new merged detail
        attributes[attribute_name] = new_attribute

    def _get_include_contents(self, context: str, include_path: Path) -> JObject:
        if include_path in self._include_cache:
            return self._include_cache[include_path]

        try:
            include_item = read_json_object_file(include_path)
            self._include_cache[include_path] = include_item
            return include_item
        except FileNotFoundError as e:
            raise SchemaException(
                f"{context} file does not exist: {include_path}"
            ) from e

    def _merge_categories_from_extensions(self, extensions: list[Extension]) -> None:
        for extension in extensions:
            self._merge_extension_attributes(
                extension, self._categories, extension.categories, "category"
            )

    def _merge_classes_from_extensions(self, extensions: list[Extension]) -> None:
        for extension in extensions:
            if extension.classes:
                self._merge_extension_items(
                    extension.name, extension.classes, self._classes, "class"
                )

    def _merge_objects_from_extensions(self, extensions: list[Extension]) -> None:
        for extension in extensions:
            if extension.objects:
                self._merge_extension_items(
                    extension.name, extension.objects, self._objects, "object"
                )

    def _merge_dictionary_from_extensions(self, extensions: list[Extension]) -> None:
        for extension in extensions:
            self._merge_extension_attributes(
                extension, self._dictionary, extension.dictionary, "dictionary"
            )

    def _merge_profiles_from_extensions(self, extensions: list[Extension]) -> None:
        # Extension profiles are extension scoped because those scoped names appear in
        # concrete events. We must maintain the once case of extension-scoped names.
        for extension in extensions:
            if extension.profiles:
                # We cannot use self._merge_extension_items since we need to use
                # extension-scoped keys in the self._extension_profiles dictionary, as
                # well as add profile with unscoped name to the
                # self._all_profiles_unscoped dictionary.
                for unscoped_profile_name, profile in extension.profiles.items():
                    profile = j_object(profile)
                    if "/" in unscoped_profile_name:
                        raise SchemaException(
                            f'Unexpected scoped profile name in "{extension.name}"'
                            f' profile "{unscoped_profile_name}"'
                        )

                    if unscoped_profile_name in self._unscoped_profiles_info:
                        other_profile_info = self._unscoped_profiles_info[
                            unscoped_profile_name
                        ]
                        if other_profile_info.is_extension_profile:
                            where_defined = (
                                f'extension "{other_profile_info.extension_name}"'
                            )
                        else:
                            where_defined = "base scheme"
                        raise SchemaException(
                            f'Collision: extension "{extension.name}" profile unscoped'
                            f' name "{unscoped_profile_name}" collides with'
                            f" {where_defined} profile with caption"
                            f' "{other_profile_info.caption}"'
                        )

                    scoped_profile_name = f"{extension.name}/{unscoped_profile_name}"
                    if scoped_profile_name in self._extension_profiles:
                        other_profile = j_object(
                            self._extension_profiles[scoped_profile_name]
                        )
                        raise SchemaException(
                            f'Collision: extension "{extension.name}" profile'
                            f' "{scoped_profile_name}" collides with extension profile'
                            f" with caption"
                            f' "{other_profile.get("caption", "<no caption>")}"'
                        )

                    self._extension_profiles[scoped_profile_name] = profile
                    self._unscoped_profiles_info[unscoped_profile_name] = ProfileInfo(
                        is_extension_profile=True,
                        extension_name=extension.name,
                        caption=j_string(profile.get("caption", "<no caption>")),
                    )

    def _merge_extension_attributes(
        self,
        extension: Extension,
        base_item: JObject,
        extension_item: JObject,
        kind: str,
    ) -> None:
        """
        Merge attributes from extension_item into base_item, preferring base_item's
        information. This is used for extension category and dictionary merging.

        In this method, "base" refers to the existing definition at this point of the
        compile process. It could be a definition from the base schema (without
        platform extensions) or another extension processed earlier.

        For an attribute that exists in extension_item but not base_item, the attribute
        is simply added. For an attribute that exists in both the extension_item and
        base_item, the attribute is merged only if the change is safe.

        For dictionaries, this also safely merges the extension item's dictionary type
        attributes, adding any dictionary types defined in the extension. Modifying
        types is not supported, as this can result in unwanted incompatibilities.
        (We could contemplate allow equivalent type definitions in the future.)
        There is one special case of dictionary type modification that is allowed: the
        1.0.0-rc.2 schema has a known problem with some of its subtypes, and in this
        one case extensions are allowed to fix the issue with a deep merge. The
        "splunk" extension fixes these specific issues.
        """
        base_attributes = j_object(base_item.setdefault("attributes", {}))
        ext_attributes = j_object(extension_item.get("attributes", {}))
        for ext_attribute_name, ext_attribute in ext_attributes.items():
            base_attribute = j_object_optional(base_attributes.get(ext_attribute_name))
            ext_attribute = j_object(ext_attribute)
            if base_attribute:
                # First, check if this is an attempt to overwrite another extension.
                if "extension" in base_attribute:
                    # This is not allowed as the result is non-deterministic, depending
                    # on the order the extensions are processed. We have no notion of
                    # extension precedence, so this is not supported.
                    raise SchemaException(
                        f'Collision: extension "{extension.name}" {kind} attribute'
                        f' "{ext_attribute_name}" collides with attribute from'
                        f' extension "{base_attribute["extension"]}"; extensions are'
                        f" not allowed to modify each other as the results are"
                        f" non-deterministic"
                    )

                # Second check for a type change. This is not supported as it creates a
                # schema that is not compatible with the base schema.
                if "type" in ext_attribute:
                    if ext_attribute["type"] != base_attribute["type"]:
                        if (
                            self._version == "1.0.0-rc.2"
                            and ext_attribute_name == "duration"
                            and ext_attribute["extension"] == "splunk"
                        ):
                            logger.info(
                                "Allowing fix of known issue in schema version"
                                ' 1.0.0-rc.2 by extension "splunk": base schema'
                                ' dictionary attribute "duration" is type "integer_t"'
                                ' but should be "long_t"'
                            )
                        else:
                            raise SchemaException(
                                f'Extension "{extension.name}" {kind} attribute'
                                f' "{ext_attribute_name}" attempted to make unsafe type'
                                f'  change; "{ext_attribute["type"]}" overwriting'
                                f' existing "{base_attribute["type"]}"'
                            )
                    if (
                        ext_attribute["type"] == "object_t"
                        # no need to check if base_attribute["type"] == "object_t"
                        # since we already know both types are the same
                        and ext_attribute["object_type"]
                        != base_attribute["object_type"]
                    ):
                        raise SchemaException(
                            f'Extension "{extension.name}" {kind} attribute'
                            f' "{ext_attribute_name}" attempted to make unsafe object'
                            f' type change; "{ext_attribute["object_type"]}"'
                            f' overwriting existing "{base_attribute["object_type"]}"'
                        )

                # Third, check if the attribute's requirement is being relaxed. This is
                # not supported as it creates a schema that is incompatible with the
                # a schema that does not include the extension.
                ext_req = j_string_optional(ext_attribute.get("requirement"))
                base_req = j_string_optional(base_attribute.get("requirement"))
                if requirement_to_rank(ext_req) < requirement_to_rank(base_req):
                    raise SchemaException(
                        f'Extension "{extension.name}" {kind} attribute'
                        f' "{ext_attribute_name}" attempted to make unsafe requirement'
                        f" change with {quote_string(ext_req)} reducing existing"
                        f" requirement of {quote_string(base_req)}"
                    )

                # TODO: Safely handle enum merges
                # Other changes are safe. So merge.
                logger.info(
                    'Extension "%s" %s attribute "%s" is safely merging over existing'
                    " attribute",
                    extension.name,
                    kind,
                    ext_attribute_name,
                )
                logger.debug(
                    "\n    extension keys:"
                    "\n        %s"
                    "\n    merging over existing keys:"
                    "\n        %s",
                    sorted(ext_attribute.keys()),
                    sorted(base_attribute.keys()),
                )

                deep_merge(base_attribute, ext_attribute)

            else:
                # The extension is adding new attribute
                base_attributes[ext_attribute_name] = ext_attribute

        # For the dictionary case, safely merge the types form the extension into the
        # base, without overwriting.
        # Note: the legacy compiler did a deep merge of types attributes.
        if "types" in extension_item:
            base_types = j_object(base_item.setdefault("types", {}))
            base_types_attributes = j_object(base_types.setdefault("attributes", {}))
            ext_types = j_object(extension_item["types"])
            ext_types_attributes = j_object(ext_types.setdefault("attributes", {}))
            # Legacy compiler variation:
            #     deep_merge(base_types_attributes, extension_types_attributes)
            for ext_attribute_name, ext_attribute in ext_types_attributes.items():
                ext_attribute = j_object(ext_attribute)
                if ext_attribute_name in base_types_attributes:
                    base_attribute = j_object(base_types_attributes[ext_attribute_name])
                    if "extension" in base_attribute:
                        base_desc = f'extension "{base_attribute["extension"]}"'
                    else:
                        base_desc = "base schema"
                    if (
                        self._version == "1.0.0-rc.2"
                        and ext_attribute["extension"] == "splunk"
                        and ext_attribute_name
                        in {
                            "bytestring_t",
                            "file_hash_t",
                            "resource_uid_t",
                            "subnet_t",
                            "uuid_t",
                        }
                    ):
                        # Schema version 1.0.0-rc.2 has a known issue. Some of its
                        # dictionary types are subtypes that do not define their base
                        # type. We will allow extensions merge types in these cases.
                        # The "splunk" extension fixes actually does fix these issues.
                        # NOTE: primitives dictionary types "string_t" and "long_t" do
                        # _not_ define "type", so we cannot do a general validation
                        # to ensure all types defines a "type".
                        logger.info(
                            "Allowing fix of known issue in schema version 1.0.0-rc.2"
                            ' by extension "splunk": %s dictionary type "%s" is a'
                            ' subtype but does not define "type"',
                            base_desc,
                            ext_attribute_name,
                        )
                        deep_merge(base_attribute, ext_attribute)
                    else:
                        raise SchemaException(
                            f'Collision: extension "{extension.name}" {kind} dictionary'
                            f' type "{ext_attribute_name}" is trying to overwrite'
                            f" {base_desc} type; modifying dictionary types is not"
                            f" supported"
                        )
                else:
                    base_types_attributes[ext_attribute_name] = ext_attribute

    @staticmethod
    def _merge_extension_items(
        extension_name: str, extension_items: JObject, items: JObject, kind: str
    ) -> None:
        for ext_item_name, ext_item in extension_items.items():
            if ext_item_name in items:
                item = j_object(items[ext_item_name])
                if "extension" in item:
                    item_kind = f'extension "{item["extension"]}" {kind}'
                else:
                    item_kind = f"base schema {kind}"
                raise SchemaException(
                    f'Collision: extension "{extension_name}" {kind} "{ext_item_name}"'
                    f" collides with {item_kind} with caption"
                    f' "{item.get("caption", "")}"'
                )
            items[ext_item_name] = ext_item

    def _consolidate_extension_patches(self, extensions: list[Extension]) -> None:
        for extension in extensions:
            for patch_name, patch in extension.class_patches.items():
                patches = self._class_patches.setdefault(patch_name, [])
                patches.append(j_object(patch))
            for patch_name, patch in extension.object_patches.items():
                patches = self._object_patches.setdefault(patch_name, [])
                patches.append(j_object(patch))

    def _enrich_dictionary_object_types(self) -> None:
        """
        Converts dictionary types not defined in dictionary's types to object types.
        """
        types = j_object(self._dictionary.setdefault("types", {}))
        types_attributes = j_object(types.setdefault("attributes", {}))
        dictionary_attributes = j_object(self._dictionary.setdefault("attributes", {}))
        for attribute_name, attribute in dictionary_attributes.items():
            attribute = j_object(attribute)
            attribute_type = attribute.get("type")
            if attribute_type not in types_attributes:
                attribute["type"] = "object_t"
                attribute["object_type"] = attribute_type
                if attribute_type not in self._objects:
                    raise SchemaException(
                        self._dictionary_error_message(
                            attribute_name,
                            attribute,
                            f'uses undefined object "{attribute_type}"',
                        )
                    )

    def _process_classes(self) -> None:
        # Extracting observables is easier to do before resolving (flattening) "extends"
        # inheritance since afterward the observable type_id enumerations will be
        # propagated to all children of event classes.
        self._observables_from_classes()

        if self.browser_mode:
            self._add_source_to_item_attributes(self._classes)
            self._add_source_to_patch_item_attributes(self._class_patches)
        self._resolve_patches(self._classes, self._class_patches, "class")
        self._resolve_extends(self._classes, "class")

        if self.browser_mode:
            # Save informational complete class hierarchy (for schema browser)
            for cls_name, cls in self._classes.items():
                cls = j_object(cls)
                cls_slice = {}
                for k in ["name", "caption", "extends", "extension"]:
                    if k in cls:
                        cls_slice[k] = cls[k]
                cls_slice["hidden?"] = is_hidden_class(cls_name, cls)
                self._all_classes[cls_name] = cls_slice

        # Remove hidden classes
        self._classes = {
            name: cls
            for name, cls in self._classes.items()
            if not is_hidden_class(name, j_object(cls))
        }

        self._enrich_classes()

    def _enrich_classes(self) -> None:
        # enrich classes
        categories = j_object(self._categories.setdefault("attributes", {}))
        for cls_name, cls in self._classes.items():
            cls = j_object(cls)
            # update class uid
            category: JObject | None = None
            category_uid = 0
            category_key = j_string_optional(cls.get("category"))
            if category_key:
                category = j_object_optional(categories.get(category_key))
                if category:
                    cls["category_name"] = category.get("caption")
                    category_uid = j_integer(category.get("uid", 0))

            if "extension_id" in cls:
                scoped_category_uid = extension_scoped_category_uid(
                    j_integer(cls["extension_id"]), category_uid
                )
                cls_uid = category_scoped_class_uid(
                    scoped_category_uid, j_integer(cls.get("uid", 0))
                )
            else:
                cls_uid = category_scoped_class_uid(
                    category_uid, j_integer(cls.get("uid", 0))
                )

            cls["uid"] = cls_uid

            # add/update type_uid attribute
            cls_attributes = j_object(cls.setdefault("attributes", {}))
            cls_caption = cls.get("caption", "UNKNOWN")
            type_uid_attribute = j_object(cls_attributes.setdefault("type_uid", {}))
            type_uid_enum = {}
            if "activity_id" in cls_attributes and "enum" in j_object(
                cls_attributes["activity_id"]
            ):
                activity_id = j_object(cls_attributes["activity_id"])
                activity_enum = j_object(activity_id["enum"])
                for activity_enum_key, activity_enum_value in activity_enum.items():
                    activity_enum_value = j_object(activity_enum_value)
                    enum_key = str(
                        class_uid_scoped_type_uid(cls_uid, int(activity_enum_key))
                    )
                    enum_value = deep_copy_j_object(j_object(activity_enum_value))
                    enum_value["caption"] = (
                        f"{cls_caption}:"
                        f" {activity_enum_value.get('caption', '<unknown>')}"
                    )
                    type_uid_enum[enum_key] = enum_value
            else:
                raise SchemaException(
                    f'Class "{cls_name}" has invalid "activity_id" definition:'
                    ' "enum" not defined'
                )
            type_uid_enum[str(class_uid_scoped_type_uid(cls_uid, 0))] = {
                "caption": f"{cls_caption}: Unknown",
            }
            type_uid_attribute["enum"] = type_uid_enum

            if self.browser_mode:
                type_uid_attribute["_source"] = cls_name

            # add class_uid and class_name attributes
            cls_uid_attribute = j_object(cls_attributes.setdefault("class_uid", {}))
            cls_name_attribute = j_object(cls_attributes.setdefault("class_name", {}))
            cls_uid_key = str(cls_uid)
            enum: JObject = {
                cls_uid_key: {
                    "caption": cls_caption,
                    "description": cls.get("description", ""),
                }
            }
            cls_uid_attribute["enum"] = enum

            if self.browser_mode:
                cls_uid_attribute["_source"] = cls_name

            cls_name_attribute["description"] = (
                "The event class name, as defined by class_uid value:"
                f" <code>{cls_caption}</code>."
            )

            # add category_uid
            # add/update category_uid and category_name attributes
            if category:
                cls["category_uid"] = category_uid

                category_uid_attribute = j_object(
                    cls_attributes.setdefault("category_uid", {})
                )
                # Replace existing enum; leaf classes only include their one category
                # Doing ths prevents including base_event's 0 - Uncategorized enum.
                enum = {}
                category_uid_key = str(category_uid)
                enum[category_uid_key] = deep_copy_j_object(category)
                category_uid_attribute["enum"] = enum

                category_name_attribute = j_object(
                    cls_attributes.setdefault("category_name", {})
                )
                category_name_attribute["description"] = (
                    f"The event category name, as defined by category_uid value:"
                    f" <code>{category.get('caption', '')}</code>."
                )
            else:
                if category_key == "other":
                    logger.info(
                        'Class "%s" uses special undefined category "other"', cls_name
                    )
                    cls["category_uid"] = 0
                elif category_key is None:
                    raise SchemaException(f'Class "{cls_name}" has no category')
                else:
                    raise SchemaException(
                        f'Class "{cls_name}" has undefined category "{category_key}"'
                    )

    def _process_objects(self) -> None:
        # Extracting observables is easier to do before resolving (flattening) "extends"
        # inheritance since afterward the observable type_id enumerations will be
        # propagated to all children of objects.
        self._observables_from_objects()

        if self.browser_mode:
            self._add_source_to_item_attributes(self._objects)
            self._add_source_to_patch_item_attributes(self._object_patches)
        self._resolve_patches(self._objects, self._object_patches, "object")
        self._resolve_extends(self._objects, "object")

        if self.browser_mode:
            # Save informational complete object hierarchy (for schema browser)
            for obj_name, obj in self._objects.items():
                obj = j_object(obj)
                obj_slice = {}
                for k in ["name", "caption", "extends", "extension"]:
                    if k in obj:
                        obj_slice[k] = obj[k]
                    obj_slice["hidden?"] = is_hidden_object(obj_name)
                self._all_objects[obj_name] = obj_slice

        # Remove hidden objects
        self._objects = {
            name: obj
            for name, obj in self._objects.items()
            if not is_hidden_object(name)
        }

    def _observables_from_classes(self) -> None:
        """Detect observable collisions and build up information for schema browser."""
        for cls_name, cls in self._classes.items():
            cls = j_object(cls)
            context = "base schema"
            self._validate_class_observables(
                cls_name, cls, "base schema", is_patch=False
            )
            self._observables_from_item_attributes(
                self._classes, cls_name, cls, "Class", context, is_patch=False
            )
            self._observables_from_item_observables(
                self._classes, cls_name, cls, "Class", context, is_patch=False
            )

        for patch_name, patch_list in self._class_patches.items():
            for patch in patch_list:
                context = f'"{patch["extension"]}" extension patch'
                self._validate_class_observables(
                    patch_name, patch, context, is_patch=True
                )
                self._observables_from_item_attributes(
                    self._classes, patch_name, patch, "Class", context, is_patch=True
                )
                self._observables_from_item_observables(
                    self._classes, patch_name, patch, "Class", context, is_patch=True
                )

    @staticmethod
    def _validate_class_observables(
        cls_name: str, cls: JObject, context: str, is_patch: bool
    ) -> None:
        if "observable" in cls:
            raise SchemaException(
                'Illegal definition of one or more attributes with "observable" in'
                f' {context} class "{cls_name}". Defining class-level observables is'
                ' not supported (this would be redundant). Instead use the "class_uid"'
                " attribute for querying, correlating, and reporting."
            )

        if not is_patch and is_hidden_class(cls_name, cls):
            attributes = j_object(cls.setdefault("attributes", {}))
            for attribute in attributes.values():
                if "observable" in j_object(attribute):
                    raise SchemaException(
                        'Illegal definition of one or more attributes with "observable"'
                        f' definition in {context} hidden class "{cls_name}". This'
                        " would cause colliding definitions of the same observable"
                        " type_id values in all children of this class. Instead, define"
                        " observables (of any kind) in non-hidden child classes of"
                        f' "{cls_name}".'
                    )

            if "observables" in cls:
                raise SchemaException(
                    f'Illegal "observables" definition in {context} hidden class'
                    f' "{cls_name}". This would cause colliding definitions of the same'
                    " observable type_id values in all children of this class. Instead,"
                    " define observables (of any kind) in non-hidden child classes of'"
                    f' "{cls_name}".'
                )

    def _observables_from_objects(self) -> None:
        """Detect observable collisions and build up information for schema browser."""
        context = "base schema"
        for obj_name, obj in self._objects.items():
            obj = j_object(obj)
            self._validate_object_observables(
                obj_name, obj, "base schema", is_patch=False
            )
            self._observables_from_object(obj_name, obj, context)
            self._observables_from_item_attributes(
                self._objects, obj_name, obj, "Object", context, is_patch=False
            )
            # Not supported:
            # self._observables_from_item_observables(self._objects, obj_name, obj,
            #     "Object", context, is_patch=False)

        for patch_name, patch_list in self._object_patches.items():
            for patch in patch_list:
                context = f'extension "{patch["extension"]}" patch'
                self._validate_object_observables(
                    patch_name, patch, context, is_patch=True
                )
                self._observables_from_object(patch_name, patch, context)
                self._observables_from_item_attributes(
                    self._objects, patch_name, patch, "Object", context, is_patch=True
                )
                # Not supported:
                # self._observables_from_item_observables(self._objects, patch_name,
                #     patch, "Object", context, is_patch=True)

    @staticmethod
    def _validate_object_observables(
        obj_name: str, obj: JObject, context: str, is_patch: bool
    ) -> None:
        if "observables" in obj:
            # Attribute-path observables would be tricky to implement as a
            # machine-driven enrichment. It would require tracking the relative from the
            # point of the object down that tree of an overall OCSF event.
            raise SchemaException(
                f'Illegal "observables" definition in {context} object "{obj_name}".'
                f" Object-specific attribute path observables are not supported."
                f" Please file an issue if you find this feature necessary."
            )

        if not is_patch and is_hidden_object(obj_name):
            attributes = j_object(obj.setdefault("attributes", {}))
            for attribute_detail in attributes.values():
                if "observable" in j_object(attribute_detail):
                    raise SchemaException(
                        f"Illegal definition of one or more attributes with"
                        f' "observable" definition in {context} hidden object'
                        f' "{obj_name}". This would cause colliding definitions of the'
                        f" same observable type_id values in all children of this"
                        f" object. Instead, define observables (of any kind) in"
                        f' non-hidden child objects of "{obj_name}".'
                    )

            if "observable" in obj:
                raise SchemaException(
                    f'Illegal "observable" definition in {context} hidden object'
                    f' "{obj_name}". This would cause colliding definitions of the same'
                    f" observable type_id values in all children of this object."
                    f" Instead, define observables (of any kind) in non-hidden child"
                    f' objects of "{obj_name}".'
                )

    def _observables_from_object(
        self, obj_name: str, obj: JObject, context: str
    ) -> None:
        caption, description = self._find_item_caption_and_description(
            self._objects, obj_name, obj
        )
        if "observable" in obj:
            observable_type_id = str(obj["observable"])
            if observable_type_id in self._observable_type_id_dict:
                entry = j_object(self._observable_type_id_dict[observable_type_id])
                raise SchemaException(
                    f"Collision of observable type_id {observable_type_id} between"
                    f' {context} "{caption}" object "observable" and'
                    f' "{entry["caption"]}": {entry["description"]}'
                )
            entry = self._make_observable_enum_entry(caption, description, "Object")
            self._observable_type_id_dict[observable_type_id] = entry

    def _observables_from_item_attributes(
        self,
        items: JObject,
        item_name: str,
        item: JObject,
        kind: str,
        context: str,
        is_patch: bool,
    ) -> None:
        # kind should be "Class" or "Object"
        if is_patch:
            caption, _ = self._find_parent_item_caption_and_description(
                items, item_name, item
            )
        else:
            caption, _ = self._find_item_caption_and_description(items, item_name, item)
        attributes = j_object(item.setdefault("attributes", {}))
        for attribute_name, attribute in attributes.items():
            attribute = j_object(attribute)
            if "observable" in attribute:
                observable_type_id = str(attribute["observable"])
                if observable_type_id in self._observable_type_id_dict:
                    entry = j_object(self._observable_type_id_dict[observable_type_id])
                    raise SchemaException(
                        f"Collision of observable type_id {observable_type_id}"
                        f' between {context} {kind} "{item_name}" caption "{caption}"'
                        f' attribute "{attribute_name}" "observable" and'
                        f' "{entry["caption"]}": {entry["description"]}'
                    )
                self._observable_type_id_dict[observable_type_id] = (
                    self._make_observable_enum_entry(
                        f"{caption} {kind}: {attribute_name}",
                        f'{kind}-specific attribute "{attribute_name}" for the'
                        f" {caption} {kind}.",
                        f"{kind}-Specific Attribute",
                    )
                )

    def _observables_from_item_observables(
        self,
        items: JObject,
        item_name: str,
        item: JObject,
        kind: str,
        context: str,
        is_patch: bool,
    ) -> None:
        # kind should be title-case: "Class" or "Object"
        if "observables" in item:
            if is_patch:
                caption, _ = self._find_parent_item_caption_and_description(
                    items, item_name, item
                )
            else:
                caption, _ = self._find_item_caption_and_description(
                    items, item_name, item
                )
            observables = j_object(item["observables"])
            for attribute_path, observable_type_id_num in observables.items():
                observable_type_id = str(observable_type_id_num)
                if observable_type_id in self._observable_type_id_dict:
                    entry = j_object(self._observable_type_id_dict[observable_type_id])
                    raise SchemaException(
                        f"Collision of observable type_id {observable_type_id} between"
                        f' {context} {kind} "{item_name}" caption "{caption}"'
                        f' "observables" attribute path "{attribute_path}" and'
                        f' "{entry["caption"]}": {entry["description"]}'
                    )
                self._observable_type_id_dict[observable_type_id] = (
                    self._make_observable_enum_entry(
                        f"{caption} {kind}: {attribute_path}",
                        f'{kind}-specific attribute "{attribute_path}" for the'
                        f" {caption} {kind}.",
                        f"{kind}-Specific Attribute",
                    )
                )

    def _make_observable_enum_entry(
        self, caption: str, description: str, observable_kind: str
    ) -> JObject:
        entry: JObject = {
            "caption": caption,
            "description": f"Observable by {observable_kind}.<br>{description}",
        }
        if self.browser_mode:
            entry["_observable_kind"] = observable_kind
        return entry

    @staticmethod
    def _find_item_caption_and_description(
        items: JObject, item_name: str, item: JObject
    ) -> tuple[str, str]:
        if "caption" in item:
            caption = j_string(item["caption"])
            description = j_string(item.get("description", caption))
            return caption, description
        return SchemaCompiler._find_parent_item_caption_and_description(
            items, item_name, item
        )

    @staticmethod
    def _find_parent_item_caption_and_description(
        items: JObject, item_name: str, item: JObject
    ) -> tuple[str, str]:
        current_item: JObject = item
        while True:
            if "extends" in item:
                parent_name = current_item["extends"]
                if parent_name in items:
                    parent_item = j_object(items[parent_name])
                    if "caption" in parent_item:
                        caption = j_string(parent_item["caption"])
                        description = j_string(parent_item.get("description", caption))
                        return caption, description
                    current_item = parent_item
                else:
                    raise SchemaException(
                        f'Ancestor "{parent_name}" of "{item_name}" is undefined.'
                    )
            else:
                break
        return item_name, item_name  # fallback

    @staticmethod
    def _add_source_to_item_attributes(items: JObject) -> None:
        for item_name, item in items.items():
            item = j_object(item)
            attributes = j_object(item.setdefault("attributes", {}))
            for attribute in attributes.values():
                attribute = j_object(attribute)
                attribute["_source"] = item_name

    @staticmethod
    def _add_source_to_patch_item_attributes(patch_dict: PatchDict) -> None:
        for patch_name, patches in patch_dict.items():
            for patch in patches:
                attributes = j_object(patch.setdefault("attributes", {}))
                for attribute in attributes.values():
                    attribute = j_object(attribute)
                    attribute["_source"] = patch_name

    def _resolve_patches(self, items: JObject, patches: PatchDict, kind: str) -> None:
        for patch_name, patch_list in patches.items():
            for patch in patch_list:
                base_name = patch["extends"]  # this will be the same as patch_name
                assert patch_name == base_name, (
                    f'Patch name "{patch_name}" should match extends base name'
                    f' "{base_name}"'
                )

                context = (
                    f'extension "{patch["extension"]}" {kind} patch "{patch_name}"'
                )
                if base_name not in items:
                    raise SchemaException(
                        f'{context} attempted to patch undefined {kind} "{base_name}"'
                    )

                base = j_object(items[base_name])

                if "extension" in base:
                    # This is not allowed as the result is non-deterministic, depending
                    # on the order the extensions are processed. We have no notion of
                    # extension precedence, so this is not supported.
                    raise SchemaException(
                        f"Illegal patch attempt: {context} attempted to patch"
                        f' "{base_name}" from extension "{base["extension"]}";'
                        f" extensions are not allowed to patch each other as the"
                        f" results are non-deterministic"
                    )
                else:
                    logger.info(
                        'Patch: %s is patching "%s" from base schema',
                        context,
                        base_name,
                    )

                self._merge_profiles(base, patch)
                self._merge_attributes(
                    j_object(base.setdefault("attributes", {})),
                    j_object(patch.setdefault("attributes", {})),
                    context,
                )
                # Top-level observable.
                # Only occurs in objects, but is safe to do for classes too.
                put_non_none(base, "observable", patch.get("observable"))
                # Top-level path-based observables.
                # Only occurs in classes, but is safe to do for objects too.
                put_non_none(base, "observables", patch.get("observables"))
                put_non_none(base, "references", patch.get("references"))
                # Top-level attribute associations.
                # Only occurs in classes, but is safe to do for objects too.
                put_non_none(base, "associations", patch.get("associations"))
                self._patch_constraints(base, patch)

                if self.browser_mode:
                    patched_by = j_array(base.setdefault("_patched_by_extensions", []))
                    patched_by.append(j_string(patch["extension"]))
                    patched_by.sort(key=lambda v: j_string(v))

    def _merge_attributes(
        self, dest_attributes: JObject, source_attributes: JObject, context: str
    ) -> None:
        if "$include" in source_attributes:
            # An included item's attributes should _not_ itself have an $include
            raise SchemaException(
                f'{context} illegally has an "$include"; this is not supported'
            )
        for source_attribute_name, source_attribute in source_attributes.items():
            source_attribute = j_object(source_attribute)
            if source_attribute_name in dest_attributes:
                dest_attribute = j_object(dest_attributes[source_attribute_name])
                self._merge_attribute_detail(
                    dest_attribute,
                    source_attribute,
                    f'{context} attribute "{source_attribute_name}"',
                )
            else:
                dest_attributes[source_attribute_name] = source_attribute

    def _merge_attribute_detail(
        self, dest_attribute: JObject, source_attribute: JObject, context: str
    ) -> None:
        for source_key, source_value in source_attribute.items():
            if source_key == "profile":
                if self.legacy_mode:
                    if source_value is None:
                        # Special meaning: attribute is not affected by profiles.
                        dest_attribute["profile"] = None
                    elif (
                        "profile" in dest_attribute
                        and dest_attribute["profile"] != source_value
                    ):
                        raise SchemaException(
                            f'{context} attempted merge of "profile" with different'
                            f' non-null value "{source_value}", existing:'
                            f" {dest_attribute} - this is not supported with legacy"
                            f" mode compilation since the output would be backwards"
                            f" incompatible with the legacy format"
                        )
                    else:
                        # OK... safe merge
                        dest_attribute["profile"] = j_string(source_value)
                else:
                    raise SchemaException(
                        f'LOGIC BUG: {context} "profile" should not exist while merging'
                        f" attributes"
                    )
            elif source_key not in dest_attribute:
                # this is always OK - safe merge, including "profiles"
                dest_attribute[source_key] = source_value
            elif source_value == dest_attribute[source_key]:
                pass  # No change - nothing to do
            elif "extension" in source_attribute and "extension" in dest_attribute:
                raise SchemaException(
                    f'{context} attempted merge of "{source_key}" on top of attribute'
                    f' from extension "{dest_attribute["extension"]}" - multiple'
                    " extensions modifying the same attribute is not supported"
                )
            elif source_key == "profiles":
                # Special merge:
                # set to None if source is None, otherwise merge set of both
                if source_value is None:
                    dest_attribute["profiles"] = None
                elif "profiles" in dest_attribute:
                    dest_profiles = j_array(dest_attribute["profiles"])
                    source_profiles = j_array(source_value)
                    merged = set(dest_profiles) | set(source_profiles)
                    dest_attribute["profiles"] = j_array(
                        sorted(merged, key=lambda v: j_string(v))
                    )
                else:
                    dest_attribute["profiles"] = j_array(source_value)
            elif (
                source_key == "requirement"
                and source_attribute.get("profiles") is not None
                and "profiles" in dest_attribute
            ):
                # Special merge of attribute affected by two profiles:
                # requirement becomes max of both
                dest_rank = requirement_to_rank(
                    j_string_optional(dest_attribute.get("requirement"))
                )
                source_rank = requirement_to_rank(
                    j_string(source_attribute["requirement"])
                )
                dest_attribute["requirement"] = rank_to_requirement(
                    max(dest_rank, source_rank)
                )
            else:
                # hopefully a safe merge - deep merge if dicts, or overwrite
                # TODO: This will add "extension" and "extension_id" because they exist
                #       in source attribute. Consider tracking that this ends up in dest
                #       because of a merge / overwrite?
                if isinstance(dest_attribute[source_key], dict) and isinstance(
                    source_value, dict
                ):
                    # TODO: Detect collisions? Perhaps with overwrite flag in
                    #       utils.deep_merge?
                    deep_merge(j_object(dest_attribute[source_key]), source_value)
                else:
                    dest_attribute[source_key] = source_value

    @staticmethod
    def _merge_profiles(dest: JObject, source: JObject) -> None:
        dest_profiles = set(j_array(dest.get("profiles", [])))
        source_profiles = set(j_array(source.get("profiles", [])))
        merged = dest_profiles.union(source_profiles)
        if merged:  # avoid adding "profiles" if neither base nor patch had any
            # sorts and converts to list (otherwise profiles are randomly sorted)
            dest["profiles"] = sorted(merged, key=lambda v: j_string(v))

    @staticmethod
    def _patch_constraints(base: JObject, patch: JObject) -> None:
        if "constraints" in patch:
            constraints = patch["constraints"]
            if constraints:
                base["constraints"] = constraints
            else:
                # Remove base constraints if patch explicitly defines an empty
                # constraints list
                del base["constraints"]

    def _resolve_extends(self, items: JObject, kind: str) -> None:
        for item_name, item in items.items():
            self._resolve_item_extends(items, item_name, j_object(item), kind)

    def _resolve_item_extends(
        self, items: JObject, item_name: str | None, item: JObject | None, kind: str
    ) -> None:
        if item_name is None or item is None:
            return

        parent_name = j_string_optional(item.get("extends"))
        parent = None
        if parent_name:
            parent = j_object(items[parent_name])
        self._resolve_item_extends(items, parent_name, parent, kind)
        assert parent_name == item.get("extends"), (
            f'{kind} "{item_name}" "extends" value should not change after'
            f' recursively processing parent: original value: "{parent_name}",'
            f' current value: "{item.get("extends", "<deleted>")}"'
        )

        if parent_name:
            parent_item = j_object_optional(items.get(parent_name))
            if parent_item:
                # Create flattened item by merging item on top of a copy of it's parent
                # with the result that new and overlapping things in item "win" over
                # those in parent. This new item replaces the existing one.
                new_item = deep_copy_j_object(parent_item)
                # The values of most keys simply replace what is in the parent, except
                # for attributes and profiles
                for source_key, source_value in item.items():
                    if source_key == "attributes":
                        new_attributes = j_object(new_item.get("attributes", {}))
                        self._merge_attributes(
                            new_attributes,
                            j_object(source_value),
                            f'{kind} "{item_name}" extending "{parent_name}"',
                        )
                        new_item["attributes"] = new_attributes
                    elif source_key == "profiles":
                        self._merge_profiles(new_item, item)
                    else:
                        new_item[source_key] = source_value

                items[item_name] = new_item
            else:
                raise SchemaException(
                    f'{kind} "{item_name}" extends undefined {kind} "{parent_name}"'
                )

    def _enrich_and_validate_dictionary(self) -> None:
        if self.browser_mode:
            self._add_common_dictionary_attribute_links()
            self._add_class_dictionary_attribute_links()
            self._add_object_dictionary_attribute_links()
        self._enrich_and_validate_dictionary_attribute_types()
        self._add_datetime_sibling_dictionary_attributes()

    def _add_common_dictionary_attribute_links(self) -> None:
        if not self.browser_mode:
            return
        if "base_event" not in self._classes:
            raise SchemaException('Schema has not defined a "base_event" class')
        base_event = j_object(self._classes["base_event"])
        link = self._make_link("common", "base_event", base_event)
        self._add_links_to_dictionary_attributes(
            "class", "base_event", base_event, link
        )

    def _add_class_dictionary_attribute_links(self) -> None:
        if not self.browser_mode:
            return
        for cls_name, cls in self._classes.items():
            cls = j_object(cls)
            link = self._make_link("class", cls_name, cls)
            self._add_links_to_dictionary_attributes("class", cls_name, cls, link)

    def _add_object_dictionary_attribute_links(self) -> None:
        if not self.browser_mode:
            return
        for obj_name, obj in self._objects.items():
            obj = j_object(obj)
            link = self._make_link("object", obj_name, obj)
            self._add_links_to_dictionary_attributes("object", obj_name, obj, link)

    @staticmethod
    def _make_link(group: str, item_name: str, item: JObject) -> JObject:
        """
        Create link reference. The group value should be "common", "class", or "object",
        with "common" being a group holding the "base_event" class, which is treated
        specially.
        """
        link: JObject = {
            "group": group,
            "type": item_name,
            "caption": item.get("caption", "*No name*"),
        }
        if "extension" in item:
            link["extension"] = item["extension"]
        if item.get("@deprecated"):
            link["deprecated?"] = True
        return link

    @staticmethod
    def _sort_links(links: JArray) -> None:
        def link_to_key(link: JValue) -> tuple[str, str]:
            link = j_object(link)
            return j_string(link["group"]), j_string(link["type"])

        links.sort(key=link_to_key)

    def _add_links_to_dictionary_attributes(
        self, kind: str, item_name: str, item: JObject, link: JObject
    ) -> None:
        if not self.browser_mode:
            return
        dictionary_attributes = j_object(self._dictionary.setdefault("attributes", {}))
        item_attributes = j_object(item.setdefault("attributes", {}))
        for item_attribute_name in item_attributes.keys():
            if item_attribute_name in dictionary_attributes:
                dictionary_attribute = j_object(
                    dictionary_attributes[item_attribute_name]
                )

                # Create copy of link to avoid polluting original in case at least one
                # attribute is an object type.
                attribute_link = deep_copy_j_object(link)
                # attribute_keys is only used to track the different attribute name uses
                # of object types. We don't track the various attribute names that use
                # dictionary types.
                if "object_type" in dictionary_attribute:
                    attribute_link["attribute_keys"] = [item_attribute_name]
                links = j_array(dictionary_attribute.setdefault("_links", []))
                links.append(attribute_link)
                self._sort_links(links)
            else:
                raise SchemaException(
                    f'{kind} "{item_name}" uses undefined attribute'
                    f' "{item_attribute_name}"'
                )

    def _enrich_and_validate_dictionary_attribute_types(self) -> None:
        dictionary_attributes = j_object(self._dictionary.setdefault("attributes", {}))
        dictionary_types = j_object(self._dictionary.setdefault("types", {}))
        dictionary_types_attributes = j_object(
            dictionary_types.setdefault("attributes", {})
        )

        for attribute_name, attribute in dictionary_attributes.items():
            attribute = j_object(attribute)
            if "type" in attribute:
                attribute_type = attribute["type"]
            else:
                raise SchemaException(
                    self._dictionary_error_message(
                        attribute_name, attribute, 'does not define "type"'
                    )
                )
            if attribute_type == "object_t":
                # Object dictionary type
                # Add "object_name" to attribute details based on caption.
                # NOTE: This must be done after resolving patches and extends so caption
                # is resolved.
                object_type = attribute["object_type"]
                if object_type in self._objects:
                    obj = j_object(self._objects[object_type])
                    attribute["object_name"] = obj.get("caption", "")
                else:
                    raise SchemaException(
                        self._dictionary_error_message(
                            attribute_name,
                            attribute,
                            f'uses undefined object type "{object_type}"',
                        )
                    )
            else:
                # Normal dictionary type
                if attribute_type in dictionary_types_attributes:
                    type_detail = j_object(dictionary_types_attributes[attribute_type])
                    attribute["type_name"] = type_detail.get("caption", "")
                else:
                    raise SchemaException(
                        self._dictionary_error_message(
                            attribute_name,
                            attribute,
                            f'uses undefined "type" "{attribute_type}"',
                        )
                    )

    @staticmethod
    def _dictionary_error_message(
        attribute_name: str, attribute: JObject, problem: str
    ) -> str:
        if "extension" in attribute:
            return (
                f'Dictionary attribute "{attribute_name}" from extension'
                f' "{attribute["extension"]}" {problem}'
            )
        return f'Dictionary attribute "{attribute_name}" {problem}'

    def _add_datetime_sibling_dictionary_attributes(self) -> None:
        """
        When "datetime" profile and "datetime_t" dictionary type are both define,
        add magic datetime dictionary attributes as siblings to dictionary attributes
        with type "timestamp_t".
        """
        got_datetime_profile = "datetime" in self._base_profiles
        dictionary_types = j_object(self._dictionary.setdefault("types", {}))
        dictionary_types_attributes = j_object(
            dictionary_types.setdefault("attributes", {})
        )
        got_datetime_t = "datetime_t" in dictionary_types_attributes
        got_timestamp_t = "timestamp_t" in dictionary_types_attributes
        if got_datetime_profile and got_datetime_t and got_timestamp_t:
            logger.info(
                'Datetime siblings of attributes with the "timestamp_t" type will be'
                " added because the following are defined in the schema: the"
                ' "datetime" profile, the "datetime_t" dictionary type, and the'
                ' "timestamp_t" dictionary type.'
            )
            # Add datetime siblings
            dictionary_attributes = j_object(
                self._dictionary.setdefault("attributes", {})
            )
            # We can't add dictionary_attributes while iterator, so instead add to
            # another dict and then merge
            additions: JObject = {}
            for attribute_name, attribute in dictionary_attributes.items():
                attribute = j_object(attribute)
                if attribute.get("type") == "timestamp_t":
                    sibling = deep_copy_j_object(attribute)
                    # No need to fix up attribute_keys as they are not used for
                    # dictionary types
                    sibling["type"] = "datetime_t"
                    sibling["type_name"] = "Datetime"
                    additions[self._make_datetime_attribute_name(attribute_name)] = (
                        sibling
                    )
            dictionary_attributes.update(additions)
        elif got_datetime_profile:
            raise SchemaException(
                'Schema defines "datetime" profile but does not define "datetime_t"'
                " dictionary type"
            )
        elif got_datetime_t:
            raise SchemaException(
                'Schema defines "datetime_t" dictionary type but does not define'
                ' "datetime" profile'
            )
        else:
            logger.info(
                'This schema does not define the "datetime" profile or the "datetime_t"'
                " dictionary type, so datetime siblings of timestamp_t attributes"
                " will not be added."
            )

    @staticmethod
    def _make_datetime_attribute_name(timestamp_name: str) -> str:
        return f"{timestamp_name}_dt"

    def _observables_from_dictionary(self) -> None:
        dictionary_types = j_object(self._dictionary.setdefault("types", {}))
        dictionary_types_attributes = j_object(
            dictionary_types.setdefault("attributes", {})
        )
        dictionary_attributes = j_object(self._dictionary.setdefault("attributes", {}))
        self._observables_from_dictionary_items(
            dictionary_types_attributes, "Dictionary Type"
        )
        self._observables_from_dictionary_items(
            dictionary_attributes, "Dictionary Attribute"
        )

    def _observables_from_dictionary_items(self, items: JObject, kind: str) -> None:
        for key, detail in items.items():
            detail = j_object(detail)
            if "observable" in detail:
                observable_type_id = str(detail["observable"])
                if observable_type_id in self._observable_type_id_dict:
                    entry = j_object(self._observable_type_id_dict[observable_type_id])
                    if "extension" in detail:
                        kind = f'extension "{detail["extension"]}" {kind}'
                    raise SchemaException(
                        f"Collision of observable type_id {observable_type_id} between"
                        f' {kind} "{key}" caption "{detail.get("caption")}"'
                        f' "observable" and "{entry["caption"]}":'
                        f" {entry['description']}"
                    )
                else:
                    entry = self._make_observable_enum_entry(
                        j_string(detail.get("caption", "")),
                        j_string(detail.get("description", "")),
                        kind,
                    )
                    self._observable_type_id_dict[observable_type_id] = entry

    def _validate_object_profiles_and_add_links(self) -> None:
        self._validate_item_profiles_and_add_links("object", self._objects)

    def _validate_class_profiles_and_add_links(self) -> None:
        self._validate_item_profiles_and_add_links("class", self._classes)

    def _validate_item_profiles_and_add_links(self, group: str, items: JObject) -> None:
        for item_name, item in items.items():
            item = j_object(item)
            if "profiles" in item:
                for profile_name in j_array(item["profiles"]):
                    profile_name = j_string(profile_name)
                    if "/" in profile_name:
                        if profile_name in self._extension_profiles:
                            profile = j_object(self._extension_profiles[profile_name])
                        else:
                            if "extension" in item:
                                full_group = f'extension "{item["extension"]}" {group}'
                            else:
                                full_group = group
                            raise SchemaException(
                                f'Undefined extension profile "{profile_name}" used in'
                                f' {full_group} "{item_name}"'
                            )
                    elif profile_name in self._base_profiles:
                        profile = j_object(self._base_profiles[profile_name])
                    else:
                        if "extension" in item:
                            full_group = f'extension "{item["extension"]}" {group}'
                        else:
                            full_group = group
                        raise SchemaException(
                            f'Undefined base schema profile "{profile_name}" used in'
                            f' {full_group} "{item_name}"'
                        )

                    if self.browser_mode:
                        link = self._make_link(group, item_name, item)
                        links = j_array(profile.setdefault("_links", []))
                        links.append(link)
                        self._sort_links(links)

    def _add_object_links(self) -> None:
        if not self.browser_mode:
            return

        dictionary_attributes = j_object(self._dictionary.setdefault("attributes", {}))
        for obj_name, obj in self._objects.items():
            obj = j_object(obj)
            links: JArray = []
            for attribute in dictionary_attributes.values():
                attribute = j_object(attribute)
                if attribute.get("object_type") == obj_name and "_links" in attribute:
                    attribute_links = deep_copy_j_array(j_array(attribute["_links"]))
                    links.extend(attribute_links)

            # Group by group and type and merge attribute_keys
            grouped_links: JObject = {}
            for link in links:
                link = j_object(link)
                group_key = f"{link['group']}:{link['type']}"
                if group_key in grouped_links:
                    group = j_object(grouped_links[group_key])
                    group_attribute_keys = j_array(group["attribute_keys"])
                    for key in j_array(link["attribute_keys"]):
                        if key not in group_attribute_keys:
                            group_attribute_keys.append(key)
                else:
                    grouped_links[group_key] = link

            # The final result is the values of the grouped_link dict
            links = list(grouped_links.values())
            self._sort_links(links)
            obj["_links"] = links

    def _update_observable_enum(self) -> None:
        if "observable" in self._objects:
            observable = j_object(self._objects["observable"])
            observable_attributes = j_object(observable.setdefault("attributes", {}))
            observable_type_id = j_object(
                observable_attributes.setdefault("type_id", {})
            )
            dest_enum_dict = j_object(observable_type_id.setdefault("enum", {}))
            for (
                source_type_id_key,
                source_enum_detail,
            ) in self._observable_type_id_dict.items():
                if source_type_id_key in dest_enum_dict:
                    # This is a defensive coding check - we should have already detected
                    # the collision
                    raise SchemaException(
                        f"Collision of observable type_id {source_type_id_key} detected"
                        f" while building observable object enum values."
                        f" This a bug. Please file an issue at"
                        f" https://github.com/ocsf/ocsf-schema-compiler/issues."
                    )
                else:
                    dest_enum_dict[source_type_id_key] = source_enum_detail

    def _consolidate_object_profiles(self) -> None:
        """
        Update object profiles to includes profile from all attributes with object
        types.
        """
        self._consolidate_profiles("object", self._objects)

    def _consolidate_class_profiles(self) -> None:
        """
        Update class profiles to include profiles from all attributes with object
        types.
        """
        self._consolidate_profiles("class", self._classes)

    # ProfilesDict is a mapping from class or object name to list of profiles or None
    # We really prefer to list[str] rather than JArray (list[JValue]), however JArray
    # works better with the types used here, and keeps Pyright happy.
    type ProfilesDict = dict[str, JArray | None]

    def _consolidate_profiles(self, group: str, items: JObject) -> None:
        for item_name, item in items.items():
            item = j_object(item)
            profiles_dict: SchemaCompiler.ProfilesDict = {}
            try:
                if group == "class":
                    # The recursive step is for objects. For classes, we need to do the
                    # first step here.
                    if "profiles" in item:
                        # Use prefix for class so it does not collide with object names
                        item_profiles = j_array(item["profiles"])
                        profiles_dict[f"class:{item_name}"] = item_profiles

                    item_attributes = j_object(item.setdefault("attributes", {}))
                    for attribute_name, attribute in item_attributes.items():
                        # This happens before enriching attributes with dictionary
                        # information, so we need to do extra work to determine actual
                        # type
                        object_type = self._find_object_type(
                            attribute_name, j_object(attribute)
                        )
                        if object_type:
                            self._gather_profiles(object_type, profiles_dict)

                else:
                    # for object, we can jump straight to _gather_profiles
                    self._gather_profiles(item_name, profiles_dict)
            except SchemaException as e:
                raise SchemaException(
                    f'Consolidating profiles of {group} "{item_name}" failed: {e}'
                ) from e

            all_profiles: set[JValue] = set()
            for profile_list in profiles_dict.values():
                if profile_list:
                    all_profiles.update(profile_list)

            if all_profiles:
                sorted_profiles = sorted(all_profiles, key=lambda v: j_string(v))
                if logger.isEnabledFor(logging.DEBUG):
                    items_with_profiles: JArray = []
                    for profile_name, profile_list in profiles_dict.items():
                        if profile_list:
                            items_with_profiles.append(profile_name)
                    items_with_profiles.sort(key=lambda v: j_string(v))
                    original_profiles = item.get("profiles")
                    if sorted_profiles == original_profiles:
                        logger.debug(
                            'Consolidated profiles of %s "%s": profiles unchanged.',
                            group,
                            item_name,
                        )
                    else:
                        logger.debug(
                            'Consolidated profiles of %s "%s".'
                            "\n    Original profiles: %s."
                            "\n    Consolidated from: %s."
                            "\n    Consolidated profiles: %s.",
                            group,
                            item_name,
                            original_profiles,
                            items_with_profiles,
                            sorted_profiles,
                        )
                item["profiles"] = j_array(sorted_profiles)
            else:
                logger.debug(
                    'Consolidated profiles of %s "%s": no profiles.', group, item_name
                )

    def _gather_profiles(
        self, obj_name: str, profiles_dict: SchemaCompiler.ProfilesDict
    ) -> None:
        """
        Gather profiles from obj_name object (if any) and its attributes that are object
        types, recursively.
        """
        if obj_name in profiles_dict:
            return  # obj_name already processed

        if obj_name not in self._objects:
            raise SchemaException(f'object "{obj_name}" is not defined')
        obj = j_object(self._objects[obj_name])

        # We specifically want actual and None values since profiles_dict is doing both
        # gathering profiles and marking things that have been processed.
        profiles_dict[obj_name] = j_array_optional(obj.get("profiles"))

        obj_attributes = j_object(obj.setdefault("attributes", {}))
        for attribute_name, attribute in obj_attributes.items():
            object_type = self._find_object_type(attribute_name, j_object(attribute))
            if object_type:
                self._gather_profiles(object_type, profiles_dict)

    def _find_object_type(self, attribute_name: str, attribute: JObject) -> str | None:
        """
        Determine object type of unprocessed object or class attribute
        (an attribute not yet merged with dictionary attribute information).
        Returns None is if attribute is not an object type (it's a dictionary type).
        """
        # We haven't merged dictionary attributes on to class and object attributes yet,
        # so "object_type" should not yet be present. The logic in this method depends
        # on the unprocessed "type", and will not work if "type" has already been
        # changed to "object_t" and "object_type" added for object types.
        assert "object_type" not in attribute, (
            f'Object attribute "{attribute_name}" unexpectedly already has'
            ' "object_type"'
        )

        dictionary_attributes = j_object(self._dictionary.setdefault("attributes", {}))
        if attribute_name not in dictionary_attributes:
            raise SchemaException(
                f'attribute "{attribute_name}" is not a defined dictionary attributes'
            )
        dictionary_attribute = j_object(dictionary_attributes[attribute_name])
        # will return None if "object_type" is not present
        return j_string_optional(dictionary_attribute.get("object_type"))

    def _verify_object_attributes_and_add_datetime(self) -> None:
        self._verify_item_attributes_and_add_datetime(self._objects, "object")

    def _verify_class_attributes_and_add_datetime(self) -> None:
        self._verify_item_attributes_and_add_datetime(self._classes, "class")

    def _verify_item_attributes_and_add_datetime(
        self, items: JObject, kind: str
    ) -> None:
        dictionary_attributes = j_object(self._dictionary.setdefault("attributes", {}))
        dictionary_types = j_object(self._dictionary.setdefault("types", {}))
        dictionary_types_attributes = j_object(
            dictionary_types.setdefault("attributes", {})
        )

        got_datetime_profile = "datetime" in self._base_profiles
        got_datetime_t = "datetime_t" in dictionary_types_attributes
        add_datetime = got_datetime_profile and got_datetime_t

        for item_name, item in items.items():
            item = j_object(item)
            # We cannot add attributes while iterating attributes, so track additions
            dt_attribute_additions: JObject = {}
            attributes = j_object(item.setdefault("attributes", {}))
            for attribute_name, attribute in attributes.items():
                attribute = j_object(attribute)
                dictionary_attribute = j_object(
                    dictionary_attributes.get(attribute_name, {})
                )
                if "description" not in attribute:
                    # No description. Make sure fallback dictionary description isn't
                    # meant to be overridden.
                    dictionary_description = j_string(
                        dictionary_attribute.get("description", "")
                    )
                    if "See specific usage" in dictionary_description:
                        self._warning(
                            'Please update the "description" of %s "%s" attribute "%s":'
                            ' "%s"',
                            kind,
                            item_name,
                            attribute_name,
                            dictionary_description,
                        )

                if add_datetime:
                    if "type" in attribute:
                        attribute_type = attribute["type"]
                    else:
                        attribute_type = dictionary_attribute.get("type")
                    if attribute_type == "timestamp_t":
                        dt_attribute = deep_copy_j_object(attribute)
                        if self.legacy_mode:
                            dt_attribute["profile"] = "datetime"
                        else:
                            dt_attribute["profiles"] = ["datetime"]
                        dt_attribute["requirement"] = "optional"
                        dt_attribute_additions[
                            self._make_datetime_attribute_name(attribute_name)
                        ] = dt_attribute

            if dt_attribute_additions:
                attributes.update(dt_attribute_additions)
                profiles = j_array(item.setdefault("profiles", []))
                if "datetime" not in profiles:
                    profiles.append("datetime")
                    # keep profiles sorted
                    profiles.sort(key=lambda v: j_string(v))

    def _ensure_attributes_have_requirement(self) -> None:
        # Track attributes in profiles, classes, and objects that incorrectly do _not_
        # have a "requirement"
        missing_requirements: list[str] = []
        self._ensure_item_attributes_have_requirement(
            self._base_profiles, "profile", missing_requirements
        )
        self._ensure_item_attributes_have_requirement(
            self._extension_profiles, "profile", missing_requirements
        )
        self._ensure_item_attributes_have_requirement(
            self._classes, "class", missing_requirements
        )
        self._ensure_item_attributes_have_requirement(
            self._objects, "object", missing_requirements
        )
        if missing_requirements:
            missing_requirements.sort()
            self._warning(
                'The following attributes do not have a "requirement" property and a'
                ' value of "optional" will be used:\n    %s',
                "\n    ".join(missing_requirements),
            )

    @staticmethod
    def _ensure_item_attributes_have_requirement(
        items: JObject, kind: str, missing_requirements: list[str]
    ) -> None:
        for item_name, item in items.items():
            item = j_object(item)
            fixed: list[str] = []
            item_attributes = j_object(item.setdefault("attributes", {}))
            for attribute_name, attribute in item_attributes.items():
                attribute = j_object(attribute)
                if attribute.get("requirement") is None:
                    attribute["requirement"] = "optional"
                    fixed.append(f'"{attribute_name}"')
            if fixed:
                fixed.sort()
                if "extension" in item:
                    name = f'extension "{item["extension"]}" {kind} "{item_name}"'
                else:
                    name = f'{kind} "{item_name}"'
                missing_requirements.append(f"{name} attribute(s): {', '.join(fixed)}")

    def _finish_attributes(self):
        self._finish_item_attributes(self._classes, "class")
        self._finish_item_attributes(self._objects, "object")

        # Profile attributes are only used for schema browser UI of profiles. They are
        # not needed for event validation as the attribute details are merged into the
        # classes and objects that use them.
        if self.browser_mode:
            # Do "annotations" processing so profile attributes match work done when
            # including profiles
            for item in self._base_profiles.values():
                item = j_object(item)
                if "annotations" in item and "attributes" in item:
                    annotations = j_object(item["annotations"])
                    item_attributes = j_object(item["attributes"])
                    for attribute in item_attributes.values():
                        attribute = j_object(attribute)
                        self._add_attribute_annotations(annotations, attribute)
            for item in self._extension_profiles.values():
                item = j_object(item)
                if "annotations" in item and "attributes" in item:
                    annotations = j_object(item["annotations"])
                    item_attributes = j_object(item["attributes"])
                    for attribute in item_attributes.values():
                        attribute = j_object(attribute)
                        self._add_attribute_annotations(annotations, attribute)
            # Finish the attributes, enriching with dictionary attribute information
            self._finish_item_attributes(self._base_profiles, "profile")
            self._finish_item_attributes(self._extension_profiles, "profile")
        else:
            for profile in self._base_profiles.values():
                profile = j_object(profile)
                if "attributes" in profile:
                    del profile["attributes"]
            for profile in self._extension_profiles.values():
                profile = j_object(profile)
                if "attributes" in profile:
                    del profile["attributes"]

    def _finish_item_attributes(self, items: JObject, kind: str) -> None:
        dictionary_attributes = j_object(self._dictionary.setdefault("attributes", {}))
        for item_name, item in items.items():
            item = j_object(item)
            attributes = j_object(item.setdefault("attributes", {}))
            new_attributes: JObject = {}
            for attribute_name, attribute in attributes.items():
                # TODO: Attribute that is not defined in dictionary attributes should
                #       never happen at this point, but does today due to the flawed
                #       splunk/splunk profile in the "splunk" extension. Once fixed,
                #       the if / else block can be removed, and here we can use an
                #       assert to catch logic bugs.
                # TODO: Start of what this block of code should eventually look like
                # assert attribute_name in dictionary_attributes, (
                #     f'Attribute "{attribute_name}" is not a defined dictionary'
                #     " attribute; this should have been caught earlier in the compile"
                #     " process"
                # )
                # new_attribute = deep_copy_j_object(
                #     j_object(dictionary_attributes[attribute_name])
                # )
                # deep_merge(new_attribute, attribute)
                # new_attributes[attribute_name] = new_attribute
                # TODO: End of what this block of code should eventually look like
                attribute = j_object(attribute)
                if attribute_name in dictionary_attributes:
                    new_attribute = deep_copy_j_object(
                        j_object(dictionary_attributes[attribute_name])
                    )
                    deep_merge(new_attribute, attribute)
                    new_attributes[attribute_name] = new_attribute
                else:
                    # This is a known issue with the 1.0.0-rc.2 with "splunk" extension
                    # compilation, so we will log and ignore this specific case, and
                    # assert otherwise.
                    if (
                        item_name == "splunk/splunk"
                        and "splunk" in self._extensions
                        and self._version == "1.0.0-rc.2"
                    ):
                        logger.debug(
                            "_finish_item_attributes - ignoring know issue with"
                            ' extension "splunk": attribute "%s" in %s "%s" is not a'
                            " defined dictionary attribute",
                            attribute_name,
                            kind,
                            item_name,
                        )
                    else:
                        assert attribute_name in dictionary_attributes, (
                            f'Attribute "{attribute_name}" in {kind} "{item_name}" is'
                            f" not a defined dictionary attribute; this should have"
                            f" been caught earlier in the compile process"
                        )

            item["attributes"] = new_attributes
            if self.browser_mode:
                self._add_sibling_of_to_attributes(new_attributes)

    @staticmethod
    def _add_sibling_of_to_attributes(attributes: JObject) -> None:
        # This must be done after finalizing attributes so full enum attribute details
        # are present. Specifically the enum attribute "sibling" key.

        sibling_of_dict: dict[str, str] = {}
        # Enum attributes point to their enum sibling through the :sibling attribute,
        # however the siblings do _not_ refer back to their related enum attribute,
        # so let's build that.
        # First pass, iterate attributes to find enum attributes and create mapping to
        # their siblings.
        for attribute_name, attribute in attributes.items():
            attribute = j_object(attribute)
            if "sibling" in attribute:
                # This is an enum attribute
                sibling_of_dict[j_string(attribute["sibling"])] = attribute_name

        if not sibling_of_dict:
            # no enum attributes present in attributes, so nothing to do
            return  # skip iterating attributes again uselessly

        # Second pass, look for enum attributes and add "_sibling_of" mapping
        for attribute_name, attribute in attributes.items():
            attribute = j_object(attribute)
            if attribute_name in sibling_of_dict:
                # This is an enum sibling. Add "_sibling_of" pointing back to its
                # related enum attribute.
                attribute["_sibling_of"] = sibling_of_dict[attribute_name]

    def _create_compile_output(self) -> JObject:
        if self.legacy_mode:
            if self.scope_extension_keys:
                classes = add_extension_scope_to_items(self._classes, self._objects)
                objects = add_extension_scope_to_items(self._objects, self._objects)
                add_extension_scope_to_dictionary(self._dictionary, self._objects)
            else:
                classes = self._classes
                objects = self._objects
            dictionary_types = j_object(self._dictionary.get("types", {}))
            return {
                "base_event": classes.get("base_event"),
                "classes": classes,
                "objects": objects,
                "dictionary_attributes": self._dictionary.get("attributes"),
                "types": dictionary_types.get("attributes"),
                "version": self._version,
            }

        output: JObject = {
            "categories": self._categories,
            "dictionary": self._dictionary,
            "classes": self._classes,
            "objects": self._objects,
            "profiles": self._base_profiles | self._extension_profiles,
            "extensions": self._extensions,
            "version": self._version,
            "compile_version": 1,
        }
        if self.browser_mode:
            output["browser_mode?"] = True
            output["all_classes"] = self._all_classes
            output["all_objects"] = self._all_objects
        return output
