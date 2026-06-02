# Path 1 — The VS Code `@pruner` Chat Participant

> How a file you attach with `#file:` becomes **pruned** text that lands in the chat
> model's context window — every concept, every memory/context state, every transfer,
> and the exact piece of code that does it.

This document covers **Path 1 only**: the VS Code extension that exposes `@pruner` inside
Copilot Chat. (The other delivery path — the Claude Code `/prune` slash command — is out of
scope here; see the README for that.)

---

## 1. One-paragraph summary

You type `@pruner #file:src/components/Header.jsx` in Copilot Chat. The extension wakes up,
runs the local `ast-pruner` CLI on that file, gets back a **semantically pruned** (much
smaller) version of the code, and **writes that pruned code into the chat reply**. Because a
chat reply becomes part of the conversation history, the *next* request the chat host sends
to its language model carries the **pruned** text instead of the full file. The result: the
model still "sees" the relevant code, but you spent a fraction of the tokens. The extension
itself never calls a model — it only shapes what goes into the conversation.

---

## 2. The mental model / key claim

**The pruner makes no LLM or network call of its own.** It is a *context shaper*, not a
chat client. Its entire job is:

1. Run a local, deterministic CLI to shrink a file.
2. Inject that shrunk text into the VS Code chat conversation buffer.

Whatever happens next — sending context to a model — is done by the **existing Chat host**
(Copilot, or whichever Language Model you've selected in VS Code's model picker). The token
savings are realized later, at **request-assembly time**, when the host bundles the
conversation (now containing pruned text) into its next model request.

```
The pruner does NOT intercept or proxy the model request.
It changes WHAT IS IN THE CONVERSATION so the host's next request is naturally smaller.
```

---

## 2b. Who generates the pruned content? Deterministic Python — **not** AI/Copilot

This is the most common misconception, so it's worth stating plainly:

> **No language model is involved in *creating* the pruned output.** The pruned code is
> produced entirely by the Python `ast-pruner` CLI using **static program analysis**.

The pipeline is reproducible, runs offline, and behaves like a compiler or linter — given
the same input it always yields the same output:

1. **tree-sitter** parses the source file into an **Abstract Syntax Tree (AST)**.
2. The **extractor** walks the AST and keeps only what's needed — *full bodies* for the
   entry file's requested symbols, *signatures only* for symbols pulled in from imported
   dependencies.
3. The **graph** module traces imports recursively (bounded by `--depth`).
4. The CLI serializes the result to **JSON on stdout**.

Relevant CLI internals (Python side): `ast_pruner/parsers/` (tree-sitter language parsers),
`ast_pruner/extractor.py` (body-stripping), `ast_pruner/graph.py` (BFS dependency
traversal), `ast_pruner/pruner.py` (orchestration).

The extension's only role in generation is to **spawn the CLI and parse its JSON** — it
adds zero intelligence of its own:

- spawn the process → [pruner-runner.ts:50-66](extension/src/pruner-runner.ts#L50-L66)
- build the `prune` args and parse the JSON → [pruner-runner.ts:68-79](extension/src/pruner-runner.ts#L68-L79)
- read the resulting `.source` field → [extension.ts:85-89](extension/src/extension.ts#L85-L89)

**Copilot/the model only *consumes* this output later.** It never *produces* it. That's a
real trust property worth highlighting in a demo: the pruning is verifiable and
deterministic, not a model guessing what to keep.

---

## 3. Concept glossary

Each VS Code primitive the extension uses, with the code anchor.

### Chat participant (`@pruner`)
A first-class actor in Copilot Chat that you summon with `@`. Declared statically in
[package.json](extension/package.json#L20-L34) under `contributes.chatParticipants` (id
`ast-pruner.pruner`, name `pruner`) and brought to life at runtime by
`vscode.chat.createChatParticipant("ast-pruner.pruner", handler)` —
[extension.ts:33-34](extension/src/extension.ts#L33-L34). The handler is the function that
runs every time you message `@pruner`.

### Activation event (`onChatParticipant:…`)
[package.json:15-17](extension/package.json#L15-L17) declares
`onChatParticipant:ast-pruner.pruner`. This is **lazy activation**: VS Code does not load
the extension until you actually invoke `@pruner`, keeping startup cheap.

### `request.references` / `#file:` attachments
When you attach a file with `#file:path`, VS Code delivers it on `request.references`. The
handler filters those references down to real file URIs —
[extension.ts:44-53](extension/src/extension.ts#L44-L53) — and bails with a help message if
none were attached.

### `ChatResponseStream` (the `stream` object) — read this carefully
`stream` is a **`vscode.ChatResponseStream`**: the object VS Code hands the participant so it
can emit its reply. A participant **does not `return` a string** — it *streams* its response
incrementally through this object. The methods used here:

- **`stream.markdown(text)`** — appends a chunk of Markdown to the reply, rendered live in
  the chat panel. This is the single most important call in Path 1: at
  [extension.ts:87-88](extension/src/extension.ts#L87-L88) it writes the pruned source into
  the chat as a fenced code block:
  ```ts
  stream.markdown("```" + lang + "\n" + f.source + "\n```\n");
  ```
  Writing here does two things at once: (1) it **displays** the pruned code to you, and
  (2) it **deposits that code into the chat conversation history**. Because the next model
  request is built from conversation history, this call is *literally the act that injects
  the pruned text into the model's next-turn context*. No separate "send to model" step
  exists in the extension — `stream.markdown` is the handoff.
- **`stream.reference(uri)`** — [extension.ts:76](extension/src/extension.ts#L76) — attaches
  a clickable "used this file" pill to the response (provenance, not context).
- **`stream.button({...})`** — [extension.ts:124-127](extension/src/extension.ts#L124-L127) —
  renders the "View savings dashboard" button at the end of the reply.

### Slash sub-command (`/dashboard`)
Declared at [package.json:27-32](extension/package.json#L27-L32) and handled first in the
request handler — [extension.ts:37-41](extension/src/extension.ts#L37-L41). Typing
`@pruner /dashboard` short-circuits pruning and just opens the savings dashboard.

### `globalStorageUri` (extension-scoped persistent storage)
A private per-extension directory VS Code provides for durable data. The usage log lives
there: `getLogPath` joins `context.globalStorageUri.fsPath` with `usage.jsonl` —
[usage-log.ts:17-19](extension/src/usage-log.ts#L17-L19). This is the same file the
`/prune` slash command and the `ast-pruner report` dashboard read from.

### Configuration (`cliPath`, `defaultDepth`)
[package.json:45-58](extension/package.json#L45-L58) declares two settings, read in the
runner: `ast-pruner.cliPath` (where the CLI binary is —
[pruner-runner.ts:38-42](extension/src/pruner-runner.ts#L38-L42)) and
`ast-pruner.defaultDepth` (import recursion depth, default 3 —
[pruner-runner.ts:44-48](extension/src/pruner-runner.ts#L44-L48)).

---

## 4. End-to-end data flow (keystroke → model context)

Each step cites the code that performs it.

1. **You type** `@pruner #file:Foo.jsx --symbols bar` and hit enter.
2. **Activation** — VS Code sees the `onChatParticipant:ast-pruner.pruner` event
   ([package.json:15-17](extension/package.json#L15-L17)) and loads the extension if needed;
   `activate()` runs ([extension.ts:10](extension/src/extension.ts#L10)).
3. **Handler fires** — the participant callback registered at
   [extension.ts:33-35](extension/src/extension.ts#L33-L35) runs with your `request`.
4. **Command check** — if it was `/dashboard`, open the dashboard and return
   ([extension.ts:37-41](extension/src/extension.ts#L37-L41)). Otherwise continue.
5. **Collect file references** — filter `request.references` to file URIs
   ([extension.ts:44-53](extension/src/extension.ts#L44-L53)); if none, print help and stop.
6. **Parse symbols** — `parseSymbols(request.prompt)` extracts `--symbols bar` into
   `["bar"]` ([extension.ts:55](extension/src/extension.ts#L55),
   [139-147](extension/src/extension.ts#L139-L147)).
7. **Per file**, skipping unsupported extensions
   ([extension.ts:60-74](extension/src/extension.ts#L60-L74)):
   - **Run the CLI** — `prune` and `benchmark` in **parallel** via `Promise.all`
     ([extension.ts:79-82](extension/src/extension.ts#L79-L82)), each `spawn`ing the
     `ast-pruner` binary ([pruner-runner.ts:50-92](extension/src/pruner-runner.ts#L50-L92)).
   - **Stream pruned source into chat** — loop over `pruneResult.files` and
     `stream.markdown` each one's `source`
     ([extension.ts:85-89](extension/src/extension.ts#L85-L89)). **← the context transfer.**
   - **Stream the savings line** — tokens saved + reduction %
     ([extension.ts:92-94](extension/src/extension.ts#L92-L94)).
   - **Log the invocation** — `appendEntry(...)` writes one JSONL row to globalStorage
     ([extension.ts:101-111](extension/src/extension.ts#L101-L111)).
8. **Totals** — if multiple files were attached, print a combined total
   ([extension.ts:117-122](extension/src/extension.ts#L117-L122)).
9. **Dashboard button** — append the CTA
   ([extension.ts:124-127](extension/src/extension.ts#L124-L127)).
10. **Next turn** — when you (or Copilot) continue the conversation, the **Chat host**
    assembles its model request from conversation history, which now contains the pruned
    code. The model receives the small version. **← where the savings are realized.**

---

## 5. Memory / context state transitions (the core)

The pruned code is not "in one place." It passes through several distinct memory/context
**homes**, each owned by a different process and with a different lifetime. Understanding
these transfers is the whole point.

```
(a) DISK ──spawn/stdin path──▶ (b) CLI SUBPROCESS ──stdout pipe──▶ (c) EXTENSION HOST JS
                                  (tree-sitter AST)   (JSON text)     (parsed objects)
                                                                            │
                                                          stream.markdown   │
                                                                            ▼
                                                              (d) CHAT CONVERSATION BUFFER
                                                                  (pruned text = history)
                                                                            │
                                                       host assembles next  │
                                                       request on next turn │
                                                                            ▼
                                                              (e) LANGUAGE MODEL REQUEST CONTEXT
                                                                  (tokens billed here)

                            ...and a side branch, not part of model context:
   (c) EXTENSION HOST JS ──appendEntry──▶ (f) globalStorage usage.jsonl  (analytics only)
```

| # | State / home | What lives here | Owned by | Lifetime | How data leaves |
|---|--------------|-----------------|----------|----------|-----------------|
| **a** | **On disk** | Original full source file | Filesystem | Until you edit/delete | Read by the CLI when spawned (file path passed as arg) |
| **b** | **CLI subprocess memory** | tree-sitter AST + extracted symbols, then JSON | The `ast-pruner` Python process | Just this one run; dies on exit | Printed to **stdout**, piped back via `runCli` ([pruner-runner.ts:50-66](extension/src/pruner-runner.ts#L50-L66)) |
| **c** | **Extension host JS memory** | `PruneResult` / `BenchmarkResult` objects | The VS Code extension host | The handler invocation (a few ms) | `JSON.parse(out)` ([pruner-runner.ts:78](extension/src/pruner-runner.ts#L78)); then read field-by-field |
| **d** | **Chat conversation buffer** | The pruned `source` as a fenced code block | VS Code Chat | The chat session / conversation thread | Written by `stream.markdown` ([extension.ts:87-88](extension/src/extension.ts#L87-L88)); becomes conversation **history** |
| **e** | **Language Model request context** | Serialized prior turns (incl. pruned text) | The Chat host (Copilot / selected LM) | One model request | Host builds the request on the **next turn**; **this is where tokens are counted/billed** |
| **f** | **Persistent globalStorage** | One JSONL row per invocation (savings stats) | The extension (durable) | Until deleted | `appendEntry` → `fs.appendFile` ([usage-log.ts:25-32](extension/src/usage-log.ts#L25-L32)); read later by the dashboard |

Key observations:

- The **transfer from (c) → (d)** — the `stream.markdown` call — is the moment "a value in
  the extension's memory" becomes "context the model will see." Everything before it is
  preparation; everything after it is the host's job.
- State **(f)** is a **dead-end branch for analytics**. The usage log never re-enters the
  model context; it only feeds the savings dashboard. Don't confuse it with context flow.
- The **token savings physically occur in state (e)**, not in the extension. The extension
  only guarantees that (d) holds the *small* version, so (e) is naturally cheaper.

---

## 6. The Copilot / Chat-host connection

The extension does **not** integrate with "Copilot" as a special API. It targets the
generic **VS Code Chat + Language Model API** (`vscode.chat.*`). Copilot Chat is simply the
surface that renders chat participants, so in practice `@pruner` shows up there.

How the pruned text actually reaches a model:

- VS Code Chat hosts **include prior participant responses in conversation history**. When
  the conversation continues, the host serializes that history into its next Language Model
  request. The pruned code, having been written via `stream.markdown`, is part of that
  history — so it rides along into the request.
- **"Copilot" here means whatever model backs the chat.** If you've selected a Claude model
  in VS Code's model picker, the pruned context flows to Claude; if it's Copilot's default
  model, it flows there. The extension is model-agnostic.

The code and manifest say this in their own words:

- The streaming loop comment: *"Stream pruned source into chat as context for Copilot"* —
  [extension.ts:84](extension/src/extension.ts#L84).
- The manifest description: *"Semantically prune code files to reduce Copilot context token
  usage. Use @pruner in Copilot Chat."* — [package.json:4](extension/package.json#L4).
- The participant description: *"Pipe pruned file context into Copilot Chat"* —
  [package.json:25](extension/package.json#L25).

---

## 7. Annotated code walkthrough

### Registration — [extension.ts:33-35](extension/src/extension.ts#L33-L35)
```ts
const participant = vscode.chat.createChatParticipant(
  "ast-pruner.pruner",
  async (request, _ctx, stream, token) => { /* handler */ },
);
```
Binds the manifest's `ast-pruner.pruner` id to a runtime handler. `request` carries your
prompt + attachments; `stream` is the reply channel (state **d**); `token` lets long work
cancel.

### Command branch — [extension.ts:37-41](extension/src/extension.ts#L37-L41)
```ts
if (request.command === "dashboard") {
  stream.markdown("Opening the savings dashboard…\n");
  await showDashboard(context);
  return;
}
```
`@pruner /dashboard` skips pruning entirely.

### Reference filtering — [extension.ts:44-53](extension/src/extension.ts#L44-L53)
Keeps only `#file:` URIs; if you attached nothing, it tells you how to attach a file and
returns.

### Symbol parsing — [extension.ts:139-147](extension/src/extension.ts#L139-L147)
```ts
const m = prompt.match(/(?:--symbols|symbols=)\s+?([A-Za-z0-9_,$\s]+)/);
```
Turns `--symbols foo,bar` in your prompt into `["foo","bar"]`, narrowing what the CLI keeps.

### Prune + benchmark — [extension.ts:79-82](extension/src/extension.ts#L79-L82)
```ts
const [pruneResult, benchResult] = await Promise.all([
  prune(filePath, symbols),
  benchmark(filePath, symbols),
]);
```
Two CLI runs in parallel: `prune` yields the actual pruned `source`; `benchmark` yields the
savings numbers. Both `spawn` the binary — [pruner-runner.ts:68-92](extension/src/pruner-runner.ts#L68-L92).

### The streaming loop (the context transfer) — [extension.ts:85-89](extension/src/extension.ts#L85-L89)
```ts
for (const f of pruneResult.files) {
  const lang = inferLang(f.rel_path);
  stream.markdown(`\n**${f.rel_path}** (${f.estimated_tokens} tokens${f.is_entry ? "" : ", signature only"})\n`);
  stream.markdown("```" + lang + "\n" + f.source + "\n```\n");
}
```
Writes each pruned file (entry file with full bodies, dependencies as signatures) into the
chat. **This is the (c) → (d) transfer** that makes the pruned text part of conversation
history.

### Savings line — [extension.ts:92-94](extension/src/extension.ts#L92-L94)
Human-readable "Saved N tokens (X% reduction)" message.

### Logging — [extension.ts:101-111](extension/src/extension.ts#L101-L111)
```ts
await appendEntry(context, { ts, file, symbols, depth, baseline_tokens,
  pruned_tokens, tokens_saved, reduction_pct, files_traversed });
```
Writes the analytics row (state **f**). Schema = `UsageEntry`
([usage-log.ts:5-15](extension/src/usage-log.ts#L5-L15)).

### Totals + button — [extension.ts:117-127](extension/src/extension.ts#L117-L127)
Combined total for multi-file turns, then the dashboard CTA button.

### The spawn boundary — [pruner-runner.ts:50-66](extension/src/pruner-runner.ts#L50-L66)
```ts
const proc = spawn(getCliPath(), args, { stdio: ["ignore", "pipe", "pipe"] });
proc.stdout.on("data", (b) => (stdout += b.toString()));
proc.on("close", (code) => code === 0 ? resolve(stdout) : reject(...));
```
The only place the extension crosses into the Python world. Collects stdout (state **b** →
**c**), rejects on non-zero exit.

### The log boundary — [usage-log.ts:25-32](extension/src/usage-log.ts#L25-L32)
```ts
await ensureLogDir(context);
const line = JSON.stringify(entry) + "\n";
await fs.appendFile(getLogPath(context), line, "utf-8");
```
Appends one JSON line to `usage.jsonl` in globalStorage (state **f**).

---

## 8. Where the saving actually happens (and where it doesn't)

- ✅ **It happens** when the Chat host assembles the **next** model request: the conversation
  now holds the *pruned* code (state **d**), so the request (state **e**) is naturally
  smaller and cheaper. The savings are a property of "the conversation is smaller," realized
  at request-assembly time.
- ❌ **It is NOT** request interception or proxying. The extension never sees, rewrites, or
  forwards the model request. It has no model client at all.
- ⚠️ **Caveat:** this relies on the Chat host including prior participant turns in the model
  context. VS Code Chat does this, which is why the approach works. A host that ignored
  participant history would still *display* the pruned code but wouldn't pass it to the
  model.

---

## 9. Sequence diagram (ASCII)

```
 You            VS Code Chat        @pruner handler        ast-pruner CLI         Language Model
  │                  │                    │                      │                      │
  │ @pruner #file:.. │                    │                      │                      │
  ├─────────────────▶│                    │                      │                      │
  │                  │ activate + invoke  │                      │                      │
  │                  ├───────────────────▶│                      │                      │
  │                  │                    │ spawn prune+benchmark │                      │
  │                  │                    ├─────────────────────▶│                      │
  │                  │                    │                      │ tree-sitter AST,     │
  │                  │                    │                      │ extract symbols      │
  │                  │                    │   JSON (pruned src)  │                      │
  │                  │                    │◀─────────────────────┤                      │
  │                  │ stream.markdown(   │                      │                      │
  │                  │   pruned source )  │                      │                      │
  │                  │◀───────────────────┤                      │                      │
  │  pruned code +   │                    │ appendEntry → usage  │                      │
  │  savings shown   │                    │ .jsonl (analytics)   │                      │
  │◀─────────────────┤                    │                      │                      │
  │                  │                    │                      │                      │
  │ (next turn) ...  │  host bundles history (now PRUNED) into request                  │
  │                  ├────────────────────────────────────────────────────────────────▶│
  │                  │                    │                      │   model sees the     │
  │                  │                    │                      │   small version ✅    │
```

---

## 10. Quick reference table

| Concept | Code anchor | Role |
|---------|-------------|------|
| Participant declaration | [package.json:20-34](extension/package.json#L20-L34) | Registers `@pruner` + `/dashboard` |
| Lazy activation | [package.json:15-17](extension/package.json#L15-L17) | Load only when `@pruner` used |
| Participant runtime | [extension.ts:33-34](extension/src/extension.ts#L33-L34) | Binds id → handler |
| `/dashboard` branch | [extension.ts:37-41](extension/src/extension.ts#L37-L41) | Open dashboard, skip pruning |
| Reference filtering | [extension.ts:44-53](extension/src/extension.ts#L44-L53) | Get attached `#file:` URIs |
| Symbol parsing | [extension.ts:139-147](extension/src/extension.ts#L139-L147) | `--symbols a,b` → `["a","b"]` |
| Prune + benchmark | [extension.ts:79-82](extension/src/extension.ts#L79-L82) | Run CLI twice in parallel |
| **Context transfer** | [extension.ts:85-89](extension/src/extension.ts#L85-L89) | `stream.markdown` pruned source into chat |
| Savings line | [extension.ts:92-94](extension/src/extension.ts#L92-L94) | Show tokens saved |
| Usage logging | [extension.ts:101-111](extension/src/extension.ts#L101-L111) | Append analytics row |
| Dashboard button | [extension.ts:124-127](extension/src/extension.ts#L124-L127) | CTA |
| Spawn boundary | [pruner-runner.ts:50-66](extension/src/pruner-runner.ts#L50-L66) | Extension ↔ Python CLI |
| `prune` args/parse | [pruner-runner.ts:68-79](extension/src/pruner-runner.ts#L68-L79) | Build CLI call, `JSON.parse` |
| Config reads | [pruner-runner.ts:38-48](extension/src/pruner-runner.ts#L38-L48) | `cliPath`, `defaultDepth` |
| Log path | [usage-log.ts:17-19](extension/src/usage-log.ts#L17-L19) | `globalStorage/usage.jsonl` |
| Log writer | [usage-log.ts:25-32](extension/src/usage-log.ts#L25-L32) | `appendFile` JSONL |

---

*See also: the Claude Code `/prune` slash command (Path 2) delivers the same CLI output into
a different host — the Claude Code conversation — instead of VS Code Chat.*
