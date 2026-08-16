from __future__ import annotations

import os
import pytest
from ast_pruner.parsers import get_parser

FIXTURES = os.path.join(os.path.dirname(__file__), "fixtures")


class TestPythonParser:
    def setup_method(self):
        self.pf = get_parser(os.path.join(FIXTURES, "entry.py")).parse(
            os.path.join(FIXTURES, "entry.py")
        )

    def test_language(self):
        assert self.pf.language == "python"

    def test_finds_functions(self):
        names = {s.name for s in self.pf.symbols}
        assert "greet" in names
        assert "unused_function" in names

    def test_finds_class(self):
        names = {s.name for s in self.pf.symbols}
        assert "Config" in names

    def test_function_has_body_range(self):
        greet = next(s for s in self.pf.symbols if s.name == "greet")
        assert greet.body_start_byte is not None
        assert greet.body_end_byte is not None
        assert greet.body_end_byte > greet.body_start_byte

    def test_imports_detected(self):
        assert len(self.pf.imports) >= 1
        specs = {i.source_specifier for i in self.pf.imports}
        assert any("helpers" in s for s in specs)


class TestJavaScriptParser:
    def setup_method(self):
        self.pf = get_parser(os.path.join(FIXTURES, "utils.js")).parse(
            os.path.join(FIXTURES, "utils.js")
        )

    def test_language(self):
        assert self.pf.language == "javascript"

    def test_finds_function(self):
        names = {s.name for s in self.pf.symbols}
        assert "processData" in names

    def test_finds_arrow_function(self):
        names = {s.name for s in self.pf.symbols}
        assert "pipe" in names

    def test_require_import_detected(self):
        specs = {i.source_specifier for i in self.pf.imports}
        assert "./date_utils" in specs


class TestTypeScriptParser:
    def setup_method(self):
        self.pf = get_parser(os.path.join(FIXTURES, "api.ts")).parse(
            os.path.join(FIXTURES, "api.ts")
        )
        self.types_pf = get_parser(os.path.join(FIXTURES, "types.ts")).parse(
            os.path.join(FIXTURES, "types.ts")
        )

    def test_language(self):
        assert self.pf.language == "typescript"

    def test_finds_exported_functions(self):
        names = {s.name for s in self.pf.symbols if s.is_exported}
        assert "getUser" in names
        assert "createUser" in names

    def test_internal_function_not_exported(self):
        internal = next((s for s in self.pf.symbols if s.name == "internalHelper"), None)
        if internal:
            assert not internal.is_exported

    def test_imports_detected(self):
        specs = {i.source_specifier for i in self.pf.imports}
        assert "./types" in specs

    def test_interfaces_have_no_body(self):
        user_iface = next((s for s in self.types_pf.symbols if s.name == "User"), None)
        assert user_iface is not None
        assert user_iface.kind == "interface"
        assert user_iface.body_start_byte is None
