from __future__ import annotations

import os

from ast_pruner.benchmark import benchmark_file, format_report

FIXTURES = os.path.join(os.path.dirname(__file__), "fixtures")


class TestBenchmark:
    def test_basic_metrics(self):
        entry = os.path.join(FIXTURES, "entry.py")
        result = benchmark_file(entry, ["greet"], depth=3)

        assert result.baseline_tokens > 0
        assert result.pruned_tokens > 0
        # Pruned should always be smaller than baseline when there's unused code
        assert result.pruned_tokens <= result.baseline_tokens
        assert result.tokens_saved >= 0

    def test_reduction_percentage(self):
        entry = os.path.join(FIXTURES, "entry.py")
        result = benchmark_file(entry, ["greet"], depth=3)

        # Should achieve meaningful reduction (entry.py has unused symbols)
        assert result.reduction_pct > 0
        assert result.reduction_pct <= 100

    def test_compression_ratio(self):
        entry = os.path.join(FIXTURES, "entry.py")
        result = benchmark_file(entry, ["greet"], depth=3)

        assert result.compression_ratio >= 1.0

    def test_per_file_breakdown(self):
        entry = os.path.join(FIXTURES, "entry.py")
        result = benchmark_file(entry, ["greet"], depth=3)

        assert len(result.per_file) == result.baseline_files
        for fm in result.per_file:
            assert fm.raw_tokens > 0
            assert fm.pruned_tokens >= 0

    def test_format_report_runs(self):
        entry = os.path.join(FIXTURES, "entry.py")
        result = benchmark_file(entry, ["greet"], depth=3)
        report = format_report(result)
        assert "Reduction" in report
        assert "Compression" in report

    def test_to_dict_serializable(self):
        import json
        entry = os.path.join(FIXTURES, "entry.py")
        result = benchmark_file(entry, ["greet"], depth=3)
        data = result.to_dict()
        # Should be JSON-serializable
        json.dumps(data)
