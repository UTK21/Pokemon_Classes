import * as path from "path";
import * as vscode from "vscode";

import { showDashboard } from "./dashboard";
import { benchmark, isCliAvailable, prune } from "./pruner-runner";
import { appendEntry, getLogPath } from "./usage-log";

const SUPPORTED_EXTS = new Set([".py", ".js", ".jsx", ".mjs", ".ts", ".tsx"]);

export async function activate(context: vscode.ExtensionContext): Promise<void> {
  context.subscriptions.push(
    vscode.commands.registerCommand("ast-pruner.showDashboard", () => showDashboard(context)),
  );

  context.subscriptions.push(
    vscode.commands.registerCommand("ast-pruner.openLog", async () => {
      const doc = await vscode.workspace.openTextDocument(getLogPath(context));
      vscode.window.showTextDocument(doc);
    }),
  );

  // Pre-flight check: warn if CLI is missing
  if (!(await isCliAvailable())) {
    const action = await vscode.window.showWarningMessage(
      "AST Pruner: the `ast-pruner` CLI was not found on PATH. Install it with `pipx install ast-pruner`, or set `ast-pruner.cliPath` in settings.",
      "Open Settings",
    );
    if (action === "Open Settings") {
      vscode.commands.executeCommand("workbench.action.openSettings", "ast-pruner.cliPath");
    }
  }

  const participant = vscode.chat.createChatParticipant(
    "ast-pruner.pruner",
    async (request, _ctx, stream, token) => {
      // Handle /dashboard slash command
      if (request.command === "dashboard") {
        stream.markdown("Opening the savings dashboard…\n");
        await showDashboard(context);
        return;
      }

      // Collect file references from the user's prompt
      const fileRefs = request.references.filter(
        (r) => r.value instanceof vscode.Uri || (r.value as any)?.uri,
      );

      if (fileRefs.length === 0) {
        stream.markdown(
          "Attach one or more files with `#file:path/to/file.ext` and I'll prune them. Try `@pruner #file:src/components/Foo.tsx`.\n",
        );
        return;
      }

      const symbols = parseSymbols(request.prompt);
      let totalSaved = 0;
      let totalBaseline = 0;
      let totalPruned = 0;

      for (const ref of fileRefs) {
        if (token.isCancellationRequested) {
          return;
        }

        const uri = (ref.value instanceof vscode.Uri
          ? ref.value
          : (ref.value as any).uri) as vscode.Uri;
        const filePath = uri.fsPath;
        const ext = path.extname(filePath).toLowerCase();

        if (!SUPPORTED_EXTS.has(ext)) {
          stream.markdown(`_Skipping ${path.basename(filePath)} — unsupported file type (${ext})._\n\n`);
          continue;
        }

        stream.reference(uri);

        try {
          const [pruneResult, benchResult] = await Promise.all([
            prune(filePath, symbols),
            benchmark(filePath, symbols),
          ]);

          // Stream pruned source into chat as context for Copilot
          for (const f of pruneResult.files) {
            const lang = inferLang(f.rel_path);
            stream.markdown(`\n**${f.rel_path}** (${f.estimated_tokens} tokens${f.is_entry ? "" : ", signature only"})\n`);
            stream.markdown("```" + lang + "\n" + f.source + "\n```\n");
          }

          // Savings line
          stream.markdown(
            `\n_Saved **${benchResult.tokens_saved.toLocaleString()} tokens** (${benchResult.reduction_pct.toFixed(1)}% reduction) on ${path.basename(filePath)} — across ${benchResult.baseline.files} file(s)._\n\n`,
          );

          totalSaved += benchResult.tokens_saved;
          totalBaseline += benchResult.baseline.tokens;
          totalPruned += benchResult.pruned.tokens;

          // Log this invocation
          await appendEntry(context, {
            ts: new Date().toISOString(),
            file: vscode.workspace.asRelativePath(uri, false),
            symbols,
            depth: benchResult.depth,
            baseline_tokens: benchResult.baseline.tokens,
            pruned_tokens: benchResult.pruned.tokens,
            tokens_saved: benchResult.tokens_saved,
            reduction_pct: benchResult.reduction_pct,
            files_traversed: benchResult.baseline.files,
          });
        } catch (err) {
          stream.markdown(`_Failed to prune ${path.basename(filePath)}: ${(err as Error).message}_\n\n`);
        }
      }

      if (fileRefs.length > 1 && totalBaseline > 0) {
        const pct = ((totalSaved / totalBaseline) * 100).toFixed(1);
        stream.markdown(
          `\n---\n**Total savings this turn: ${totalSaved.toLocaleString()} tokens (${pct}%)** — ${totalBaseline.toLocaleString()} → ${totalPruned.toLocaleString()}.\n`,
        );
      }

      stream.button({
        command: "ast-pruner.showDashboard",
        title: "View savings dashboard",
      });
    },
  );

  participant.iconPath = new vscode.ThemeIcon("scissors");
  context.subscriptions.push(participant);
}

export function deactivate(): void {
  // no-op
}

function parseSymbols(prompt: string): string[] {
  // Match `--symbols foo,bar` or `symbols=foo,bar`
  const m = prompt.match(/(?:--symbols|symbols=)\s+?([A-Za-z0-9_,$\s]+)/);
  if (!m) return [];
  return m[1]
    .split(",")
    .map((s) => s.trim())
    .filter((s) => s.length > 0);
}

function inferLang(filePath: string): string {
  const ext = path.extname(filePath).toLowerCase();
  if (ext === ".py") return "python";
  if (ext === ".ts" || ext === ".tsx") return "typescript";
  return "javascript";
}
