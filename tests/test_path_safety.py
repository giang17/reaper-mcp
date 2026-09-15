"""Tests for reaper_mcp_shared/path_safety.py.

Covers the existing safe_path guard (previously untested) plus the
sandbox-escape fix from a hardening pass: safe_path only validates the
top-level path a caller supplies, once. A symlink/junction placed anywhere
inside an otherwise-legitimate, already-validated folder can silently
redirect a recursive walk to a completely different location on disk -
verified live against real loops_tools code before this fix landed (a
junction inside an allowed folder made both an os.walk and a pathlib
rglob walk return files from a totally separate, never-validated
directory). prune_unsafe_subdirs closes that by re-validating every
directory a walk is about to descend into, not just the one requested.
"""

import os

import pytest

from reaper_mcp_shared.error_codes import ReaperMCPError
from reaper_mcp_shared.path_safety import (
    is_excluded_dir_name,
    is_excluded_file_name,
    prune_unsafe_subdirs,
    safe_path,
)


class TestSafePath:
    def test_rejects_empty_path(self):
        with pytest.raises(ReaperMCPError):
            safe_path("")

    @pytest.mark.skipif(os.name != "nt", reason="uses the Windows blocklist to prove traversal resolution")
    def test_traversal_into_blocked_dir_is_caught_via_resolution(self):
        # The literal ".." check is dead code (normpath/realpath already
        # collapse it) - traversal is actually caught because the
        # blocklist check runs against the fully-resolved canonical path.
        # Must stay on the same drive as SYSTEMROOT for this to resolve
        # onto the real blocked directory.
        sysroot = os.environ.get("SYSTEMROOT", r"C:\Windows")
        drive = os.path.splitdrive(sysroot)[0]
        traversal_path = drive + r"\Users\Public\..\..\Windows\System32"
        with pytest.raises(ReaperMCPError):
            safe_path(traversal_path)

    def test_rejects_relative_path(self):
        with pytest.raises(ReaperMCPError):
            safe_path("some/relative/path")

    def test_allows_normal_absolute_path(self, tmp_path):
        result = safe_path(str(tmp_path))
        assert os.path.isabs(result)

    @pytest.mark.skipif(os.name != "nt", reason="Windows-specific blocklist")
    def test_blocks_windows_system_root(self):
        with pytest.raises(ReaperMCPError):
            safe_path(r"C:\Windows\System32")

    @pytest.mark.skipif(os.name != "nt", reason="Windows-specific blocklist")
    def test_blocks_program_files(self):
        with pytest.raises(ReaperMCPError):
            safe_path(r"C:\Program Files")

    @pytest.mark.skipif(os.name != "nt", reason="8.3 short-name aliasing is Windows-only")
    def test_short_name_alias_cannot_bypass_blocklist(self):
        # C:\PROGRA~1 is the legacy 8.3 alias for "C:\Program Files" -
        # confirmed live that realpath resolves it before the blocklist
        # check runs, so this can't be used to sneak past the guard.
        with pytest.raises(ReaperMCPError):
            safe_path(r"C:\PROGRA~1")

    @pytest.mark.skipif(os.name == "nt", reason="POSIX-specific blocklist")
    def test_blocks_etc(self):
        with pytest.raises(ReaperMCPError):
            safe_path("/etc")


class TestIsExcludedDirName:
    @pytest.mark.parametrize("name", [".ssh", ".git", ".gnupg", ".aws", ".SSH", ".GIT"])
    def test_known_secrets_adjacent_names_excluded(self, name):
        assert is_excluded_dir_name(name) is True

    @pytest.mark.parametrize("name", ["Footsteps", "Drums", "my_ssh_notes", "gitignore"])
    def test_unrelated_names_not_excluded(self, name):
        assert is_excluded_dir_name(name) is False


class TestIsExcludedFileName:
    @pytest.mark.parametrize("name", [".env", ".ENV", "id_rsa", "known_hosts", ".netrc"])
    def test_known_secret_files_excluded(self, name):
        assert is_excluded_file_name(name) is True

    @pytest.mark.parametrize("name", ["Kick_140bpm.wav", "environment.wav", "id_rsa.wav"])
    def test_unrelated_and_audio_files_not_excluded(self, name):
        # id_rsa.wav (an audio file that merely contains the substring) is
        # NOT excluded - this checks exact basenames, not substrings, so a
        # legitimately-named audio file isn't accidentally dropped.
        assert is_excluded_file_name(name) is False


class TestPruneUnsafeSubdirs:
    def test_removes_excluded_dir_names(self, tmp_path):
        (tmp_path / "Drums").mkdir()
        (tmp_path / ".ssh").mkdir()
        dirnames = ["Drums", ".ssh"]
        prune_unsafe_subdirs(dirnames, str(tmp_path), str(tmp_path))
        assert dirnames == ["Drums"]

    def test_keeps_subdirs_that_resolve_within_root(self, tmp_path):
        (tmp_path / "a" / "b").mkdir(parents=True)
        dirnames = ["a"]
        prune_unsafe_subdirs(dirnames, str(tmp_path), str(tmp_path))
        assert dirnames == ["a"]

    def test_removes_subdir_whose_realpath_escapes_root(self, tmp_path, monkeypatch):
        # Simulates a symlink/junction without needing real filesystem
        # symlink privileges (Windows CI may not have Developer Mode /
        # admin rights) - deterministic across all three OSes this
        # project tests on.
        escape_target = str(tmp_path.parent / "outside_root")
        (tmp_path / "sneaky").mkdir()

        real_realpath = os.path.realpath

        def fake_realpath(p):
            if os.path.basename(p) == "sneaky":
                return escape_target
            return real_realpath(p)

        monkeypatch.setattr(os.path, "realpath", fake_realpath)
        dirnames = ["sneaky"]
        prune_unsafe_subdirs(dirnames, str(tmp_path), str(tmp_path))
        assert dirnames == []

    def test_root_itself_is_kept_not_treated_as_escaping(self, tmp_path):
        # A directory that resolves to exactly root_realpath (not a
        # sub-path of it) must not be pruned - the equality branch.
        dirnames = ["."]
        prune_unsafe_subdirs(dirnames, str(tmp_path), str(tmp_path))
        assert dirnames == ["."]


@pytest.mark.skipif(os.name == "nt", reason="unprivileged symlinks are unreliable on Windows CI")
class TestRealSymlinkEscape:
    """One real-filesystem confirmation on platforms where creating a
    symlink doesn't need elevated privileges, in addition to the
    monkeypatched unit test above.
    """

    def test_symlinked_subdir_pruned(self, tmp_path):
        allowed = tmp_path / "allowed"
        allowed.mkdir()
        secret = tmp_path / "secret"
        secret.mkdir()
        (secret / "leaked.wav").write_bytes(b"")
        (allowed / "legit.wav").write_bytes(b"")
        os.symlink(secret, allowed / "sneaky_link", target_is_directory=True)

        from reaper_mcp.tools.loops_tools import _iter_audio_files

        found = [p.name for p in _iter_audio_files(allowed, recursive=True)]
        assert found == ["legit.wav"]
