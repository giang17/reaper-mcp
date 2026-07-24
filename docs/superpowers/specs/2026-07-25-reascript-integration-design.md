# ReaScript Integration — Design

Date: 2026-07-25
Status: Approved, pending implementation plan

## Background

GitHub issue #4 proposed several post-production
gaps in reaper-mcp's tool surface. Item 3 of that list:

> User script integration — discover local ReaScripts (scan a scripts
> directory, parse headers), run registered actions by name/ID, and a
> result-return convention (e.g. ExtState) so outcomes are visible to the
> agent. This would unlock years of accumulated user scripts without
> porting each one.

The repo owner chose to build this in-house rather than leave it to the
external contributor ("a lot of people would want this"), reasoning that
users who have invested significant time writing their own ReaScripts
want the AI able to trigger that existing work, not have it re-implemented
as new MCP tools one at a time.

This is the first reaper-mcp feature that gives the AI a path to
executing local script code rather than calling fixed, audited REAPER API
functions through our own handlers — a materially different risk category
than anything else in the tool surface, so the trust boundary was worked
out carefully before any implementation detail.

## Trust boundary

Two shapes were considered:

1. **Only already-registered actions** — discovery limited to scripts the
   user already manually loaded into REAPER's own Actions list. Simplest,
   safest, but doesn't cover scripts sitting unregistered in the Scripts
   folder (the common case for anything not yet bound to a toolbar
   button/shortcut).
2. **Scan REAPER's own Scripts folder, auto-register on demand** —
   broader coverage, chosen. Critically, the scanned/executable location
   is **hard-coded to `reaper.GetResourcePath() .. "/Scripts"`** — never
   an arbitrary, AI- or conversation-supplied path. The AI cannot be
   directed (by the user, by a prompt-injected document, by anything) to
   scan or execute scripts from anywhere else. The trust boundary is
   physical: whatever the user has actually placed in REAPER's own
   Scripts folder, the same folder REAPER's own "Load ReaScript" menu
   item and ReaPack both use.

## Architecture

Three new Lua handlers, one new Python tool module
(`reaper_mcp/tools/script_tools.py` — kept separate from existing modules
so future scripting-related features have an obvious home).

### `script_list(filter: str = "")`

Recursively scans the Scripts folder for `.lua` and `.eel` files only
(`.py` excluded — Python ReaScripts depend on the user's separate
`reaper_python` setup being configured, and fail silently with no clean
error back to us if it isn't). Extension filtering happens Lua-side
during the walk.

For each match, reads the first ~20 lines and parses ReaPack-style header
comments (`@description`, `@about`) if present — this is a de facto
community convention already used by ReaPack-indexed scripts, not
something we're inventing. Pure text parsing; nothing is executed or
loaded as code during discovery.

Capped at 300 results (matching the `max_results`-style ceilings already
used elsewhere, e.g. `item_get_all`). `filter` is an optional
case-insensitive substring match against path + description, for
libraries larger than the cap (a full ReaPack install can have thousands
of scripts).

Returns per script: `{path (relative to Scripts/), description}`.

**Correction found during implementation:** the original draft of this
spec also included a `registered` boolean (already has a command_id or
not). REAPER's only relevant API, `AddRemoveReaScript(add, sectionID,
scriptfn, commit)`, has side effects in both directions — `add=true`
registers, `add=false` *de-registers* — there is no side-effect-free way
to query registration status. Checking it during discovery would mean
either registering every script just by listing them (defeats discovery
being read-only) or risking de-registering the user's existing actions.
Dropped from the output.

### `script_run(script_path: str, wait_seconds: float = 5.0)`

`script_path` must be one of the relative paths `script_list` returned.
Re-validated server-side with a new containment check, same philosophy as
`reaper_mcp_shared/path_safety.py`'s existing denylist logic but scoped
differently: resolve `script_path` against the Scripts folder and require
the result stays inside it, rejecting `../` traversal — rather than
`path_safety.py`'s job of blocking a fixed list of system directories
from arbitrary absolute paths. Likely lands as a small sibling helper
next to `safe_path`, not a reuse of `safe_path` itself.

Execution flow:

1. Python tool validates `script_path` shape and `wait_seconds` bounds
   (0 <= wait_seconds <= 30, say — an explicit ceiling so a bad value
   can't turn this into an unbounded wait).
2. Python calls Lua `script_run_start`: registers the script via
   `reaper.AddRemoveReaScript(true, section, full_path, true)` if not
   already registered (idempotent — safe to call on every invocation),
   clears the known ExtState result key, runs it via
   `reaper.Main_OnCommand(command_id, 0)`, returns immediately with
   `{command_id}`. This call is fast and does not block REAPER's main
   thread beyond whatever the script itself does synchronously before
   returning control (see "Concurrency" below).
3. Python then polls a second, cheap Lua call `script_read_result`
   (a single non-blocking `reaper.GetExtState` read) every ~200ms up to
   the `wait_seconds` budget, stopping early if a result appears.
4. Returns `{command_id, ran: true, result: <parsed or raw or null>,
   result_found: bool}` to the AI as a single tool call — the multi-call
   polling underneath is invisible to the caller.

**Why polling lives in Python, not Lua:** this bridge runs on a single
`reaper.defer` loop (`reaper_scripts/reaper_mcp_server.lua`'s
`main_loop`) — every command handler runs to completion before the next
one starts. A blocking multi-second wait *inside* a Lua handler would
freeze REAPER's UI (and potentially audio) for that entire window, on
every script run. Splitting "fire" and "read result" into two fast Lua
calls, with the wait/retry loop implemented as `asyncio` polling on the
Python side, keeps every individual Lua-side call near-instant.

### Result convention (documented, not enforced)

A script that wants to report a result back to the AI calls, before
finishing:

```lua
reaper.SetExtState("reaper_mcp_script_result", "last_result", <string>, false)
```

(`false` = ephemeral, not persisted to the project or REAPER's ini.) We
attempt `json.decode` on whatever's there; on failure, return it as a raw
string. Scripts that don't opt into this — including the large number of
existing scripts written with no knowledge of reaper-mcp, and any
background/`defer`-based script that hasn't finished by the time the
poll window expires — simply come back as `result: null, result_found:
false`. This is an explicit, documented limitation, not a bug: retrofit
capture for arbitrary pre-existing scripts isn't attempted.

## Concurrency

The existing IPC layer already serializes all commands through a single
cross-process mutex (`_ipc_mutex` in `reaper_client.py`) — only one
command executes at a time end-to-end. This means a single fixed ExtState
key (`"last_result"`) is safe with no collision risk between rapid or
concurrent calls; there's never more than one `script_run` in flight.

It also means a script that itself blocks synchronously for a long time
(rare, but possible — e.g. a script with its own modal dialog) will hold
up the entire MCP command queue for that duration, the same way any other
slow Lua-side operation already can. Not a new risk this feature
introduces, but worth noting: `script_run` should document that it
inherits whatever blocking behavior the target script has.

## Security

- Discovery and header-parsing execute nothing — plain file reads only.
- Execution is confined to REAPER's own Scripts folder, hard-coded
  server-side, never an AI- or user-conversation-supplied path.
- `script_path` traversal-checked before use, independent of what
  `script_list` returned.
- `.py` scripts excluded from both discovery and execution.
- No new dynamic-code-eval surface introduced on our side — registration
  goes through REAPER's own `AddRemoveReaScript` API, the same mechanism
  REAPER's own "Load ReaScript" menu action uses. We are not writing an
  interpreter or eval path of our own.
- This feature is a strictly bigger capability than anything else in the
  tool surface (it can run any code the user has placed in their own
  Scripts folder) — `00_core.md`'s existing guidance on confirming before
  destructive/hard-to-reverse actions should be extended to mention
  `script_run` explicitly, since its blast radius is unknowable ahead of
  time (a script could do anything a REAPER script can do).

## Error handling

- `script_list`: malformed/unreadable individual files are skipped with
  no metadata (path + empty description) rather than failing the whole
  scan — matches the tolerant-scan convention used elsewhere
  (`_load_state_safe` in `compose_edit_tools.py`).
- `script_run`: unknown/non-existent `script_path` → `ReaperMCPError
  INVALID_PARAMETER` before anything reaches Lua. Registration failure
  (`AddRemoveReaScript` returns a falsy command_id) → clear error naming
  the path. `wait_seconds` out of bounds → `VALUE_OUT_OF_RANGE`.

## Testing

Unit tests (mocked client, matching existing test conventions):

- `script_list`: `.py` files excluded, header parsing with/without
  `@description`/`@about` tags, `filter` substring matching, result cap.
- `script_run`: path-traversal rejection (`../../../whatever`),
  `wait_seconds` bounds validation, poll-loop stops early on result found,
  poll-loop returns `result_found: false` after timeout with no result,
  JSON-vs-raw-string result fallback.
- Lua handlers follow the existing `handlers["..."] = function(p) ... end`
  dispatch-table pattern already used throughout
  `reaper_mcp_server.lua`.

## Files touched

- `reaper_scripts/reaper_mcp_server.lua` — 3 new handlers: `script_list`,
  `script_run_start`, `script_read_result`.
- `reaper_mcp/tools/script_tools.py` — new module.
- `reaper_mcp/instructions/00_core.md` — extend the existing
  confirm-before-destructive-actions guidance to cover `script_run`.
- `tests/test_script_tools.py` — new.
- `CONTRIBUTING.md` — brief mention alongside the external-generation-
  pipeline guidance already added this session.
- `CHANGELOG.md` — entry under `[0.5.0]`, referencing issue #4.

## Explicitly out of scope (this pass)

- `.py` ReaScript support (documented above).
- Passing arguments/parameters into a script beyond running it.
- Unregistering scripts, or any other action-list management.
- Capturing results from genuinely background/`defer`-based scripts that
  outlive the poll window.

These are natural follow-ups if this proves useful, not required for a
first version.
