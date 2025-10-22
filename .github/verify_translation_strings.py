"""Verify that all entity keys have corresponding translation strings."""

from __future__ import annotations

import ast
from collections.abc import Iterator
import json
from pathlib import Path
import re
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


def attribute_to_key(node: ast.Attribute, register_aliases: set[str]) -> str | None:
    """Extract attribute name if it originates from register_names alias."""

    names = dotted_path(node)
    if not names:
        return None

    base, *rest = names
    if base not in register_aliases or not rest:
        return None

    for attr in reversed(rest):
        if attr != "value":
            return attr
    return None


class EntityKeyCollector(ast.NodeVisitor):
    """Collect translation keys referenced in entity descriptions within a module."""

    def __init__(self, register_aliases: set[str]) -> None:
        """Initialise an empty collector."""

        self.entity_keys: set[str] = set()
        self.register_aliases = register_aliases
        self._binding_stack: list[dict[str, str]] = [{}]

    def _push_scope(self) -> None:
        self._binding_stack.append({})

    def _pop_scope(self) -> None:
        self._binding_stack.pop()

    def _add_binding(self, name: str, raw_key: str) -> None:
        self._binding_stack[-1][name] = raw_key

    def _lookup_binding(self, name: str) -> str | None:
        for scope in reversed(self._binding_stack):
            if name in scope:
                return scope[name]
        return None

    def _resolve_node(self, node: ast.AST) -> str | None:
        if isinstance(node, ast.Attribute):
            return attribute_to_key(node, self.register_aliases)
        if isinstance(node, ast.Constant) and isinstance(node.value, str):
            return node.value
        if isinstance(node, ast.Name):
            return self._lookup_binding(node.id)
        return None

    def _bind_function_defaults(
        self, node: ast.FunctionDef | ast.AsyncFunctionDef
    ) -> None:
        positional_args = list(node.args.posonlyargs) + list(node.args.args)
        defaults = node.args.defaults
        if defaults:
            for arg, default in zip(
                positional_args[-len(defaults) :], defaults, strict=False
            ):
                if key := self._resolve_node(default):
                    self._add_binding(arg.arg, key)

        for kw_arg, default in zip(
            node.args.kwonlyargs, node.args.kw_defaults, strict=False
        ):
            if default is None:
                continue
            if key := self._resolve_node(default):
                self._add_binding(kw_arg.arg, key)

    def visit_Call(self, node: ast.Call) -> None:
        """Inspect call nodes for entity descriptions and record their keys."""

        call_name = get_call_name(node.func)
        if call_name and call_name.endswith("EntityDescription"):
            # Skip 'key' if 'translation_key' is explicitly provided
            has_translation_key = any(
                kw.arg == "translation_key" for kw in node.keywords
            )
            for keyword in node.keywords:
                if keyword.arg == "key":
                    if has_translation_key:
                        continue
                elif keyword.arg != "translation_key":
                    continue

                if raw_key := self._resolve_node(keyword.value):
                    self.entity_keys.add(normalize_translation_key(raw_key))
        # Continue traversal to handle nested calls
        self.generic_visit(node)

    def visit_FunctionDef(self, node: ast.FunctionDef) -> None:
        """Track bindings within a synchronous function scope."""

        self._push_scope()
        self._bind_function_defaults(node)
        self.generic_visit(node)
        self._pop_scope()

    def visit_AsyncFunctionDef(self, node: ast.AsyncFunctionDef) -> None:
        """Track bindings within an asynchronous function scope."""

        self._push_scope()
        self._bind_function_defaults(node)
        self.generic_visit(node)
        self._pop_scope()

    def visit_ClassDef(self, node: ast.ClassDef) -> None:
        """Track bindings defined on a class body."""

        self._push_scope()
        self.generic_visit(node)
        self._pop_scope()

    def visit_Assign(self, node: ast.Assign) -> None:
        """Capture bindings from simple assignments."""

        raw_key = self._resolve_node(node.value)
        if raw_key is not None:
            for target in node.targets:
                if isinstance(target, ast.Name):
                    self._add_binding(target.id, raw_key)
        self.generic_visit(node)

    def visit_AnnAssign(self, node: ast.AnnAssign) -> None:
        """Capture bindings from annotated assignments."""

        if node.value is not None and isinstance(node.target, ast.Name):
            if raw_key := self._resolve_node(node.value):
                self._add_binding(node.target.id, raw_key)
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


def collect_entity_keys(component_path: Path) -> dict[str, set[str]]:
    """Collect entity keys defined in each platform module."""

    entity_keys_by_platform: dict[str, set[str]] = {}

    for platform_file in component_path.glob("*.py"):
        platform = platform_file.stem
        entity_keys_by_platform[platform] = set(iter_entity_keys(platform_file))

    return entity_keys_by_platform


def verify_translations(component_path: Path) -> int:
    """Verify that all entity keys have translations and no orphan strings."""

    strings_file = component_path / "strings.json"
    if not strings_file.exists():
        sys.stderr.write(f"Error: {strings_file} not found\n")
        return 1

    translation_keys = get_translation_keys(strings_file)
    entity_keys_by_platform = collect_entity_keys(component_path)

    missing_translations: dict[str, set[str]] = {}
    orphan_translations: dict[str, set[str]] = {}

    for platform, entity_keys in entity_keys_by_platform.items():
        if not entity_keys:
            continue

        translations = translation_keys.get(platform, set())
        missing = entity_keys - translations
        if missing:
            missing_translations[platform] = missing

    for platform, translations in translation_keys.items():
        entity_keys = entity_keys_by_platform.get(platform, set())
        unused = translations - entity_keys

        unused = {
            key
            for key in unused
            if not (re.match(r"^pv_\d\d", key) or re.match(r"^state_\d_\d", key))
        }
        if unused:
            orphan_translations[platform] = unused

    if missing_translations or orphan_translations:
        if missing_translations:
            sys.stderr.write("❌ Missing translation keys found:\n\n")
            for platform, keys in sorted(missing_translations.items()):
                sys.stderr.write(f"  {platform}:\n")
                for key in sorted(keys):
                    sys.stderr.write(f"    - {key}\n")
            sys.stderr.write(
                "\nPlease add the missing keys to strings.json under the "
                'appropriate "entity" section.\n\n'
            )

        if orphan_translations:
            sys.stderr.write("❌ Unused translation keys found:\n\n")
            for platform, keys in sorted(orphan_translations.items()):
                sys.stderr.write(f"  {platform}:\n")
                for key in sorted(keys):
                    sys.stderr.write(f"    - {key}\n")
            sys.stderr.write(
                "\nPlease remove these keys or update the corresponding entity descriptions.\n"
            )

        return 1

    sys.stdout.write(
        "✅ All entity keys have corresponding translation strings and no unused entries\n"
    )
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
