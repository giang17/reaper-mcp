# `project_get_overview` Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add `project_get_overview()` to reaper-mcp — a single cheap call bundling track/item/marker counts, the region list, change_count, and a lightweight selection summary, closing the gap found in issue #4 item 1.

**Architecture:** One new Lua handler that reuses the exact same REAPER API calls `project_get_info`, `marker_get_all`, `project_get_change_count`, `selection_get_time`, `selection_get_selected_tracks`, and `selection_get_selected_items` already use — consolidated into one response, with the selection portion returning indices/counts only (not full track/item detail objects) to stay genuinely lightweight. One thin Python wrapper, no parameters.

**Tech Stack:** Lua (REAPER bridge), Python 3.10+ (MCP tool layer). No new pure-logic validation exists to unit test (no parameters) — verified via live REAPER smoke test, matching this codebase's established convention for Lua-only-logic additions.

## Global Constraints

- Purely additive — do not change any existing tool's return shape.
- Selection summary returns `selected_track_indices`/`selected_item_indices` (plain index lists) and counts only — never full `build_track_info`/`build_item_info` objects, to keep this call cheap regardless of how much is selected.
- `regions` filtered to `is_region == true` only (point markers excluded) — matches the issue's literal "region list" wording.
- Target version: `0.6.0`. `CHANGELOG.md`'s `## [0.6.0]` section already has multiple entries from this session's other issue-#4 work.
- Spec: `docs/superpowers/specs/2026-07-25-project-get-overview-design.md` — read it before starting.

---

### Task 1: `project_get_overview` — Lua handler + Python tool

**Files:**
- Modify: `reaper_scripts/reaper_mcp_server.lua` (add handler after `project.project_get_change_count`, ~line 976)
- Modify: `reaper_mcp/tools/project_tools.py` (add tool after `project_get_change_count`, ~line 30)

**Interfaces:**
- Produces: Lua command `"project_get_overview"` taking no params, returning:
  ```json
  {
    "name": "...", "track_count": 0, "item_count": 0, "marker_count": 0,
    "regions": [{"index": 0, "number": 1, "name": "...", "start": 0.0, "end": 8.0}],
    "change_count": 0,
    "selection": {
      "selected_track_count": 0, "selected_track_indices": [],
      "selected_item_count": 0, "selected_item_indices": [],
      "time_selection": {"start": 0.0, "end": 0.0, "length": 0.0}
    }
  }
  ```
  Python tool: `project_get_overview() -> dict`.

- [ ] **Step 1: Read the handlers being consolidated, for reference**

Before writing, read these in `reaper_scripts/reaper_mcp_server.lua` so the new handler matches their exact REAPER API usage:
- `project.project_get_info` (~line 952) — track_count/item_count/marker_count/name
- `marker.marker_get_all` (~line 1992) — the `EnumProjectMarkers3` loop and its return fields
- `project.project_get_change_count` (~line 973) — `GetProjectStateChangeCount`
- `selection.selection_get_selected_tracks` (~line 2153) — the selected-track loop and `IP_TRACKNUMBER` index lookup
- `selection.selection_get_selected_items` (~line 2164) — the selected-item loop and the global-index lookup
- `selection.selection_get_time` (~line 2121) — `GetSet_LoopTimeRange`

- [ ] **Step 2: Write the Lua handler**

Add immediately after `project.project_get_change_count` (after its closing `end`, before `project.project_new`):

```lua
function project.project_get_overview(p)
  local _, name = reaper.GetProjectName(0, "")
  local track_count = reaper.CountTracks(0)
  local item_count = reaper.CountMediaItems(0)
  local marker_count = reaper.CountProjectMarkers(0)

  local regions = {}
  for i = 0, marker_count - 1 do
    local _, isrgn, pos, rgnend, rname, num = reaper.EnumProjectMarkers3(0, i)
    if isrgn then
      regions[#regions+1] = {
        index = i, number = num, name = rname, start = pos, ["end"] = rgnend,
      }
    end
  end

  local sel_track_count = reaper.CountSelectedTracks(0)
  local selected_track_indices = {}
  for i = 0, sel_track_count - 1 do
    local tr = reaper.GetSelectedTrack(0, i)
    selected_track_indices[#selected_track_indices+1] =
      math.floor(reaper.GetMediaTrackInfo_Value(tr, "IP_TRACKNUMBER") - 1)
  end

  local sel_item_count = reaper.CountSelectedMediaItems(0)
  local selected_item_indices = {}
  for i = 0, sel_item_count - 1 do
    local it = reaper.GetSelectedMediaItem(0, i)
    for gi = 0, item_count - 1 do
      if reaper.GetMediaItem(0, gi) == it then
        selected_item_indices[#selected_item_indices+1] = gi
        break
      end
    end
  end

  local t_start, t_end = reaper.GetSet_LoopTimeRange(false, false, 0, 0, false)

  return {
    name = name,
    track_count = track_count,
    item_count = item_count,
    marker_count = marker_count,
    regions = regions,
    change_count = math.floor(reaper.GetProjectStateChangeCount(0)),
    selection = {
      selected_track_count = sel_track_count,
      selected_track_indices = selected_track_indices,
      selected_item_count = sel_item_count,
      selected_item_indices = selected_item_indices,
      time_selection = {start = t_start, ["end"] = t_end, length = t_end - t_start},
    },
  }
end
```

- [ ] **Step 3: Write the Python tool**

In `reaper_mcp/tools/project_tools.py`, add immediately after `project_get_change_count` (after its `return await client.execute("project_get_change_count")` line):

```python
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
```

- [ ] **Step 4: Verify register() still loads cleanly**

Run: `python -c "from mcp.server.fastmcp import FastMCP; import reaper_mcp.tools.project_tools as pt; mcp = FastMCP('test'); pt.register(mcp); print('OK')"`
Expected: `OK` with no errors.

- [ ] **Step 5: Run the full test suite**

Run: `pytest tests/ -x -q`
Expected: PASS — no existing tests reference `project_get_overview`, so this just confirms nothing else broke.

- [ ] **Step 6: Live smoke test**

1. Reload the Lua script in REAPER, restart the MCP server/session so the new tool is live.
2. In a project with at least 2 tracks, 2 items, and 1 region: select 1 track and 1 item, set a time selection.
3. Call `project_get_overview()`. Confirm:
   - `track_count`/`item_count`/`marker_count` match what `project_get_info()` reports separately.
   - `regions` contains the region (and does NOT contain any point markers, if you also have one).
   - `change_count` matches what `project_get_change_count()` reports separately.
   - `selection.selected_track_indices`/`selected_item_indices` match what `selection_get_selected_tracks()`/`selection_get_selected_items()` report (just compare the indices — the overview won't have the full detail those return).
   - `selection.time_selection` matches what `selection_get_time()` reports.
4. Make an edit (e.g. move the track), call `project_get_overview()` again, confirm `change_count` increased.

- [ ] **Step 7: Commit**

```bash
git add reaper_scripts/reaper_mcp_server.lua reaper_mcp/tools/project_tools.py
git commit -m "feat: add project_get_overview tool (issue #4)"
```

---

### Task 2: CHANGELOG entry

**Files:**
- Modify: `CHANGELOG.md`

- [ ] **Step 1: Add the entry**

Under `## [0.6.0]`'s existing `### Added` section, add:

```markdown
- **`project_get_overview`** — one cheap call bundling track/item/marker
  counts, the region list, `change_count`, and a lightweight selection
  summary (indices/counts, not full detail). Closes a gap found
  re-auditing issue #4 item 1: the original request asked for this as a
  cheap single read, but the shipped implementation required composing
  up to 6 separate calls to assemble the same picture. Purely additive —
  every existing granular tool (`project_get_info`, `marker_get_all`,
  `selection_get_*`) is unchanged. (issue #4)
```

- [ ] **Step 2: Run the full test suite one more time**

Run: `pytest tests/ -x -q`
Expected: PASS.

- [ ] **Step 3: Commit**

```bash
git add CHANGELOG.md
git commit -m "docs: changelog entry for project_get_overview (issue #4)"
```

---

## Self-Review Notes (for whoever executes this plan)

- **Spec coverage:** counts, region-list filtering, change_count, lightweight selection summary (indices not full objects), Lua reuse of existing API calls, live-smoke-test verification — all covered in Task 1.
- **Type consistency:** the Lua handler's `selection` sub-object field names (`selected_track_count`, `selected_track_indices`, `selected_item_count`, `selected_item_indices`, `time_selection`) must match exactly what Step 6's smoke test checks against — don't rename one without the other.
- **Insertion point:** both the Lua handler and Python tool go immediately after `project_get_change_count` in their respective files — keeps the three related "cheap check" tools (`project_get_info`, `project_get_change_count`, `project_get_overview`) grouped together for anyone reading the file top to bottom.
