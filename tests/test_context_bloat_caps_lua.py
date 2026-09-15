"""Source-level guards for item_get_all/marker_get_all's max_results.

Found in a hardening pass: unlike midi_get_notes/envelope_get_points
(which pass max_results to Lua and stop enumerating early), item_get_all's
Python wrapper validated max_results but never forwarded it — Lua built,
JSON-encoded, and transmitted every item in the project every time, and
only THEN did Python slice off the excess and discard it. marker_get_all
had no cap at all. Neither reduced the real per-call cost (Lua-side
enumeration, IPC file size, JSON parse) that max_results exists to bound;
they only trimmed the final response Python handed back.

These are cheap regression guards so a future refactor of either handler
can't quietly drop the early-stop and reintroduce the same antipattern.
"""

from pathlib import Path

LUA = (
    Path(__file__).resolve().parent.parent
    / "reaper_scripts"
    / "reaper_mcp_server.lua"
)


def _function_body(src: str, signature: str, end_anchor: str) -> str:
    start = src.index(signature)
    end = src.index("\nend\n", src.index(end_anchor, start))
    return src[start:end]


class TestItemGetAllLua:
    def test_stops_enumerating_at_max_results(self):
        src = LUA.read_text(encoding="utf-8")
        body = _function_body(src, "function item.item_get_all(p)", "total_items")
        assert "if returned >= max_results then break end" in body

    def test_uses_one_pass_index_map_not_nested_scan(self):
        # The old version rescanned every project item, per track item
        # (O(n_on_track * total)) - confirms the index_by_item map fix
        # (same pattern as item_split_at_transients elsewhere in this
        # file) is in place instead.
        src = LUA.read_text(encoding="utf-8")
        body = _function_body(src, "function item.item_get_all(p)", "total_items")
        assert "index_by_item[reaper.GetMediaItem(0, gi)] = gi" in body

    def test_reports_truncated_flag(self):
        src = LUA.read_text(encoding="utf-8")
        body = _function_body(src, "function item.item_get_all(p)", "total_items")
        assert "truncated = candidates > returned" in body


class TestMarkerGetAllLua:
    def test_stops_enumerating_at_max_results(self):
        src = LUA.read_text(encoding="utf-8")
        body = _function_body(src, "function marker.marker_get_all(p)", "count = count")
        assert "returned = math.min(count, max_results)" in body

    def test_reports_truncated_flag(self):
        src = LUA.read_text(encoding="utf-8")
        body = _function_body(src, "function marker.marker_get_all(p)", "count = count")
        assert "truncated = count > returned" in body


class TestBuildFxParamsLua:
    def test_stops_enumerating_at_max_results(self):
        src = LUA.read_text(encoding="utf-8")
        body = _function_body(src, "local function build_fx_params(tr, fx_idx, max_results)", "params_shown")
        assert "if #params >= max_results then" in body

    def test_reports_truncated_flag(self):
        src = LUA.read_text(encoding="utf-8")
        body = _function_body(src, "local function build_fx_params(tr, fx_idx, max_results)", "params_shown")
        assert "truncated = capped" in body

    def test_has_a_default_so_every_caller_is_protected(self):
        # build_fx_params has two call sites (fx_get_params and
        # fx_set_preset's opt-in include_params) - only fx_get_params
        # passes max_results explicitly, so the function needs its own
        # default for the other caller to get the same backstop for free.
        src = LUA.read_text(encoding="utf-8")
        body = _function_body(src, "local function build_fx_params(tr, fx_idx, max_results)", "params_shown")
        assert "max_results = max_results or 300" in body
