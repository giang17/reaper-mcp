"""Tests for project render-metadata payload validation (project_tools).

Pure logic only — no REAPER/IPC mocking, matching the pattern used by
tests/test_marker_tools.py for markers_apply.
"""

import pytest

from reaper_mcp.tools.project_tools import _build_metadata_payload
from reaper_mcp_shared.error_codes import ReaperMCPError


class TestBuildMetadataPayload:
    def test_keeps_non_empty_fields(self):
        out = _build_metadata_payload({
            "title": "Andante",
            "author": "Giang",
            "album": "",
            "comment": "",
        })
        assert out == {"title": "Andante", "author": "Giang"}

    def test_all_empty_raises(self):
        with pytest.raises(ReaperMCPError, match="at least one metadata field"):
            _build_metadata_payload({"title": "", "author": "", "album": ""})

    def test_no_fields_raises(self):
        with pytest.raises(ReaperMCPError, match="at least one metadata field"):
            _build_metadata_payload({})

    def test_coerces_int_to_str(self):
        # callers may pass numeric track numbers; they must be stringified
        out = _build_metadata_payload({"track_number": 5})
        assert out == {"track_number": "5"}

    def test_field_length_cap(self):
        too_long = "x" * 1025
        with pytest.raises(ReaperMCPError, match="track_number too long"):
            _build_metadata_payload({"track_number": too_long})

    def test_field_length_cap_boundary_ok(self):
        exactly_cap = "x" * 1024
        out = _build_metadata_payload({"title": exactly_cap})
        assert out == {"title": exactly_cap}

    def test_multibyte_field_measured_in_bytes(self):
        # 'é' is 2 bytes in UTF-8; 513 chars = 1026 bytes -> over the 1024 byte
        # cap, even though the char count (513) is well under a naive char limit.
        over_in_bytes = "é" * 513
        assert len(over_in_bytes.encode("utf-8")) == 1026
        assert len(over_in_bytes) == 513  # char count alone would pass
        with pytest.raises(ReaperMCPError, match="too long"):
            _build_metadata_payload({"comment": over_in_bytes})

    def test_only_some_fields_too_long(self):
        # a long field raises even when valid fields are also present
        with pytest.raises(ReaperMCPError, match="album too long"):
            _build_metadata_payload({
                "title": "ok",
                "album": "y" * 2000,
            })
