import { spawn } from "child_process";
import * as vscode from "vscode";

export interface PrunedFile {
  path: string;
  rel_path: string;
  depth: number;
  is_entry: boolean;
  symbols: string[];
  source: string;
  estimated_tokens: number;
}

export interface PruneResult {
  entry: string;
  requested_symbols: string[];
  total_tokens: number;
  files: PrunedFile[];
}

export interface BenchmarkResult {
  entry_file: string;
  requested_symbols: string[];
  depth: number;
  baseline: { files: number; tokens: number };
  pruned: { files: number; tokens: number };
  tokens_saved: number;
  reduction_pct: number;
  compression_ratio: number;
  per_file: Array<{
    path: string;
    raw_tokens: number;
    pruned_tokens: number;
    reduction_pct: number;
  }>;
}

function getCliPath(): string {
  return vscode.workspace
    .getConfiguration("ast-pruner")
    .get<string>("cliPath", "ast-pruner");
}

function getDefaultDepth(): number {
  return vscode.workspace
    .getConfiguration("ast-pruner")
    .get<number>("defaultDepth", 3);
}

function runCli(args: string[]): Promise<string> {
  return new Promise((resolve, reject) => {
    const proc = spawn(getCliPath(), args, { stdio: ["ignore", "pipe", "pipe"] });
    let stdout = "";
    let stderr = "";
    proc.stdout.on("data", (b) => (stdout += b.toString()));
    proc.stderr.on("data", (b) => (stderr += b.toString()));
    proc.on("error", (err) => reject(err));
    proc.on("close", (code) => {
      if (code === 0) {
        resolve(stdout);
      } else {
        reject(new Error(`ast-pruner exited ${code}: ${stderr || stdout}`));
      }
    });
  });
}

export async function prune(
  filePath: string,
  symbols: string[],
  depth?: number,
): Promise<PruneResult> {
  const args = ["prune", filePath, "--format", "json", "--depth", String(depth ?? getDefaultDepth())];
  if (symbols.length > 0) {
    args.push("--symbols", symbols.join(","));
  }
  const out = await runCli(args);
  return JSON.parse(out);
}

export async function benchmark(
  filePath: string,
  symbols: string[],
  depth?: number,
): Promise<BenchmarkResult> {
  const args = ["benchmark", filePath, "--format", "json", "--depth", String(depth ?? getDefaultDepth())];
  if (symbols.length > 0) {
    args.push("--symbols", symbols.join(","));
  }
  const out = await runCli(args);
  return JSON.parse(out);
}

export async function generateReport(logPath: string, outputPath: string): Promise<void> {
  await runCli(["report", "--log", logPath, "--output", outputPath]);
}

export async function isCliAvailable(): Promise<boolean> {
  try {
    await runCli(["--help"]);
    return true;
  } catch {
    return false;
  }
}
