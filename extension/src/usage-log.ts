import { promises as fs } from "fs";
import * as path from "path";
import * as vscode from "vscode";

export interface UsageEntry {
  ts: string;
  file: string;
  symbols: string[];
  depth: number;
  baseline_tokens: number;
  pruned_tokens: number;
  tokens_saved: number;
  reduction_pct: number;
  files_traversed: number;
}

export function getLogPath(context: vscode.ExtensionContext): string {
  return path.join(context.globalStorageUri.fsPath, "usage.jsonl");
}

export async function ensureLogDir(context: vscode.ExtensionContext): Promise<void> {
  await fs.mkdir(context.globalStorageUri.fsPath, { recursive: true });
}

export async function appendEntry(
  context: vscode.ExtensionContext,
  entry: UsageEntry,
): Promise<void> {
  await ensureLogDir(context);
  const line = JSON.stringify(entry) + "\n";
  await fs.appendFile(getLogPath(context), line, "utf-8");
}
