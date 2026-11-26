"""track_set_input's -1 shorthand reaches REAPER as "all MIDI inputs".

The tool has always documented and accepted -1 as "MIDI all", but the Lua
handler passed it straight to I_RECINPUT, where REAPER reads any negative
value as "no input" - so asking for all MIDI inputs cleared the input
instead. The handler now translates -1 to 6112 (4096 MIDI flag, device 63
= all inputs, channel 0 = all channels) and passes every other value through.

These run the real handler under lupa with a stubbed `reaper`.
"""

from pathlib import Path

import pytest

LUA_SRC = (
    Path(__file__).resolve().parent.parent
    / "reaper_scripts"
    / "reaper_mcp_server.lua"
)


def _load_handler(lupa):
    """Return (call, writes): call(params) runs the handler, writes logs I_RECINPUT sets."""
    source = LUA_SRC.read_text(encoding="utf-8")
    start = source.index("local RECINPUT_MIDI_ALL")
    end = source.index("\nend\n", source.index("function track.track_set_input(p)"))
    runtime = lupa.LuaRuntime()
    runtime.execute(
        """
        writes = {}
        reaper = {
          SetMediaTrackInfo_Value = function(tr, key, value)
            writes[#writes + 1] = key .. "=" .. string.format("%d", value)
          end,
        }
        track = {}
        function get_numbered_track(p) return "TRACK0", p.track_index, nil end
        function build_track_info(tr, idx) return idx end
        """
    )
    runtime.execute(source[start:end] + "\nend\n")
    handler = runtime.eval("track.track_set_input")

    def call(params):
        return handler(runtime.table_from(params))

    def writes():
        return list(runtime.eval("writes").values())

    return call, writes


def test_minus_one_sets_all_midi_inputs_all_channels():
    lupa = pytest.importorskip("lupa")
    call, writes = _load_handler(lupa)
    call({"track_index": 0, "input_index": -1})
    assert writes() == ["I_RECINPUT=6112"]


@pytest.mark.parametrize("value", [0, 1, 1024, 4096, 4097, 6112])
def test_other_values_pass_through_unchanged(value):
    lupa = pytest.importorskip("lupa")
    call, writes = _load_handler(lupa)
    call({"track_index": 0, "input_index": value})
    assert writes() == [f"I_RECINPUT={value}"]


def test_missing_input_index_is_refused_without_a_write():
    lupa = pytest.importorskip("lupa")
    call, writes = _load_handler(lupa)
    result = call({"track_index": 0})
    assert result[1] == "Missing parameter: input_index"
    assert writes() == []
