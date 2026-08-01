from mcp.server.fastmcp import FastMCP
from reaper_mcp_shared.error_codes import ReaperMCPError, ErrorCode
from reaper_mcp_shared.constants import ALLOWED_EXPORT_FORMATS
from reaper_mcp_shared.path_safety import safe_path as _safe_path

# Per-field byte cap for project render metadata. Tags are short descriptors;
# anything approaching 1 KB almost certainly means wrong data was piped in.
_METADATA_MAX_FIELD_BYTES = 1024


def _build_metadata_payload(fields: dict) -> dict:
    """Filter metadata fields down to non-empty values; raise if none remain.

    Pure logic, extracted from ``project_set_metadata`` so the "empty strings
    are ignored" / "at least one field required" / "per-field length cap"
    contract can be unit-tested without REAPER.

    Args:
        fields: mapping of logical field name (title, author, ...) to value.

    Returns:
        The subset of ``fields`` whose value is truthy, as strings.

    Raises:
        ReaperMCPError: if every field is empty, or any field exceeds the cap.
    """
    payload = {k: str(v) for k, v in fields.items() if v}
    if not payload:
        raise ReaperMCPError(
            ErrorCode.VALUE_OUT_OF_RANGE,
            "at least one metadata field must be non-empty",
        )
    for k, v in payload.items():
        if len(v.encode("utf-8")) > _METADATA_MAX_FIELD_BYTES:
            raise ReaperMCPError(
                ErrorCode.VALUE_OUT_OF_RANGE,
                f"{k} too long ({len(v)} chars) — cap is "
                f"{_METADATA_MAX_FIELD_BYTES} bytes per field",
            )
    return payload


def register(mcp: FastMCP):
    from reaper_mcp.main import client

    @mcp.tool()
    async def project_get_info() -> dict:
        """Get project info (name, BPM, time sig, tracks, length, markers, render settings).

        For post-production work, prefer project_get_overview() instead —
        one call for this plus the region list, change_count, and a
        selection summary, versus composing several calls yourself.

        `path` is the recording/media directory (exists even for a brand
        new, never-saved project). `file_path` is the actual .rpp project
        file's path — empty string if this project has never been saved.
        """
        return await client.execute("project_get_info")

    @mcp.tool()
    async def project_get_change_count() -> dict:
        """Cheap check for whether the project has changed since you last looked.

        Returns a monotonically increasing counter that bumps on any edit.
        Compare against a value you saved earlier to decide whether you need
        to re-fetch heavier data (track_get_all, item_get_all) instead of
        blindly re-querying every turn.
        """
        return await client.execute("project_get_change_count")

    @mcp.tool()
    async def project_get_overview() -> dict:
        """One cheap call for post-production awareness: counts, region list, change_count, and a selection summary.

        Bundles what project_get_info + marker_get_all + project_get_change_count +
        selection_get_time + selection_get_selected_tracks + selection_get_selected_items
        would otherwise take 6 separate calls to assemble. The selection summary
        returns indices and counts only (not full track/item detail) to stay
        genuinely lightweight — call selection_get_selected_tracks/items directly
        if you need full detail on what's currently selected.
        """
        return await client.execute("project_get_overview")

    @mcp.tool()
    async def project_new() -> dict:
        """Create a new empty REAPER project. Returns the new project info."""
        return await client.execute("project_new")

    @mcp.tool()
    async def project_open(path: str) -> dict:
        """Open .rpp project file.

        Args:
            path: Absolute path to .rpp file.
        """
        path = _safe_path(path)
        return await client.execute("project_open", path=path)

    @mcp.tool()
    async def project_save() -> dict:
        """Save the current project. Returns project info confirming the save."""
        return await client.execute("project_save")

    @mcp.tool()
    async def project_save_as(path: str) -> dict:
        """Save project to new path. This project's active file becomes
        `path` going forward — subsequent project_save calls target it,
        not the original file. Use project_backup instead if you want a
        snapshot copy without switching your active file.

        Args:
            path: Absolute .rpp path.
        """
        path = _safe_path(path)
        return await client.execute("project_save_as", path=path)

    @mcp.tool()
    async def project_backup(path: str) -> dict:
        """Save a snapshot copy to `path` WITHOUT changing this project's
        active file — unlike project_save_as, your next project_save still
        targets the original file. Use this before a risky/destructive
        change (wiping MIDI, deleting tracks, clean=True mix passes) to
        leave a recoverable copy of what existed beforehand.

        Args:
            path: Absolute .rpp path for the backup copy.
        """
        path = _safe_path(path)
        return await client.execute("project_backup", path=path)

    @mcp.tool()
    async def project_export_audio(path: str, format: str = "wav") -> dict:
        """Render project to audio file.

        Args:
            path: Output file path.
            format: wav, mp3, ogg, flac, or aiff.
        """
        fmt = format.lower()
        if fmt not in ALLOWED_EXPORT_FORMATS:
            raise ReaperMCPError(
                ErrorCode.INVALID_FORMAT,
                f"Format must be one of: {', '.join(sorted(ALLOWED_EXPORT_FORMATS))}",
            )
        path = _safe_path(path)
        return await client.execute_long("project_export_audio", path=path, format=fmt)

    @mcp.tool()
    async def project_undo() -> dict:
        """Undo last action."""
        return await client.execute("project_undo")

    @mcp.tool()
    async def project_redo() -> dict:
        """Redo last undone action."""
        return await client.execute("project_redo")

    @mcp.tool()
    async def project_get_notes() -> dict:
        """Get the project notes/description text."""
        return await client.execute("project_get_notes")

    @mcp.tool()
    async def project_set_notes(notes: str) -> dict:
        """Set the project notes/description text.

        Args:
            notes: The text to set as project notes (max 100 KB).
        """
        # 100 KB is plenty for notes; anything larger usually means wrong data got piped here.
        max_bytes = 100 * 1024
        if len(notes.encode("utf-8")) > max_bytes:
            raise ReaperMCPError(
                ErrorCode.VALUE_OUT_OF_RANGE,
                f"notes too long ({len(notes)} chars) — cap is 100 KB",
            )
        return await client.execute("project_set_notes", notes=notes)

    @mcp.tool()
    async def project_get_metadata() -> dict:
        """Get project render metadata (title, author, album, comment, etc.).

        These are the metadata fields REAPER embeds into rendered files
        (ID3/BWF/Vorbis/APE tags) and substitutes into render-filename
        templates ($title, $artist, ...). Reachable in the GUI via the
        Render dialog's Metadata section.

        Note: REAPER's API exposes WHICH fields are set (the tag list), but
        not their VALUES — values are write-only via GetSetProjectInfo_String
        (verified on REAPER 7.78). The returned `fields_set` maps each known
        logical field to true when any of its tags is present; `tags_present`
        gives the raw tag list (e.g. ["ID3:TIT2", "VORBIS:TITLE"]).
        """
        return await client.execute("project_get_metadata")

    @mcp.tool()
    async def project_set_metadata(
        title: str = "",
        author: str = "",
        album: str = "",
        comment: str = "",
        genre: str = "",
        year: str = "",
        track_number: str = "",
        composer: str = "",
        isrc: str = "",
        copyright: str = "",
    ) -> dict:
        """Set project render metadata fields. Non-empty fields are written.

        Each field is written to every tag format REAPER can embed on render
        (ID3 for mp3/wav-bwf, VORBIS for flac/ogg, APE for mpc/wv) so the
        value survives regardless of the render format chosen later. Empty
        strings are ignored and leave any existing value for that field
        untouched. Setting a field again overwrites its previous value.

        Args:
            title: Track / project title.
            author: Artist / author.
            album: Album name.
            comment: Free-form comment.
            genre: Genre.
            year: Year / date.
            track_number: Track number.
            composer: Composer.
            isrc: ISRC code.
            copyright: Copyright string.
        """
        payload = _build_metadata_payload({
            "title": title, "author": author, "album": album, "comment": comment,
            "genre": genre, "year": year, "track_number": track_number,
            "composer": composer, "isrc": isrc, "copyright": copyright,
        })
        return await client.execute("project_set_metadata", **payload)

    @mcp.tool()
    async def project_set_grid(grid_division: float) -> dict:
        """Set grid division (1.0=quarter, 0.5=eighth, 0.25=sixteenth).

        Args:
            grid_division: Grid size in quarter notes.
        """
        if grid_division <= 0:
            raise ReaperMCPError(ErrorCode.VALUE_OUT_OF_RANGE, "Grid division must be > 0")
        return await client.execute("project_set_grid", grid_division=grid_division)
