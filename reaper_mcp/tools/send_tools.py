from mcp.server.fastmcp import FastMCP
from reaper_mcp_shared.error_codes import ReaperMCPError, ErrorCode


def register(mcp: FastMCP):
    from reaper_mcp.main import client

    @mcp.tool()
    async def send_create(
        source_track: int,
        dest_track: int,
        midi_source_channel: int | None = None,
        midi_dest_channel: int | None = None,
    ) -> dict:
        """Create send between tracks. Prefer setup_routing for batch.

        To create a MIDI-only send to a multi-timbral VSTi track, pass
        midi_source_channel and midi_dest_channel (0=all, 1-16). The send
        will carry MIDI on the specified channels. Audio on the send can
        be muted separately via send_set_mute.

        Args:
            source_track: Source track index.
            dest_track: Destination track index.
            midi_source_channel: If set, enables MIDI routing. 0=all channels, 1-16=specific. Must be paired with midi_dest_channel.
            midi_dest_channel: Target channel on the destination track. 0=all, 1-16. Must be paired with midi_source_channel.
        """
        if source_track < 0:
            raise ReaperMCPError(ErrorCode.VALUE_OUT_OF_RANGE, "source_track must be >= 0")
        if dest_track < 0:
            raise ReaperMCPError(ErrorCode.VALUE_OUT_OF_RANGE, "dest_track must be >= 0")
        if source_track == dest_track:
            raise ReaperMCPError(ErrorCode.INVALID_PARAMETER, "Source and destination must be different tracks")
        if (midi_source_channel is None) != (midi_dest_channel is None):
            raise ReaperMCPError(
                ErrorCode.INVALID_PARAMETER,
                "midi_source_channel and midi_dest_channel must both be set or both be None",
            )
        for label, val in (("midi_source_channel", midi_source_channel), ("midi_dest_channel", midi_dest_channel)):
            if val is not None and not (0 <= val <= 31):
                raise ReaperMCPError(
                    ErrorCode.VALUE_OUT_OF_RANGE,
                    f"{label} must be 0-31 (0=all, 1-16, 31=disabled), got {val}",
                )
        params = {"source_track": source_track, "dest_track": dest_track}
        if midi_source_channel is not None:
            params["midi_source_channel"] = midi_source_channel
            params["midi_dest_channel"] = midi_dest_channel
        return await client.execute("send_create", **params)

    @mcp.tool()
    async def send_remove(track_index: int, send_index: int) -> dict:
        """Remove a send.

        Args:
            track_index: Source track index.
            send_index: Send index.
        """
        if track_index < 0:
            raise ReaperMCPError(ErrorCode.VALUE_OUT_OF_RANGE, "track_index must be >= 0")
        if send_index < 0:
            raise ReaperMCPError(ErrorCode.VALUE_OUT_OF_RANGE, "send_index must be >= 0")
        return await client.execute("send_remove", track_index=track_index, send_index=send_index)

    @mcp.tool()
    async def send_get_all(track_index: int) -> dict:
        """Get all sends/receives on a track.

        Args:
            track_index: Track index.
        """
        if track_index < 0:
            raise ReaperMCPError(ErrorCode.VALUE_OUT_OF_RANGE, "track_index must be >= 0")
        return await client.execute("send_get_all", track_index=track_index)

    @mcp.tool()
    async def send_set_volume(track_index: int, send_index: int, volume_db: float) -> dict:
        """Set send volume.

        Args:
            track_index: Source track.
            send_index: Send index.
            volume_db: dB (0=unity).
        """
        if track_index < 0:
            raise ReaperMCPError(ErrorCode.VALUE_OUT_OF_RANGE, "track_index must be >= 0")
        if send_index < 0:
            raise ReaperMCPError(ErrorCode.VALUE_OUT_OF_RANGE, "send_index must be >= 0")
        return await client.execute("send_set_volume", track_index=track_index,
                                    send_index=send_index, volume_db=volume_db)

    @mcp.tool()
    async def send_set_pan(track_index: int, send_index: int, pan: float) -> dict:
        """Set send pan.

        Args:
            track_index: Source track.
            send_index: Send index.
            pan: -1.0 to 1.0.
        """
        if track_index < 0:
            raise ReaperMCPError(ErrorCode.VALUE_OUT_OF_RANGE, "track_index must be >= 0")
        if send_index < 0:
            raise ReaperMCPError(ErrorCode.VALUE_OUT_OF_RANGE, "send_index must be >= 0")
        if not -1.0 <= pan <= 1.0:
            raise ReaperMCPError(ErrorCode.VALUE_OUT_OF_RANGE, "Pan must be -1.0 to 1.0")
        return await client.execute("send_set_pan", track_index=track_index,
                                    send_index=send_index, pan=pan)

    @mcp.tool()
    async def send_set_mute(track_index: int, send_index: int, mute: bool) -> dict:
        """Mute/unmute send.

        Args:
            track_index: Source track.
            send_index: Send index.
            mute: True=mute.
        """
        if track_index < 0:
            raise ReaperMCPError(ErrorCode.VALUE_OUT_OF_RANGE, "track_index must be >= 0")
        if send_index < 0:
            raise ReaperMCPError(ErrorCode.VALUE_OUT_OF_RANGE, "send_index must be >= 0")
        return await client.execute("send_set_mute", track_index=track_index,
                                    send_index=send_index, mute=mute)

    @mcp.tool()
    async def send_set_midi_channel(
        track_index: int,
        send_index: int,
        midi_source_channel: int,
        midi_dest_channel: int,
    ) -> dict:
        """Set MIDI source/destination channel on an existing send.

        Enables or changes MIDI routing on a track send. Use this to route
        MIDI from a source track to a specific channel on a multi-timbral
        VSTi (e.g. ARIA Player, Kontakt multi) on the destination track.

        To disable MIDI on the send, set both channels to 31.

        Args:
            track_index: Source track index.
            send_index: Send index to modify.
            midi_source_channel: Source MIDI channel. 0=all channels, 1-16=specific, 31=disabled.
            midi_dest_channel: Destination MIDI channel. 0=all, 1-16=specific, 31=disabled.
        """
        if track_index < 0:
            raise ReaperMCPError(ErrorCode.VALUE_OUT_OF_RANGE, "track_index must be >= 0")
        if send_index < 0:
            raise ReaperMCPError(ErrorCode.VALUE_OUT_OF_RANGE, "send_index must be >= 0")
        for label, val in (("midi_source_channel", midi_source_channel), ("midi_dest_channel", midi_dest_channel)):
            if not isinstance(val, int) or not (0 <= val <= 31):
                raise ReaperMCPError(
                    ErrorCode.VALUE_OUT_OF_RANGE,
                    f"{label} must be 0-31 (0=all, 1-16, 31=disabled), got {val}",
                )
        return await client.execute(
            "send_set_midi_channel",
            track_index=track_index,
            send_index=send_index,
            midi_source_channel=midi_source_channel,
            midi_dest_channel=midi_dest_channel,
        )

    @mcp.tool()
    async def send_get_routing_diagram() -> dict:
        """Get full project routing diagram (sends, receives, outputs)."""
        return await client.execute("send_get_routing_diagram")
