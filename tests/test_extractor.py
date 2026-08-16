from __future__ import annotations

import os
import pytest
from ast_pruner.parsers import get_parser
from ast_pruner.extractor import extract_full, extract_signatures

FIXTURES = os.path.join(os.path.dirname(__file__), "fixtures")


class TestExtractFull:
    def setup_method(self):
        self.pf = get_parser(os.path.join(FIXTURES, "entry.py")).parse(
            os.path.join(FIXTURES, "entry.py")
        )

    def test_keeps_requested_symbol(self):
        result = extract_full(self.pf, {"greet"})
        assert "def greet" in result

    def test_excludes_unrequested_symbol(self):
        result = extract_full(self.pf, {"greet"})
        assert "unused_function" not in result

    def test_full_body_preserved(self):
        result = extract_full(self.pf, {"greet"})
        assert "Hello" in result or "format_name" in result

    def test_keeps_relevant_import(self):
        result = extract_full(self.pf, {"greet"})
        assert "helpers" in result or "format_name" in result


class TestExtractSignatures:
    def setup_method(self):
        self.pf = get_parser(os.path.join(FIXTURES, "helpers.py")).parse(
            os.path.join(FIXTURES, "helpers.py")
        )

    def test_signature_present(self):
        result = extract_signatures(self.pf, {"format_name"})
        assert "def format_name" in result

    def test_body_replaced_with_pass(self):
        result = extract_signatures(self.pf, {"format_name"})
        assert "pass" in result

    def test_body_implementation_removed(self):
        result = extract_signatures(self.pf, {"format_name"})
        assert "strip" not in result  # implementation detail gone

    def test_excludes_unrequested(self):
        result = extract_signatures(self.pf, {"format_name"})
        assert "internal_helper" not in result


class TestExtractSignaturesJS:
    def setup_method(self):
        self.pf = get_parser(os.path.join(FIXTURES, "date_utils.js")).parse(
            os.path.join(FIXTURES, "date_utils.js")
        )

    def test_signature_present(self):
        result = extract_signatures(self.pf, {"formatDate"})
        assert "function formatDate" in result or "formatDate" in result

    def test_body_replaced(self):
        result = extract_signatures(self.pf, {"formatDate"})
        assert "toISOString" not in result
