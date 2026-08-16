# ast-pruner

**Cut LLM context tokens by 60–80% by sending function signatures instead of full dependency files.**

Every file you paste into Copilot or Claude drags its imports along — most of which the model only needs to know exist, not how they're implemented. `ast-pruner` parses a file into its AST, traces the imports, and produces a minimal version: the entry file kept in full, every dependency reduced to just its function and class signatures.

On a real React app: **8,987 tokens saved across 6 files** (59% average reduction) — see the dashboard at the end of this README.

For a deeper walkthrough of what each file in this project does, see [EXPLANATIONS.md](EXPLANATIONS.md).

---

## Quick start

```bash
# 1. Install the CLI globally
pipx install /path/to/AST_PRUNERV

# 2. Prune a single file (writes pruned source to stdout)
ast-pruner prune src/components/Header.jsx

# 3. Measure savings on a file
ast-pruner benchmark src/components/Header.jsx
```

For the better experience, install one of the [editor integrations](#editor-integrations) below — they keep you out of the terminal.

---

## How token counting works

This is the most important section, because every "X tokens saved" number you'll see depends on it.

### Where the unit comes from

The tokenizer is **`tiktoken` with the `cl100k_base` encoding** — the same encoding GPT-4 and the Claude API use when they tally context. So "tokens" here means the exact same unit those APIs bill you for.

The relevant function lives in [ast_pruner/renderer.py](ast_pruner/renderer.py):

```python
def estimate_tokens(source: str) -> int:
    try:
        import tiktoken
        enc = tiktoken.get_encoding("cl100k_base")
        return len(enc.encode(source))
    except ImportError:
        return max(1, len(source) // 4)
```

If `tiktoken` isn't installed, it falls back to a `len // 4` heuristic (English text averages ~4 characters per token). The fallback introduces a ~5% margin of error — fine for trend tracking, not for exact billing. Install with `pip install -e ".[tokens]"` to get the accurate path. The token-counting library is an optional dependency declared in `pyproject.toml`.

### A concrete example

Run on a real file from the React-food-delivery-app project:

```
ast-pruner benchmark src/pages/Cart.jsx

Metric                           Baseline          Pruned        Saved
----------------------------------------------------------------------
Files                                   4               4            -
Tokens                               1823             672         1151

Reduction         : 63.1%
Compression ratio : 2.71x
```

The math:

| Number | What it means | How it was computed |
|---|---|---|
| **Baseline: 1,823** | What you'd send if you pasted Cart.jsx and **every file it transitively imports**, in full | Sum of `estimate_tokens(raw_file_text)` across all 4 files in the dependency graph |
| **Pruned: 672** | What `ast-pruner` actually emits | Sum of `estimate_tokens(pruned_source)` per file: entry kept full, deps reduced to signatures |
| **Saved: 1,151** | What you didn't have to send | `1823 - 672` — pure subtraction, no extra estimation |
| **Reduction %: 63.1** | Relative win | `1151 / 1823 * 100` |
| **Compression ratio: 2.71x** | Context shrank to ~37% of original size | `1823 / 672` |

### What "baseline" includes

Every file in the dependency graph at the configured `--depth` (default 3), each counted **in full** as if you'd just pasted it. The traversal logic lives in [ast_pruner/graph.py](ast_pruner/graph.py); the baseline computation is in [ast_pruner/benchmark.py](ast_pruner/benchmark.py).

### What "pruned" includes

- **Entry file**: full bodies of the requested symbols, plus the imports they reference.
- **Dependency files**: only the symbols actually used by the entry, with function and class **bodies stripped** to `pass` (Python) or `{}` (JS/TS). Interfaces and type aliases stay verbatim because they have no body to strip.

The extraction logic lives in [ast_pruner/extractor.py](ast_pruner/extractor.py); per-file token stamping happens in `renderer.py::build_pruned_file`.

### What "saved" really measures

The difference in tokens between what would have been sent and what was actually sent **as LLM context**. This is a measurement of input-side savings only — not output tokens (model responses), not cache hits, not anything else. If your LLM bill is dominated by context (which is usually the case for code assistants), this number is roughly proportional to the dollars or rate-limit headroom you got back.

### Where the dashboard numbers come from

Every invocation (whether via CLI, VS Code extension, or Claude Code slash command) appends a single JSON line to the shared usage log. The dashboard generator reads that file and just sums the fields — no re-tokenization:

```python
agg.total_baseline_tokens = sum(e.get("baseline_tokens", 0) for e in entries)
agg.total_pruned_tokens = sum(e.get("pruned_tokens", 0) for e in entries)
agg.total_tokens_saved = sum(e.get("tokens_saved", 0) for e in entries)
```

So the cumulative "tokens saved" stat on the dashboard is the sum of per-invocation savings, computed at the time each prune ran. It's not an estimate after the fact.

---

## Editor integrations — how to actually use this day-to-day

Two ways to use ast-pruner without leaving your editor. Both shell out to the same CLI and write to the same usage log, so the dashboard shows lifetime savings across both.

### A — GitHub Copilot Chat (VS Code extension)

Once-only setup:

```bash
cd /Users/utkarshchaudhary/Desktop/projects/AST_PRUNER/extension
npm install
npm run package
code --install-extension ast-pruner-0.1.0.vsix
```

Then in any project, in the Copilot Chat panel:

```
@pruner #file:src/components/Header.jsx
```

What happens:

1. Extension extracts the file reference from your message
2. Spawns `ast-pruner prune` and `ast-pruner benchmark` as subprocesses
3. Streams the pruned source back into chat as a fenced code block — Copilot picks this up as context for the next turn
4. Streams a one-line savings summary: *"Saved 1,151 tokens (63.1% reduction) on Cart.jsx"*
5. Appends the metrics to `~/Library/Application Support/Code/User/globalStorage/local.ast-pruner/usage.jsonl`
6. Adds a "View savings dashboard" button — clicking opens the HTML dashboard in a VS Code webview

Slash command available inside the participant:

- `@pruner /dashboard` — open the savings dashboard directly

Settings (Cmd+, → search "ast-pruner"):

- `ast-pruner.cliPath` — defaults to `ast-pruner` on PATH; set to an absolute path if not resolved
- `ast-pruner.defaultDepth` — default import recursion depth (default 3)

### B — Claude Code (slash commands)

Two global slash commands live at `~/.claude/commands/`. No install — just markdown files (already created).

**`/prune <file> [--symbols a,b] [--depth N]`**

What it does:

1. Runs `ast-pruner prune` and `ast-pruner benchmark` on the file
2. Loads the pruned source into Claude's context (replacing what would have been a full-file attach)
3. Logs to the **same JSONL** the VS Code extension writes to (cross-tool unified log)
4. Reports savings: *"Saved 1,151 tokens (63.1% reduction). Loaded Cart.jsx + 3 dependency signatures."*
5. Subsequent turns in the session reason about the pruned context

Example session:

```
> /prune src/pages/Cart.jsx

[Claude runs the CLI, logs, loads context]
Saved 1,151 tokens (63.1% reduction).

> now refactor this to use a custom hook
[Claude answers using only the pruned context]
```

**`/dashboard`**

Regenerates the HTML dashboard from the unified JSONL log and opens it in your default browser. Wraps:

```bash
ast-pruner report \
  --log "$HOME/Library/Application Support/Code/User/globalStorage/local.ast-pruner/usage.jsonl" \
  --output "$HOME/Desktop/projects/AST_PRUNER/dashboard.html" && \
open "$HOME/Desktop/projects/AST_PRUNER/dashboard.html"
```

**Important gotcha**: Claude Code scans `~/.claude/commands/` at **session startup**. If you add or modify a slash command, restart Claude Code (or open a new session) for it to be picked up. A running session won't see new commands.

### Why both integrations share one log

The JSONL file lives in VS Code's globalStorage path (`~/Library/Application Support/Code/User/globalStorage/local.ast-pruner/usage.jsonl`) and both the extension and the slash command write to that exact path. The dashboard reflects every invocation regardless of which tool triggered it — one source of truth for "how many tokens have I saved this week".

---

## CLI reference

Three subcommands. All support `--format json` for programmatic consumption.

### `ast-pruner prune <file>`

Produce the pruned source. The main command — this is what the editor integrations call.

```bash
ast-pruner prune src/api.py                                  # all exports
ast-pruner prune src/api.py --symbols handle_request,validate
ast-pruner prune src/app.js --depth 2                        # shallower trace
ast-pruner prune src/api.py --output context.txt             # write to file
ast-pruner prune src/api.py --format json                    # machine-readable
```

### `ast-pruner benchmark <file>`

Measure how much you'd save on a file. Does not modify anything — just reports.

```bash
ast-pruner benchmark src/components/Cart.jsx
ast-pruner benchmark src/api.py --symbols handle_request --format json
```

### `ast-pruner report --log <jsonl> --output <html>`

Generate the HTML dashboard from a usage log.

```bash
ast-pruner report \
  --log ~/Library/Application\ Support/Code/User/globalStorage/local.ast-pruner/usage.jsonl \
  --output ./dashboard.html
```

---

## Supported languages

| Language | Extensions |
|----------|-----------|
| Python | `.py` |
| JavaScript | `.js`, `.jsx`, `.mjs` |
| TypeScript | `.ts`, `.tsx` |

---

## Output example

```
# === src/api.py (87 tokens) ===
from .models import User

def handle_request(req: Request) -> Response:
    user = User.from_dict(req.body)
    return Response(user.to_json())

# === src/models.py (42 tokens) ===
class User:
    def __init__(self, name: str, email: str) -> None:
        pass
    def from_dict(cls, data: dict) -> "User":
        pass
    def to_json(self) -> str:
        pass

# ---
# Total: 129 tokens across 2 files
```

---

## Where data lives

| Thing | Path |
|---|---|
| Usage log (JSONL, one invocation per line) | `~/Library/Application Support/Code/User/globalStorage/local.ast-pruner/usage.jsonl` |
| Generated dashboard | `~/Desktop/projects/AST_PRUNER/dashboard.html` (or wherever you point `--output`) |
| Claude Code slash commands | `~/.claude/commands/prune.md`, `~/.claude/commands/dashboard.md` |
| VS Code extension code | `extension/` |
| Python source | `ast_pruner/` |

Each usage log line has the schema documented in `BenchmarkResult.to_dict()` (see [ast_pruner/benchmark.py](ast_pruner/benchmark.py)).

---

## Limitations

- **Fallback tokenizer is approximate.** Without `tiktoken`, the `len // 4` heuristic is off by ~5%. Install with `pip install -e ".[tokens]"` for exact counts.
- **External packages aren't traced.** Imports that don't start with `.` (`react`, `lodash`, etc.) are treated as external and skipped. The pruner only follows local relative imports.
- **Binary asset imports inflate the baseline.** Files like `import logo from "./logo.png"` cause the PNG's raw bytes to be tokenized, which can produce an artificially huge baseline number. Real-text-only reductions are more honest. Example: Header.jsx shows 83.7% reduction, but ~80% of that is the PNG; the actual JS code reduction is ~11%.
- **Re-exports aren't traced through.** `export { x } from "./y"` doesn't get followed yet — `x` won't be pruned from the source file.
- **No caching.** Each invocation re-parses everything. Fine for individual files; not optimized for whole-project sweeps.

---

## Project documentation

For a file-by-file walkthrough of the codebase — what each module, parser, and extension file does — see [EXPLANATIONS.md](EXPLANATIONS.md).
