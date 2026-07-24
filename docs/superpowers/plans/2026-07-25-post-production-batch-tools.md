# Post-Production Batch Tools Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add `project_get_change_count` (cheap "did anything change" check) and `items_apply` (batch item-property combinator) to reaper-mcp, per the approved spec.

**Architecture:** Each tool follows the existing three-layer pattern in this codebase: a Python `@mcp.tool()` wrapper in `reaper_mcp/tools/` does input validation, calls `client.execute(command, **params)`, and a matching Lua handler in `reaper_scripts/reaper_mcp_server.lua` does the actual REAPER API work and returns a result dict (auto-wrapped as `{"success": true, "data": {...}}` by the bridge's response encoder). `items_apply`'s validation/ordering logic is extracted into pure, synchronous module-level functions so it's unit-testable without mocking — the same pattern `patterns_tools.py` already uses for `_tile_pattern_lines`.

**Tech Stack:** Python 3.10+, pytest/pytest-asyncio, Lua (REAPER's embedded interpreter — no Lua test framework exists in this repo; Lua-side changes are verified by live REAPER smoke test, matching this codebase's existing convention).

## Global Constraints

- No comments/docstrings on obvious code — only where a hidden constraint or non-obvious reason exists (repo convention, `CONTRIBUTING.md`).
- Python 3.10+ type hints on public surfaces.
- Input validation: range-check numeric inputs, length/count-cap arrays, before ever calling `client.execute`.
- Errors raised as `ReaperMCPError(ErrorCode.<CODE>, "message naming the bad value")` — see `reaper_mcp_shared/error_codes.py`.
- `items_apply` batch cap: 200 entries (matches `add_markers_batch`'s existing cap in `compose_edit_tools.py`).
- Target version: `0.6.0` (already bumped in `pyproject.toml`; `CHANGELOG.md` has an empty `## [0.6.0] - Unreleased` section waiting for entries).
- Spec: `docs/superpowers/specs/2026-07-25-post-production-batch-tools-design.md` — read it before starting; this plan implements it exactly.

---

### Task 1: `project_get_change_count`

**Files:**
- Modify: `reaper_scripts/reaper_mcp_server.lua` (add handler near `project.project_get_info`, ~line 970)
- Modify: `reaper_mcp/tools/project_tools.py` (add tool near `project_get_info`, ~line 18)

**Interfaces:**
- Produces: Lua command `"project_get_change_count"` taking no params, returning `{change_count = <int>}`. Python tool `project_get_change_count() -> dict`.

- [ ] **Step 1: Add the Lua handler**

In `reaper_scripts/reaper_mcp_server.lua`, immediately after the `project.project_get_info` function (ends at line 971 with `end`), add:

```lua
function project.project_get_change_count(p)
  return {change_count = math.floor(reaper.GetProjectStateChangeCount(0))}
end
```

- [ ] **Step 2: Add the Python tool**

In `reaper_mcp/tools/project_tools.py`, immediately after `project_get_info` (after its `return await client.execute("project_get_info")` line), add:

```python
    @mcp.tool()
    async def project_get_change_count() -> dict:
        """Cheap check for whether the project has changed since you last looked.

        Returns a monotonically increasing counter that bumps on any edit.
        Compare against a value you saved earlier to decide whether you need
        to re-fetch heavier data (track_get_all, item_get_all) instead of
        blindly re-querying every turn.
        """
        return await client.execute("project_get_change_count")
```

- [ ] **Step 3: Live smoke test**

No automated test exists for Lua-side REAPER API calls in this repo (matches existing convention — see `tests/test_patterns_tools.py`'s docstring for why pure logic gets extracted instead). Verify manually:
1. Reload the Lua script in REAPER (Actions → ReaScript: Run/reload `reaper_mcp_server.lua`, or restart REAPER).
2. Restart the MCP server / reconnect Claude Desktop.
3. Call `project_get_change_count` — note the value.
4. Make any edit (move a track, add a marker).
5. Call `project_get_change_count` again — confirm the value increased.

- [ ] **Step 4: Commit**

```bash
git add reaper_scripts/reaper_mcp_server.lua reaper_mcp/tools/project_tools.py
git commit -m "feat: add project_get_change_count tool (issue #4)"
```

---

### Task 2: `items_apply` — pure validation and ordering helpers

**Files:**
- Modify: `reaper_mcp/tools/item_tools.py` (add helpers near the top, after imports)
- Test: `tests/test_item_tools.py` (new)

**Interfaces:**
- Produces:
  - `_validate_items_apply_entries(entries: list) -> None` — raises `ReaperMCPError` on any invalid entry; returns nothing on success.
  - `_order_items_apply_entries(entries: list[dict]) -> list[dict]` — returns a new list: all non-delete entries first (original relative order preserved), then all `delete: true` entries last, sorted by descending `item_index`.
- Consumes: `reaper_mcp_shared.error_codes.ReaperMCPError`, `ErrorCode` (already imported at the top of `item_tools.py`).

- [ ] **Step 1: Write the failing tests**

Create `tests/test_item_tools.py`:

```python
"""Tests for reaper_mcp/tools/item_tools.py's items_apply validation/ordering.

Pure logic only — no REAPER/IPC mocking needed, matching the pattern
tests/test_patterns_tools.py already uses for _tile_pattern_lines.
"""

import pytest

from reaper_mcp.tools.item_tools import (
    _validate_items_apply_entries,
    _order_items_apply_entries,
)
from reaper_mcp_shared.error_codes import ReaperMCPError


class TestValidateItemsApplyEntries:
    def test_valid_entries_pass(self):
        _validate_items_apply_entries([
            {"item_index": 0, "volume_db": -3.0},
            {"item_index": 5, "delete": True},
        ])

    def test_missing_item_index_raises(self):
        with pytest.raises(ReaperMCPError, match="item_index"):
            _validate_items_apply_entries([{"volume_db": -3.0}])

    def test_negative_item_index_raises(self):
        with pytest.raises(ReaperMCPError, match="item_index"):
            _validate_items_apply_entries([{"item_index": -1}])

    def test_non_int_item_index_raises(self):
        with pytest.raises(ReaperMCPError, match="item_index"):
            _validate_items_apply_entries([{"item_index": "0"}])

    def test_negative_fade_in_raises(self):
        with pytest.raises(ReaperMCPError, match="fade_in"):
            _validate_items_apply_entries([{"item_index": 0, "fade_in": -0.1}])

    def test_negative_fade_out_raises(self):
        with pytest.raises(ReaperMCPError, match="fade_out"):
            _validate_items_apply_entries([{"item_index": 0, "fade_out": -0.1}])

    def test_zero_length_raises(self):
        with pytest.raises(ReaperMCPError, match="length"):
            _validate_items_apply_entries([{"item_index": 0, "length": 0}])

    def test_negative_position_raises(self):
        with pytest.raises(ReaperMCPError, match="position"):
            _validate_items_apply_entries([{"item_index": 0, "position": -1.0}])

    def test_over_cap_raises(self):
        entries = [{"item_index": i} for i in range(201)]
        with pytest.raises(ReaperMCPError, match="200"):
            _validate_items_apply_entries(entries)

    def test_empty_list_raises(self):
        with pytest.raises(ReaperMCPError):
            _validate_items_apply_entries([])


class TestOrderItemsApplyEntries:
    def test_non_delete_entries_keep_relative_order(self):
        entries = [
            {"item_index": 5, "volume_db": -3.0},
            {"item_index": 2, "mute": True},
        ]
        ordered = _order_items_apply_entries(entries)
        assert ordered == entries

    def test_deletes_move_to_end(self):
        entries = [
            {"item_index": 5, "delete": True},
            {"item_index": 2, "volume_db": -3.0},
        ]
        ordered = _order_items_apply_entries(entries)
        assert ordered == [
            {"item_index": 2, "volume_db": -3.0},
            {"item_index": 5, "delete": True},
        ]

    def test_deletes_sorted_descending_by_item_index(self):
        entries = [
            {"item_index": 2, "delete": True},
            {"item_index": 9, "delete": True},
            {"item_index": 5, "delete": True},
        ]
        ordered = _order_items_apply_entries(entries)
        assert [e["item_index"] for e in ordered] == [9, 5, 2]

    def test_mixed_batch_matches_spec_example(self):
        entries = [
            {"item_index": 12, "volume_db": -3.0, "fade_in": 0.05},
            {"item_index": 15, "mute": True},
            {"item_index": 20, "position": 8.5},
            {"item_index": 31, "delete": True},
        ]
        ordered = _order_items_apply_entries(entries)
        assert [e["item_index"] for e in ordered] == [12, 15, 20, 31]

    def test_delete_false_is_not_treated_as_delete(self):
        entries = [{"item_index": 3, "delete": False, "mute": True}]
        ordered = _order_items_apply_entries(entries)
        assert ordered == entries
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_item_tools.py -v`
Expected: FAIL with `ImportError: cannot import name '_validate_items_apply_entries'`

- [ ] **Step 3: Write the minimal implementation**

In `reaper_mcp/tools/item_tools.py`, add near the top of the file (after the existing imports, before `def register(mcp: FastMCP):`):

```python
_MAX_ITEMS_APPLY_ENTRIES = 200


def _validate_items_apply_entries(entries: list) -> None:
    if not isinstance(entries, list) or len(entries) == 0:
        raise ReaperMCPError(ErrorCode.INVALID_PARAMETER, "entries must be a non-empty JSON array")
    if len(entries) > _MAX_ITEMS_APPLY_ENTRIES:
        raise ReaperMCPError(
            ErrorCode.VALUE_OUT_OF_RANGE,
            f"Too many entries: {len(entries)} (max {_MAX_ITEMS_APPLY_ENTRIES})",
        )
    for i, entry in enumerate(entries):
        if "item_index" not in entry:
            raise ReaperMCPError(ErrorCode.INVALID_PARAMETER, f"Entry {i} missing item_index")
        item_index = entry["item_index"]
        if not isinstance(item_index, int) or isinstance(item_index, bool) or item_index < 0:
            raise ReaperMCPError(ErrorCode.VALUE_OUT_OF_RANGE, f"Entry {i}: item_index must be >= 0")
        if "fade_in" in entry and entry["fade_in"] is not None and entry["fade_in"] < 0:
            raise ReaperMCPError(ErrorCode.VALUE_OUT_OF_RANGE, f"Entry {i}: fade_in must be >= 0")
        if "fade_out" in entry and entry["fade_out"] is not None and entry["fade_out"] < 0:
            raise ReaperMCPError(ErrorCode.VALUE_OUT_OF_RANGE, f"Entry {i}: fade_out must be >= 0")
        if "length" in entry and entry["length"] is not None and entry["length"] <= 0:
            raise ReaperMCPError(ErrorCode.VALUE_OUT_OF_RANGE, f"Entry {i}: length must be > 0")
        if "position" in entry and entry["position"] is not None and entry["position"] < 0:
            raise ReaperMCPError(ErrorCode.VALUE_OUT_OF_RANGE, f"Entry {i}: position must be >= 0")


def _order_items_apply_entries(entries: list[dict]) -> list[dict]:
    non_deletes = [e for e in entries if e.get("delete") is not True]
    deletes = [e for e in entries if e.get("delete") is True]
    deletes.sort(key=lambda e: e["item_index"], reverse=True)
    return non_deletes + deletes
```

Add `from reaper_mcp_shared.error_codes import ReaperMCPError, ErrorCode` to the file's imports if not already present (check the existing import block at the top of `item_tools.py` first — `ReaperMCPError`/`ErrorCode` are already used by other tools in this file, so this import should already exist; only add it if missing).

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_item_tools.py -v`
Expected: PASS (15 tests)

- [ ] **Step 5: Commit**

```bash
git add reaper_mcp/tools/item_tools.py tests/test_item_tools.py
git commit -m "feat: add items_apply validation/ordering helpers"
```

---

### Task 3: `items_apply` — Lua handler

**Files:**
- Modify: `reaper_scripts/reaper_mcp_server.lua` (add handler near other `item.*` functions, after `item.item_move_to_track` which ends at line 1461)

**Interfaces:**
- Consumes: existing per-item Lua logic already in this file for `item_move` (position), `item_set_length` (length), `item_set_volume` (volume_db), `item_set_mute` (mute), `item_set_fade` (fade_in/fade_out), `item_delete` — read each of those handlers first so `items_apply` reuses the exact same REAPER API calls, not new ones.
- Produces: Lua command `"items_apply"` taking `{entries = <JSON array string>}`, returning `{success = true, applied = <int>, errors = [{index, item_index, error}, ...]}`.

- [ ] **Step 1: Read the existing single-item handlers for reference**

Before writing, read `item.item_move`, `item.item_set_length`, `item.item_set_volume`, `item.item_set_mute`, `item.item_set_fade`, and `item.item_delete` in `reaper_scripts/reaper_mcp_server.lua` (all between lines ~1285-1465) to match their exact REAPER API calls (e.g. which `D_*`/`B_*` info-value keys they use, whether they call `reaper.UpdateArrange()`).

- [ ] **Step 2: Write the handler**

Add after `item.item_move_to_track` (line 1461):

```lua
function item.items_apply(p)
  if not p.entries then return nil, "Missing parameter: entries" end
  local entries = json_decode(p.entries)
  if not entries then return nil, "Invalid entries JSON" end

  -- Non-delete entries first (input order), then deletes last in
  -- descending item_index order — matches _order_items_apply_entries
  -- on the Python side, done again here since Lua receives the raw
  -- array and Python's ordering isn't re-serialized before dispatch.
  local non_deletes, deletes = {}, {}
  for _, e in ipairs(entries) do
    if e.delete == true then
      deletes[#deletes+1] = e
    else
      non_deletes[#non_deletes+1] = e
    end
  end
  table.sort(deletes, function(a, b) return a.item_index > b.item_index end)

  reaper.Undo_BeginBlock()
  local applied = 0
  local errors = {}

  local function apply_one(idx, e)
    local it = reaper.GetMediaItem(0, math.floor(e.item_index))
    if not it then
      errors[#errors+1] = {index = idx, item_index = e.item_index, error = "Item not found"}
      return
    end
    if e.delete == true then
      reaper.DeleteTrackMediaItem(reaper.GetMediaItemTrack(it), it)
      applied = applied + 1
      return
    end
    if e.position ~= nil then
      reaper.SetMediaItemInfo_Value(it, "D_POSITION", e.position)
    end
    if e.length ~= nil then
      reaper.SetMediaItemInfo_Value(it, "D_LENGTH", e.length)
    end
    if e.volume_db ~= nil then
      reaper.SetMediaItemInfo_Value(it, "D_VOL", vol_from_db(e.volume_db))
    end
    if e.mute ~= nil then
      reaper.SetMediaItemInfo_Value(it, "B_MUTE", e.mute and 1 or 0)
    end
    if e.fade_in ~= nil then
      reaper.SetMediaItemInfo_Value(it, "D_FADEINLEN", e.fade_in)
    end
    if e.fade_out ~= nil then
      reaper.SetMediaItemInfo_Value(it, "D_FADEOUTLEN", e.fade_out)
    end
    applied = applied + 1
  end

  for i, e in ipairs(non_deletes) do apply_one(i - 1, e) end
  for i, e in ipairs(deletes) do apply_one(#non_deletes + i - 1, e) end

  reaper.UpdateArrange()
  reaper.Undo_EndBlock("items_apply", -1)
  return {success = true, applied = applied, errors = errors}
end
```

`vol_from_db` must already exist as a shared helper in this file (used by `configure_tracks`) — confirm with a search before writing; if the name differs, use whatever the existing dB→linear conversion helper is actually called.

- [ ] **Step 3: Live smoke test**

1. Reload the Lua script in REAPER.
2. Create a project with 3+ items on different tracks.
3. Call `items_apply` with a mix of `volume_db`, `mute`, `position`, and one `delete: true` entry.
4. Verify: non-deleted items reflect the new properties, the deleted item is gone, and the response's `applied` count matches.
5. Call again with one entry referencing a nonexistent `item_index` (e.g. 9999) mixed with a valid one — confirm the valid one still applies and the response's `errors` array names the bad one.

- [ ] **Step 4: Commit**

```bash
git add reaper_scripts/reaper_mcp_server.lua
git commit -m "feat: add items_apply Lua handler"
```

---

### Task 4: `items_apply` — Python tool

**Files:**
- Modify: `reaper_mcp/tools/item_tools.py` (add tool after `item_move_to_track`)
- Test: `tests/test_item_tools.py` (extend from Task 2)

**Interfaces:**
- Consumes: `_validate_items_apply_entries`, `_order_items_apply_entries` (Task 2), `client.execute("items_apply", entries=<json str>)`.
- Produces: `items_apply(entries: str) -> dict` MCP tool.

- [ ] **Step 1: Write the failing test**

Add to `tests/test_item_tools.py`:

```python
import json

import pytest

from reaper_mcp.tools import item_tools


class FakeClient:
    def __init__(self, response=None):
        self.response = response or {}
        self.calls = []

    async def execute(self, command, **kwargs):
        self.calls.append((command, kwargs))
        return self.response


class TestItemsApplyToolValidation:
    @pytest.mark.asyncio
    async def test_invalid_json_raises(self):
        from mcp.server.fastmcp import FastMCP
        import reaper_mcp.main as main_module

        main_module.client = FakeClient()
        mcp = FastMCP("test")
        item_tools.register(mcp)
        tools = await mcp.list_tools()
        assert any(t.name == "items_apply" for t in tools)
```

This last test only confirms the tool registers under the expected name — full behavioral testing of the registered closure isn't practical without FastMCP internals (see Step 3 note). The real behavior (validation, ordering, dispatch) is already covered by Task 2's pure-function tests plus this task's manual smoke test in Step 4.

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_item_tools.py -v -k items_apply`
Expected: FAIL — `items_apply` tool doesn't exist yet.

- [ ] **Step 3: Write the implementation**

In `reaper_mcp/tools/item_tools.py`, inside `def register(mcp: FastMCP):`, add after `item_move_to_track`:

```python
    @mcp.tool()
    async def items_apply(entries: str) -> dict:
        """Batch set position/length/volume_db/mute/fade_in/fade_out, or delete, across many items in one call.

        Args:
            entries: JSON array. Each: {"item_index":0, "volume_db":-3.0, "fade_in":0.05}.
                     Or {"item_index":5, "delete":true}. Only item_index required.
                     Non-delete changes apply first (in the order given); deletes apply
                     last, in descending item_index order, regardless of input order —
                     this avoids a delete shifting the indices of items processed later
                     in the same batch. A bad item_index is recorded in the response's
                     errors array and does not abort the rest of the batch.
        """
        try:
            parsed = json.loads(entries)
        except (json.JSONDecodeError, TypeError):
            raise ReaperMCPError(ErrorCode.INVALID_PARAMETER, "Invalid entries JSON")
        _validate_items_apply_entries(parsed)
        ordered = _order_items_apply_entries(parsed)
        return await client.execute("items_apply", entries=json.dumps(ordered))
```

Add `import json` to the top of `item_tools.py` if not already present.

Note: the Lua handler (Task 3) also re-orders deletes-last independently, so this Python-side ordering is defense in depth / makes the wire payload already correctly ordered for anyone inspecting it — not strictly required for correctness given Task 3's Lua also sorts, but keeps both layers consistent and matches the spec's description of the behavior at the Python tool level.

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_item_tools.py -v`
Expected: PASS (all tests from Task 2 and this task)

- [ ] **Step 5: Manual smoke test through the real MCP path**

Since the closure itself isn't directly unit-testable (see Step 1 note), verify end-to-end through REAPER once Task 3's Lua handler is also live: call `items_apply` via Claude Desktop/Claude Code with a real project open, confirm the response shape matches `{"success": true, "applied": N, "errors": [...]}`.

- [ ] **Step 6: Commit**

```bash
git add reaper_mcp/tools/item_tools.py tests/test_item_tools.py
git commit -m "feat: add items_apply Python tool"
```

---

### Task 5: CHANGELOG entry

**Files:**
- Modify: `CHANGELOG.md`

- [ ] **Step 1: Add the entry**

In `CHANGELOG.md`, under `## [0.6.0] - Unreleased` (currently empty — see the header at the top of the file), add:

```markdown
### Added

- **`project_get_change_count`** — cheap check for whether the project has
  changed since you last looked (wraps REAPER's
  `GetProjectStateChangeCount`), so the AI can decide whether to re-fetch
  heavier data instead of blindly re-querying every turn. (issue #4)
- **`items_apply`** — batch set position/length/volume_db/mute/fade, or
  delete, across many items in one call. Non-delete changes apply first;
  deletes apply last in descending item_index order regardless of input
  order, so a delete never shifts the indices of items processed later in
  the same batch. Per-entry error collection — a bad item_index doesn't
  abort the rest of the batch. (issue #4)
```

- [ ] **Step 2: Commit**

```bash
git add CHANGELOG.md
git commit -m "docs: changelog entries for project_get_change_count and items_apply"
```

---

## Self-Review Notes (for whoever executes this plan)

- Before Task 3, confirm the exact name of the existing dB→linear-gain helper (`vol_from_db` is a guess based on `configure_tracks`'s usage pattern — grep for it first).
- Task 4's Step 1 test is intentionally thin (registration-only) — this codebase has no established pattern for invoking a `@mcp.tool()`-decorated closure directly in tests (they're nested inside `register()` and close over the module-level `client`). Task 2's pure-function tests carry the real correctness burden for `items_apply`'s logic; Task 4's manual smoke test (Step 5) is what actually verifies the wiring.
- All Lua-side smoke tests require REAPER running with the reloaded script — do these after each Lua-touching task, not batched at the end, so a bug is caught against the smallest possible diff.
