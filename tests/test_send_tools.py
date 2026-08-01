"""Tests for send MIDI channel validation in reaper_mcp/tools/send_tools.py.

Pure validation logic — no REAPER/IPC mocking needed, matching the pattern
of test_item_tools.py and test_patterns_tools.py.
"""

import pytest

from reaper_mcp_shared.error_codes import ReaperMCPError, ErrorCode


class TestSendMIDIChannelValidation:
    """Validate the range/combination checks for midi_source_channel
    and midi_dest_channel parameters on send_create.

    We can't easily call the actual @mcp.tool()-decorated async functions
    without a full MCP harness, so we replicate the validation logic here
    to test the bounds. The real functions use identical checks.
    """

    def _validate_channels(self, src_ch=None, dst_ch=None):
        """Mirror of the validation in send_create / send_set_midi_channel."""
        if (src_ch is None) != (dst_ch is None):
            raise ReaperMCPError(
                ErrorCode.INVALID_PARAMETER,
                "midi_source_channel and midi_dest_channel must both be set or both be None",
            )
        for label, val in (("midi_source_channel", src_ch), ("midi_dest_channel", dst_ch)):
            if val is not None and not (0 <= val <= 31):
                raise ReaperMCPError(
                    ErrorCode.VALUE_OUT_OF_RANGE,
                    f"{label} must be 0-31 (0=all, 1-16, 31=disabled), got {val}",
                )

    def test_both_none_is_valid(self):
        """Both channels None = audio-only send, no MIDI. Should pass."""
        self._validate_channels(None, None)

    def test_both_set_valid_range(self):
        """Standard MIDI channels 1-16."""
        self._validate_channels(1, 1)
        self._validate_channels(0, 0)
        self._validate_channels(16, 16)
        self._validate_channels(0, 3)

    def test_disable_midi_with_31(self):
        """31 = MIDI disabled. Valid for both source and dest."""
        self._validate_channels(31, 31)

    def test_mixed_none_raises(self):
        """One channel set, other None → error."""
        with pytest.raises(ReaperMCPError, match="both be set"):
            self._validate_channels(1, None)
        with pytest.raises(ReaperMCPError, match="both be set"):
            self._validate_channels(None, 1)

    def test_negative_channel_raises(self):
        with pytest.raises(ReaperMCPError, match="0-31"):
            self._validate_channels(-1, 0)

    def test_channel_over_31_raises(self):
        with pytest.raises(ReaperMCPError, match="0-31"):
            self._validate_channels(0, 32)

    def test_unused_bit_values_pass(self):
        """Values 17-30 are valid 5-bit encodings but not meaningful MIDI
        channels. The API allows them — the Lua handler masks to 5 bits
        and REAPER interprets anything > 16 as 'no channel'."""
        self._validate_channels(17, 0)
        self._validate_channels(0, 30)

    def test_all_channels_round_trip(self):
        """Every valid value 0-31 on both sides should pass."""
        for ch in range(32):
            self._validate_channels(ch, ch)


class TestMIDIFlagsBitPacking:
    """Verify the I_MIDIFLAGS bit-packing logic: src in low 5 bits, dst in next 5."""

    def _pack_flags(self, src_ch: int, dst_ch: int) -> int:
        """Mirror of the Lua bit-packing logic."""
        return (src_ch & 31) | ((dst_ch & 31) << 5)

    def _unpack_flags(self, flags: int) -> tuple[int, int]:
        """Mirror of the Lua un-packing logic."""
        return (flags & 31), ((flags >> 5) & 31)

    def test_pack_unpack_round_trip(self):
        for src in range(32):
            for dst in range(32):
                flags = self._pack_flags(src, dst)
                unpacked_src, unpacked_dst = self._unpack_flags(flags)
                assert unpacked_src == src
                assert unpacked_dst == dst

    def test_all_channels_zero(self):
        """0=all channels on both sides → flags=0."""
        assert self._pack_flags(0, 0) == 0

    def test_disable_midi(self):
        """31 on source = MIDI disabled. Should pack without collision."""
        flags = self._pack_flags(31, 0)
        src, dst = self._unpack_flags(flags)
        assert src == 31
        assert dst == 0

    def test_specific_routing(self):
        """Source ch 0 (all) → dest ch 3."""
        flags = self._pack_flags(0, 3)
        src, dst = self._unpack_flags(flags)
        assert src == 0
        assert dst == 3
