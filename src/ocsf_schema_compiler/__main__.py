import json
import logging
from argparse import ArgumentParser
from pathlib import Path
from sys import stderr
from time import perf_counter

from ocsf_schema_compiler import __version__
from ocsf_schema_compiler.compiler import SchemaCompiler

logger = logging.getLogger(__name__)


def main():
    parser = ArgumentParser(
        description=f"Open Cybersecurity Schema Framework Schema Compiler, version "
        f"{__version__}. Compile an OCSF schema directory structure down to a single"
        " JSON object written to standard output. Logs are written to standard error."
        " Source code at https://github.com/ocsf/ocsf-schema-compiler.",
    )
    _ = parser.add_argument(
        "path",
        type=Path,
        help="path to an OCSF schema directory (e.g., a git clone of"
        " https://github.com/ocsf/ocsf-schema)",
    )
    _ = parser.add_argument(
        "-i",
        "--ignore-platform-extensions",
        action="store_true",
        default=False,
        help="ignore platform extensions (if any); these are in an extensions directory"
        " under the schema directory; default: %(default)s",
    )
    _ = parser.add_argument(
        "-e",
        "--extensions-path",
        action="append",
        type=Path,
        metavar="PATH",
        dest="extensions_paths",
        help="optional path to a directory containing one or more OCSF schema"
        " extensions; can be repeated",
    )
    group = parser.add_mutually_exclusive_group()
    _ = group.add_argument(
        "-b",
        "--browser-mode",
        action="store_true",
        default=False,
        help="include extra information needed by the schema browser (the OCSF Server);"
        " cannot be used with the -l, --legacy-mode option; default: %(default)s",
    )
    _ = group.add_argument(
        "-l",
        "--legacy-mode",
        action="store_true",
        default=False,
        help="output schema in legacy export schema layout; cannot be used with the"
        " -b, --browser-mode option; default: %(default)s",
    )
    _ = parser.add_argument(
        "-s",
        "--scope-extension-keys",
        action="store_true",
        default=False,
        help="scope extension keys; can only be used with the -l, --legacy-mode option;"
        " default: %(default)s",
    )
    _ = parser.add_argument(
        "--log-level",
        choices=("DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"),
        default="INFO",
        help="set log level; logs are written to standard error; default: %(default)s",
    )
    _ = parser.add_argument(
        "-v",
        "--version",
        action="version",
        version="%(prog)s " + __version__,
    )

    args = parser.parse_args()
    if args.scope_extension_keys and not args.legacy_mode:  # pyright: ignore[reportAny]
        parser.error("-s, --scope-extension-keys requires -l, --legacy-mode")

    logging.basicConfig(
        format="%(levelname)s: %(message)s",
        style="%",
        stream=stderr,
        level=args.log_level,  # pyright: ignore[reportAny]
    )

    start_seconds = perf_counter()

    compiler = SchemaCompiler(
        args.path,  # pyright: ignore[reportAny]
        args.ignore_platform_extensions,  # pyright: ignore[reportAny]
        args.extensions_paths,  # pyright: ignore[reportAny]
        args.browser_mode,  # pyright: ignore[reportAny]
        args.legacy_mode,  # pyright: ignore[reportAny]
        args.scope_extension_keys,  # pyright: ignore[reportAny]
    )
    output = compiler.compile()

    duration = perf_counter() - start_seconds
    logger.info("Schema compilation took %.3f seconds", duration)

    print(json.dumps(output))


if __name__ == "__main__":
    main()
