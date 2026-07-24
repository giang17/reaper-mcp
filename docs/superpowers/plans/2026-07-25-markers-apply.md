# `markers_apply` Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add `markers_apply` — batch marker/region edit and delete — to reaper-mcp, per the approved spec (issue #4, item 2's remaining half).

**Architecture:** Exact structural mirror of `items_apply` (already shipped, live-verified this session): pure validation/ordering helpers in `reaper_mcp/tools/marker_tools.py`, a thin `@mcp.tool()` wrapper, and a Lua handler in `reaper_scripts/reaper_mcp_server.lua` that applies non-delete entries first (input order) then deletes last (descending index order) to avoid index-shift bugs, with per-entry error collection instead of fail-fast.

**Tech Stack:** Python 3.10+, pytest/pytest-asyncio, Lua (no automated Lua test framework in this repo — verified by live REAPER smoke test).

## Global Constraints

- Mirror `items_apply`'s shape exactly: one JSON entry per object, whichever fields are present get applied, `delete: true` deletes.
- Batch cap: 200 entries (matches `items_apply`/`add_markers_batch`).
- Reuse existing helpers — do not duplicate color validation (`_validate_color_array` in `compose_edit_tools.py`) or the color-parsing Lua helper (`native_color_from_array`).
- `start`/`end` only apply to a region; `position` only to a point marker. The Lua handler checks the marker's actual `is_region` (from `EnumProjectMarkers3`), not a caller-supplied flag — a mismatched field is silently ignored, not an error.
- Target version: `0.6.0`. `CHANGELOG.md`'s `## [0.6.0] - Unreleased` section already has 4 `### Added` entries from this session's other issue-#4 work — this adds a 5th.
- Spec: `docs/superpowers/specs/2026-07-25-markers-apply-design.md` — read it before starting.

---

### Task 1: `markers_apply` — pure validation and ordering helpers

**Files:**
- Modify: `reaper_mcp/tools/marker_tools.py` (add helpers after `_validate_color`, before `def register`)
- Test: `tests/test_marker_tools.py` (new)

**Interfaces:**
- Produces:
  - `_validate_markers_apply_entries(entries: list) -> None` — raises `ReaperMCPError` on any invalid entry.
  - `_order_markers_apply_entries(entries: list[dict]) -> list[dict]` — non-delete entries first (original order), then `delete: true` entries last, sorted by descending `marker_index`.

- [ ] **Step 1: Write the failing tests**

Create `tests/test_marker_tools.py`:

```python
"""Tests for reaper_mcp/tools/marker_tools.py's markers_apply validation/ordering.

Pure logic only — no REAPER/IPC mocking needed, matching the pattern
tests/test_item_tools.py already uses for items_apply.
"""

import pytest

from reaper_mcp.tools.marker_tools import (
    _validate_markers_apply_entries,
    _order_markers_apply_entries,
)
from reaper_mcp_shared.error_codes import ReaperMCPError


class TestValidateMarkersApplyEntries:
    def test_valid_entries_pass(self):
        _validate_markers_apply_entries([
            {"marker_index": 0, "name": "Line 1"},
            {"marker_index": 5, "delete": True},
        ])

    def test_missing_marker_index_raises(self):
        with pytest.raises(ReaperMCPError, match="marker_index"):
            _validate_markers_apply_entries([{"name": "x"}])

    def test_negative_marker_index_raises(self):
        with pytest.raises(ReaperMCPError, match="marker_index"):
            _validate_markers_apply_entries([{"marker_index": -1}])

    def test_non_int_marker_index_raises(self):
        with pytest.raises(ReaperMCPError, match="marker_index"):
            _validate_markers_apply_entries([{"marker_index": "0"}])

    def test_negative_position_raises(self):
        with pytest.raises(ReaperMCPError, match="position"):
            _validate_markers_apply_entries([{"marker_index": 0, "position": -1.0}])

    def test_negative_start_raises(self):
        with pytest.raises(ReaperMCPError, match="start"):
            _validate_markers_apply_entries([{"marker_index": 0, "start": -1.0, "end": 5.0}])

    def test_end_not_greater_than_start_raises(self):
        with pytest.raises(ReaperMCPError, match="end"):
            _validate_markers_apply_entries([{"marker_index": 0, "start": 5.0, "end": 5.0}])

    def test_start_without_end_is_fine(self):
        # A caller might only want to move a region's start — end is optional.
        _validate_markers_apply_entries([{"marker_index": 0, "start": 5.0}])

    def test_invalid_color_raises(self):
        with pytest.raises(ReaperMCPError):
            _validate_markers_apply_entries([{"marker_index": 0, "color": [999, 0, 0]}])

    def test_name_too_long_raises(self):
        with pytest.raises(ReaperMCPError, match="Name"):
            _validate_markers_apply_entries([{"marker_index": 0, "name": "x" * 2000}])

    def test_over_cap_raises(self):
        entries = [{"marker_index": i} for i in range(201)]
        with pytest.raises(ReaperMCPError, match="200"):
            _validate_markers_apply_entries(entries)

    def test_empty_list_raises(self):
        with pytest.raises(ReaperMCPError):
            _validate_markers_apply_entries([])


class TestOrderMarkersApplyEntries:
    def test_non_delete_entries_keep_relative_order(self):
        entries = [
            {"marker_index": 5, "name": "a"},
            {"marker_index": 2, "name": "b"},
        ]
        ordered = _order_markers_apply_entries(entries)
        assert ordered == entries

    def test_deletes_move_to_end_sorted_descending(self):
        entries = [
            {"marker_index": 2, "delete": True},
            {"marker_index": 9, "delete": True},
            {"marker_index": 5, "name": "keep"},
        ]
        ordered = _order_markers_apply_entries(entries)
        assert ordered == [
            {"marker_index": 5, "name": "keep"},
            {"marker_index": 9, "delete": True},
            {"marker_index": 2, "delete": True},
        ]

    def test_delete_false_is_not_treated_as_delete(self):
        entries = [{"marker_index": 3, "delete": False, "name": "x"}]
        ordered = _order_markers_apply_entries(entries)
        assert ordered == entries
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_marker_tools.py -v`
Expected: FAIL with `ImportError: cannot import name '_validate_markers_apply_entries'`

- [ ] **Step 3: Write the minimal implementation**

In `reaper_mcp/tools/marker_tools.py`, add an import and the two helpers. First, add this import at the top (alongside the existing ones):

```python
from reaper_mcp.tools.compose_edit_tools import _validate_color_array
```

Then add, after `_validate_color` and before `def register(mcp: FastMCP):`:

```python
_MAX_MARKERS_APPLY_ENTRIES = 200


def _validate_markers_apply_entries(entries: list) -> None:
    if not isinstance(entries, list) or len(entries) == 0:
        raise ReaperMCPError(ErrorCode.INVALID_PARAMETER, "entries must be a non-empty JSON array")
    if len(entries) > _MAX_MARKERS_APPLY_ENTRIES:
        raise ReaperMCPError(
            ErrorCode.VALUE_OUT_OF_RANGE,
            f"Too many entries: {len(entries)} (max {_MAX_MARKERS_APPLY_ENTRIES})",
        )
    for i, entry in enumerate(entries):
        if "marker_index" not in entry:
            raise ReaperMCPError(ErrorCode.INVALID_PARAMETER, f"Entry {i} missing marker_index")
        marker_index = entry["marker_index"]
        if not isinstance(marker_index, int) or isinstance(marker_index, bool) or marker_index < 0:
            raise ReaperMCPError(ErrorCode.VALUE_OUT_OF_RANGE, f"Entry {i}: marker_index must be >= 0")
        if entry.get("position") is not None and entry["position"] < 0:
            raise ReaperMCPError(ErrorCode.VALUE_OUT_OF_RANGE, f"Entry {i}: position must be >= 0")
        if entry.get("start") is not None and entry["start"] < 0:
            raise ReaperMCPError(ErrorCode.VALUE_OUT_OF_RANGE, f"Entry {i}: start must be >= 0")
        if entry.get("start") is not None and entry.get("end") is not None and entry["end"] <= entry["start"]:
            raise ReaperMCPError(ErrorCode.VALUE_OUT_OF_RANGE, f"Entry {i}: end must be greater than start")
        if entry.get("color") is not None:
            _validate_color_array(entry["color"], f"Entry {i}")
        if entry.get("name") is not None and len(entry["name"]) > MAX_LABEL_LENGTH:
            raise ReaperMCPError(ErrorCode.VALUE_OUT_OF_RANGE, f"Entry {i}: Name too long (max {MAX_LABEL_LENGTH})")


def _order_markers_apply_entries(entries: list[dict]) -> list[dict]:
    non_deletes = [e for e in entries if e.get("delete") is not True]
    deletes = [e for e in entries if e.get("delete") is True]
    deletes.sort(key=lambda e: e["marker_index"], reverse=True)
    return non_deletes + deletes
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_marker_tools.py -v`
Expected: PASS (16 tests)

- [ ] **Step 5: Commit**

```bash
git add reaper_mcp/tools/marker_tools.py tests/test_marker_tools.py
git commit -m "feat: add markers_apply validation/ordering helpers (issue #4)"
```

---

### Task 2: `markers_apply` — Lua handler

**Files:**
- Modify: `reaper_scripts/reaper_mcp_server.lua` (add handler after `marker.marker_go_to`, ~line 2043)

**Interfaces:**
- Consumes: `native_color_from_array` (existing, line ~423), `json_decode` (existing).
- Produces: Lua command `"markers_apply"` taking `{entries = <JSON array string>}`, returning `{success = true, applied = <int>, errors = [{index, marker_index, error}, ...]}`.

- [ ] **Step 1: Read `marker.marker_edit` and `marker.marker_delete` for reference**

Read both in `reaper_scripts/reaper_mcp_server.lua` (~lines 2021-2037) before writing — `markers_apply` reuses the exact same `EnumProjectMarkers3`/`SetProjectMarkerByIndex2`/`DeleteProjectMarkerByIndex` calls those use, just looped and extended to handle `end` and `color`.

- [ ] **Step 2: Write the handler**

Add after `marker.marker_go_to` (after its closing `end`, before the `-- SELECTION handlers` comment block):

```lua
function marker.markers_apply(p)
  if not p.entries then return nil, "Missing parameter: entries" end
  local entries = json_decode(p.entries)
  if not entries then return nil, "Invalid entries JSON" end

  -- Non-delete entries first (input order), then deletes last in
  -- descending marker_index order — matches _order_markers_apply_entries
  -- on the Python side, done again here since Lua receives the raw
  -- array and must be correct on its own regardless of input order.
  local non_deletes, deletes = {}, {}
  for _, e in ipairs(entries) do
    if e.delete == true then
      deletes[#deletes+1] = e
    else
      non_deletes[#non_deletes+1] = e
    end
  end
  table.sort(deletes, function(a, b) return a.marker_index > b.marker_index end)

  reaper.Undo_BeginBlock()
  local applied = 0
  local errors = {}

  local function apply_one(idx, e)
    local mi = math.floor(e.marker_index)
    local count = reaper.CountProjectMarkers(0)
    if mi < 0 or mi >= count then
      errors[#errors+1] = {index = idx, marker_index = e.marker_index, error = "Marker not found"}
      return
    end
    if e.delete == true then
      reaper.DeleteProjectMarkerByIndex(0, mi)
      applied = applied + 1
      return
    end
    local _, isrgn, pos, rgnend, name, num, color = reaper.EnumProjectMarkers3(0, mi)
    if e.name ~= nil then name = e.name end
    if isrgn then
      if e.start ~= nil then pos = e.start end
      if e["end"] ~= nil then rgnend = e["end"] end
    else
      if e.position ~= nil then pos = e.position end
    end
    if e.color ~= nil then
      local c, err = native_color_from_array(e.color)
      if not c then
        errors[#errors+1] = {index = idx, marker_index = e.marker_index, error = err}
        return
      end
      color = c
    end
    reaper.SetProjectMarkerByIndex2(0, mi, isrgn, pos, rgnend, num, name, color, 0)
    applied = applied + 1
  end

  for i, e in ipairs(non_deletes) do apply_one(i - 1, e) end
  for i, e in ipairs(deletes) do apply_one(#non_deletes + i - 1, e) end

  reaper.UpdateArrange()
  reaper.Undo_EndBlock("markers_apply", -1)
  return {success = true, applied = applied, errors = errors}
end
```

- [ ] **Step 3: Live smoke test**

1. Reload the Lua script in REAPER, restart the MCP server/session so the new Python tool (Task 3) is also live.
2. Create a project with at least 2 point markers and 1 region (or use `add_markers_batch`).
3. Call `markers_apply` with: a rename on one marker, a `start`/`end` move on the region, a `color` change on another, and a `delete: true` on one entry.
4. Verify via `marker_get_all` that every change landed correctly and the deleted one is gone.
5. Call again with one entry referencing a nonexistent `marker_index` mixed with a valid one — confirm the valid one still applies and the response's `errors` array names the bad one.

- [ ] **Step 4: Commit**

```bash
git add reaper_scripts/reaper_mcp_server.lua
git commit -m "feat: add markers_apply Lua handler (issue #4)"
```

---

### Task 3: `markers_apply` — Python tool

**Files:**
- Modify: `reaper_mcp/tools/marker_tools.py` (add tool after `marker_go_to`)

**Interfaces:**
- Consumes: `_validate_markers_apply_entries`, `_order_markers_apply_entries` (Task 1), `client.execute("markers_apply", entries=<json str>)`.
- Produces: `markers_apply(entries: str) -> dict` MCP tool.

- [ ] **Step 1: Write the tool**

In `reaper_mcp/tools/marker_tools.py`, add `import json` to the top of the file if not already present, then add inside `register(mcp)`, after `marker_go_to`:

```python
    @mcp.tool()
    async def markers_apply(entries: str) -> dict:
        """Batch edit (name/position/start/end/color) or delete markers and regions in one call.

        Args:
            entries: JSON array. Each: {"marker_index":0, "name":"Line 12"}.
                     Region bounds: {"marker_index":5, "start":10.0, "end":14.5}.
                     Point marker position: {"marker_index":2, "position":8.0}.
                     Color: {"marker_index":7, "color":[200,90,60]} (0-255 each).
                     Delete: {"marker_index":9, "delete":true}. Only marker_index required.
                     start/end only apply to regions, position only to point markers — a
                     mismatched field (e.g. start/end on a point marker) is silently
                     ignored, not an error. Non-delete changes apply first (in the order
                     given); deletes apply last, in descending marker_index order,
                     regardless of input order — this avoids a delete shifting the
                     indices of markers processed later in the same batch. A bad
                     marker_index is recorded in the response's errors array and does
                     not abort the rest of the batch.
        """
        try:
            parsed = json.loads(entries)
        except (json.JSONDecodeError, TypeError):
            raise ReaperMCPError(ErrorCode.INVALID_PARAMETER, "Invalid entries JSON")
        _validate_markers_apply_entries(parsed)
        ordered = _order_markers_apply_entries(parsed)
        return await client.execute("markers_apply", entries=json.dumps(ordered))
```

- [ ] **Step 2: Run the full test suite**

Run: `pytest tests/ -x -q`
Expected: PASS, all tests including `tests/test_marker_tools.py` and every pre-existing test.

- [ ] **Step 3: Manual smoke test through the real MCP path**

With Task 2's Lua handler live, call `markers_apply` via Claude Desktop/Claude Code against a real project. Confirm the response shape matches `{"success": true, "applied": N, "errors": [...]}` and that `marker_get_all` reflects the changes afterward.

- [ ] **Step 4: Commit**

```bash
git add reaper_mcp/tools/marker_tools.py
git commit -m "feat: add markers_apply Python tool (issue #4)"
```

---

### Task 4: CHANGELOG entry

**Files:**
- Modify: `CHANGELOG.md`

- [ ] **Step 1: Add the entry**

Under `## [0.6.0] - Unreleased`'s existing `### Added` section (already has 4 entries from this session's other issue-#4 work), add:

```markdown
- **`markers_apply`** — batch edit (name/position/start/end/color) or
  delete markers and regions in one call, closing the other half of
  issue #4's batch-combinator request (`items_apply` covered media
  items; this covers markers/regions — creation was already batched via
  `add_markers_batch`, only edit/delete were still one-at-a-time). Also
  extends marker editing to support a region's `end` and `color`, which
  the existing single-marker `marker_edit` never supported. Non-delete
  changes apply first; deletes apply last in descending marker_index
  order regardless of input order, so a delete never shifts the indices
  of markers processed later in the same batch. Per-entry error
  collection — a bad marker_index doesn't abort the rest of the batch.
  (issue #4)
```

- [ ] **Step 2: Run the full test suite one more time**

Run: `pytest tests/ -x -q`
Expected: PASS.

- [ ] **Step 3: Commit**

```bash
git add CHANGELOG.md
git commit -m "docs: changelog entry for markers_apply (issue #4)"
```

---

## Self-Review Notes (for whoever executes this plan)

- **Spec coverage:** shape (mirrors `items_apply`), `start`/`end`/`position`-mismatch handling (silently ignored, not errored), color reuse (`_validate_color_array` Python-side, `native_color_from_array` Lua-side), execution order, per-entry error collection, CHANGELOG — all covered above.
- **Cross-module import:** Task 1 imports `_validate_color_array` from `reaper_mcp.tools.compose_edit_tools` into `marker_tools.py`. This is a deliberate reuse, not a new pattern to invent — if it turns out `compose_edit_tools.py` imports anything from `marker_tools.py` (creating a circular import), check that before assuming this works; as of this plan being written, `compose_edit_tools.py` has no such reverse dependency.
- **Type consistency:** `_validate_markers_apply_entries` returns `None` (raises on error) and `_order_markers_apply_entries` returns `list[dict]` — same signatures as `item_tools.py`'s equivalents, used the same way in `markers_apply`.
- **Lua's `end` field:** Lua's `end` is a reserved keyword — the existing codebase already handles this by using bracket-string indexing (`p["end"]`, `entry["end"]`), never `p.end`. Task 2's code follows this (`e["end"]`) — don't "simplify" it to `e.end`, that's a syntax error in Lua.
