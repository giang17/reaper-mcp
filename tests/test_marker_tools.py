"""Tests for reaper_mcp/tools/marker_tools.py's markers_apply validation/ordering.

Pure logic only — no REAPER/IPC mocking needed, matching the pattern
tests/test_item_tools.py already uses for items_apply.
"""

import pytest

from reaper_mcp.tools.marker_tools import (
    _validate_markers_apply_entries,
    _order_markers_apply_entries,
)
from reaper_mcp_shared.error_codes import ReaperMCPError


class TestValidateMarkersApplyEntries:
    def test_valid_entries_pass(self):
        _validate_markers_apply_entries([
            {"marker_index": 0, "name": "Line 1"},
            {"marker_index": 5, "delete": True},
        ])

    def test_missing_marker_index_raises(self):
        with pytest.raises(ReaperMCPError, match="marker_index"):
            _validate_markers_apply_entries([{"name": "x"}])

    def test_negative_marker_index_raises(self):
        with pytest.raises(ReaperMCPError, match="marker_index"):
            _validate_markers_apply_entries([{"marker_index": -1}])

    def test_non_int_marker_index_raises(self):
        with pytest.raises(ReaperMCPError, match="marker_index"):
            _validate_markers_apply_entries([{"marker_index": "0"}])

    def test_negative_position_raises(self):
        with pytest.raises(ReaperMCPError, match="position"):
            _validate_markers_apply_entries([{"marker_index": 0, "position": -1.0}])

    def test_negative_start_raises(self):
        with pytest.raises(ReaperMCPError, match="start"):
            _validate_markers_apply_entries([{"marker_index": 0, "start": -1.0, "end": 5.0}])

    def test_end_not_greater_than_start_raises(self):
        with pytest.raises(ReaperMCPError, match="end"):
            _validate_markers_apply_entries([{"marker_index": 0, "start": 5.0, "end": 5.0}])

    def test_start_without_end_is_fine(self):
        _validate_markers_apply_entries([{"marker_index": 0, "start": 5.0}])

    def test_invalid_color_raises(self):
        with pytest.raises(ReaperMCPError):
            _validate_markers_apply_entries([{"marker_index": 0, "color": [999, 0, 0]}])

    def test_name_too_long_raises(self):
        with pytest.raises(ReaperMCPError, match="Name"):
            _validate_markers_apply_entries([{"marker_index": 0, "name": "x" * 2000}])

    def test_over_cap_raises(self):
        entries = [{"marker_index": i} for i in range(201)]
        with pytest.raises(ReaperMCPError, match="200"):
            _validate_markers_apply_entries(entries)

    def test_empty_list_raises(self):
        with pytest.raises(ReaperMCPError):
            _validate_markers_apply_entries([])


class TestOrderMarkersApplyEntries:
    def test_non_delete_entries_keep_relative_order(self):
        entries = [
            {"marker_index": 5, "name": "a"},
            {"marker_index": 2, "name": "b"},
        ]
        ordered = _order_markers_apply_entries(entries)
        assert ordered == entries

    def test_deletes_move_to_end_sorted_descending(self):
        entries = [
            {"marker_index": 2, "delete": True},
            {"marker_index": 9, "delete": True},
            {"marker_index": 5, "name": "keep"},
        ]
        ordered = _order_markers_apply_entries(entries)
        assert ordered == [
            {"marker_index": 5, "name": "keep"},
            {"marker_index": 9, "delete": True},
            {"marker_index": 2, "delete": True},
        ]

    def test_delete_false_is_not_treated_as_delete(self):
        entries = [{"marker_index": 3, "delete": False, "name": "x"}]
        ordered = _order_markers_apply_entries(entries)
        assert ordered == entries
