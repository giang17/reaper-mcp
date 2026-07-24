import asyncio
import json
import time

from mcp.server.fastmcp import FastMCP
from reaper_mcp_shared.error_codes import ReaperMCPError, ErrorCode

_MAX_WAIT_SECONDS = 30.0
_DEFAULT_POLL_INTERVAL = 0.2


def _parse_script_result(raw: str):
    if not raw:
        return None
    try:
        return json.loads(raw)
    except (json.JSONDecodeError, TypeError):
        return raw


def _validate_script_path(script_path: str) -> str:
    if not script_path or not isinstance(script_path, str):
        raise ReaperMCPError(ErrorCode.INVALID_PARAMETER, "script_path must be a non-empty string")
    normalized = script_path.replace("\\", "/")
    if normalized.startswith("/") or (len(normalized) >= 2 and normalized[1] == ":"):
        raise ReaperMCPError(ErrorCode.INVALID_PATH, "script_path must be relative to the Scripts folder")
    if any(part == ".." for part in normalized.split("/")):
        raise ReaperMCPError(ErrorCode.INVALID_PATH, "script_path must not contain '..'")
    return normalized


def _validate_wait_seconds(wait_seconds: float) -> None:
    if not (0 <= wait_seconds <= _MAX_WAIT_SECONDS):
        raise ReaperMCPError(
            ErrorCode.VALUE_OUT_OF_RANGE,
            f"wait_seconds must be between 0 and {_MAX_WAIT_SECONDS}",
        )


async def _poll_for_result(client, wait_seconds: float, poll_interval: float = _DEFAULT_POLL_INTERVAL):
    deadline = time.monotonic() + wait_seconds
    while True:
        raw_result = await client.execute("script_read_result")
        data = raw_result.get("data", raw_result) if isinstance(raw_result, dict) else {}
        raw_value = data.get("value", "") if isinstance(data, dict) else ""
        if raw_value:
            return _parse_script_result(raw_value), True
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            return None, False
        await asyncio.sleep(min(poll_interval, remaining))


def register(mcp: FastMCP):
    from reaper_mcp.main import client

    @mcp.tool()
    async def script_list(filter: str = "") -> dict:
        """List ReaScripts (.lua/.eel only) found in REAPER's own Scripts folder.

        Never scans anywhere else — this is hard-coded to REAPER's Scripts
        folder, not a caller-supplied path. Returns each script's path
        (relative to the Scripts folder — pass this straight to script_run)
        and description (parsed from an @description/@about header comment
        if present, empty string otherwise). Capped at 300 results; use
        filter (case-insensitive substring match against path + description)
        to narrow a larger install.

        Args:
            filter: Optional case-insensitive substring filter.
        """
        return await client.execute("script_list", filter=filter)

    @mcp.tool()
    async def script_run(script_path: str, wait_seconds: float = 5.0) -> dict:
        """Run a ReaScript from REAPER's own Scripts folder and optionally read back a result.

        script_path must be one of the relative paths script_list returned.
        Registers the script as a REAPER action if it isn't already (safe to
        call every time), runs it, then waits up to wait_seconds for the
        script to report a result via
        reaper.SetExtState("reaper_mcp_script_result", "last_result", <string>, false).
        Scripts that don't opt into this convention — including anything
        that hasn't finished running (e.g. a background/defer-based script)
        by the time wait_seconds elapses — come back with result_found: false.

        This runs arbitrary local script code. Confirm with the user before
        calling this unless they've already given clear, specific
        instruction to run this exact script.

        Args:
            script_path: Relative path from script_list, e.g. "MyScripts/foo.lua".
            wait_seconds: How long to wait for a result, 0-30. Default 5.0.
        """
        normalized = _validate_script_path(script_path)
        _validate_wait_seconds(wait_seconds)
        start_result = await client.execute("script_run_start", script_path=normalized)
        start_data = start_result.get("data", start_result)
        command_id = start_data.get("command_id")
        result, found = await _poll_for_result(client, wait_seconds)
        return {"command_id": command_id, "ran": True, "result": result, "result_found": found}
