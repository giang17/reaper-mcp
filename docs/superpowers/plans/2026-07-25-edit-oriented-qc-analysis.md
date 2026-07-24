# Edit-Oriented QC Analysis Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add `analyze_silence`, `analyze_peaks`, and `analyze_region_qc` to `reaper_mcp/tools/analysis_tools.py`, per the approved spec — silence and click/pop candidate detection, plus per-region QC reports, for post-production review workflows (issue #4, item 5).

**Architecture:** Two new pure-numpy detector functions (`_find_silence_candidates`, `_find_peak_candidates`) that `analyze_silence`, `analyze_peaks`, and `analyze_region_qc` all call — one implementation of each detector, not three. Everything stays inside the existing `analysis_tools.py` module, behind its existing `_AVAILABLE` optional-dependency gate. No REAPER/Lua dependency added — `analyze_region_qc` takes `regions` as an explicit JSON parameter the caller populates from `marker_get_all()`, not a live REAPER query.

**Tech Stack:** Python 3.10+, numpy (already an optional dependency of this module), pytest. Tests use synthetic numpy arrays — no real audio files needed.

## Global Constraints

- All three new tools live in `reaper_mcp/tools/analysis_tools.py` — no new module.
- Reuse the existing `_load_wav`, `_to_mono`, `_safe_audio_path` helpers already in that file — do not duplicate path validation or WAV loading.
- `threshold_db` parameters must be `<= 0` (matches `analyze_clipping`'s existing convention).
- Breath detection is explicitly out of scope — do not add it "while you're in there."
- Target version: `0.6.0`. `CHANGELOG.md`'s `## [0.6.0] - Unreleased` section already has three `### Added` entries from earlier issue-#4 work this session — this plan's Task 6 adds a fourth.
- Spec: `docs/superpowers/specs/2026-07-25-edit-oriented-qc-analysis-design.md` — read it before starting.

---

### Task 1: `_find_silence_candidates` — pure detector helper

**Files:**
- Modify: `reaper_mcp/tools/analysis_tools.py` (add after `_peak_db`, before `def register`)
- Test: `tests/test_analysis_tools.py` (new)

**Interfaces:**
- Produces: `_find_silence_candidates(mono: np.ndarray, sr: int, threshold_db: float, min_duration: float) -> list[dict]`. Each dict: `{"start_sec": float, "end_sec": float, "duration_sec": float}`, rounded to 3 decimal places. `mono` is a 1-D float array (already mono, already the caller's responsibility via `_to_mono`).

- [ ] **Step 1: Write the failing tests**

Create `tests/test_analysis_tools.py`:

```python
"""Tests for reaper_mcp/tools/analysis_tools.py's edit-oriented QC detectors.

Pure numpy logic — synthetic arrays, no real audio files needed. Skipped
entirely if numpy isn't installed (matches this module's own optional
numpy/soundfile/pyloudnorm dependency).
"""

import pytest

np = pytest.importorskip("numpy")

from reaper_mcp.tools.analysis_tools import (
    _find_silence_candidates,
    _find_peak_candidates,
)


def _silence_db_to_linear(db):
    return 10 ** (db / 20.0)


class TestFindSilenceCandidates:
    def test_no_silence_in_loud_signal(self):
        sr = 44100
        mono = np.full(sr, 0.5, dtype=np.float64)
        candidates = _find_silence_candidates(mono, sr, threshold_db=-40.0, min_duration=0.3)
        assert candidates == []

    def test_finds_injected_silence_span(self):
        sr = 44100
        mono = np.full(sr * 2, 0.5, dtype=np.float64)
        # Inject 0.5s of near-silence starting at 1.0s.
        start_sample = sr * 1
        end_sample = start_sample + int(sr * 0.5)
        mono[start_sample:end_sample] = 0.0001
        candidates = _find_silence_candidates(mono, sr, threshold_db=-40.0, min_duration=0.3)
        assert len(candidates) == 1
        assert candidates[0]["start_sec"] == pytest.approx(1.0, abs=0.01)
        assert candidates[0]["duration_sec"] == pytest.approx(0.5, abs=0.01)

    def test_short_silence_below_min_duration_not_flagged(self):
        sr = 44100
        mono = np.full(sr, 0.5, dtype=np.float64)
        # Inject only 0.1s of silence — below the 0.3s min_duration default.
        mono[1000:1000 + int(sr * 0.1)] = 0.0
        candidates = _find_silence_candidates(mono, sr, threshold_db=-40.0, min_duration=0.3)
        assert candidates == []

    def test_all_silent_file_flagged_as_one_span(self):
        sr = 44100
        mono = np.zeros(sr, dtype=np.float64)
        candidates = _find_silence_candidates(mono, sr, threshold_db=-40.0, min_duration=0.3)
        assert len(candidates) == 1
        assert candidates[0]["duration_sec"] == pytest.approx(1.0, abs=0.01)

    def test_empty_array_returns_no_candidates(self):
        candidates = _find_silence_candidates(np.array([]), 44100, threshold_db=-40.0, min_duration=0.3)
        assert candidates == []
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_analysis_tools.py -v`
Expected: FAIL with `ImportError: cannot import name '_find_silence_candidates'`

- [ ] **Step 3: Write the minimal implementation**

In `reaper_mcp/tools/analysis_tools.py`, add after `_peak_db` (and before `def register(mcp: FastMCP):`):

```python
def _find_silence_candidates(mono, sr: int, threshold_db: float, min_duration: float) -> list:
    if mono.size == 0:
        return []
    threshold_linear = 10 ** (threshold_db / 20.0)
    below = np.abs(mono) <= threshold_linear
    candidates = []
    n = len(below)
    i = 0
    while i < n:
        if below[i]:
            start = i
            while i < n and below[i]:
                i += 1
            end = i
            duration = (end - start) / sr
            if duration >= min_duration:
                candidates.append({
                    "start_sec": round(start / sr, 3),
                    "end_sec": round(end / sr, 3),
                    "duration_sec": round(duration, 3),
                })
        else:
            i += 1
    return candidates
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_analysis_tools.py -v`
Expected: `TestFindSilenceCandidates` tests PASS. The `_find_peak_candidates` import will still fail — that's Task 2. Run with `-k FindSilenceCandidates` to isolate: `pytest tests/test_analysis_tools.py -v -k FindSilenceCandidates`

- [ ] **Step 5: Commit**

```bash
git add reaper_mcp/tools/analysis_tools.py tests/test_analysis_tools.py
git commit -m "feat: add silence-candidate detection helper (issue #4)"
```

---

### Task 2: `_find_peak_candidates` — pure detector helper

**Files:**
- Modify: `reaper_mcp/tools/analysis_tools.py`
- Test: `tests/test_analysis_tools.py`

**Interfaces:**
- Produces: `_find_peak_candidates(mono: np.ndarray, sr: int, sensitivity: float) -> list[dict]`. Each dict: `{"time_sec": float, "magnitude_db": float | None}` (rounded to 3/2 decimals respectively; `magnitude_db` is `None` only in the degenerate zero-magnitude case, which shouldn't occur since a flagged sample is by definition above a positive threshold).

- [ ] **Step 1: Write the failing tests**

Add to `tests/test_analysis_tools.py`:

```python
class TestFindPeakCandidates:
    def test_no_candidates_in_silence(self):
        sr = 44100
        mono = np.zeros(sr, dtype=np.float64)
        candidates = _find_peak_candidates(mono, sr, sensitivity=3.0)
        assert candidates == []

    def test_no_candidates_in_steady_tone(self):
        sr = 44100
        t = np.arange(sr) / sr
        mono = 0.5 * np.sin(2 * np.pi * 440 * t)
        candidates = _find_peak_candidates(mono, sr, sensitivity=3.0)
        assert candidates == []

    def test_finds_injected_spike_against_quiet_baseline(self):
        sr = 44100
        rng = np.random.default_rng(42)
        mono = rng.normal(0, 1e-5, sr).astype(np.float64)
        spike_idx = sr // 2
        mono[spike_idx:spike_idx + 5] = 0.5
        candidates = _find_peak_candidates(mono, sr, sensitivity=3.0)
        assert len(candidates) == 1
        assert candidates[0]["time_sec"] == pytest.approx(spike_idx / sr, abs=0.001)
        assert candidates[0]["magnitude_db"] is not None
        assert candidates[0]["magnitude_db"] > -10.0

    def test_empty_array_returns_no_candidates(self):
        candidates = _find_peak_candidates(np.array([]), 44100, sensitivity=3.0)
        assert candidates == []

    def test_higher_sensitivity_finds_fewer_candidates(self):
        sr = 44100
        rng = np.random.default_rng(7)
        mono = rng.normal(0, 1e-4, sr).astype(np.float64)
        # A moderate bump — clears a low sensitivity threshold but not a high one.
        bump_idx = sr // 2
        mono[bump_idx:bump_idx + 5] = 0.01
        low_sensitivity = _find_peak_candidates(mono, sr, sensitivity=1.0)
        high_sensitivity = _find_peak_candidates(mono, sr, sensitivity=50.0)
        assert len(low_sensitivity) >= len(high_sensitivity)
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_analysis_tools.py -v -k FindPeakCandidates`
Expected: FAIL with `ImportError: cannot import name '_find_peak_candidates'`

- [ ] **Step 3: Write the minimal implementation**

Add to `reaper_mcp/tools/analysis_tools.py`, after `_find_silence_candidates`:

```python
def _find_peak_candidates(mono, sr: int, sensitivity: float) -> list:
    n = mono.size
    if n == 0:
        return []
    abs_samples = np.abs(mono)
    window = max(1, int(sr * 0.05))  # 50ms local baseline window
    kernel = np.ones(window) / window
    baseline = np.convolve(abs_samples, kernel, mode="same")
    floor = 1e-4  # absolute magnitude floor so near-zero baseline doesn't trivially flag noise
    threshold = baseline * sensitivity + floor
    flagged = abs_samples > threshold

    candidates = []
    i = 0
    while i < n:
        if flagged[i]:
            start = i
            while i < n and flagged[i]:
                i += 1
            end = i
            segment = abs_samples[start:end]
            peak_offset = int(np.argmax(segment))
            peak_idx = start + peak_offset
            magnitude = float(abs_samples[peak_idx])
            if magnitude > 0:
                magnitude_db = round(20.0 * np.log10(magnitude), 2)
            else:
                magnitude_db = None
            candidates.append({
                "time_sec": round(peak_idx / sr, 3),
                "magnitude_db": magnitude_db,
            })
        else:
            i += 1
    return candidates
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_analysis_tools.py -v`
Expected: PASS (all `TestFindSilenceCandidates` and `TestFindPeakCandidates` tests)

- [ ] **Step 5: Commit**

```bash
git add reaper_mcp/tools/analysis_tools.py tests/test_analysis_tools.py
git commit -m "feat: add peak/click-candidate detection helper (issue #4)"
```

---

### Task 3: `analyze_silence` tool

**Files:**
- Modify: `reaper_mcp/tools/analysis_tools.py` (add inside `register(mcp)`, after `analyze_clipping`)

**Interfaces:**
- Consumes: `_load_wav`, `_to_mono`, `_find_silence_candidates` (Task 1).
- Produces: `analyze_silence(wav_path: str, threshold_db: float = -40.0, min_duration: float = 0.3) -> dict` MCP tool.

- [ ] **Step 1: Write the tool**

In `reaper_mcp/tools/analysis_tools.py`, inside `register(mcp)`, add after `analyze_clipping` (after its closing `return {...}` block):

```python
    @mcp.tool()
    async def analyze_silence(wav_path: str, threshold_db: float = -40.0, min_duration: float = 0.3) -> dict:
        """Find candidate silence spans — amplitude at/below threshold_db for at least min_duration.

        Flags candidates for review; does not claim certainty (e.g. an
        intentional dramatic pause looks identical to a bad edit here).

        Args:
            wav_path: Path to a rendered WAV file.
            threshold_db: Silence threshold in dBFS. Must be <= 0. Default -40.0.
            min_duration: Minimum span length in seconds to flag. Default 0.3.
        """
        if threshold_db > 0:
            raise ReaperMCPError(ErrorCode.INVALID_PARAMETER, "threshold_db must be <= 0")
        if min_duration <= 0:
            raise ReaperMCPError(ErrorCode.VALUE_OUT_OF_RANGE, "min_duration must be > 0")
        samples, sr = _load_wav(wav_path)
        mono = _to_mono(samples.astype(np.float64))
        candidates = _find_silence_candidates(mono, sr, threshold_db, min_duration)
        total_silence = round(sum(c["duration_sec"] for c in candidates), 3)
        hint = (
            "No silence candidates found."
            if not candidates
            else f"{len(candidates)} silence candidate(s) found ({total_silence}s total)."
        )
        return {
            "threshold_db": threshold_db,
            "min_duration": min_duration,
            "candidates": candidates,
            "total_silence_sec": total_silence,
            "hint": hint,
        }
```

- [ ] **Step 2: Manual verification**

No REAPER connection needed for this one — it's pure file I/O + numpy, same as every other tool in this file. Run against any real WAV file you have:

```bash
python -c "
import asyncio
from mcp.server.fastmcp import FastMCP
import reaper_mcp.tools.analysis_tools as at
mcp = FastMCP('test')
at.register(mcp)
"
```

This just confirms `register()` still runs without error (no syntax mistakes). Full behavioral confidence comes from Task 1's `_find_silence_candidates` tests — `analyze_silence` itself is a thin wrapper with input validation, matching this file's existing `analyze_clipping`/`analyze_loudness` pattern of no dedicated tool-level test (see this file's existing tests, or lack thereof, before this plan).

- [ ] **Step 3: Commit**

```bash
git add reaper_mcp/tools/analysis_tools.py
git commit -m "feat: add analyze_silence tool (issue #4)"
```

---

### Task 4: `analyze_peaks` tool

**Files:**
- Modify: `reaper_mcp/tools/analysis_tools.py` (add inside `register(mcp)`, after `analyze_silence`)

**Interfaces:**
- Consumes: `_load_wav`, `_to_mono`, `_find_peak_candidates` (Task 2).
- Produces: `analyze_peaks(wav_path: str, sensitivity: float = 3.0) -> dict` MCP tool.

- [ ] **Step 1: Write the tool**

Add after `analyze_silence`:

```python
    @mcp.tool()
    async def analyze_peaks(wav_path: str, sensitivity: float = 3.0) -> dict:
        """Find click/pop candidates — short transients that spike well above the local baseline.

        Distinct from analyze_clipping (which catches sustained over-threshold
        content): this looks for isolated spikes against the surrounding
        signal, the actual signature of a click/pop rather than a loud
        musical passage.

        Args:
            wav_path: Path to a rendered WAV file.
            sensitivity: How many multiples of the local baseline counts as
                         a candidate. Higher = fewer, more confident candidates.
                         Must be > 0. Default 3.0.
        """
        if sensitivity <= 0:
            raise ReaperMCPError(ErrorCode.VALUE_OUT_OF_RANGE, "sensitivity must be > 0")
        samples, sr = _load_wav(wav_path)
        mono = _to_mono(samples.astype(np.float64))
        candidates = _find_peak_candidates(mono, sr, sensitivity)
        hint = (
            "No peak/click candidates found."
            if not candidates
            else f"{len(candidates)} peak/click candidate(s) found — listen and trim "
                 f"or use spectral repair if confirmed."
        )
        return {
            "sensitivity": sensitivity,
            "candidates": candidates,
            "hint": hint,
        }
```

- [ ] **Step 2: Manual verification**

Same as Task 3, Step 2 — confirm `register()` still runs cleanly. Behavioral confidence comes from Task 2's tests.

- [ ] **Step 3: Commit**

```bash
git add reaper_mcp/tools/analysis_tools.py
git commit -m "feat: add analyze_peaks tool (issue #4)"
```

---

### Task 5: `analyze_region_qc` tool — region clamping + composition

**Files:**
- Modify: `reaper_mcp/tools/analysis_tools.py` (add helper + tool)
- Test: `tests/test_analysis_tools.py`

**Interfaces:**
- Consumes: `_load_wav`, `_to_mono`, `_find_silence_candidates` (Task 1), `_find_peak_candidates` (Task 2).
- Produces:
  - `_clamp_region(start: float, end: float, total_duration_sec: float) -> tuple[float, float]` — clamps both bounds into `[0, total_duration_sec]`, swaps if `end < start` after clamping.
  - `analyze_region_qc(wav_path: str, regions: str) -> dict` MCP tool.

- [ ] **Step 1: Write the failing tests for `_clamp_region`**

Add to `tests/test_analysis_tools.py`:

```python
from reaper_mcp.tools.analysis_tools import _clamp_region


class TestClampRegion:
    def test_region_within_bounds_unchanged(self):
        assert _clamp_region(2.0, 5.0, 10.0) == (2.0, 5.0)

    def test_end_past_file_duration_clamped(self):
        assert _clamp_region(8.0, 15.0, 10.0) == (8.0, 10.0)

    def test_start_negative_clamped_to_zero(self):
        assert _clamp_region(-3.0, 5.0, 10.0) == (0.0, 5.0)

    def test_region_entirely_past_end_clamps_to_zero_length(self):
        assert _clamp_region(12.0, 15.0, 10.0) == (10.0, 10.0)

    def test_swapped_bounds_after_clamping_get_reordered(self):
        # start clamps to 10.0, end already 10.0 -> equal, no swap needed here,
        # but an inverted input (end < start) must still come out ordered.
        assert _clamp_region(6.0, 3.0, 10.0) == (3.0, 6.0)
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_analysis_tools.py -v -k ClampRegion`
Expected: FAIL with `ImportError: cannot import name '_clamp_region'`

- [ ] **Step 3: Write `_clamp_region` and the `analyze_region_qc` tool**

Add to `reaper_mcp/tools/analysis_tools.py`, after `_find_peak_candidates`:

```python
def _clamp_region(start: float, end: float, total_duration_sec: float) -> tuple:
    start = max(0.0, min(start, total_duration_sec))
    end = max(0.0, min(end, total_duration_sec))
    if end < start:
        start, end = end, start
    return start, end
```

Add `import json` to the top of `analysis_tools.py` if not already present (check the existing import block first — this file currently has no `json` import since every tool takes scalar args; `analyze_region_qc` is the first to take a JSON string param).

Then, inside `register(mcp)`, add after `analyze_peaks`:

```python
    @mcp.tool()
    async def analyze_region_qc(wav_path: str, regions: str) -> dict:
        """Per-region silence + peak/click candidate report — the post-production QC pass.

        regions is a JSON array populated from marker_get_all() (regions are
        markers with is_region: true), e.g.
        '[{"name":"Line 12","start":10.2,"end":14.8}]'. A region extending
        past the actual audio's duration is clamped, not rejected — the
        returned region's start/end reflect what was actually analyzed.

        Args:
            wav_path: Path to a rendered WAV file.
            regions: JSON array of {"name": str, "start": float, "end": float}.
        """
        try:
            parsed = json.loads(regions)
        except (json.JSONDecodeError, TypeError):
            raise ReaperMCPError(ErrorCode.INVALID_PARAMETER, "Invalid regions JSON")
        if not isinstance(parsed, list) or len(parsed) == 0:
            raise ReaperMCPError(ErrorCode.INVALID_PARAMETER, "regions must be a non-empty JSON array")
        if len(parsed) > 200:
            raise ReaperMCPError(ErrorCode.VALUE_OUT_OF_RANGE, f"Too many regions: {len(parsed)} (max 200)")
        for i, r in enumerate(parsed):
            if "start" not in r or "end" not in r:
                raise ReaperMCPError(ErrorCode.INVALID_PARAMETER, f"Region {i} missing start/end")

        samples, sr = _load_wav(wav_path)
        mono = _to_mono(samples.astype(np.float64))
        total_duration = mono.size / sr if sr else 0.0

        results = []
        total_flags = 0
        for r in parsed:
            start, end = _clamp_region(float(r["start"]), float(r["end"]), total_duration)
            start_idx = int(start * sr)
            end_idx = int(end * sr)
            segment = mono[start_idx:end_idx]

            silence = _find_silence_candidates(segment, sr, threshold_db=-40.0, min_duration=0.3)
            peaks = _find_peak_candidates(segment, sr, sensitivity=3.0)
            for c in silence:
                c["start_sec"] = round(c["start_sec"] + start, 3)
                c["end_sec"] = round(c["end_sec"] + start, 3)
            for c in peaks:
                c["time_sec"] = round(c["time_sec"] + start, 3)

            flag_count = len(silence) + len(peaks)
            total_flags += flag_count
            results.append({
                "name": r.get("name", ""),
                "start": start,
                "end": end,
                "silence_candidates": silence,
                "peak_candidates": peaks,
                "flag_count": flag_count,
            })

        hint = (
            f"{total_flags} candidate(s) across {len(results)} region(s) — "
            f"review flagged regions before final edit."
            if total_flags
            else f"No candidates found across {len(results)} region(s)."
        )
        return {
            "region_count": len(results),
            "regions": results,
            "total_flags": total_flags,
            "hint": hint,
        }
```

- [ ] **Step 4: Run all tests to verify they pass**

Run: `pytest tests/test_analysis_tools.py -v`
Expected: PASS (all tests in the file)

- [ ] **Step 5: Commit**

```bash
git add reaper_mcp/tools/analysis_tools.py tests/test_analysis_tools.py
git commit -m "feat: add analyze_region_qc tool (issue #4)"
```

---

### Task 6: CHANGELOG entry

**Files:**
- Modify: `CHANGELOG.md`

- [ ] **Step 1: Add the entry**

Under `## [0.6.0] - Unreleased`'s existing `### Added` section (already has entries for `project_get_change_count`, `items_apply`, and ReaScript integration from earlier this session), add:

```markdown
- **Edit-oriented QC analysis** — `analyze_silence` and `analyze_peaks`
  find silence and click/pop candidates in a rendered WAV file;
  `analyze_region_qc` runs both scoped to each region from `marker_get_all()`,
  producing a per-region punch list for post-production review. These flag
  *candidates* for human review, not certainties. Breath detection is
  deliberately not included — reliably telling a breath apart from quiet
  room tone needs spectral/ML classification, not an amplitude heuristic;
  it's left for a real ML-based approach later rather than shipping
  something unreliable under the same name. This whole feature needs
  real-world testing with post-production users before its output should
  be trusted as more than a rough first pass. (issue #4)
```

- [ ] **Step 2: Run the full test suite**

Run: `pytest tests/ -x -q`
Expected: PASS, all tests including the new `tests/test_analysis_tools.py` and every pre-existing test.

- [ ] **Step 3: Commit**

```bash
git add CHANGELOG.md
git commit -m "docs: changelog entry for edit-oriented QC analysis (issue #4)"
```

---

## Self-Review Notes (for whoever executes this plan)

- **Spec coverage:** `analyze_silence`, `analyze_peaks`, `analyze_region_qc`, shared detector helpers, region clamping, breath-detection deferral documented in the CHANGELOG (not just the spec) — all covered above.
- **numpy availability:** every test file in this plan uses `pytest.importorskip("numpy")` at module level, matching the fact that `analysis_tools.py` itself is entirely gated behind `_AVAILABLE`. If numpy isn't installed in the environment executing this plan, these tests skip cleanly rather than erroring — don't "fix" that by making numpy a hard dependency of the test file.
- **Type consistency:** `_find_silence_candidates` and `_find_peak_candidates` both take `(mono, sr, ...)` positionally in that order across every task that calls them (Tasks 3, 4, 5) — double-check this if implementing out of order.
- **`analyze_region_qc`'s time offsets:** silence/peak candidate times from the two shared helpers are relative to the *sliced segment* (0 = region start), and are shifted by `+ start` before being added to the response — this makes the reported times absolute (matching the region's own `start`/`end`, which are absolute project/file time from `marker_get_all()`), so a human reviewer can jump straight to that timestamp. Don't skip the offset step — it's the difference between a usable report and one where every region's candidates confusingly start near 0.
