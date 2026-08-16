from __future__ import annotations

from typing import Optional

import tree_sitter_python as tspython
from tree_sitter import Language, Node, Parser

from ast_pruner.models import ImportedSymbol, ParsedFile, ParsedSymbol
from ast_pruner.parsers.base import BaseParser

PY_LANGUAGE = Language(tspython.language())
_parser = Parser(PY_LANGUAGE)


def _text(node: Node, source: bytes) -> str:
    return source[node.start_byte:node.end_byte].decode("utf-8", errors="replace")


def _child_by_field(node: Node, field: str) -> Optional[Node]:
    return node.child_by_field_name(field)


class PythonParser(BaseParser):
    def parse(self, abs_path: str) -> ParsedFile:
        with open(abs_path, "rb") as f:
            source = f.read()

        tree = _parser.parse(source)
        root = tree.root_node

        symbols = self._extract_symbols(root, source)
        imports = self._extract_imports(root, source)

        return ParsedFile(
            abs_path=abs_path,
            language="python",
            source=source,
            symbols=symbols,
            imports=imports,
        )

    def _extract_symbols(self, root: Node, source: bytes) -> list[ParsedSymbol]:
        symbols: list[ParsedSymbol] = []
        for child in root.children:
            sym = self._node_to_symbol(child, source, exported=True)
            if sym:
                symbols.append(sym)
        return symbols

    def _node_to_symbol(self, node: Node, source: bytes, exported: bool) -> Optional[ParsedSymbol]:
        if node.type == "function_definition":
            return self._parse_function(node, source, exported)
        if node.type == "class_definition":
            return self._parse_class(node, source, exported)
        if node.type == "decorated_definition":
            return self._parse_decorated(node, source, exported)
        if node.type in ("expression_statement", "assignment"):
            return self._parse_assignment(node, source, exported)
        return None

    def _parse_function(self, node: Node, source: bytes, exported: bool) -> Optional[ParsedSymbol]:
        name_node = _child_by_field(node, "name")
        if not name_node:
            return None
        body_node = _child_by_field(node, "body")
        return ParsedSymbol(
            name=_text(name_node, source),
            kind="function",
            start_byte=node.start_byte,
            end_byte=node.end_byte,
            start_line=node.start_point[0],
            end_line=node.end_point[0],
            is_exported=exported,
            body_start_byte=body_node.start_byte if body_node else None,
            body_end_byte=body_node.end_byte if body_node else None,
        )

    def _parse_class(self, node: Node, source: bytes, exported: bool) -> Optional[ParsedSymbol]:
        name_node = _child_by_field(node, "name")
        if not name_node:
            return None
        body_node = _child_by_field(node, "body")
        return ParsedSymbol(
            name=_text(name_node, source),
            kind="class",
            start_byte=node.start_byte,
            end_byte=node.end_byte,
            start_line=node.start_point[0],
            end_line=node.end_point[0],
            is_exported=exported,
            body_start_byte=body_node.start_byte if body_node else None,
            body_end_byte=body_node.end_byte if body_node else None,
        )

    def _parse_decorated(self, node: Node, source: bytes, exported: bool) -> Optional[ParsedSymbol]:
        definition = _child_by_field(node, "definition")
        if not definition:
            return None
        inner = self._node_to_symbol(definition, source, exported)
        if not inner:
            return None
        # Use outer decorated_definition span so decorators are included
        return ParsedSymbol(
            name=inner.name,
            kind=inner.kind,
            start_byte=node.start_byte,
            end_byte=node.end_byte,
            start_line=node.start_point[0],
            end_line=node.end_point[0],
            is_exported=inner.is_exported,
            body_start_byte=inner.body_start_byte,
            body_end_byte=inner.body_end_byte,
        )

    def _parse_assignment(self, node: Node, source: bytes, exported: bool) -> Optional[ParsedSymbol]:
        # Handle simple top-level assignments: FOO = ... or foo: int = ...
        if node.type == "expression_statement":
            child = node.children[0] if node.children else None
            if not child or child.type != "assignment":
                return None
            node = child
        name_node = _child_by_field(node, "left")
        if not name_node or name_node.type != "identifier":
            return None
        return ParsedSymbol(
            name=_text(name_node, source),
            kind="variable",
            start_byte=node.start_byte,
            end_byte=node.end_byte,
            start_line=node.start_point[0],
            end_line=node.end_point[0],
            is_exported=exported,
            body_start_byte=None,
            body_end_byte=None,
        )

    def _extract_imports(self, root: Node, source: bytes) -> list[ImportedSymbol]:
        imports: list[ImportedSymbol] = []
        for child in root.children:
            if child.type == "import_from_statement":
                imports.extend(self._parse_from_import(child, source))
            elif child.type == "import_statement":
                imports.extend(self._parse_plain_import(child, source))
        return imports

    def _parse_from_import(self, node: Node, source: bytes) -> list[ImportedSymbol]:
        # from .module import foo, bar as baz
        module_node = _child_by_field(node, "module_name")
        specifier = _text(module_node, source) if module_node else ""

        # Count leading dots for relative imports
        dots = 0
        for ch in node.children:
            if ch.type == ".":
                dots += 1
            elif ch.type not in ("from", "import"):
                break

        if dots > 0:
            # relative import — convert to a dot-prefixed specifier
            specifier = "." * dots + specifier
        elif not specifier.startswith("."):
            # absolute import from external package (no dot prefix)
            pass

        results: list[ImportedSymbol] = []
        for ch in node.children:
            if ch.type == "dotted_name" and ch != module_node:
                name = _text(ch, source)
                results.append(ImportedSymbol(name=name, alias=name, source_specifier=specifier))
            elif ch.type == "aliased_import":
                name_node = _child_by_field(ch, "name")
                alias_node = _child_by_field(ch, "alias")
                if name_node:
                    name = _text(name_node, source).split(".")[-1]
                    alias = _text(alias_node, source) if alias_node else name
                    results.append(ImportedSymbol(name=alias, alias=name, source_specifier=specifier))
            elif ch.type == "wildcard_import":
                results.append(ImportedSymbol(name="*", alias="*", source_specifier=specifier))
        return results

    def _parse_plain_import(self, node: Node, source: bytes) -> list[ImportedSymbol]:
        results: list[ImportedSymbol] = []
        for ch in node.children:
            if ch.type == "dotted_name":
                name = _text(ch, source)
                results.append(ImportedSymbol(name=name, alias=name, source_specifier=name))
            elif ch.type == "aliased_import":
                name_node = _child_by_field(ch, "name")
                alias_node = _child_by_field(ch, "alias")
                if name_node:
                    name = _text(name_node, source)
                    alias = _text(alias_node, source) if alias_node else name
                    results.append(ImportedSymbol(name=alias, alias=name, source_specifier=name))
        return results
