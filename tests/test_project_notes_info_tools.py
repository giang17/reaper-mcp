"""Tests for the Project Settings -> Notes tab Title/Author payload.

project_set_notes_info reuses _build_metadata_payload (the same pure helper
project_set_metadata uses) to enforce its "empty strings are ignored / at
least one field required / per-field length cap" contract. These tests fix
that contract for the Notes-tab field set {title, author}.

Pure logic only — no REAPER/IPC mocking, matching test_project_metadata_tools.py.
"""

import pytest

from reaper_mcp.tools.project_tools import _build_metadata_payload
from reaper_mcp_shared.error_codes import ReaperMCPError


class TestNotesInfoPayload:
    def test_keeps_both_fields(self):
        out = _build_metadata_payload({"title": "Andante D-Moll", "author": "glm-5.2"})
        assert out == {"title": "Andante D-Moll", "author": "glm-5.2"}

    def test_keeps_only_title(self):
        out = _build_metadata_payload({"title": "Andante", "author": ""})
        assert out == {"title": "Andante"}

    def test_keeps_only_author(self):
        out = _build_metadata_payload({"title": "", "author": "glm-5.2"})
        assert out == {"author": "glm-5.2"}

    def test_both_empty_raises(self):
        with pytest.raises(ReaperMCPError, match="at least one metadata field"):
            _build_metadata_payload({"title": "", "author": ""})

    def test_title_length_cap(self):
        with pytest.raises(ReaperMCPError, match="title too long"):
            _build_metadata_payload({"title": "x" * 1025, "author": ""})

    def test_author_length_cap(self):
        with pytest.raises(ReaperMCPError, match="author too long"):
            _build_metadata_payload({"title": "", "author": "y" * 2000})

    def test_coerces_int_author(self):
        # a numeric author (unlikely but possible) must stringify, not crash
        out = _build_metadata_payload({"title": "", "author": 2026})
        assert out == {"author": "2026"}

    def test_multibyte_title_measured_in_bytes(self):
        # 'ü' is 2 bytes in UTF-8; 513 chars = 1026 bytes -> over the byte cap
        over = "ü" * 513
        assert len(over.encode("utf-8")) == 1026
        with pytest.raises(ReaperMCPError, match="too long"):
            _build_metadata_payload({"title": over, "author": ""})
