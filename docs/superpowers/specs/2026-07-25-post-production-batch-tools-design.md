# Post-Production Batch Tools — Design

Date: 2026-07-25
Status: Approved, pending implementation plan

## Background

GitHub issue #4 raised several post-production gaps in reaper-mcp's tool
surface. This spec covers items 1 and 2 of that list (item 3, ReaScript
integration, has its own spec —
`2026-07-25-reascript-integration-design.md`; item 5, edit-oriented QC,
is not scoped yet; item 4, an external TTS pipeline, is explicitly left
to a separate companion MCP server, not this repo).

## 1. `project_get_change_count`

Item 1 of the issue asked for a lightweight project overview (region
list, track/item counts, a cheap "changed since I last checked" signal).
Investigation found `project_get_info` already returns
`track_count`/`item_count`/`marker_count`, and `marker_get_all` already
returns the full region list (regions are markers with `is_region:
true`). The only genuinely new capability is exposing REAPER's
`GetProjectStateChangeCount` — a monotonically increasing counter that
bumps on any project edit, letting the AI cheaply decide whether it needs
to re-fetch heavier data (`track_get_all`, `item_get_all`) instead of
blindly re-querying every turn.

Scoped as a small dedicated tool (not a field bolted onto
`project_get_info`) per explicit direction — this project isn't
optimizing token footprint aggressively right now, clarity of a
purpose-built tool wins.

```
project_get_change_count() -> {"change_count": <int>}
```

- New Lua handler: `project.project_get_change_count`, wrapping
  `reaper.GetProjectStateChangeCount(0)`.
- New Python tool in `reaper_mcp/tools/project_tools.py`. No parameters,
  no validation needed.

## 2. `items_apply`

Item 2 asked for batch combinators — today every item mutation
(`item_move`, `item_delete`, `item_set_volume`, `item_set_mute`,
`item_set_fade`) is one call per item; only creation-style batch tools
exist (`add_markers_batch`). Scoped to **items only** — region edit/delete
stays one-at-a-time for now (a smaller, separate gap, not addressed here).

Shape follows `configure_tracks`'s existing convention (one entry per
object, set whichever fields are present) rather than a generic
verb-based op-list:

```json
[
  {"item_index": 12, "volume_db": -3.0, "fade_in": 0.05},
  {"item_index": 15, "mute": true},
  {"item_index": 20, "position": 8.5},
  {"item_index": 31, "delete": true}
]
```

Fields map 1:1 to existing single-item tools: `position` → `item_move`,
`length` → `item_set_length`, `volume_db` → `item_set_volume`, `mute` →
`item_set_mute`, `fade_in`/`fade_out` → `item_set_fade`, `delete` →
`item_delete`. `split` is deliberately excluded — it creates new items
and shifts indices, and is already served by dedicated tools
(`item_split_at_positions`, `item_split_at_transients`); mixing it into a
flat batch invites the same class of index-shift bug PR #5 just fixed
elsewhere in this codebase.

**Execution order:** all non-delete property changes apply first in
array order, then all `delete: true` entries apply last in descending
`item_index` order, regardless of the order the caller listed them in.
This prevents a delete from shifting the indices of items processed
later in the same batch.

**Error handling:** per-entry, not fail-fast (deliberately diverging from
`configure_tracks`' abort-on-first-error convention). A bad `item_index`
gets recorded in an `errors` array and the rest of the batch keeps
going — this is a bulk cleanup tool aimed at dozens of items at once, and
one stale index shouldn't discard 39 good edits:

```json
{"success": true, "applied": 39, "errors": [
  {"index": 12, "item_index": 87, "error": "Item not found"}
]}
```

**Validation (Python side, before anything reaches Lua):** JSON array,
non-empty, capped at 200 entries (matching `add_markers_batch`'s cap),
each entry requires `item_index >= 0` (int); `fade_in`/`fade_out` >= 0 if
present, `length` > 0 if present, `position` >= 0 if present — the same
bounds each underlying single-item tool already enforces.

- New Lua handler: `item.items_apply`.
- New Python tool in `reaper_mcp/tools/item_tools.py`.

## Testing

- `project_get_change_count`: trivial — one test confirming the value
  round-trips from the mocked client.
- `items_apply`: JSON validation errors (malformed, empty, over-cap,
  bad field bounds), delete-ordering (descending index, applied after
  property changes regardless of input order), per-entry error
  collection on a bad `item_index` without aborting the rest of the
  batch.

## Files touched

- `reaper_scripts/reaper_mcp_server.lua` — 2 new handlers.
- `reaper_mcp/tools/project_tools.py` — 1 new tool.
- `reaper_mcp/tools/item_tools.py` — 1 new tool.
- `tests/` — new tests for both.
- `CHANGELOG.md` — entry under `[0.6.0]` once implemented, referencing
  issue #4.

## Explicitly out of scope (this pass)

- Region/marker batch edit/delete (issue #4 item 2 also mentioned this;
  deferred — creation is already batched via `add_markers_batch`, only
  edit/delete remain one-at-a-time, treated as a smaller follow-up).
- Bundling `items_apply` with `split` — stays a dedicated tool.
- A combined "project overview" tool bundling counts + regions +
  change_count — rejected in favor of the smaller
  `project_get_change_count` addition, since the rest already exists.
