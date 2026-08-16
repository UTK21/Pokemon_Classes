from __future__ import annotations

import re
from typing import Optional

from ast_pruner.models import ImportedSymbol, ParsedFile, ParsedSymbol


def _collect_identifiers(source: bytes, start: int, end: int) -> set[str]:
    """Extract all identifier-like tokens from a byte slice using a simple regex."""
    chunk = source[start:end].decode("utf-8", errors="replace")
    return set(re.findall(r"\b([A-Za-z_$][A-Za-z0-9_$]*)\b", chunk))


def _filter_used_imports(
    pf: ParsedFile, kept_symbols: list[ParsedSymbol]
) -> list[ImportedSymbol]:
    """Return only imports whose local name appears in the kept symbols' source regions."""
    used_ids: set[str] = set()
    for sym in kept_symbols:
        used_ids |= _collect_identifiers(pf.source, sym.start_byte, sym.end_byte)

    return [imp for imp in pf.imports if imp.name in used_ids or imp.name == "*"]


def _strip_body_python(source: bytes, sym: ParsedSymbol) -> bytes:
    """Replace the function/class body with `pass`, preserving indentation."""
    if sym.body_start_byte is None or sym.body_end_byte is None:
        return source

    body_bytes = source[sym.body_start_byte:sym.body_end_byte]
    # Detect indentation from the first non-empty line of the body
    indent = b"    "
    for line in body_bytes.split(b"\n"):
        stripped = line.lstrip()
        if stripped:
            leading = len(line) - len(stripped)
            indent = line[:leading] if leading else b"    "
            break

    stub = b"\n" + indent + b"pass"
    return source[:sym.body_start_byte] + stub + source[sym.body_end_byte:]


def _strip_body_js(source: bytes, sym: ParsedSymbol) -> bytes:
    """Replace a JS/TS function body (statement_block) with ` {}`."""
    if sym.body_start_byte is None or sym.body_end_byte is None:
        return source
    stub = b" {}"
    return source[:sym.body_start_byte] + stub + source[sym.body_end_byte:]


def _strip_class_method_bodies_js(source: bytes, sym: ParsedSymbol) -> bytes:
    """
    For JS/TS classes: strip each method body while keeping method signatures.
    We do a lightweight scan for statement_block nodes inside the class body.
    """
    if sym.body_start_byte is None or sym.body_end_byte is None:
        return source

    # Find nested { } blocks inside the class body and replace their content
    # We work on the class body slice only, then splice back.
    body_src = source[sym.body_start_byte:sym.body_end_byte]
    result = _strip_nested_blocks(body_src)
    return source[:sym.body_start_byte] + result + source[sym.body_end_byte:]


def _strip_nested_blocks(src: bytes) -> bytes:
    """
    Replace the content of { ... } blocks (that are not the outermost) with nothing.
    This is a simple brace-counting approach — not full AST, but sufficient for signature extraction.
    """
    out: list[bytes] = []
    depth = 0
    i = 0
    in_string: Optional[int] = None  # byte value of opening quote
    escape_next = False

    while i < len(src):
        b = src[i:i+1]

        if escape_next:
            out.append(b)
            escape_next = False
            i += 1
            continue

        if b == b"\\":
            out.append(b)
            escape_next = True
            i += 1
            continue

        # Simple string tracking (single/double quotes, backticks)
        if in_string is not None:
            out.append(b)
            if b == in_string:
                in_string = None
            i += 1
            continue

        if b in (b'"', b"'", b"`"):
            out.append(b)
            in_string = b
            i += 1
            continue

        if b == b"{":
            depth += 1
            out.append(b)
            if depth > 1:
                # We're inside a method body — skip until matching }
                i += 1
                inner_depth = 1
                while i < len(src) and inner_depth > 0:
                    cb = src[i:i+1]
                    if cb == b"{":
                        inner_depth += 1
                    elif cb == b"}":
                        inner_depth -= 1
                    i += 1
                out.append(b"}")
                depth -= 1
                continue
        elif b == b"}":
            depth -= 1
            out.append(b)
        else:
            out.append(b)

        i += 1

    return b"".join(out)


def _reconstruct(
    source: bytes,
    kept_imports: list[ImportedSymbol],
    kept_symbols: list[ParsedSymbol],
    strip: bool,
    language: str,
) -> str:
    """
    Build the pruned source string from byte ranges.
    Import lines are taken from the raw source; symbol regions are sliced and optionally stripped.
    """
    parts: list[bytes] = []

    # Rebuild import lines from the original source
    # Find import lines by scanning source lines for import statements
    import_lines = _extract_import_lines(source, kept_imports, language)
    if import_lines:
        parts.append(import_lines)
        parts.append(b"\n")

    # Sort symbols by start_byte ascending
    sorted_syms = sorted(kept_symbols, key=lambda s: s.start_byte)

    for sym in sorted_syms:
        sym_bytes = source[sym.start_byte:sym.end_byte]

        if strip:
            if language == "python":
                # Apply stripping on the full source then slice back
                patched = _strip_body_python(source, sym)
                sym_bytes = patched[sym.start_byte:sym.end_byte + _body_delta(source, sym, language)]
            elif sym.kind == "class":
                patched = _strip_class_method_bodies_js(source, sym)
                sym_bytes = patched[sym.start_byte:sym.start_byte + len(patched) - len(source) + sym.end_byte - sym.start_byte]
            else:
                patched = _strip_body_js(source, sym)
                sym_bytes = patched[sym.start_byte:sym.end_byte + _body_delta(source, sym, language)]

        parts.append(b"\n")
        parts.append(sym_bytes.rstrip())
        parts.append(b"\n")

    return b"".join(parts).decode("utf-8", errors="replace").strip() + "\n"


def _body_delta(source: bytes, sym: ParsedSymbol, language: str) -> int:
    """Compute the byte-length difference after body replacement."""
    if sym.body_start_byte is None or sym.body_end_byte is None:
        return 0
    original_body_len = sym.body_end_byte - sym.body_start_byte
    stub = b"\n    pass" if language == "python" else b" {}"
    return len(stub) - original_body_len


def _extract_import_lines(source: bytes, kept_imports: list[ImportedSymbol], language: str) -> bytes:
    """
    Extract raw import lines from the source that correspond to the kept imports.
    We match by specifier/module name found in each line.
    """
    if not kept_imports:
        return b""

    lines = source.split(b"\n")
    result_lines: list[bytes] = []
    seen: set[str] = set()

    specifiers = {imp.source_specifier for imp in kept_imports}

    for line in lines:
        line_str = line.decode("utf-8", errors="replace")
        is_import_line = False

        if language == "python":
            is_import_line = line_str.lstrip().startswith(("import ", "from "))
        else:
            is_import_line = (
                line_str.lstrip().startswith("import ")
                or line_str.lstrip().startswith("const ")
                or line_str.lstrip().startswith("let ")
                or line_str.lstrip().startswith("var ")
            ) and "require(" in line_str or line_str.lstrip().startswith("import ")

        if not is_import_line:
            continue

        for spec in specifiers:
            if spec in line_str and spec not in seen:
                result_lines.append(line)
                seen.add(spec)
                break

    return b"\n".join(result_lines)


def extract_full(pf: ParsedFile, requested: set[str]) -> str:
    """
    Return pruned source with full bodies for the requested symbols only,
    plus the imports those symbols reference.
    """
    kept = [s for s in pf.symbols if s.name in requested]
    if not kept and requested:
        # Fall back: return all symbols if none matched (avoids empty output)
        kept = pf.symbols

    used_imports = _filter_used_imports(pf, kept)
    return _reconstruct(pf.source, used_imports, kept, strip=False, language=pf.language)


def extract_signatures(pf: ParsedFile, requested: set[str]) -> str:
    """
    Return pruned source with bodies stripped for the requested symbols only.
    Used for dependency files.
    """
    kept = [s for s in pf.symbols if s.name in requested]
    if not kept and requested:
        kept = pf.symbols

    used_imports = _filter_used_imports(pf, kept)
    return _reconstruct(pf.source, used_imports, kept, strip=True, language=pf.language)
