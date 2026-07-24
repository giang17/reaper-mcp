"""Tests for reaper_mcp/tools/script_tools.py.

Path-containment and result-parsing are pure functions, tested directly
without mocking — the actual filesystem scan and script execution happen
in Lua (reaper_scripts/reaper_mcp_server.lua) and have no automated test
in this repo (no Lua test framework exists here); those are verified by
live REAPER smoke test instead, per this codebase's existing convention.
"""

import pytest

from reaper_mcp.tools.script_tools import _validate_script_path
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
