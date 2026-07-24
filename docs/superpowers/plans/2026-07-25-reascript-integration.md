# ReaScript Integration Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Let the AI discover and run the user's own ReaScripts (Lua/EEL2) — scoped strictly to REAPER's own Scripts folder — and read back an optional result via a documented `ExtState` convention, per the approved spec.

**Architecture:** New self-contained tool module `reaper_mcp/tools/script_tools.py` (registered like every other module via `register(mcp)`, auto-discovered by `tool_registry.py`), backed by 3 new Lua handlers in a new `script` table in `reaper_scripts/reaper_mcp_server.lua`. Path-containment and result-parsing logic is pure Python, unit-tested directly; the multi-second "wait for a result" behavior is implemented as Python-side polling of a fast, non-blocking Lua read (never a blocking loop inside a Lua handler — REAPER's single-threaded `reaper.defer` loop would freeze the whole UI for the wait duration otherwise).

**Tech Stack:** Python 3.10+, pytest/pytest-asyncio, Lua (no Lua test framework in this repo — Lua changes are verified via live REAPER smoke test, matching existing convention).

## Global Constraints

- Discovery/execution confined to `reaper.GetResourcePath() .. "/Scripts"` — hard-coded, **never** an AI- or conversation-supplied path. This is the whole point of the design; do not add a parameter that overrides it.
- `.py` files excluded from discovery and execution entirely.
- `script_path` validated on both the Python side (string-level pre-check, no filesystem access needed) and the Lua side (authoritative — resolves against the real Scripts folder).
- No new dynamic-code-eval surface on our side — registration goes through REAPER's own `AddRemoveReaScript` API only.
- Errors raised as `ReaperMCPError(ErrorCode.<CODE>, "message")` — see `reaper_mcp_shared/error_codes.py`.
- Target version: `0.6.0`. `CHANGELOG.md` has an empty `## [0.6.0] - Unreleased` section.
- Spec: `docs/superpowers/specs/2026-07-25-reascript-integration-design.md` — read it before starting. This plan implements it, with one correction noted below (Task 4).
- **Do not reference any external contributor's name anywhere in code, comments, docs, or commit messages for this feature** — reference issue #4 by number only. (Explicit instruction from this session.)

---

### Task 1: New module skeleton + registry wiring

**Files:**
- Create: `reaper_mcp/tools/script_tools.py`
- Modify: `reaper_mcp/tool_registry.py`

**Interfaces:**
- Produces: `reaper_mcp.tools.script_tools.register(mcp: FastMCP) -> None` (empty body for now — a docstring-only placeholder tool is fine temporarily, or skip defining any `@mcp.tool()` yet and just define `register` as a no-op; either way `hasattr(module, "register")` must be `True`).

- [ ] **Step 1: Create the module skeleton**

Create `reaper_mcp/tools/script_tools.py`:

```python
from mcp.server.fastmcp import FastMCP
from reaper_mcp_shared.error_codes import ReaperMCPError, ErrorCode


def register(mcp: FastMCP):
    from reaper_mcp.main import client
```

- [ ] **Step 2: Register the module in `tool_registry.py`**

In `reaper_mcp/tool_registry.py`:
1. Add `"script_tools"` to `_EXPECTED_MODULES` (alphabetically, between `"quantize_tools"` and `"selection_tools"`).
2. Add `"script_tools"` to the `"composition"` profile's set (alongside `"loops_tools"`, `"chops_tools"`).

- [ ] **Step 3: Run the existing registry tests to verify the module is picked up**

Run: `pytest tests/test_tool_registry.py -v`
Expected: PASS — `test_every_registrable_module_is_expected` and `test_full_profile_registers_every_expected_module` confirm the new module is discovered and matches `_EXPECTED_MODULES`.

- [ ] **Step 4: Commit**

```bash
git add reaper_mcp/tools/script_tools.py reaper_mcp/tool_registry.py
git commit -m "feat: scaffold script_tools module (issue #4)"
```

---

### Task 2: `_validate_script_path` — pure path-containment pre-check

**Files:**
- Modify: `reaper_mcp/tools/script_tools.py`
- Test: `tests/test_script_tools.py` (new)

**Interfaces:**
- Produces: `_validate_script_path(script_path: str) -> str` — returns the normalized (forward-slash) relative path on success, raises `ReaperMCPError` on any traversal/absolute-path attempt.

- [ ] **Step 1: Write the failing tests**

Create `tests/test_script_tools.py`:

```python
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
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_script_tools.py -v`
Expected: FAIL with `ImportError: cannot import name '_validate_script_path'`

- [ ] **Step 3: Write the minimal implementation**

Add to `reaper_mcp/tools/script_tools.py`, after the imports:

```python
def _validate_script_path(script_path: str) -> str:
    if not script_path or not isinstance(script_path, str):
        raise ReaperMCPError(ErrorCode.INVALID_PARAMETER, "script_path must be a non-empty string")
    normalized = script_path.replace("\\", "/")
    if normalized.startswith("/") or (len(normalized) >= 2 and normalized[1] == ":"):
        raise ReaperMCPError(ErrorCode.INVALID_PATH, "script_path must be relative to the Scripts folder")
    if any(part == ".." for part in normalized.split("/")):
        raise ReaperMCPError(ErrorCode.INVALID_PATH, "script_path must not contain '..'")
    return normalized
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_script_tools.py -v`
Expected: PASS (10 tests)

- [ ] **Step 5: Commit**

```bash
git add reaper_mcp/tools/script_tools.py tests/test_script_tools.py
git commit -m "feat: add script_path containment pre-check"
```

---

### Task 3: `_parse_script_result` — pure result-parsing helper

**Files:**
- Modify: `reaper_mcp/tools/script_tools.py`
- Test: `tests/test_script_tools.py`

**Interfaces:**
- Produces: `_parse_script_result(raw: str) -> object | None` — `None` for empty/falsy input, parsed JSON if `raw` is valid JSON, otherwise the raw string unchanged.

- [ ] **Step 1: Write the failing tests**

Add to `tests/test_script_tools.py`:

```python
from reaper_mcp.tools.script_tools import _parse_script_result


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
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_script_tools.py -v -k ParseScriptResult`
Expected: FAIL with `ImportError`.

- [ ] **Step 3: Write the minimal implementation**

Add to `reaper_mcp/tools/script_tools.py`:

```python
import json


def _parse_script_result(raw: str):
    if not raw:
        return None
    try:
        return json.loads(raw)
    except (json.JSONDecodeError, TypeError):
        return raw
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_script_tools.py -v`
Expected: PASS (15 tests total)

- [ ] **Step 5: Commit**

```bash
git add reaper_mcp/tools/script_tools.py tests/test_script_tools.py
git commit -m "feat: add script result JSON-or-raw-string parsing"
```

---

### Task 4: Lua handler — `script_list`

**Files:**
- Modify: `reaper_scripts/reaper_mcp_server.lua`

**Correction from spec:** the spec's `script_list` output included a `registered` boolean per script. REAPER's only relevant API, `reaper.AddRemoveReaScript(add, sectionID, scriptfn, commit)`, has side effects in both directions — `add=true` registers, `add=false` *de-registers* — there is no side-effect-free "is this already registered" query. Checking registration status during discovery would mean either registering every script just by listing them (defeats the point of discovery being read-only) or risking de-registering the user's existing actions. **`registered` is dropped from the output.** Update the spec file to match once this task is done (Step 4 below).

**Interfaces:**
- Produces: Lua command `"script_list"` taking `{filter = "<string, may be empty>"}`, returning `{success = true, scripts = [{path, description}, ...], count = <int>}`, capped at 300 results.

- [ ] **Step 1: Add the `script` table and helpers**

In `reaper_scripts/reaper_mcp_server.lua`, add a new `local script = {}` table after `local tempo = {}` (line 3989) and before the handlers-registration loop (line 4254). Also add the scan helpers near the top of that new section:

```lua
local script = {}

local function reascript_ext_ok(name)
  local ext = name:match("%.([%a%d]+)$")
  if not ext then return false end
  ext = ext:lower()
  return ext == "lua" or ext == "eel"
end

local function parse_script_header(full_path)
  local f = io.open(full_path, "r")
  if not f then return "" end
  local description, about = "", ""
  local line_count = 0
  for line in f:lines() do
    line_count = line_count + 1
    if line_count > 20 then break end
    local d = line:match("@description%s+(.+)")
    if d then description = d end
    local a = line:match("@about%s*(.*)")
    if a and a ~= "" and about == "" then about = a end
  end
  f:close()
  if description ~= "" then return description end
  return about
end

local function scan_scripts_dir(base, rel, filter, results, max_results)
  if #results >= max_results then return end
  local i = 0
  while true do
    local fname = reaper.EnumerateFiles(base, i)
    if not fname then break end
    if reascript_ext_ok(fname) then
      local rel_path = (rel == "" and fname or (rel .. "/" .. fname))
      local full_path = base .. "/" .. fname
      local description = parse_script_header(full_path)
      if filter == "" or rel_path:lower():find(filter, 1, true) or description:lower():find(filter, 1, true) then
        results[#results+1] = {path = rel_path, description = description}
        if #results >= max_results then return end
      end
    end
    i = i + 1
  end
  local j = 0
  while true do
    local subdir = reaper.EnumerateSubdirectories(base, j)
    if not subdir then break end
    local rel_sub = (rel == "" and subdir or (rel .. "/" .. subdir))
    scan_scripts_dir(base .. "/" .. subdir, rel_sub, filter, results, max_results)
    if #results >= max_results then return end
    j = j + 1
  end
end

function script.script_list(p)
  local filter = (p.filter or ""):lower()
  local scripts_root = reaper.GetResourcePath() .. "/Scripts"
  local results = {}
  scan_scripts_dir(scripts_root, "", filter, results, 300)
  return {success = true, scripts = results, count = #results}
end
```

- [ ] **Step 2: Wire it into the handlers loop**

Add `for k, v in pairs(script) do handlers[k] = v end` to the loop starting at line 4254, alongside the other `for k, v in pairs(...)` lines.

- [ ] **Step 3: Live smoke test**

1. Reload the Lua script in REAPER.
2. Confirm you have at least one `.lua` file somewhere under REAPER's Scripts folder (check via Actions → Show action list → ReaScript path, or just place a trivial test script there).
3. Call `script_list` with no filter — confirm your test script appears with the right relative `path`.
4. If your test script has a `--@description ...` header comment, confirm it's captured.
5. Call `script_list` with a `filter` that matches only a subset — confirm filtering works.
6. Place a `.py` file in the same folder — confirm it does NOT appear in results.

- [ ] **Step 4: Update the spec to match the correction**

In `docs/superpowers/specs/2026-07-25-reascript-integration-design.md`, find the `script_list` section and remove `registered (bool...)` from the documented return shape, replacing it with a note matching the correction described at the top of this task.

- [ ] **Step 5: Commit**

```bash
git add reaper_scripts/reaper_mcp_server.lua docs/superpowers/specs/2026-07-25-reascript-integration-design.md
git commit -m "feat: add script_list Lua handler (scan REAPER Scripts folder)"
```

---

### Task 5: Lua handlers — `script_run_start` and `script_read_result`

**Files:**
- Modify: `reaper_scripts/reaper_mcp_server.lua`

**Interfaces:**
- Produces:
  - Lua command `"script_run_start"` taking `{script_path = "<relative path>"}`, returning `{success = true, command_id = <int>}`.
  - Lua command `"script_read_result"` taking no params, returning `{value = "<string, possibly empty>"}`.

- [ ] **Step 1: Add a Lua-side containment helper and both handlers**

Add to the `script` table section (after `script.script_list`):

```lua
local function safe_script_path(script_path)
  local normalized = script_path:gsub("\\", "/")
  if normalized:sub(1, 1) == "/" then return nil, "script_path must be relative" end
  if normalized:match("^%a:") then return nil, "script_path must be relative" end
  for part in normalized:gmatch("[^/]+") do
    if part == ".." then return nil, "script_path must not contain '..'" end
  end
  return normalized
end

function script.script_run_start(p)
  if not p.script_path then return nil, "Missing parameter: script_path" end
  local normalized, err = safe_script_path(p.script_path)
  if not normalized then return nil, err end

  local scripts_root = reaper.GetResourcePath() .. "/Scripts"
  local full_path = scripts_root .. "/" .. normalized

  local f = io.open(full_path, "r")
  if not f then return nil, "Script file not found: " .. normalized end
  f:close()

  reaper.SetExtState("reaper_mcp_script_result", "last_result", "", false)

  local cmd_id = reaper.AddRemoveReaScript(true, 0, full_path, true)
  if not cmd_id or cmd_id == 0 then
    return nil, "Failed to register script: " .. normalized
  end
  reaper.Main_OnCommand(cmd_id, 0)
  return {success = true, command_id = cmd_id}
end

function script.script_read_result(p)
  local value = reaper.GetExtState("reaper_mcp_script_result", "last_result")
  return {value = value or ""}
end
```

Both functions land in `handlers` automatically via the `for k, v in pairs(script) do handlers[k] = v end` line added in Task 4, Step 2 — no further wiring needed.

- [ ] **Step 2: Live smoke test**

1. Reload the Lua script in REAPER.
2. Write a trivial test script into the Scripts folder, e.g. `test_result.lua`:
   ```lua
   reaper.SetExtState("reaper_mcp_script_result", "last_result", '{"hello":"world"}', false)
   ```
3. Call `script_run_start` with `script_path = "test_result.lua"`. Confirm you get back a `command_id`.
4. Call `script_read_result` immediately after — confirm `value` is `'{"hello":"world"}'`.
5. Call `script_run_start` again with a path containing `../` (e.g. `"../../../whatever.lua"`) — confirm it's rejected with an error, not executed.
6. Call `script_run_start` with a path that doesn't exist — confirm a clear "Script file not found" error, not a crash.

- [ ] **Step 3: Commit**

```bash
git add reaper_scripts/reaper_mcp_server.lua
git commit -m "feat: add script_run_start and script_read_result Lua handlers"
```

---

### Task 6: Python tool — `script_list`

**Files:**
- Modify: `reaper_mcp/tools/script_tools.py`

**Interfaces:**
- Produces: `script_list(filter: str = "") -> dict` MCP tool.

- [ ] **Step 1: Write the tool**

Inside `register(mcp)` in `reaper_mcp/tools/script_tools.py`, add:

```python
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
```

- [ ] **Step 2: Manual smoke test through the real MCP path**

No automated test — this is a thin pass-through with no branching logic to unit test (the real logic lives in the already-smoke-tested Lua handler from Task 4). Once Task 4's Lua handler is live, call `script_list` via Claude Desktop/Claude Code and confirm the response matches what the raw Lua smoke test in Task 4 showed.

- [ ] **Step 3: Commit**

```bash
git add reaper_mcp/tools/script_tools.py
git commit -m "feat: add script_list Python tool"
```

---

### Task 7: Python tool — `script_run` (validation + polling orchestration)

**Files:**
- Modify: `reaper_mcp/tools/script_tools.py`
- Test: `tests/test_script_tools.py`

**Interfaces:**
- Consumes: `_validate_script_path` (Task 2), `_parse_script_result` (Task 3).
- Produces:
  - `_validate_wait_seconds(wait_seconds: float) -> None` — raises on out-of-bounds.
  - `_poll_for_result(client, wait_seconds: float, poll_interval: float = 0.2) -> tuple[object | None, bool]` — polls `client.execute("script_read_result")` until a non-empty value appears or `wait_seconds` elapses; returns `(parsed_result, found)`.
  - `script_run(script_path: str, wait_seconds: float = 5.0) -> dict` MCP tool.

- [ ] **Step 1: Write the failing tests for `_validate_wait_seconds` and `_poll_for_result`**

Add to `tests/test_script_tools.py`:

```python
import pytest

from reaper_mcp.tools.script_tools import _validate_wait_seconds, _poll_for_result
from reaper_mcp_shared.error_codes import ReaperMCPError


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
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_script_tools.py -v -k "WaitSeconds or PollForResult"`
Expected: FAIL with `ImportError`.

- [ ] **Step 3: Write the minimal implementation**

Add to `reaper_mcp/tools/script_tools.py`:

```python
import asyncio
import time

_MAX_WAIT_SECONDS = 30.0
_DEFAULT_POLL_INTERVAL = 0.2


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
```

Then, inside `register(mcp)`, add the tool after `script_list`:

```python
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
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_script_tools.py -v`
Expected: PASS (24 tests total)

- [ ] **Step 5: Manual smoke test through the real MCP path**

With Task 5's Lua handlers live, call `script_run` via Claude Desktop/Claude Code against the `test_result.lua` script from Task 5's smoke test. Confirm the response is `{"command_id": <id>, "ran": true, "result": {"hello": "world"}, "result_found": true}`.

- [ ] **Step 6: Commit**

```bash
git add reaper_mcp/tools/script_tools.py tests/test_script_tools.py
git commit -m "feat: add script_run Python tool with polling-based result capture"
```

---

### Task 8: Docs — `00_core.md` guidance, `CONTRIBUTING.md`, `CHANGELOG.md`

**Files:**
- Modify: `reaper_mcp/instructions/00_core.md`
- Modify: `CONTRIBUTING.md`
- Modify: `CHANGELOG.md`

- [ ] **Step 1: Extend the destructive-action confirmation guidance**

In `reaper_mcp/instructions/00_core.md`, the existing "Working on an existing project" section (lines 1-21) lists specific destructive/hard-to-reverse actions that require confirming with the user first (wiping MIDI, deleting tracks/items, `clean=True` mix passes). Add `script_run` to that list, since its blast radius can't be known ahead of time — it runs arbitrary user script code. Change the sentence at lines 6-11 from:

```markdown
Most sessions are on a project that already has real work in it, not a
blank one. Before doing anything **destructive or hard-to-reverse** on a
project that already has content — wiping MIDI, deleting tracks/items, or
an `engine_mix`/`engine_master` pass with `clean=True` (which removes
existing mix FX before applying new ones) — **describe what you're about
to do and wait for the user to confirm**, unless they've already given
clear, specific instruction to do exactly that action.
```

to:

```markdown
Most sessions are on a project that already has real work in it, not a
blank one. Before doing anything **destructive or hard-to-reverse** on a
project that already has content — wiping MIDI, deleting tracks/items, an
`engine_mix`/`engine_master` pass with `clean=True` (which removes
existing mix FX before applying new ones), or running a script via
`script_run` (its effect can't be known ahead of time — it executes
whatever the script does) — **describe what you're about to do and wait
for the user to confirm**, unless they've already given clear, specific
instruction to do exactly that action.
```

- [ ] **Step 2: Add a brief mention to `CONTRIBUTING.md`**

`CONTRIBUTING.md` already has an "## External generation pipelines" section from this session's earlier CONTRIBUTING.md addition. Add a short new section after it (before "## Code style"):

```markdown
## Running local ReaScripts

`script_tools.py` gives the AI a path to executing the user's own local
scripts — a materially bigger capability than everything else in this
tool surface, which only calls fixed, audited REAPER API functions
through our own handlers. If you extend this feature, keep the trust
boundary intact: discovery and execution stay hard-coded to REAPER's own
Scripts folder (`reaper.GetResourcePath() .. "/Scripts"`), never an
AI- or conversation-supplied path. Don't add a parameter that overrides
this.
```

- [ ] **Step 3: Add the CHANGELOG entry**

In `CHANGELOG.md`, under `## [0.6.0] - Unreleased`, add (or extend the `### Added` section from the other plan's Task 5 if it already exists):

```markdown
- **ReaScript integration** — `script_list` discovers `.lua`/`.eel`
  scripts in REAPER's own Scripts folder (never an AI-supplied path);
  `script_run` registers and runs one, optionally waiting up to 30s for a
  result the script reports via a documented `ExtState` convention.
  Lets the AI trigger scripts users have already written, instead of
  reimplementing that logic as new MCP tools one at a time. (issue #4)
```

- [ ] **Step 4: Run the full test suite**

Run: `pytest tests/ -x -q`
Expected: PASS, all tests including the new `tests/test_script_tools.py` and `tests/test_item_tools.py` (from the other plan, if already merged) and every pre-existing test.

- [ ] **Step 5: Final end-to-end smoke test**

With everything live: ask the AI (via Claude Desktop/Claude Code) to list your ReaScripts and run one that reports a result — confirm the whole path works exactly as a real user would experience it, not just via the piecemeal smoke tests from earlier tasks.

- [ ] **Step 6: Commit**

```bash
git add reaper_mcp/instructions/00_core.md CONTRIBUTING.md CHANGELOG.md
git commit -m "docs: ReaScript integration guidance and changelog entry"
```

---

## Self-Review Notes (for whoever executes this plan)

- **Spec coverage:** every component in the spec (`script_list`, `script_run`, the result convention, the trust boundary, security notes) has a task above. The one deviation (`registered` field dropped) is corrected in both the plan (Task 4) and the spec file itself (Task 4, Step 4) — don't let them drift.
- **No external names:** double-check before committing that no commit message, code comment, or doc edit in this feature references anyone by username — issue #4 by number only, per this session's explicit instruction.
- **Task ordering matters:** Tasks 4-5 (Lua) must be live in REAPER before Tasks 6-7's manual smoke-test steps can actually be verified — if executing with fresh subagents per task, make sure whoever runs Task 6/7 has a way to reload the Lua script first, or defer those smoke-test steps to Task 8's final end-to-end pass.
- **Type consistency:** `_poll_for_result` returns `(result, found)` — a 2-tuple — consistently in Task 7's tests and in `script_run`'s usage. `_validate_script_path` returns the normalized string (not a bool) — `script_run` uses that return value directly as `normalized`, not the raw `script_path` argument.
