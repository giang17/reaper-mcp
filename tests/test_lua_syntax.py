"""Syntax-check reaper_mcp_server.lua on every CI run.

Added after a real incident: an edit to this file introduced a stray `#`
where a `--` comment continuation was meant, which is a Lua syntax
error - not caught by any existing test, since every other test in this
suite checks the Lua source as *text* (substring assertions) rather than
actually parsing it. A syntax error in this file would have gone
completely unnoticed until someone tried to run it inside REAPER.

Uses lupa (a Python binding to Lua) purely to *compile* the source - this
never executes any `reaper.*` call, so it works with no REAPER connection
and needs no REAPER-specific stubs.
"""

from pathlib import Path

import pytest

lupa = pytest.importorskip("lupa")

LUA_SRC = (
    Path(__file__).resolve().parent.parent
    / "reaper_scripts"
    / "reaper_mcp_server.lua"
)


def test_reaper_mcp_server_lua_compiles():
    runtime = lupa.LuaRuntime()
    source = LUA_SRC.read_text(encoding="utf-8")
    try:
        runtime.compile(source)
    except Exception as e:  # lupa raises a Lua syntax error, not a Python one
        pytest.fail(f"reaper_mcp_server.lua has a syntax error: {e}")
