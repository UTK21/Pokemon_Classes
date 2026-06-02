# AST Pruner — VS Code Extension

Pipe semantically pruned file context into Copilot Chat to save tokens.

## Use

In Copilot Chat:

```
@pruner #file:src/components/Foo.jsx
```

The extension runs `ast-pruner` locally on the file, streams the pruned source back into chat, and logs the savings. View accumulated stats with:

```
@pruner /dashboard
```

## Requirements

- Python `ast-pruner` CLI on your PATH. Install with:
  ```bash
  pipx install /path/to/AST_PRUNER
  ```

## Settings

- `ast-pruner.cliPath` — path to the `ast-pruner` binary (default: looks it up on PATH)
- `ast-pruner.defaultDepth` — import recursion depth (default: 3)
