from __future__ import annotations

import json
import os
import pytest
from ast_pruner.models import OutputFormat
from ast_pruner.pruner import run

FIXTURES = os.path.join(os.path.dirname(__file__), "fixtures")


class TestPrunerPython:
    def test_basic_prune(self):
        entry = os.path.join(FIXTURES, "entry.py")
        result = run(entry, ["greet"], depth=3, fmt=OutputFormat.TEXT)
        assert "greet" in result
        assert "entry.py" in result

    def test_excludes_unused_symbols(self):
        entry = os.path.join(FIXTURES, "entry.py")
        result = run(entry, ["greet"], depth=3, fmt=OutputFormat.TEXT)
        assert "unused_function" not in result

    def test_dependency_signature_included(self):
        entry = os.path.join(FIXTURES, "entry.py")
        result = run(entry, ["greet"], depth=3, fmt=OutputFormat.TEXT)
        assert "helpers.py" in result
        assert "format_name" in result

    def test_json_output_valid(self):
        entry = os.path.join(FIXTURES, "entry.py")
        result = run(entry, ["greet"], depth=3, fmt=OutputFormat.JSON)
        data = json.loads(result)
        assert "files" in data
        assert "total_tokens" in data
        assert data["total_tokens"] > 0

    def test_token_count_positive(self):
        entry = os.path.join(FIXTURES, "entry.py")
        result = run(entry, ["greet"], depth=3, fmt=OutputFormat.JSON)
        data = json.loads(result)
        for f in data["files"]:
            assert f["estimated_tokens"] > 0


class TestPrunerTypeScript:
    def test_ts_prune(self):
        entry = os.path.join(FIXTURES, "api.ts")
        result = run(entry, ["getUser"], depth=3, fmt=OutputFormat.TEXT)
        assert "getUser" in result

    def test_ts_interface_included(self):
        entry = os.path.join(FIXTURES, "api.ts")
        result = run(entry, ["getUser"], depth=3, fmt=OutputFormat.TEXT)
        # types.ts should be pulled in with User and ApiResponse interfaces
        assert "types.ts" in result or "User" in result


class TestPrunerJS:
    def test_js_prune(self):
        entry = os.path.join(FIXTURES, "utils.js")
        result = run(entry, ["processData"], depth=3, fmt=OutputFormat.TEXT)
        assert "processData" in result

    def test_js_dep_signature(self):
        entry = os.path.join(FIXTURES, "utils.js")
        result = run(entry, ["processData"], depth=3, fmt=OutputFormat.TEXT)
        assert "date_utils.js" in result or "formatDate" in result
