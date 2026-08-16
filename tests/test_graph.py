from __future__ import annotations

import os
import pytest
from ast_pruner.graph import build_graph

FIXTURES = os.path.join(os.path.dirname(__file__), "fixtures")
CIRCULAR = os.path.join(FIXTURES, "circular")


class TestBuildGraph:
    def test_entry_node_present(self):
        entry = os.path.join(FIXTURES, "entry.py")
        graph = build_graph(entry, {"greet"}, max_depth=3)
        assert entry in graph.nodes

    def test_dependency_discovered(self):
        entry = os.path.join(FIXTURES, "entry.py")
        graph = build_graph(entry, {"greet"}, max_depth=3)
        helpers = os.path.join(FIXTURES, "helpers.py")
        assert helpers in graph.nodes

    def test_depth_zero_is_entry(self):
        entry = os.path.join(FIXTURES, "entry.py")
        graph = build_graph(entry, {"greet"}, max_depth=3)
        assert graph.nodes[entry].depth == 0

    def test_dependency_depth_is_one(self):
        entry = os.path.join(FIXTURES, "entry.py")
        graph = build_graph(entry, {"greet"}, max_depth=3)
        helpers = os.path.join(FIXTURES, "helpers.py")
        if helpers in graph.nodes:
            assert graph.nodes[helpers].depth == 1

    def test_depth_limit_respected(self):
        entry = os.path.join(FIXTURES, "entry.py")
        graph = build_graph(entry, {"greet"}, max_depth=0)
        # With depth=0, no deps should be followed
        assert len(graph.nodes) == 1

    def test_circular_import_no_infinite_loop(self):
        entry = os.path.join(CIRCULAR, "a.py")
        # Should terminate without hanging
        graph = build_graph(entry, {"foo"}, max_depth=5)
        assert entry in graph.nodes
        # Both a and b may be present, but no infinite recursion
        assert len(graph.nodes) <= 3  # a, b, and maybe __init__

    def test_js_dependency_traversal(self):
        entry = os.path.join(FIXTURES, "utils.js")
        graph = build_graph(entry, {"processData"}, max_depth=3)
        date_utils = os.path.join(FIXTURES, "date_utils.js")
        assert date_utils in graph.nodes
