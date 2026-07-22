# Task 3 Report: Shared Redis Connection Gate

## Scope

Implemented the shared synchronous `RedisConnectionGate` and its immutable
`ConnectionOperation`, `ConnectionTarget`, and `ConnectionPermit` values. The gate is
injectable through `ApplicationContainer`; routine tests receive `FakeConnectionGate`
and never contact Redis or a network device.

The existing `reserve_terminal_session()` and `release_terminal_session()` methods and
their process-local counter remain unchanged for Task 5.

## GitNexus impact before edits

- `ApplicationContainer`: MEDIUM, 20 impacted symbols/files, 10 direct importers, no
  indexed execution processes.
- `Settings`: MEDIUM, 30 impacted symbols/files, 8 direct importers, no indexed
  execution processes.
- `ApplicationContainer.__init__`: LOW, no indexed callers.
- `Settings.validate_runtime_security`: LOW, no indexed callers.
- `backend/tests/conftest.py::container`: LOW, no indexed callers.

No HIGH or CRITICAL result required an edit stop.

## Delivered behavior

- Redis WATCH/MULTI/EXEC admission with eight bounded retries and fail-closed
  `connection_gate_unavailable` handling.
- Redis server time read inside each watched transaction.
- Rolling connection-test and terminal-open windows: five admissions in 60 seconds;
  the sixth is denied.
- Three authentication failures in 60 seconds create a tuple-scoped 60-second
  cooldown; authentication success clears only that endpoint/profile failure counter.
- Global SSH capacity uses `MAX_DEVICE_CONNECTIONS`; per-device SSH, global terminal,
  and per-device terminal defaults are all three.
- Permit keys and global/device ZSET members expire after the bounded 3,900-second
  default TTL. Expired ZSET members are pruned in the admitting transaction.
- Release is idempotent and removes only the named permit member.
- Endpoint/profile SHA-256 is computed before Redis access from lowercase
  `host:port:profile-id`. Redis keys contain only static dimension labels, the digest,
  and opaque UUIDs; no address, hostname, credential, or terminal content is stored.
- All gate settings are available in `Settings`, `.env.example`, and the shared
  API/worker/migration Compose environment. The previous
  `DEVICE_CONNECTION_LIMIT` name remains an accepted compatibility alias.

## TDD evidence

- Initial RED: `test_connection_gate.py` failed collection because the gate module did
  not exist.
- Config RED: two tests failed on missing settings and Compose/env exposure.
- Container RED: injection test failed because `ApplicationContainer` did not accept
  `connection_gate`.
- Terminal invariant RED: a terminal target without a device ID raised an unsanitized
  `ValueError`; it now fails closed as `connection_gate_unavailable`.
- Release mutation check: replacing exact `ZREM` with whole-key deletion made
  `test_release_removes_only_the_named_permit` fail; restoring member-specific release
  made it pass.
- Fake release-call RED: de-duplicating recorded calls hid a caller double-release; the
  fake now records every call while the concrete gate remains idempotent.
- Focused GREEN: 24 passed.

## Verification

- `python -m ruff check --no-cache .`: passed.
- `pyright`: 0 errors, 0 warnings.
- `pytest`: 169 passed, 1 separately opted-in lab test skipped.
- Production Compose config: passed.
- Development Compose overlay config: passed.
- No lab opt-in was set and no real device, scan, authentication, or configuration was
  attempted.

## GitNexus pre-commit scope

`detect_changes --scope compare --base-ref 14619de` against the existing main index
reported MEDIUM risk: 10 files, 12 indexed symbols, and four affected flows. The flows
are the expected API/worker settings and container construction paths through
`_connection_parameters`, `execute_job`, `get_settings`, and `create_session_factory`.
Adjacent unchanged symbols reported from shared hunks (`session_factory`,
`snapshot_store`, `trusted_origins`, `_read_database_password`, and `FakeTransport`)
were inspected; their bodies are unchanged. The new gate symbols are not present in the
older `cb90e06` index, as expected. No unexpected execution flow was found.
