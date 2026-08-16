import { promises as fs } from "fs";
import * as os from "os";
import * as path from "path";
import * as vscode from "vscode";

import { generateReport } from "./pruner-runner";
import { getLogPath } from "./usage-log";

export async function showDashboard(context: vscode.ExtensionContext): Promise<void> {
  const logPath = getLogPath(context);

  if (!(await fileExists(logPath))) {
    vscode.window.showInformationMessage(
      "AST Pruner: no usage logged yet. Invoke @pruner in Copilot Chat first.",
    );
    return;
  }

  // Generate HTML to a temp file via the CLI (single source of truth)
  const tmpPath = path.join(os.tmpdir(), `ast-pruner-report-${Date.now()}.html`);

  try {
    await generateReport(logPath, tmpPath);
  } catch (err) {
    vscode.window.showErrorMessage(`Failed to generate dashboard: ${err}`);
    return;
  }

  const html = await fs.readFile(tmpPath, "utf-8");

  const panel = vscode.window.createWebviewPanel(
    "astPrunerDashboard",
    "AST Pruner: Savings Dashboard",
    vscode.ViewColumn.Active,
    {
      enableScripts: true,
      retainContextWhenHidden: true,
    },
  );

  panel.webview.html = html;
}

async function fileExists(p: string): Promise<boolean> {
  try {
    await fs.access(p);
    return true;
  } catch {
    return false;
  }
}
