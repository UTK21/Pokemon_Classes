from __future__ import annotations

import os

from ast_pruner.parsers.base import BaseParser


def get_parser(abs_path: str) -> BaseParser:
    ext = os.path.splitext(abs_path)[1].lower()
    if ext == ".py":
        from ast_pruner.parsers.python_parser import PythonParser
        return PythonParser()
    if ext in {".ts", ".tsx"}:
        from ast_pruner.parsers.typescript_parser import TypeScriptParser
        return TypeScriptParser(tsx=ext == ".tsx")
    # .js, .jsx, .mjs
    from ast_pruner.parsers.javascript_parser import JavaScriptParser
    return JavaScriptParser()
