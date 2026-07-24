# `markers_apply` — Batch Marker/Region Edit and Delete — Design

Date: 2026-07-25
Status: Approved, pending implementation plan

## Background

GitHub issue #4, item 2, asked for batch combinators for both items and
regions. `items_apply` (batch move/delete/set_volume/set_mute/set_fade
across media items) shipped earlier this session and is live-verified in
REAPER. This spec covers the remaining half: marker/region batch edit and
delete. Creation was already batched (`add_markers_batch`, existing
before this session) — only edit (`marker_edit`) and delete
(`marker_delete`) are still one-at-a-time.

## Gap found while reading the existing handlers

`marker.marker_edit` (`reaper_scripts/reaper_mcp_server.lua`) currently
only supports editing `position` and `name`. It cannot edit a region's
`end` (only a region's `start`, via `position`) or `color`, even though
creation (`marker_add_region`, `add_markers_batch`) already supports
both. `markers_apply` closes this gap — it isn't adding a new concept,
just extending edit to match what creation already does.

## Design

Mirrors `items_apply`'s established shape and semantics exactly (see
`reaper_mcp/tools/item_tools.py`'s `items_apply` and
`reaper_scripts/reaper_mcp_server.lua`'s `item.items_apply`, shipped and
live-verified earlier this session):

```json
[
  {"marker_index": 2, "name": "Line 12 (revised)"},
  {"marker_index": 5, "start": 10.0, "end": 14.5},
  {"marker_index": 7, "color": [200, 90, 60]},
  {"marker_index": 9, "delete": true}
]
```

- `marker_index` required on every entry — the enumeration index from
  `marker_get_all` (same value space `marker_edit`/`marker_delete`
  already use).
- `name`: new label, any marker or region.
- `position`: new position for a point marker. For a region, moving both
  edges independently uses `start`/`end` instead (see below) — `position`
  on a region entry is ignored (regions don't have a single "position").
- `start`/`end`: new bounds for a region. Only meaningful on an entry
  whose marker is actually a region — the Lua handler checks the
  marker's real `is_region` flag (from `EnumProjectMarkers3`), not a
  caller-supplied flag, so a mismatched field (e.g. `start`/`end` on a
  point marker) is silently ignored rather than corrupting a point
  marker into something malformed.
- `color`: `[r, g, b]`, each 0-255 — reuses the existing
  `_validate_color_array` helper from `compose_edit_tools.py` (already
  used by `configure_tracks`/`add_markers_batch`) rather than
  duplicating that validation.
- `delete: true`: deletes the marker/region. Any other fields on the same
  entry are ignored when `delete` is present (matches `items_apply`'s
  convention).

**Execution order:** identical reasoning to `items_apply` — non-delete
entries apply first (input order preserved), then all `delete: true`
entries apply last, in descending `marker_index` order. Deleting a marker
shifts every later enumeration index down by one
(`DeleteProjectMarkerByIndex`'s documented behavior, same class of issue
`items_apply` already solved for media items) — processing deletes last,
highest-index-first, means no delete in the batch ever invalidates an
index another entry in the same batch still needs.

**Error handling:** per-entry, not fail-fast — matches `items_apply`
(confirmed as the preferred convention earlier this session: "a batch of
40 edits doesn't get torched by one stale index"). A bad `marker_index`
is recorded in an `errors` array; the rest of the batch keeps going.

```json
{"success": true, "applied": 3, "errors": [
  {"index": 1, "marker_index": 99, "error": "Marker not found"}
]}
```

**Validation (Python side, before anything reaches Lua):** JSON array,
non-empty, capped at 200 entries (matches `items_apply`/
`add_markers_batch`'s existing caps). Each entry requires
`marker_index >= 0` (int). `color`, if present, validated via the
existing `_validate_color_array`. `start`/`end`/`position`, if present,
must be `>= 0`; if both `start` and `end` are present, `end` must be `>
start` (matches `marker_add_region`'s existing validation).

## Files touched

- `reaper_scripts/reaper_mcp_server.lua` — new `marker.markers_apply`
  handler. Extends the existing marker-editing logic (currently only in
  `marker.marker_edit`) to also handle `end` and `color`, reusing the
  same `native_color_from_array` helper `configure_tracks`/
  `add_markers_batch` already use.
- `reaper_mcp/tools/marker_tools.py` — new `_validate_markers_apply_entries`
  and `_order_markers_apply_entries` pure helpers (same split as
  `item_tools.py`'s `_validate_items_apply_entries`/
  `_order_items_apply_entries`), plus the `markers_apply` tool itself.
- `tests/test_marker_tools.py` — new. Same test shape as
  `tests/test_item_tools.py`: validation errors, delete-ordering
  (descending index, applied after non-delete entries regardless of
  input order).
- `CHANGELOG.md` — entry under `[0.6.0]`, referencing issue #4.

## Explicitly out of scope (this pass)

- Editing a marker's `is_region` type (converting a point marker into a
  region or vice versa) — not something either `marker_add`/
  `marker_add_region` or `marker_edit` support today; out of scope for a
  batch-edit tool to introduce.
- Batch `marker_go_to` — not an edit, doesn't fit this tool's shape.
