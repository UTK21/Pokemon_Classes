from __future__ import annotations

from typing import Optional

import tree_sitter_javascript as tsjs
from tree_sitter import Language, Node, Parser

from ast_pruner.models import ImportedSymbol, ParsedFile, ParsedSymbol
from ast_pruner.parsers.base import BaseParser

JS_LANGUAGE = Language(tsjs.language())
_parser = Parser(JS_LANGUAGE)


def _text(node: Node, source: bytes) -> str:
    return source[node.start_byte:node.end_byte].decode("utf-8", errors="replace")


def _child_by_field(node: Node, field: str) -> Optional[Node]:
    return node.child_by_field_name(field)


def _strip_quotes(s: str) -> str:
    if len(s) >= 2 and s[0] in ('"', "'", "`") and s[-1] == s[0]:
        return s[1:-1]
    return s


class JavaScriptParser(BaseParser):
    """Parser for .js / .jsx / .mjs files."""

    def _get_language(self) -> Language:
        return JS_LANGUAGE

    def _make_parser(self) -> Parser:
        return Parser(self._get_language())

    def parse(self, abs_path: str) -> ParsedFile:
        with open(abs_path, "rb") as f:
            source = f.read()

        p = self._make_parser()
        tree = p.parse(source)
        root = tree.root_node

        symbols = self._extract_symbols(root, source)
        imports = self._extract_imports(root, source)

        return ParsedFile(
            abs_path=abs_path,
            language="javascript",
            source=source,
            symbols=symbols,
            imports=imports,
        )

    def _extract_symbols(self, root: Node, source: bytes) -> list[ParsedSymbol]:
        symbols: list[ParsedSymbol] = []
        for child in root.children:
            syms = self._node_to_symbols(child, source)
            symbols.extend(syms)
        return symbols

    def _node_to_symbols(self, node: Node, source: bytes) -> list[ParsedSymbol]:
        if node.type == "function_declaration":
            s = self._parse_function_decl(node, source, exported=False)
            return [s] if s else []
        if node.type == "class_declaration":
            s = self._parse_class_decl(node, source, exported=False)
            return [s] if s else []
        if node.type in ("lexical_declaration", "variable_declaration"):
            return self._parse_var_decl(node, source, exported=False)
        if node.type == "export_statement":
            return self._parse_export(node, source)
        if node.type == "expression_statement":
            s = self._parse_module_exports(node, source)
            return [s] if s else []
        return []

    def _parse_function_decl(self, node: Node, source: bytes, exported: bool) -> Optional[ParsedSymbol]:
        name_node = _child_by_field(node, "name")
        body_node = _child_by_field(node, "body")
        name = _text(name_node, source) if name_node else "default"
        return ParsedSymbol(
            name=name,
            kind="function",
            start_byte=node.start_byte,
            end_byte=node.end_byte,
            start_line=node.start_point[0],
            end_line=node.end_point[0],
            is_exported=exported,
            body_start_byte=body_node.start_byte if body_node else None,
            body_end_byte=body_node.end_byte if body_node else None,
        )

    def _parse_class_decl(self, node: Node, source: bytes, exported: bool) -> Optional[ParsedSymbol]:
        name_node = _child_by_field(node, "name")
        body_node = _child_by_field(node, "body")
        name = _text(name_node, source) if name_node else "default"
        return ParsedSymbol(
            name=name,
            kind="class",
            start_byte=node.start_byte,
            end_byte=node.end_byte,
            start_line=node.start_point[0],
            end_line=node.end_point[0],
            is_exported=exported,
            body_start_byte=body_node.start_byte if body_node else None,
            body_end_byte=body_node.end_byte if body_node else None,
        )

    def _parse_var_decl(self, node: Node, source: bytes, exported: bool) -> list[ParsedSymbol]:
        results: list[ParsedSymbol] = []
        for child in node.children:
            if child.type != "variable_declarator":
                continue
            name_node = _child_by_field(child, "name")
            value_node = _child_by_field(child, "value")
            if not name_node:
                continue
            name = _text(name_node, source)
            # Arrow function or regular function expression stored in a variable
            if value_node and value_node.type in ("arrow_function", "function"):
                body_node = _child_by_field(value_node, "body")
                results.append(ParsedSymbol(
                    name=name,
                    kind="function",
                    start_byte=node.start_byte,
                    end_byte=node.end_byte,
                    start_line=node.start_point[0],
                    end_line=node.end_point[0],
                    is_exported=exported,
                    body_start_byte=body_node.start_byte if body_node else None,
                    body_end_byte=body_node.end_byte if body_node else None,
                ))
            else:
                results.append(ParsedSymbol(
                    name=name,
                    kind="variable",
                    start_byte=node.start_byte,
                    end_byte=node.end_byte,
                    start_line=node.start_point[0],
                    end_line=node.end_point[0],
                    is_exported=exported,
                    body_start_byte=None,
                    body_end_byte=None,
                ))
        return results

    def _parse_export(self, node: Node, source: bytes) -> list[ParsedSymbol]:
        results: list[ParsedSymbol] = []
        for child in node.children:
            if child.type == "function_declaration":
                s = self._parse_function_decl(child, source, exported=True)
                if s:
                    results.append(s)
            elif child.type == "class_declaration":
                s = self._parse_class_decl(child, source, exported=True)
                if s:
                    results.append(s)
            elif child.type in ("lexical_declaration", "variable_declaration"):
                results.extend(self._parse_var_decl(child, source, exported=True))
            elif child.type == "export_clause":
                # export { foo, bar as baz }
                for spec in child.children:
                    if spec.type == "export_specifier":
                        name_node = _child_by_field(spec, "name")
                        alias_node = _child_by_field(spec, "alias")
                        if name_node:
                            name = _text(alias_node or name_node, source)
                            results.append(ParsedSymbol(
                                name=name,
                                kind="variable",
                                start_byte=node.start_byte,
                                end_byte=node.end_byte,
                                start_line=node.start_point[0],
                                end_line=node.end_point[0],
                                is_exported=True,
                                body_start_byte=None,
                                body_end_byte=None,
                            ))
            # export default ...
            elif child.type not in ("export", "default", ";", "from", "string"):
                # catch export default function / class with no name
                if child.type in ("function", "class"):
                    body_node = _child_by_field(child, "body")
                    results.append(ParsedSymbol(
                        name="default",
                        kind="function" if child.type == "function" else "class",
                        start_byte=node.start_byte,
                        end_byte=node.end_byte,
                        start_line=node.start_point[0],
                        end_line=node.end_point[0],
                        is_exported=True,
                        body_start_byte=body_node.start_byte if body_node else None,
                        body_end_byte=body_node.end_byte if body_node else None,
                    ))
        return results

    def _parse_module_exports(self, node: Node, source: bytes) -> Optional[ParsedSymbol]:
        # module.exports = { ... } or module.exports.foo = function() {}
        child = node.children[0] if node.children else None
        if not child or child.type != "assignment_expression":
            return None
        left = _child_by_field(child, "left")
        if not left or left.type != "member_expression":
            return None
        obj = _child_by_field(left, "object")
        prop = _child_by_field(left, "property")
        if not obj or not prop:
            return None
        if _text(obj, source) != "module" or _text(prop, source) != "exports":
            return None
        return ParsedSymbol(
            name="module.exports",
            kind="variable",
            start_byte=node.start_byte,
            end_byte=node.end_byte,
            start_line=node.start_point[0],
            end_line=node.end_point[0],
            is_exported=True,
            body_start_byte=None,
            body_end_byte=None,
        )

    def _extract_imports(self, root: Node, source: bytes) -> list[ImportedSymbol]:
        imports: list[ImportedSymbol] = []
        for child in root.children:
            if child.type == "import_statement":
                imports.extend(self._parse_es_import(child, source))
            elif child.type in ("lexical_declaration", "variable_declaration"):
                imp = self._parse_require(child, source)
                if imp:
                    imports.extend(imp)
            elif child.type == "expression_statement":
                # bare require() calls
                imp = self._parse_bare_require(child, source)
                if imp:
                    imports.extend(imp)
        return imports

    def _parse_es_import(self, node: Node, source: bytes) -> list[ImportedSymbol]:
        source_node = _child_by_field(node, "source")
        if not source_node:
            return []
        specifier = _strip_quotes(_text(source_node, source))
        results: list[ImportedSymbol] = []

        for child in node.children:
            if child.type == "import_clause":
                for sub in child.children:
                    if sub.type == "identifier":
                        # import Foo from './foo' — default import
                        name = _text(sub, source)
                        results.append(ImportedSymbol(name=name, alias="default", source_specifier=specifier))
                    elif sub.type == "named_imports":
                        for spec in sub.children:
                            if spec.type == "import_specifier":
                                name_node = _child_by_field(spec, "name")
                                alias_node = _child_by_field(spec, "alias")
                                if name_node:
                                    orig = _text(name_node, source)
                                    local = _text(alias_node, source) if alias_node else orig
                                    results.append(ImportedSymbol(name=local, alias=orig, source_specifier=specifier))
                    elif sub.type == "namespace_import":
                        # import * as ns from './foo'
                        for ns_child in sub.children:
                            if ns_child.type == "identifier":
                                results.append(ImportedSymbol(name=_text(ns_child, source), alias="*", source_specifier=specifier))
        return results

    def _parse_require(self, node: Node, source: bytes) -> Optional[list[ImportedSymbol]]:
        # const { foo, bar } = require('./module') or const foo = require('./module')
        results: list[ImportedSymbol] = []
        for child in node.children:
            if child.type != "variable_declarator":
                continue
            value = _child_by_field(child, "value")
            name_node = _child_by_field(child, "name")
            if not value or value.type != "call_expression":
                continue
            fn = _child_by_field(value, "function")
            args = _child_by_field(value, "arguments")
            if not fn or _text(fn, source) != "require" or not args:
                continue
            spec_nodes = [c for c in args.children if c.type == "string"]
            if not spec_nodes:
                continue
            specifier = _strip_quotes(_text(spec_nodes[0], source))

            if not name_node:
                continue
            if name_node.type == "object_pattern":
                for prop in name_node.children:
                    if prop.type == "shorthand_property_identifier_pattern":
                        n = _text(prop, source)
                        results.append(ImportedSymbol(name=n, alias=n, source_specifier=specifier))
                    elif prop.type == "pair_pattern":
                        key = _child_by_field(prop, "key")
                        val = _child_by_field(prop, "value")
                        if key and val:
                            results.append(ImportedSymbol(
                                name=_text(val, source),
                                alias=_text(key, source),
                                source_specifier=specifier,
                            ))
            elif name_node.type == "identifier":
                results.append(ImportedSymbol(name=_text(name_node, source), alias="default", source_specifier=specifier))
        return results if results else None

    def _parse_bare_require(self, node: Node, source: bytes) -> Optional[list[ImportedSymbol]]:
        return None  # bare require() with no assignment — skip
