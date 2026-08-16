from __future__ import annotations

import os
import pytest
from ast_pruner.resolver import resolve, resolve_python_import, detect_language

FIXTURES = os.path.join(os.path.dirname(__file__), "fixtures")


def test_detect_language_py():
    assert detect_language("/foo/bar.py") == "python"


def test_detect_language_ts():
    assert detect_language("/foo/bar.ts") == "typescript"


def test_detect_language_tsx():
    assert detect_language("/foo/bar.tsx") == "typescript"


def test_detect_language_js():
    assert detect_language("/foo/bar.js") == "javascript"


def test_resolve_relative_py():
    entry = os.path.join(FIXTURES, "entry.py")
    result = resolve_python_import(["helpers"], entry, dots=1)
    assert result is not None
    assert result.endswith("helpers.py")


def test_resolve_external_returns_none():
    entry = os.path.join(FIXTURES, "entry.py")
    assert resolve("react", entry) is None
    assert resolve("os", entry) is None


def test_resolve_js_relative():
    utils = os.path.join(FIXTURES, "utils.js")
    result = resolve("./date_utils", utils)
    assert result is not None
    assert result.endswith("date_utils.js")


def test_resolve_ts_relative():
    api = os.path.join(FIXTURES, "api.ts")
    result = resolve("./types", api)
    assert result is not None
    assert result.endswith("types.ts")


def test_resolve_nonexistent_returns_none():
    utils = os.path.join(FIXTURES, "utils.js")
    assert resolve("./nonexistent_xyz", utils) is None
