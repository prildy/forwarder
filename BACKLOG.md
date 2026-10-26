# Backlog

The orchestrator agent picks the top unchecked item each cycle and ticks it (`- [x]`)
in its PR. Edit this file to steer the agent — keep items **small** (under ~300 changed
lines), specific, and verifiable by `pytest`.

Paths are relative to the repo root; the forwarder app lives in `files/`.

- [x] Add unit tests for `resolver.py` edge cases that aren't yet covered in `files/tests/test_resolver.py` (document which paths are untested before adding).
- [x] Add tests for the `Signal` Pydantic model in `files/main.py` — reject malformed schema-2.0 / 2.1 payloads (missing blocks, out-of-range values) and assert the 422 path.
- [ ] Harden `files/main.py` webhook dedupe (`event_id` / `symbol+timeframe+bar_time`) against duplicate alerts arriving out of order; add a regression test.
- [ ] Audit `files/main.py` for any DB call not wrapped in `asyncio.to_thread` and move it off the event loop (per `files/CLAUDE.md`); add a test if feasible.

<!--
Format: one actionable item per line. Good items name the file/function and the
observable behaviour to change, e.g.:
- [ ] add input validation to `parse_signal()` in files/main.py; reject bar_time in the future with a 422
Avoid: anything touching .github/workflows/, .claude/, CLAUDE.md, .env*, or adding
new runtime dependencies to files/requirements.txt without justification in the PR.
-->
