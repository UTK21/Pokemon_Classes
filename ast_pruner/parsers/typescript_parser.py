from __future__ import annotations

from typing import Optional

import tree_sitter_typescript as tsts
from tree_sitter import Language, Node, Parser

from ast_pruner.models import ImportedSymbol, ParsedFile, ParsedSymbol
from ast_pruner.parsers.javascript_parser import JavaScriptParser, _child_by_field, _text

TS_LANGUAGE = Language(tsts.language_typescript())
TSX_LANGUAGE = Language(tsts.language_tsx())


class TypeScriptParser(JavaScriptParser):
    """Parser for .ts / .tsx files. Extends JS parser with TS-specific nodes."""

    def __init__(self, tsx: bool = False) -> None:
        self._tsx = tsx

    def _get_language(self) -> Language:
        return TSX_LANGUAGE if self._tsx else TS_LANGUAGE

    def _make_parser(self) -> Parser:
        return Parser(self._get_language())

    def parse(self, abs_path: str) -> ParsedFile:
        pf = super().parse(abs_path)
        pf.language = "typescript"
        return pf

    def _node_to_symbols(self, node: Node, source: bytes) -> list[ParsedSymbol]:
        # Handle TS-only top-level node types first
        if node.type == "interface_declaration":
            s = self._parse_interface(node, source, exported=False)
            return [s] if s else []
        if node.type == "type_alias_declaration":
            s = self._parse_type_alias(node, source, exported=False)
            return [s] if s else []
        if node.type == "ambient_declaration":
            # declare function / declare class / declare const
            return self._parse_ambient(node, source)
        # Fall through to JS handling (includes export_statement which wraps TS nodes)
        syms = super()._node_to_symbols(node, source)
        return syms

    def _parse_export(self, node: Node, source: bytes) -> list[ParsedSymbol]:
        results: list[ParsedSymbol] = []
        for child in node.children:
            if child.type == "interface_declaration":
                s = self._parse_interface(child, source, exported=True)
                if s:
                    results.append(s)
            elif child.type == "type_alias_declaration":
                s = self._parse_type_alias(child, source, exported=True)
                if s:
                    results.append(s)
            elif child.type == "enum_declaration":
                s = self._parse_enum(child, source, exported=True)
                if s:
                    results.append(s)
        # Also collect JS-level exports (functions, classes, vars)
        results.extend(super()._parse_export(node, source))
        # Deduplicate by (name, start_byte) — TS and JS loops may both fire
        seen: set[tuple[str, int]] = set()
        deduped: list[ParsedSymbol] = []
        for sym in results:
            key = (sym.name, sym.start_byte)
            if key not in seen:
                seen.add(key)
                deduped.append(sym)
        return deduped

    def _parse_interface(self, node: Node, source: bytes, exported: bool) -> Optional[ParsedSymbol]:
        name_node = _child_by_field(node, "name")
        if not name_node:
            return None
        return ParsedSymbol(
            name=_text(name_node, source),
            kind="interface",
            start_byte=node.start_byte,
            end_byte=node.end_byte,
            start_line=node.start_point[0],
            end_line=node.end_point[0],
            is_exported=exported,
            body_start_byte=None,
            body_end_byte=None,
        )

    def _parse_type_alias(self, node: Node, source: bytes, exported: bool) -> Optional[ParsedSymbol]:
        name_node = _child_by_field(node, "name")
        if not name_node:
            return None
        return ParsedSymbol(
            name=_text(name_node, source),
            kind="type",
            start_byte=node.start_byte,
            end_byte=node.end_byte,
            start_line=node.start_point[0],
            end_line=node.end_point[0],
            is_exported=exported,
            body_start_byte=None,
            body_end_byte=None,
        )

    def _parse_enum(self, node: Node, source: bytes, exported: bool) -> Optional[ParsedSymbol]:
        name_node = _child_by_field(node, "name")
        if not name_node:
            return None
        return ParsedSymbol(
            name=_text(name_node, source),
            kind="type",
            start_byte=node.start_byte,
            end_byte=node.end_byte,
            start_line=node.start_point[0],
            end_line=node.end_point[0],
            is_exported=exported,
            body_start_byte=None,
            body_end_byte=None,
        )

    def _parse_ambient(self, node: Node, source: bytes) -> list[ParsedSymbol]:
        results: list[ParsedSymbol] = []
        for child in node.children:
            if child.type == "function_signature":
                name_node = _child_by_field(child, "name")
                if name_node:
                    results.append(ParsedSymbol(
                        name=_text(name_node, source),
                        kind="function",
                        start_byte=node.start_byte,
                        end_byte=node.end_byte,
                        start_line=node.start_point[0],
                        end_line=node.end_point[0],
                        is_exported=True,
                        body_start_byte=None,
                        body_end_byte=None,
                    ))
        return results
