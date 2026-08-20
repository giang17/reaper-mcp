"""Tests for ReaperClient's heartbeat-staleness crash detection.

Pure logic against a real temp file's mtime — no REAPER/IPC needed.
"""

import os
import time

from reaper_mcp.reaper_client import ReaperClient
from reaper_mcp_shared.constants import Connection


class TestHeartbeatStale:
    def test_fresh_lock_file_not_stale(self, tmp_path, monkeypatch):
        lock_file = tmp_path / "server.lock"
        lock_file.write_text("1")
        monkeypatch.setattr(Connection, "LOCK_FILE", str(lock_file))

        client = ReaperClient.__new__(ReaperClient)  # skip __init__'s dir setup
        assert client._heartbeat_stale() is False

    def test_old_lock_file_is_stale(self, tmp_path, monkeypatch):
        lock_file = tmp_path / "server.lock"
        lock_file.write_text("1")
        old_time = time.time() - 120  # older than _HEARTBEAT_STALE_SECONDS (60)
        os.utime(lock_file, (old_time, old_time))
        monkeypatch.setattr(Connection, "LOCK_FILE", str(lock_file))

        client = ReaperClient.__new__(ReaperClient)
        assert client._heartbeat_stale() is True

    def test_missing_lock_file_is_not_reported_as_stale(self, tmp_path, monkeypatch):
        """A missing file is a different failure mode (server never started),
        handled separately by _check_server's existence check — staleness
        can't be determined without a file to read mtime from, so this must
        fail open (False) rather than claim staleness it can't confirm."""
        missing = tmp_path / "does-not-exist.lock"
        monkeypatch.setattr(Connection, "LOCK_FILE", str(missing))

        client = ReaperClient.__new__(ReaperClient)
        assert client._heartbeat_stale() is False

    def test_boundary_just_under_threshold_not_stale(self, tmp_path, monkeypatch):
        lock_file = tmp_path / "server.lock"
        lock_file.write_text("1")
        recent = time.time() - 30  # well under the 60s threshold
        os.utime(lock_file, (recent, recent))
        monkeypatch.setattr(Connection, "LOCK_FILE", str(lock_file))

        client = ReaperClient.__new__(ReaperClient)
        assert client._heartbeat_stale() is False
