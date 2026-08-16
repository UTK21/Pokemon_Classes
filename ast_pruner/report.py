"""
Generate an HTML dashboard from a JSONL usage log.

Each log line is a JSON object with at minimum:
  ts, file, baseline_tokens, pruned_tokens, tokens_saved, reduction_pct

Output: a single self-contained HTML file with Chart.js (CDN) charts.
"""
from __future__ import annotations

import json
import os
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any


@dataclass
class Aggregates:
    total_invocations: int = 0
    total_baseline_tokens: int = 0
    total_pruned_tokens: int = 0
    total_tokens_saved: int = 0
    avg_reduction_pct: float = 0.0
    top_files: list[tuple[str, int]] = field(default_factory=list)  # (path, tokens_saved)
    cumulative_series: list[tuple[str, int]] = field(default_factory=list)  # (date, cumulative_saved)
    reduction_histogram: dict[str, int] = field(default_factory=dict)  # bucket label -> count

    def to_dict(self) -> dict[str, Any]:
        return {
            "total_invocations": self.total_invocations,
            "total_baseline_tokens": self.total_baseline_tokens,
            "total_pruned_tokens": self.total_pruned_tokens,
            "total_tokens_saved": self.total_tokens_saved,
            "avg_reduction_pct": round(self.avg_reduction_pct, 2),
            "top_files": self.top_files,
            "cumulative_series": self.cumulative_series,
            "reduction_histogram": self.reduction_histogram,
        }


def load_log(log_path: str) -> list[dict]:
    """Read a JSONL file. Silently skip blank or malformed lines."""
    if not os.path.isfile(log_path):
        return []
    entries: list[dict] = []
    with open(log_path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                entries.append(json.loads(line))
            except json.JSONDecodeError:
                continue
    return entries


def compute_aggregates(entries: list[dict]) -> Aggregates:
    agg = Aggregates()
    if not entries:
        return agg

    agg.total_invocations = len(entries)
    agg.total_baseline_tokens = sum(e.get("baseline_tokens", 0) for e in entries)
    agg.total_pruned_tokens = sum(e.get("pruned_tokens", 0) for e in entries)
    agg.total_tokens_saved = sum(e.get("tokens_saved", 0) for e in entries)

    reductions = [e.get("reduction_pct", 0.0) for e in entries]
    agg.avg_reduction_pct = sum(reductions) / len(reductions) if reductions else 0.0

    # Top files: aggregate savings per file path
    per_file: dict[str, int] = defaultdict(int)
    for e in entries:
        per_file[e.get("file", "<unknown>")] += e.get("tokens_saved", 0)
    agg.top_files = sorted(per_file.items(), key=lambda kv: kv[1], reverse=True)[:10]

    # Cumulative savings over time (sorted by timestamp, grouped by date)
    by_date: dict[str, int] = defaultdict(int)
    for e in entries:
        ts = e.get("ts", "")
        date = ts[:10] if len(ts) >= 10 else "unknown"
        by_date[date] += e.get("tokens_saved", 0)
    sorted_dates = sorted(by_date.keys())
    running = 0
    for d in sorted_dates:
        running += by_date[d]
        agg.cumulative_series.append((d, running))

    # Reduction % histogram (10-point buckets)
    buckets = ["0-10", "10-20", "20-30", "30-40", "40-50",
               "50-60", "60-70", "70-80", "80-90", "90-100"]
    hist: dict[str, int] = {b: 0 for b in buckets}
    for r in reductions:
        idx = min(int(r // 10), 9)
        hist[buckets[idx]] += 1
    agg.reduction_histogram = hist

    return agg


def render_html(agg: Aggregates, generated_at: str | None = None) -> str:
    """Render a self-contained HTML dashboard."""
    if generated_at is None:
        generated_at = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    data_js = json.dumps(agg.to_dict())

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<title>ast-pruner — Token Savings Dashboard</title>
<script src="https://cdn.jsdelivr.net/npm/chart.js"></script>
<style>
  body {{
    font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", system-ui, sans-serif;
    background: #0d1117; color: #e6edf3; margin: 0; padding: 2rem;
  }}
  h1 {{ margin: 0 0 0.25rem 0; font-size: 1.75rem; }}
  .subtitle {{ color: #8b949e; margin-bottom: 2rem; }}
  .hero {{
    display: grid; grid-template-columns: repeat(4, 1fr); gap: 1rem;
    margin-bottom: 2rem;
  }}
  .stat {{
    background: #161b22; border: 1px solid #30363d; border-radius: 8px;
    padding: 1.25rem;
  }}
  .stat-value {{ font-size: 1.75rem; font-weight: 600; color: #58a6ff; }}
  .stat-label {{ font-size: 0.8rem; color: #8b949e; text-transform: uppercase;
                 letter-spacing: 0.04em; margin-top: 0.25rem; }}
  .grid {{ display: grid; grid-template-columns: 1fr 1fr; gap: 1.5rem; }}
  .card {{
    background: #161b22; border: 1px solid #30363d; border-radius: 8px;
    padding: 1.5rem;
  }}
  .card h2 {{ margin: 0 0 1rem 0; font-size: 1rem; color: #c9d1d9; }}
  .empty {{ text-align: center; color: #8b949e; padding: 3rem; }}
  canvas {{ max-height: 280px; }}
</style>
</head>
<body>

<h1>ast-pruner — Token Savings Dashboard</h1>
<div class="subtitle">Generated {generated_at} · How much LLM context you've avoided sending</div>

<div id="root"></div>

<script>
const data = {data_js};

const root = document.getElementById("root");

if (data.total_invocations === 0) {{
  root.innerHTML = '<div class="empty">No usage logged yet. Try invoking <code>@pruner</code> in Copilot Chat first.</div>';
}} else {{
  const fmt = (n) => n.toLocaleString();

  root.innerHTML = `
    <div class="hero">
      <div class="stat">
        <div class="stat-value">${{fmt(data.total_tokens_saved)}}</div>
        <div class="stat-label">Tokens saved (lifetime)</div>
      </div>
      <div class="stat">
        <div class="stat-value">${{data.total_invocations}}</div>
        <div class="stat-label">Times invoked</div>
      </div>
      <div class="stat">
        <div class="stat-value">${{data.avg_reduction_pct}}%</div>
        <div class="stat-label">Average reduction</div>
      </div>
      <div class="stat">
        <div class="stat-value">${{fmt(data.total_baseline_tokens)}}</div>
        <div class="stat-label">Baseline (if unpruned)</div>
      </div>
    </div>

    <div class="grid">
      <div class="card"><h2>Cumulative tokens saved over time</h2><canvas id="cumChart"></canvas></div>
      <div class="card"><h2>Top files by tokens saved</h2><canvas id="topChart"></canvas></div>
      <div class="card"><h2>Baseline vs Pruned (totals)</h2><canvas id="ratioChart"></canvas></div>
      <div class="card"><h2>Reduction % distribution</h2><canvas id="histChart"></canvas></div>
    </div>
  `;

  const palette = ["#58a6ff", "#3fb950", "#d29922", "#f85149", "#bc8cff"];
  Chart.defaults.color = "#8b949e";
  Chart.defaults.borderColor = "#30363d";

  new Chart(document.getElementById("cumChart"), {{
    type: "line",
    data: {{
      labels: data.cumulative_series.map(x => x[0]),
      datasets: [{{
        label: "Cumulative tokens saved",
        data: data.cumulative_series.map(x => x[1]),
        borderColor: palette[0], backgroundColor: palette[0] + "33",
        fill: true, tension: 0.3,
      }}],
    }},
    options: {{ responsive: true, plugins: {{ legend: {{ display: false }} }} }},
  }});

  new Chart(document.getElementById("topChart"), {{
    type: "bar",
    data: {{
      labels: data.top_files.map(x => x[0].split("/").slice(-2).join("/")),
      datasets: [{{
        label: "Tokens saved",
        data: data.top_files.map(x => x[1]),
        backgroundColor: palette[1],
      }}],
    }},
    options: {{ indexAxis: "y", responsive: true,
                plugins: {{ legend: {{ display: false }} }} }},
  }});

  new Chart(document.getElementById("ratioChart"), {{
    type: "doughnut",
    data: {{
      labels: ["Pruned (sent)", "Saved (not sent)"],
      datasets: [{{
        data: [data.total_pruned_tokens, data.total_tokens_saved],
        backgroundColor: [palette[3], palette[1]],
      }}],
    }},
    options: {{ responsive: true }},
  }});

  new Chart(document.getElementById("histChart"), {{
    type: "bar",
    data: {{
      labels: Object.keys(data.reduction_histogram),
      datasets: [{{
        label: "Invocations",
        data: Object.values(data.reduction_histogram),
        backgroundColor: palette[2],
      }}],
    }},
    options: {{ responsive: true,
                plugins: {{ legend: {{ display: false }} }},
                scales: {{ x: {{ title: {{ display: true, text: "Reduction %" }} }} }} }},
  }});
}}
</script>
</body>
</html>
"""


def generate_report(log_path: str, output_path: str) -> dict[str, Any]:
    """
    Read JSONL log, compute aggregates, write HTML dashboard.
    Returns the aggregates dict (useful for tests / programmatic use).
    """
    entries = load_log(log_path)
    agg = compute_aggregates(entries)
    html = render_html(agg)
    with open(output_path, "w", encoding="utf-8") as f:
        f.write(html)
    return agg.to_dict()
