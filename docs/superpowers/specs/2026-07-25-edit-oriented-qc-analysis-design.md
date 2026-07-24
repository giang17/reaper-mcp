# Edit-Oriented QC Analysis — Design

Date: 2026-07-25
Status: Approved, pending implementation plan

## Background

GitHub issue #4, item 5:

> Edit-oriented analysis — silence/breath/peak candidate detection and
> per-region QC, extending the existing analysis tools from "mix metrics"
> toward "candidates for human review".

This is the last unstarted piece of issue #4. Items 1-3 (post-production
change-count, `items_apply` batch item edits, ReaScript
discovery/execution) shipped earlier this session and are live-verified
in REAPER. Item 2's other half (region/marker batch edit/delete) and item
4 (an external ElevenLabs voice pipeline, intentionally left to a
separate companion server / the external contributor) are out of scope
here.

`reaper_mcp/tools/analysis_tools.py` already exists: a pure DSP module
with zero dependency on REAPER/Lua — every tool takes a rendered WAV path
and returns objective metrics (LUFS, clipping, frequency balance, stereo
field), gated behind an optional `numpy`/`soundfile`/`pyloudnorm`
dependency (`_AVAILABLE`/`_IMPORT_ERROR` pattern, installed via
`pip install 'reaper-mcp[analysis]'`). This feature extends that same
module and convention rather than introducing a new architecture.

## Scope decision: breath detection deferred

Silence and click/pop detection have clear, reliable DSP signatures
(sustained low amplitude; short-duration transient spike well above local
baseline). Breath detection does not — an amplitude-only heuristic cannot
reliably distinguish a breath from quiet room tone or background noise;
doing this properly needs spectral or ML-based classification, which is
out of scope for this pass. **Breath detection is deferred, not shipped.**
This is a scope decision made explicitly, not an oversight — silence and
peak/click detection ship now because they're solid ground; breath
detection is left for a real ML-based approach later rather than shipping
an unreliable heuristic under the same name.

This whole feature — even the "solid ground" parts — needs real testing
with actual post-production users before its output should be trusted as
more than a rough first pass. It's shipping because it's useful for
triage, not because its candidates are guaranteed correct.

## Components

All three land in `reaper_mcp/tools/analysis_tools.py`, behind the
existing `_AVAILABLE` gate — no new module, no new dependency beyond what
that file already requires.

### `analyze_silence(wav_path: str, threshold_db: float = -40.0, min_duration: float = 0.3) -> dict`

Scans the whole file for spans where amplitude stays at or below
`threshold_db` for at least `min_duration` seconds. Same shape as the
existing `analyze_clipping` (threshold + a Python-side scan over the
sample array, no external DSP library beyond what's already imported).

Returns:
```json
{
  "threshold_db": -40.0,
  "min_duration": 0.3,
  "candidates": [{"start_sec": 12.4, "end_sec": 13.1, "duration_sec": 0.7}],
  "total_silence_sec": 0.7,
  "hint": "1 silence candidate found (0.7s total)."
}
```

### `analyze_peaks(wav_path: str, sensitivity: float = 3.0) -> dict`

Click/pop candidate detection — distinct from `analyze_clipping`'s
absolute-threshold check (which catches sustained over-0dBFS content).
This looks for short-duration transients whose local energy spikes well
above the surrounding rolling-window baseline — the actual signature of a
click/pop, not just a loud musical passage (which raises energy smoothly
across a wider window, not as an isolated spike). `sensitivity` is a
multiplier on how many standard deviations above the local rolling
baseline counts as a candidate; higher = fewer, more confident
candidates.

Returns:
```json
{
  "sensitivity": 3.0,
  "candidates": [{"time_sec": 5.2, "magnitude_db": 14.3}],
  "hint": "2 peak/click candidates found — listen and trim or use spectral repair if confirmed."
}
```

### `analyze_region_qc(wav_path: str, regions: str) -> dict`

The per-region composition layer — the actual "candidates for human
review, per region" deliverable the issue asked for. `regions` is a JSON
array the caller populates from `marker_get_all()` (regions are markers
with `is_region: true`); this tool does not call into REAPER itself,
keeping `analysis_tools.py`'s existing zero-Lua-dependency convention
intact — same reasoning as the module's current design (read-only file
analysis, testable without any REAPER connection).

```json
regions: [{"name": "Line 12", "start": 10.2, "end": 14.8}, ...]
```

For each region, slices the loaded WAV to `[start, end)` and runs both
silence and peak/click detection scoped to just that slice (same
underlying logic as `analyze_silence`/`analyze_peaks`, refactored into
shared helper functions both the whole-file tools and this one call, so
there's exactly one implementation of each detector).

Returns:
```json
{
  "region_count": 3,
  "regions": [
    {
      "name": "Line 12", "start": 10.2, "end": 14.8,
      "silence_candidates": [...], "peak_candidates": [...],
      "flag_count": 2
    }
  ],
  "total_flags": 5,
  "hint": "5 candidates across 3 regions — review flagged regions before final edit."
}
```

## Error handling

- All three reuse the existing `_load_wav`/`_safe_audio_path` helpers
  already in the file — same path validation, same "file not found /
  render first" error, same empty-file guard.
- `analyze_region_qc`: malformed `regions` JSON → `ReaperMCPError
  INVALID_PARAMETER`. A region whose `start`/`end` falls outside the
  loaded audio's actual duration is clamped to the file's bounds rather
  than raising — a region marker slightly past the end of a render
  shouldn't abort the whole QC pass, just report what's actually there
  (and the returned region's `end` reflects what was actually analyzed,
  not the requested value, so this is visible rather than silent).
- `threshold_db` for `analyze_silence` must be `<= 0` (same convention as
  `analyze_clipping`'s `threshold_db` validation).
- `sensitivity` for `analyze_peaks` must be `> 0`.

## Testing

Pure DSP logic, testable with synthetic `numpy` arrays — no real audio
files needed, matching how a real implementer would want to iterate
quickly:

- Silence detection: a synthetic array with an injected low-amplitude
  span of known start/end/duration; confirm it's found and spans shorter
  than `min_duration` are NOT flagged.
- Peak/click detection: a synthetic array with an injected short spike
  against a quiet baseline; confirm it's found and a smooth loud passage
  (no isolated spike) is NOT flagged.
- Region slicing: confirm a region's candidates only include
  detections within `[start, end)`, and that a region extending past the
  file's actual length gets clamped rather than raising or silently
  truncating data without saying so.
- Threshold/sensitivity validation errors.

## Files touched

- `reaper_mcp/tools/analysis_tools.py` — 3 new tools, 2 new shared
  detector helper functions (`_find_silence_candidates`,
  `_find_peak_candidates`) that `analyze_silence`/`analyze_peaks`/
  `analyze_region_qc` all call, so the detection logic exists exactly
  once.
- `tests/test_analysis_tools.py` — new.
- `CHANGELOG.md` — entry under `[0.6.0]`, referencing issue #4, with the
  breath-detection deferral and "needs real user testing" caveat stated
  explicitly, not just implied.

## Explicitly out of scope (this pass)

- Breath detection (see "Scope decision" above).
- Any REAPER/Lua dependency in these tools — stays pure file analysis.
- Automatic fixing/trimming of flagged candidates — this is a QC/review
  tool, not an editing tool. Acting on a flagged candidate (e.g. trimming
  silence) is a separate, existing tool (`item_split`, `item_set_length`,
  the new `items_apply`), left to the AI/user to decide after reviewing
  the QC report.
