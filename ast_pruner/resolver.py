from __future__ import annotations

import os
from typing import Optional

_JS_EXTS = [".js", ".jsx", ".mjs", ".ts", ".tsx"]
_TS_EXTS = [".ts", ".tsx", ".js", ".jsx", ".mjs"]
_PY_EXTS = [".py"]

_INDEX_JS = ["/index.js", "/index.jsx", "/index.ts", "/index.tsx"]
_INDEX_PY = ["/__init__.py"]

_EXT_MAP: dict[str, list[str]] = {
    "python": _PY_EXTS,
    "javascript": _JS_EXTS,
    "typescript": _TS_EXTS,
}

_INDEX_MAP: dict[str, list[str]] = {
    "python": _INDEX_PY,
    "javascript": _INDEX_JS,
    "typescript": _INDEX_JS,
}


def detect_language(abs_path: str) -> str:
    ext = os.path.splitext(abs_path)[1].lower()
    if ext == ".py":
        return "python"
    if ext in {".ts", ".tsx"}:
        return "typescript"
    return "javascript"


def resolve(specifier: str, importing_file_abs: str) -> Optional[str]:
    """
    Resolve a relative import specifier to an absolute file path.
    Returns None for external packages or unresolvable paths.
    """
    if not specifier.startswith("."):
        return None

    base_dir = os.path.dirname(importing_file_abs)
    raw = os.path.normpath(os.path.join(base_dir, specifier))
    lang = detect_language(importing_file_abs)

    # Try exact path first (specifier already has an extension)
    if os.path.isfile(raw):
        return raw

    # Try appending known extensions
    for ext in _EXT_MAP[lang]:
        candidate = raw + ext
        if os.path.isfile(candidate):
            return candidate

    # Try directory/index.*
    for suffix in _INDEX_MAP[lang]:
        candidate = raw + suffix
        if os.path.isfile(candidate):
            return candidate

    return None


def resolve_python_import(module_parts: list[str], importing_file_abs: str, dots: int) -> Optional[str]:
    """
    Resolve a Python relative import like `from ..utils import foo`.
    dots: number of leading dots (1 = same package, 2 = parent package, etc.)
    module_parts: the module name parts after the dots (empty for `from . import x`).
    """
    base = os.path.dirname(importing_file_abs)
    for _ in range(dots - 1):
        base = os.path.dirname(base)

    if not module_parts:
        # `from . import x` — look in the package __init__.py
        candidate = os.path.join(base, "__init__.py")
        return candidate if os.path.isfile(candidate) else None

    module_path = os.path.join(base, *module_parts)

    # Try as a .py file
    candidate = module_path + ".py"
    if os.path.isfile(candidate):
        return candidate

    # Try as a package
    candidate = os.path.join(module_path, "__init__.py")
    if os.path.isfile(candidate):
        return candidate

    return None
