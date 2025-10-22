"""Verify that all entity keys have corresponding translation strings."""

from __future__ import annotations

import ast
from collections.abc import Iterator
import json
from pathlib import Path
import sys


def normalize_translation_key(raw_key: str) -> str:
    """Normalise the key to the expected translation key format."""

    return (
        raw_key.replace("#", "_")
        .replace("-", "_")
        .replace(" ", "_")
        .replace("/", "_")
        .lower()
    )


def get_call_name(func: ast.AST) -> str | None:
    """Return the textual name for a call node."""

    if isinstance(func, ast.Name):
        return func.id
    if isinstance(func, ast.Attribute):
        return func.attr
    return None


def dotted_path(node: ast.AST) -> list[str] | None:
    """Return the dotted path represented by a node."""

    parts: list[str] = []
    current: ast.AST = node

    while isinstance(current, ast.Attribute):
        parts.append(current.attr)
        current = current.value

    if isinstance(current, ast.Name):
        parts.append(current.id)
    else:
        return None

    parts.reverse()
    return parts


def attribute_to_key(
    node: ast.Attribute, register_aliases: set[str]
) -> tuple[str, bool] | None:
    """Extract attribute name if it originates from register_names alias."""

    names = dotted_path(node)
    if not names:
        return None

    base, *rest = names
    if base not in register_aliases or not rest:
        return None

    for attr in reversed(rest):
        if attr != "value":
            return attr, True

    return rest[-1], True


def extract_key_string(
    node: ast.AST, register_aliases: set[str]
) -> tuple[str, bool] | None:
    """Best effort extraction of the entity key from an AST node."""

    if isinstance(node, ast.Attribute):
        return attribute_to_key(node, register_aliases)

    return None


class EntityKeyCollector(ast.NodeVisitor):
    """Collect translation keys referenced in entity descriptions within a module."""

    def __init__(self, register_aliases: set[str]) -> None:
        """Initialise an empty collector."""

        self.entity_keys: set[str] = set()
        self.register_aliases = register_aliases

    def visit_Call(self, node: ast.Call) -> None:
        """Inspect call nodes for entity descriptions and record their keys."""

        call_name = get_call_name(node.func)
        if call_name and call_name.endswith("EntityDescription"):
            for keyword in node.keywords:
                if keyword.arg == "key":
                    result = extract_key_string(keyword.value, self.register_aliases)
                    if result is None:
                        continue
                    raw_key, _ = result
                    self.entity_keys.add(normalize_translation_key(raw_key))
        # Continue traversal to handle nested calls
        self.generic_visit(node)


def find_register_aliases(tree: ast.AST) -> set[str]:
    """Return the alias names used for huawei_solar.register_names."""

    aliases: set[str] = set()

    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and node.module == "huawei_solar":
            for alias in node.names:
                if alias.name == "register_names":
                    aliases.add(alias.asname or alias.name)
        elif isinstance(node, ast.Import):
            for alias in node.names:
                if alias.name == "huawei_solar.register_names":
                    aliases.add(alias.asname or alias.name.split(".")[-1])

    return aliases


def iter_entity_keys(file_path: Path) -> Iterator[str]:
    """Yield normalised entity keys referenced in the given Python module."""

    try:
        source = file_path.read_text(encoding="utf-8")
    except OSError as err:
        sys.stderr.write(f"Error reading {file_path}: {err}\n")
        return iter(())

    try:
        tree = ast.parse(source)
    except SyntaxError as err:
        sys.stderr.write(f"Error parsing {file_path}: {err}\n")
        return iter(())

    register_aliases = find_register_aliases(tree)
    if not register_aliases:
        return iter(())

    collector = EntityKeyCollector(register_aliases)
    collector.visit(tree)
    return iter(collector.entity_keys)


def get_translation_keys(strings_file: Path) -> dict[str, set[str]]:
    """Extract all translation keys from strings.json grouped by platform."""

    try:
        strings_data = json.loads(strings_file.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as err:
        sys.stderr.write(f"Error loading {strings_file}: {err}\n")
        return {}

    translation_keys: dict[str, set[str]] = {}

    for platform, entities in strings_data.get("entity", {}).items():
        translation_keys[platform] = set(entities.keys())

    return translation_keys


def verify_translations(component_path: Path) -> int:
    """Verify that all entity keys have translations."""

    strings_file = component_path / "strings.json"
    if not strings_file.exists():
        sys.stderr.write(f"Error: {strings_file} not found\n")
        return 1

    translation_keys = get_translation_keys(strings_file)

    missing_translations: dict[str, set[str]] = {}

    for platform, platform_keys in translation_keys.items():
        platform_file = component_path / f"{platform}.py"
        if not platform_file.exists():
            continue

        entity_keys = set(iter_entity_keys(platform_file))
        if not entity_keys:
            continue

        missing = entity_keys - platform_keys
        if missing:
            missing_translations[platform] = missing

    # Also check for platforms with entity descriptions but no translation section yet
    for platform_file in component_path.glob("*.py"):
        platform = platform_file.stem
        if platform in translation_keys:
            continue
        entity_keys = set(iter_entity_keys(platform_file))
        if entity_keys:
            missing_translations.setdefault(platform, set()).update(entity_keys)

    if missing_translations:
        sys.stderr.write("❌ Missing translation keys found:\n\n")
        for platform, keys in sorted(missing_translations.items()):
            sys.stderr.write(f"  {platform}:\n")
            for key in sorted(keys):
                sys.stderr.write(f"    - {key}\n")
        sys.stderr.write(
            "\nPlease add the missing keys to strings.json under the "
            'appropriate "entity" section.\n'
        )
        return 1

    sys.stdout.write("✅ All entity keys have corresponding translation strings\n")
    return 0


def main() -> int:
    """Main entry point."""

    script_dir = Path(__file__).parent
    component_path = script_dir.parent

    if not (component_path / "manifest.json").exists():
        sys.stderr.write(f"Error: manifest.json not found in {component_path}\n")
        sys.stderr.write("Please run this script from the component directory\n")
        return 1

    return verify_translations(component_path)


if __name__ == "__main__":
    sys.exit(main())
