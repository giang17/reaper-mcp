from mcp.server.fastmcp import FastMCP
from reaper_mcp_shared.error_codes import ReaperMCPError, ErrorCode


def _validate_script_path(script_path: str) -> str:
    if not script_path or not isinstance(script_path, str):
        raise ReaperMCPError(ErrorCode.INVALID_PARAMETER, "script_path must be a non-empty string")
    normalized = script_path.replace("\\", "/")
    if normalized.startswith("/") or (len(normalized) >= 2 and normalized[1] == ":"):
        raise ReaperMCPError(ErrorCode.INVALID_PATH, "script_path must be relative to the Scripts folder")
    if any(part == ".." for part in normalized.split("/")):
        raise ReaperMCPError(ErrorCode.INVALID_PATH, "script_path must not contain '..'")
    return normalized


def register(mcp: FastMCP):
    from reaper_mcp.main import client
