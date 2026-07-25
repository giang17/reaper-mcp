# `project_get_overview` — Design

Date: 2026-07-25
Status: Approved, pending implementation plan

## Background

Re-auditing issue #4 item 1 ("Post-production awareness") found a real
gap: the issue asked for a lightweight overview (region list, track/item
counts) **and** a selection snapshot as cheap single reads, so an agent
can tell whether re-querying is needed instead of blindly re-reading.
What actually shipped requires composing up to 6 separate tool calls
(`project_get_info` + `marker_get_all` + `selection_get_time` +
`selection_get_selected_tracks` + `selection_get_selected_items`, plus
the already-correct `project_get_change_count`) to get that full
picture — undercutting the efficiency the request was actually about.

This is additive: every existing granular tool stays exactly as-is for
when the AI only needs one specific piece.

## Design

One new tool, `project_get_overview()`, no parameters, bundling:

- `name`, `track_count`, `item_count`, `marker_count` — same values
  `project_get_info` already returns for these fields.
- `regions` — the region subset of what `marker_get_all` returns
  (filtered to `is_region == true` — point markers excluded, matching
  the issue's literal "region list" wording), each
  `{index, number, name, start, end}`.
- `change_count` — same value `project_get_change_count` returns.
- `selection` — `{selected_track_count, selected_track_indices,
  selected_item_count, selected_item_indices, time_selection: {start,
  end, length}}`.

**Selection stays lightweight on purpose.** `selection_get_selected_tracks`/
`selection_get_selected_items` return full track/item detail objects
(name, color, volume, position, etc.) for every selected object — fine
for their own purpose, but pulling that much detail into a call meant to
be a cheap overview would defeat the point, especially if a lot is
selected. `project_get_overview`'s selection summary returns indices and
counts only; the AI calls the existing heavier tools if it actually needs
full detail on what's selected.

## Implementation

New Lua handler `project.project_get_overview` reuses the exact same
REAPER API calls each existing handler already uses — no new REAPER API
surface, just consolidated into one response:

- `reaper.CountTracks`, `reaper.CountMediaItems`, `reaper.CountProjectMarkers`
  (same as `project_get_info`)
- `reaper.EnumProjectMarkers3` looped, filtered to `isrgn == true` (same
  loop `marker_get_all` already runs, just filtered)
- `reaper.GetProjectStateChangeCount` (same as `project_get_change_count`)
- `reaper.CountSelectedTracks` / `GetSelectedTrack` /
  `GetMediaTrackInfo_Value(..., "IP_TRACKNUMBER")` (same as
  `selection_get_selected_tracks`, but collecting just the index instead
  of calling `build_track_info`)
- `reaper.CountSelectedMediaItems` / `GetSelectedMediaItem` + the same
  linear global-index lookup `selection_get_selected_items` already does
  (same O(n×m) shape as that existing tool — not a regression, matching
  established precedent, not worth optimizing beyond what the codebase
  already accepts elsewhere)
- `reaper.GetSet_LoopTimeRange(false, false, 0, 0, false)` (same as
  `selection_get_time`)

Python side: thin wrapper, no parameters, no validation needed — same
shape as `project_get_change_count`.

## Testing

No new validation logic to unit-test (no parameters). Verified via live
REAPER smoke test, matching this codebase's established convention for
Lua-side changes: create tracks/items/regions, select some, call
`project_get_overview`, confirm every field matches what the individual
existing tools report for the same project state.

## Files touched

- `reaper_scripts/reaper_mcp_server.lua` — 1 new handler.
- `reaper_mcp/tools/project_tools.py` — 1 new tool.
- `CHANGELOG.md` — entry under `[0.6.0]`, referencing issue #4.

## Explicitly out of scope (this pass)

- Changing any existing tool's return shape — this is purely additive.
- Bundling `project_get_overview` into `project_get_change_count` or vice
  versa — they stay separate tools serving different purposes (gate vs.
  detail), consistent with the earlier decision to keep the change-count
  check minimal.
