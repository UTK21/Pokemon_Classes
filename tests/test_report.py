from __future__ import annotations

import json
import os

from ast_pruner.report import compute_aggregates, generate_report, load_log, render_html


def _write_log(path: str, entries: list[dict]) -> None:
    with open(path, "w", encoding="utf-8") as f:
        for e in entries:
            f.write(json.dumps(e) + "\n")


SAMPLE = [
    {"ts": "2026-05-29T10:00:00Z", "file": "src/a.py",
     "baseline_tokens": 100, "pruned_tokens": 30, "tokens_saved": 70, "reduction_pct": 70.0},
    {"ts": "2026-05-29T11:00:00Z", "file": "src/b.py",
     "baseline_tokens": 200, "pruned_tokens": 80, "tokens_saved": 120, "reduction_pct": 60.0},
    {"ts": "2026-05-30T09:00:00Z", "file": "src/a.py",
     "baseline_tokens": 150, "pruned_tokens": 50, "tokens_saved": 100, "reduction_pct": 66.7},
]


class TestLoadLog:
    def test_missing_file_returns_empty(self, tmp_path):
        result = load_log(str(tmp_path / "nonexistent.jsonl"))
        assert result == []

    def test_skips_blank_lines(self, tmp_path):
        log = tmp_path / "log.jsonl"
        log.write_text('\n{"ts":"2026-05-29","tokens_saved":50}\n\n')
        result = load_log(str(log))
        assert len(result) == 1

    def test_skips_malformed_lines(self, tmp_path):
        log = tmp_path / "log.jsonl"
        log.write_text('not json\n{"ts":"2026-05-29","tokens_saved":50}\n')
        result = load_log(str(log))
        assert len(result) == 1


class TestComputeAggregates:
    def test_empty(self):
        agg = compute_aggregates([])
        assert agg.total_invocations == 0
        assert agg.total_tokens_saved == 0

    def test_totals(self):
        agg = compute_aggregates(SAMPLE)
        assert agg.total_invocations == 3
        assert agg.total_baseline_tokens == 450
        assert agg.total_pruned_tokens == 160
        assert agg.total_tokens_saved == 290

    def test_avg_reduction(self):
        agg = compute_aggregates(SAMPLE)
        # (70 + 60 + 66.7) / 3 ≈ 65.57
        assert abs(agg.avg_reduction_pct - 65.57) < 0.1

    def test_top_files(self):
        agg = compute_aggregates(SAMPLE)
        # a.py: 70 + 100 = 170; b.py: 120
        assert agg.top_files[0] == ("src/a.py", 170)
        assert agg.top_files[1] == ("src/b.py", 120)

    def test_cumulative_series(self):
        agg = compute_aggregates(SAMPLE)
        # 2026-05-29: 70+120=190; 2026-05-30: +100 = 290
        assert agg.cumulative_series == [("2026-05-29", 190), ("2026-05-30", 290)]

    def test_reduction_histogram(self):
        agg = compute_aggregates(SAMPLE)
        # 70% -> 70-80, 60% -> 60-70, 66.7% -> 60-70
        assert agg.reduction_histogram["60-70"] == 2
        assert agg.reduction_histogram["70-80"] == 1


class TestRenderHtml:
    def test_renders_with_data(self):
        agg = compute_aggregates(SAMPLE)
        html = render_html(agg, generated_at="2026-05-31 12:00:00")
        assert "<!DOCTYPE html>" in html
        assert "Chart" in html  # Chart.js reference present
        assert "290" in html  # total tokens saved

    def test_renders_empty(self):
        agg = compute_aggregates([])
        html = render_html(agg, generated_at="2026-05-31 12:00:00")
        assert "<!DOCTYPE html>" in html
        # Should render without crashing


class TestGenerateReport:
    def test_writes_html_file(self, tmp_path):
        log = tmp_path / "log.jsonl"
        _write_log(str(log), SAMPLE)
        out = tmp_path / "report.html"

        result = generate_report(str(log), str(out))
        assert out.exists()
        assert result["total_invocations"] == 3
        assert result["total_tokens_saved"] == 290

        content = out.read_text()
        assert "<!DOCTYPE html>" in content

    def test_handles_empty_log(self, tmp_path):
        log = tmp_path / "empty.jsonl"
        log.write_text("")
        out = tmp_path / "report.html"

        result = generate_report(str(log), str(out))
        assert result["total_invocations"] == 0
        assert out.exists()
