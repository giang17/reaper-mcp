"""Tests for reaper_mcp/tools/item_tools.py's items_apply validation/ordering.

Pure logic only — no REAPER/IPC mocking needed, matching the pattern
tests/test_patterns_tools.py already uses for _tile_pattern_lines.
"""

import pytest

from reaper_mcp.tools.item_tools import (
    _validate_items_apply_entries,
    _order_items_apply_entries,
)
from reaper_mcp_shared.error_codes import ReaperMCPError


class TestValidateItemsApplyEntries:
    def test_valid_entries_pass(self):
        _validate_items_apply_entries([
            {"item_index": 0, "volume_db": -3.0},
            {"item_index": 5, "delete": True},
        ])

    def test_missing_item_index_raises(self):
        with pytest.raises(ReaperMCPError, match="item_index"):
            _validate_items_apply_entries([{"volume_db": -3.0}])

    def test_negative_item_index_raises(self):
        with pytest.raises(ReaperMCPError, match="item_index"):
            _validate_items_apply_entries([{"item_index": -1}])

    def test_non_int_item_index_raises(self):
        with pytest.raises(ReaperMCPError, match="item_index"):
            _validate_items_apply_entries([{"item_index": "0"}])

    def test_negative_fade_in_raises(self):
        with pytest.raises(ReaperMCPError, match="fade_in"):
            _validate_items_apply_entries([{"item_index": 0, "fade_in": -0.1}])

    def test_negative_fade_out_raises(self):
        with pytest.raises(ReaperMCPError, match="fade_out"):
            _validate_items_apply_entries([{"item_index": 0, "fade_out": -0.1}])

    def test_zero_length_raises(self):
        with pytest.raises(ReaperMCPError, match="length"):
            _validate_items_apply_entries([{"item_index": 0, "length": 0}])

    def test_negative_position_raises(self):
        with pytest.raises(ReaperMCPError, match="position"):
            _validate_items_apply_entries([{"item_index": 0, "position": -1.0}])

    def test_over_cap_raises(self):
        entries = [{"item_index": i} for i in range(201)]
        with pytest.raises(ReaperMCPError, match="200"):
            _validate_items_apply_entries(entries)

    def test_empty_list_raises(self):
        with pytest.raises(ReaperMCPError):
            _validate_items_apply_entries([])


class TestOrderItemsApplyEntries:
    def test_non_delete_entries_keep_relative_order(self):
        entries = [
            {"item_index": 5, "volume_db": -3.0},
            {"item_index": 2, "mute": True},
        ]
        ordered = _order_items_apply_entries(entries)
        assert ordered == entries

    def test_deletes_move_to_end(self):
        entries = [
            {"item_index": 5, "delete": True},
            {"item_index": 2, "volume_db": -3.0},
        ]
        ordered = _order_items_apply_entries(entries)
        assert ordered == [
            {"item_index": 2, "volume_db": -3.0},
            {"item_index": 5, "delete": True},
        ]

    def test_deletes_sorted_descending_by_item_index(self):
        entries = [
            {"item_index": 2, "delete": True},
            {"item_index": 9, "delete": True},
            {"item_index": 5, "delete": True},
        ]
        ordered = _order_items_apply_entries(entries)
        assert [e["item_index"] for e in ordered] == [9, 5, 2]

    def test_mixed_batch_matches_spec_example(self):
        entries = [
            {"item_index": 12, "volume_db": -3.0, "fade_in": 0.05},
            {"item_index": 15, "mute": True},
            {"item_index": 20, "position": 8.5},
            {"item_index": 31, "delete": True},
        ]
        ordered = _order_items_apply_entries(entries)
        assert [e["item_index"] for e in ordered] == [12, 15, 20, 31]

    def test_delete_false_is_not_treated_as_delete(self):
        entries = [{"item_index": 3, "delete": False, "mute": True}]
        ordered = _order_items_apply_entries(entries)
        assert ordered == entries
