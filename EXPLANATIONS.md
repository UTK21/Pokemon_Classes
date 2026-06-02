# EXPLANATIONS.md — what each file does

A file-by-file tour of the ast-pruner codebase. Grouped by layer, with one paragraph per file explaining its role, key functions, and how it connects to its neighbours.

For the high-level "what is this and how do I use it", see [README.md](README.md).

---

## Architecture in one diagram

```
┌─────────────────────────────────────────────────────────┐
│  Editor integrations                                    │
│  • VS Code extension (@pruner in Copilot Chat)         │
│  • Claude Code slash commands (/prune, /dashboard)     │
└──────────────────┬──────────────────────────────────────┘
                   │ shell out
                   ▼
┌─────────────────────────────────────────────────────────┐
│  CLI                  ast-pruner <cmd> [args]          │
│  • prune              • benchmark      • report        │
└──────────────────┬──────────────────────────────────────┘
                   │
                   ▼
┌─────────────────────────────────────────────────────────┐
│  Orchestration       pruner.py                          │
│  Glues parsing → graph → extraction → rendering        │
└──────────────────┬──────────────────────────────────────┘
                   │
   ┌───────────────┼───────────────┬──────────────────┐
   ▼               ▼               ▼                  ▼
┌────────┐   ┌────────────┐  ┌──────────┐    ┌────────────┐
│Parsers │   │ Dependency │  │Extractor │    │  Renderer  │
│per-lang│   │   Graph    │  │body strip│    │ text/json  │
└────────┘   └────────────┘  └──────────┘    └────────────┘
```

---

## Core pipeline

### [ast_pruner/cli.py](ast_pruner/cli.py)
The click-based command-line entry point. Defines three subcommands (`prune`, `benchmark`, `report`) and parses their flags into calls against the underlying functions in `pruner.py`, `benchmark.py`, and `report.py`. Each subcommand has both a human-readable text mode and a `--format json` mode so the editor integrations can parse the output programmatically.

### [ast_pruner/pruner.py](ast_pruner/pruner.py)
The pipeline orchestrator. The `run(file, symbols, depth, fmt)` function ties everything together: it resolves the entry path, calls `build_graph` to enumerate reachable files, runs `extract_full` on the entry node and `extract_signatures` on every dependency node, stamps token counts onto each `PrunedFile` via `build_pruned_file`, and finally hands the result to the renderer. Also contains `_get_all_exports` — the helper that figures out what symbols to extract when the user doesn't pass `--symbols`.

### [ast_pruner/models.py](ast_pruner/models.py)
Single source of truth for all shared dataclasses. Holds `ParsedFile` (raw bytes + extracted symbols + imports), `ParsedSymbol` (with byte ranges so the extractor can slice precisely), `ImportedSymbol`, `DependencyNode`, `DependencyGraph`, `PrunedFile`, `PruneResult`, and the `OutputFormat` enum. Every other module imports from here so types stay consistent across the codebase.

---

## Parsing layer

The parsing layer uses **tree-sitter** — the same parsing library editors use for syntax highlighting — because it gives one consistent API across multiple languages, plus byte-accurate AST node positions (essential for the body-stripping done later).

### [ast_pruner/parsers/base.py](ast_pruner/parsers/base.py)
Defines the abstract `BaseParser` interface that every language parser implements. Concretely it's just `parse(abs_path) -> ParsedFile` — every concrete parser reads a file, runs tree-sitter, and returns a populated `ParsedFile`. This keeps the orchestrator language-agnostic.

### [ast_pruner/parsers/__init__.py](ast_pruner/parsers/__init__.py)
The factory. `get_parser(filepath)` looks at the file extension and returns the appropriate concrete parser: Python for `.py`, TypeScript for `.ts`/`.tsx`, JavaScript for `.js`/`.jsx`/`.mjs`. Used by the orchestrator so it never has to switch on language itself.

### [ast_pruner/parsers/python_parser.py](ast_pruner/parsers/python_parser.py)
Handles Python via `tree_sitter_python`. Walks the top-level AST nodes looking for `function_definition`, `class_definition`, `decorated_definition` (for `@decorator` functions), and top-level assignments. Extracts both the outer span (for keeping decorators) and the inner `block` body span (for stripping). Import parsing covers `import x`, `import x as y`, `from .module import a, b as c`, and relative imports with multiple leading dots (e.g. `from ..foo import bar`).

### [ast_pruner/parsers/javascript_parser.py](ast_pruner/parsers/javascript_parser.py)
Handles JS/JSX/MJS via `tree_sitter_javascript`. Recognizes named function declarations, class declarations, arrow functions stored in `const`/`let`/`var`, `export` statements (ES modules), and CommonJS patterns (`module.exports = ...`, `const { x } = require("./y")`). Default exports get the synthetic name `"default"` so they're selectable via `--symbols default`. Body byte ranges come from `statement_block` and `class_body` nodes.

### [ast_pruner/parsers/typescript_parser.py](ast_pruner/parsers/typescript_parser.py)
Extends `JavaScriptParser` to add TypeScript-specific node types: `interface_declaration`, `type_alias_declaration`, `enum_declaration`, and `ambient_declaration` (`declare function`, `declare class`). Interfaces and type aliases get `body_start_byte=None` because there's no implementation body to strip — they're already pure declarations. Switches between the `typescript` and `tsx` tree-sitter grammars based on the file extension.

---

## Graph & extraction

### [ast_pruner/resolver.py](ast_pruner/resolver.py)
Turns import specifiers into absolute filesystem paths. `resolve("./foo", "/path/to/bar.ts")` tries `/path/to/foo.ts`, `/path/to/foo.tsx`, `/path/to/foo/index.ts`, etc., based on the importing file's language. Non-relative specifiers (`"react"`, `"os"`) return `None` so the graph traversal knows to skip them. Also exposes `resolve_python_import` which handles Python's leading-dot relative imports separately because their syntax doesn't fit the JS-style path resolution.

### [ast_pruner/graph.py](ast_pruner/graph.py)
The BFS dependency traversal. Starts from the entry file's `ParsedFile` and works outward: for each node's `requested_symbols`, it scans the corresponding AST byte range looking for identifier references that match any import. The matching imports get resolved to absolute paths via `resolver.resolve`, and their target files become new graph nodes. Cycle detection is a simple `visited: set` — if a path's already been enqueued, its needed symbols get *merged* into the existing node (handles diamond dependencies) rather than triggering a re-enqueue. Stops at `max_depth`.

### [ast_pruner/extractor.py](ast_pruner/extractor.py)
The actual byte-level surgery. Two entry points: `extract_full(parsed_file, requested)` keeps the bodies of the requested symbols intact (used on the entry file), and `extract_signatures(parsed_file, requested)` strips bodies down to `pass`/`{}` (used on every dependency file). Class methods are handled by `_strip_nested_blocks`, a small brace-counting scanner that strips the inner method bodies while preserving the class shell and method signatures. String literals are tracked correctly so `{` inside strings doesn't confuse the brace counter.

---

## Measurement & output

### [ast_pruner/renderer.py](ast_pruner/renderer.py)
Owns the canonical `estimate_tokens(source)` function and the output formatters. `estimate_tokens` tries `tiktoken` with `cl100k_base` first (the GPT-4/Claude tokenizer) and falls back to `len(source) // 4` if `tiktoken` isn't installed. `render()` produces either the text format (with `# === path (N tokens) ===` headers) or JSON. `build_pruned_file()` is what stamps the per-file token count onto each `PrunedFile` — call it whenever you create one.

### [ast_pruner/benchmark.py](ast_pruner/benchmark.py)
Quantifies savings. `benchmark_file(entry, symbols, depth)` calls `build_graph` to enumerate all reachable files (the baseline universe), reads each one's raw text and tokenizes it, then runs the pruner and parses its JSON to get the pruned token total. Difference is "saved", `saved/baseline` is reduction %, `baseline/pruned` is the compression ratio. The `BenchmarkResult.to_dict()` method produces exactly the schema that gets appended to the usage log.

### [ast_pruner/report.py](ast_pruner/report.py)
The dashboard generator. `load_log(path)` reads a JSONL file, `compute_aggregates(entries)` sums tokens, computes a top-files leaderboard, builds a cumulative-savings time series, and bucketizes reductions into a histogram. `render_html()` produces a single self-contained HTML file with **Chart.js loaded from CDN** (no Python plotting deps), styled in dark theme with four charts: cumulative line, top-files bar, baseline-vs-pruned donut, and reduction histogram.

---

## VS Code extension

The extension lives in [extension/](extension/) and is built with TypeScript + esbuild + the `@vscode/vsce` packaging tool.

### [extension/src/extension.ts](extension/src/extension.ts)
The activation entry point. Calls `vscode.chat.createChatParticipant("ast-pruner.pruner", handler)` to register `@pruner` as a Copilot Chat participant. The handler parses file references from `request.references`, calls `prune()` and `benchmark()` in parallel, streams the pruned source back to the chat via `stream.markdown()` (which Copilot picks up as context), and appends each invocation to the usage log. Also registers the `ast-pruner.showDashboard` and `ast-pruner.openLog` commands.

### [extension/src/pruner-runner.ts](extension/src/pruner-runner.ts)
The subprocess wrapper. Uses `child_process.spawn` (not `exec`, to avoid shell injection) to invoke the Python CLI. Exports `prune()`, `benchmark()`, `generateReport()`, and `isCliAvailable()`. The CLI path comes from the `ast-pruner.cliPath` setting, defaulting to `"ast-pruner"` (looked up on PATH).

### [extension/src/usage-log.ts](extension/src/usage-log.ts)
Append-only JSONL writer. `appendEntry(context, entry)` writes one JSON object per line to `context.globalStorageUri/usage.jsonl`. Crash-safe (just appends), shared across all VS Code workspaces (it's globalStorage, not workspaceStorage). The Claude Code slash command writes to this same file, which is how the dashboard ends up showing savings from both tools.

### [extension/src/dashboard.ts](extension/src/dashboard.ts)
Opens the dashboard webview. Shells out to `ast-pruner report` to generate the HTML to a temp file, reads that file's contents, and stuffs them into a `vscode.WebviewPanel`. Using the CLI to generate the HTML (rather than re-implementing in TypeScript) keeps the dashboard logic single-sourced.

### [extension/package.json](extension/package.json)
The extension manifest. Declares the `chatParticipants` contribution (`@pruner` with the `/dashboard` slash command), the `commands` contribution, and the `configuration` schema (cliPath, defaultDepth). Activation event is `onChatParticipant:ast-pruner.pruner` so the extension only loads when someone actually invokes it.

### [extension/esbuild.config.mjs](extension/esbuild.config.mjs)
Build config. Bundles the TypeScript source into a single CommonJS file at `dist/extension.js` for VS Code to load, with `vscode` marked as external (it's provided by the host).

---

## Claude Code slash commands

These live outside the project at `~/.claude/commands/` — Claude Code discovers them globally.

### `~/.claude/commands/prune.md`
Defines the `/prune <file>` slash command. YAML frontmatter declares `description`, `argument-hint`, and `allowed-tools: Bash, Read`. The Markdown body is the prompt template that gets expanded when the user types `/prune` — it tells Claude (in the running session) to run `ast-pruner prune` and `ast-pruner benchmark` on the given file, parse the JSON, append to the unified usage log, and use the pruned source as context for subsequent turns.

### `~/.claude/commands/dashboard.md`
Defines `/dashboard`. Same format, much smaller body — just runs the one-liner that regenerates the HTML and opens it in the browser. Reads from the same JSONL the VS Code extension writes to.

---

## Tests

All tests use pytest. Run with `.venv/bin/pytest tests/` — 68 tests total, all passing.

### tests/test_resolver.py
Covers `resolve()` and `resolve_python_import()`: relative imports across `.py`/`.js`/`.ts` extensions, external packages returning `None`, nonexistent files, and language detection from extension.

### tests/test_parsers.py
Per-language parser tests. Verifies that each parser finds the expected functions/classes/interfaces, attaches correct byte ranges, detects imports (ES, CommonJS, Python relative), and assigns `body_start_byte=None` to TypeScript interfaces.

### tests/test_extractor.py
Covers `extract_full` and `extract_signatures`. Verifies that requested symbols are kept, unrequested ones excluded, full bodies preserved in entry mode, and bodies stripped to `pass`/`{}` in signature mode. Also checks that imports actually referenced by kept symbols are retained while unused ones are dropped.

### tests/test_graph.py
BFS traversal tests. Validates that the entry node is present, dependencies are discovered, depths are assigned correctly, the depth limit is respected, circular imports don't cause infinite loops, and JS dependency traversal works alongside Python.

### tests/test_pruner.py
End-to-end on fixtures. Calls `pruner.run()` directly for both Python and TypeScript/JavaScript fixtures, validates the text and JSON output formats, and confirms that token counts are positive integers.

### tests/test_benchmark.py
Validates the benchmark math: baseline > pruned ≥ 0, reduction percentage in 0–100, compression ratio ≥ 1, per-file breakdown matches the graph node count, the result is JSON-serializable.

### tests/test_report.py
Tests the dashboard generator. Verifies that malformed/blank log lines are skipped, aggregates are correctly summed, top-files leaderboard is ordered descending, the cumulative time series is monotonically non-decreasing, the reduction histogram buckets correctly, and `generate_report()` writes a valid HTML file with the expected content.

---

## Test fixtures

### tests/fixtures/entry.py + tests/fixtures/helpers.py
The minimal Python pair used to verify that imports are traced (`entry.py` imports `format_name` from `helpers.py`), the entry's full body is kept, and the helper is stripped to its signature.

### tests/fixtures/api.ts + tests/fixtures/types.ts
The TypeScript counterpart: `api.ts` imports `User` and `ApiResponse` interfaces from `types.ts`. Verifies that interfaces are kept verbatim (no body to strip) and functions are signature-stripped.

### tests/fixtures/utils.js + tests/fixtures/date_utils.js
JavaScript CommonJS pair: `utils.js` uses `require("./date_utils")`. Verifies that CommonJS imports are detected and traced.

### tests/fixtures/circular/a.py + tests/fixtures/circular/b.py
Mutual imports between `a.py` and `b.py`. Used to verify that the BFS terminates rather than recursing forever.

---

## Configuration & packaging

### [pyproject.toml](pyproject.toml)
Python project metadata. Declares the four required dependencies (`tree-sitter`, the three language grammars, `click`), an optional `tokens` extra that pulls in `tiktoken` for accurate counting, and the dev extra (`pytest`, `ruff`, `mypy`). The `[project.scripts]` block defines `ast-pruner = "ast_pruner.cli:main"` — this is what makes `ast-pruner` available as a binary on PATH after `pipx install`.

### [extension/tsconfig.json](extension/tsconfig.json)
Strict TypeScript config for the extension. Target ES2022, CommonJS module output, source maps on (for debugging in VS Code's Extension Development Host).

### [extension/.vscodeignore](extension/.vscodeignore)
What `vsce package` excludes from the .vsix. Drops `src/`, `node_modules/`, `out/`, sourcemaps — keeps only the bundled `dist/` and the manifest.

---

## How the pieces talk to each other (one concrete trace)

When the user types `@pruner #file:Cart.jsx` in Copilot Chat:

1. **VS Code** invokes the chat participant registered by `extension.ts`.
2. The handler calls `prune("Cart.jsx", [], 3)` and `benchmark("Cart.jsx", [], 3)` in `pruner-runner.ts`, which spawn `ast-pruner prune` and `ast-pruner benchmark` as subprocesses.
3. **The CLI** in `cli.py` dispatches to `pruner.run()` and `benchmark.benchmark_file()`.
4. **The orchestrator** in `pruner.py` calls `get_parser("Cart.jsx")` → `JavaScriptParser.parse()` → returns a `ParsedFile`.
5. It then calls `build_graph()` in `graph.py`, which traverses imports, calling `resolver.resolve()` to map specifiers to paths, and parses each dependency file.
6. For each node, `extract_full` (entry) or `extract_signatures` (dependencies) in `extractor.py` slices the source bytes, strips method bodies, and reassembles.
7. `renderer.py::build_pruned_file` stamps `estimated_tokens` on each `PrunedFile` using `estimate_tokens()`.
8. `renderer.py::render()` serializes the result to JSON.
9. The CLI prints JSON to stdout; the extension parses it, streams the pruned source into chat, computes the savings line from the benchmark result, and appends a row to the JSONL log via `usage-log.ts`.
10. **Copilot** sees the pruned source as part of its context for the next message.

Every box in the architecture diagram at the top of this file participates in that trace.
