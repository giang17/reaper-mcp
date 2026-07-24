"""Tests for reaper_mcp/tools/script_tools.py.

Path-containment and result-parsing are pure functions, tested directly
without mocking — the actual filesystem scan and script execution happen
in Lua (reaper_scripts/reaper_mcp_server.lua) and have no automated test
in this repo (no Lua test framework exists here); those are verified by
live REAPER smoke test instead, per this codebase's existing convention.
"""

import pytest

from reaper_mcp.tools.script_tools import (
    _validate_script_path,
    _parse_script_result,
    _validate_wait_seconds,
    _poll_for_result,
)
from reaper_mcp_shared.error_codes import ReaperMCPError


class TestValidateScriptPath:
    def test_simple_relative_path_passes(self):
        assert _validate_script_path("myscript.lua") == "myscript.lua"

    def test_nested_relative_path_passes(self):
        assert _validate_script_path("ReaTeam Scripts/foo.lua") == "ReaTeam Scripts/foo.lua"

    def test_backslashes_normalized_to_forward_slashes(self):
        assert _validate_script_path("sub\\foo.lua") == "sub/foo.lua"

    def test_empty_string_raises(self):
        with pytest.raises(ReaperMCPError):
            _validate_script_path("")

    def test_none_raises(self):
        with pytest.raises(ReaperMCPError):
            _validate_script_path(None)

    def test_leading_slash_raises(self):
        with pytest.raises(ReaperMCPError):
            _validate_script_path("/etc/passwd")

    def test_windows_drive_letter_raises(self):
        with pytest.raises(ReaperMCPError):
            _validate_script_path("C:/Windows/System32/evil.lua")

    def test_dotdot_traversal_raises(self):
        with pytest.raises(ReaperMCPError):
            _validate_script_path("../../../etc/passwd")

    def test_dotdot_in_middle_raises(self):
        with pytest.raises(ReaperMCPError):
            _validate_script_path("sub/../../escape.lua")

    def test_dotdot_disguised_with_backslash_raises(self):
        with pytest.raises(ReaperMCPError):
            _validate_script_path("sub\\..\\..\\escape.lua")


class TestParseScriptResult:
    def test_empty_string_returns_none(self):
        assert _parse_script_result("") is None

    def test_valid_json_object_parsed(self):
        assert _parse_script_result('{"ok": true, "count": 3}') == {"ok": True, "count": 3}

    def test_valid_json_number_parsed(self):
        assert _parse_script_result("42") == 42

    def test_non_json_string_returned_raw(self):
        assert _parse_script_result("done!") == "done!"

    def test_malformed_json_returned_raw(self):
        assert _parse_script_result('{"unterminated": ') == '{"unterminated": '


class TestValidateWaitSeconds:
    def test_zero_is_valid(self):
        _validate_wait_seconds(0)

    def test_typical_value_is_valid(self):
        _validate_wait_seconds(5.0)

    def test_max_boundary_is_valid(self):
        _validate_wait_seconds(30.0)

    def test_negative_raises(self):
        with pytest.raises(ReaperMCPError):
            _validate_wait_seconds(-1.0)

    def test_over_max_raises(self):
        with pytest.raises(ReaperMCPError):
            _validate_wait_seconds(30.1)


class FakeResultClient:
    """Returns one value from `values` per call to execute(); the last
    value repeats once the sequence is exhausted (simulates 'still no
    result yet' followed eventually by a real one, or a permanent timeout
    if every value is empty)."""

    def __init__(self, values):
        self.values = list(values)
        self.calls = 0

    async def execute(self, command, **kwargs):
        self.calls += 1
        idx = min(self.calls - 1, len(self.values) - 1)
        return {"success": True, "data": {"value": self.values[idx]}}


class TestPollForResult:
    @pytest.mark.asyncio
    async def test_returns_immediately_when_result_present_on_first_read(self):
        client = FakeResultClient(['{"ok": true}'])
        result, found = await _poll_for_result(client, wait_seconds=1.0, poll_interval=0.01)
        assert found is True
        assert result == {"ok": True}
        assert client.calls == 1

    @pytest.mark.asyncio
    async def test_finds_result_after_a_few_empty_reads(self):
        client = FakeResultClient(["", "", "done"])
        result, found = await _poll_for_result(client, wait_seconds=1.0, poll_interval=0.01)
        assert found is True
        assert result == "done"
        assert client.calls == 3

    @pytest.mark.asyncio
    async def test_times_out_with_no_result(self):
        client = FakeResultClient([""])
        result, found = await _poll_for_result(client, wait_seconds=0.03, poll_interval=0.01)
        assert found is False
        assert result is None

    @pytest.mark.asyncio
    async def test_wait_seconds_zero_still_tries_once(self):
        client = FakeResultClient(['{"fast": true}'])
        result, found = await _poll_for_result(client, wait_seconds=0.0, poll_interval=0.01)
        assert found is True
        assert result == {"fast": True}
