# Build verification · 5 October 2026

This local source snapshot carries the Telegram order list and the follow-up criteria package. The earlier Telegram minimal v1 Library item and separate P0v3 artifact remain separate and were not overwritten.

## Follow-up criteria package

- Completion adds optional `worker_completion_comment`, distinct from the master's `closure_comment`. The nullable column preserves legacy rows as `NULL`; old clients may omit it. New values must be JSON strings up to 1000 characters; empty is allowed. PWA, Streamlit, API response and `complete` audit event carry the field independently.
- New unscheduled issue requests require a validated, unique `before_photo` image before the order can be committed. The order, image row/file, audit and notification share one SQLite transaction; failures remove the file and roll back database rows. Existing photo upload authorization and duplicate detection remain, including the pre-acceptance replacement route.
- Added revisioned manual ordering per responsible master plus worker/brigade scope. Reorder validates the complete active ID set inside a SQLite write transaction; assignment/status changes invalidate stale writes and status/priority/deadline remain independent. Bootstrap reads orders, saved positions, and revision in one SQLite read snapshot so it cannot pair stale IDs with a newer revision.
- Streamlit move buttons use revision-specific widget IDs and bind an immutable context tuple (scope, revision, full target order, selected order, direction). If a click reaches a still-current widget after a concurrent write, its old revision gets 409 with a refresh notice and is never retried. If the five-second fragment has already refreshed, a delayed WidgetStates event carries the old widget ID and is discarded instead of being rebound to the new queue context.
- Text review and aggregate shift-summary adapters already exist. Current verification uses local fakes/rules-only; no actual model credentials or external calls were used. `.env.example`, README and requirements mapping list the settings needed for an owner-authorized live test.

## Telegram behavior

- The `/site` button accepts the exact `https://legless-bennie-sheepish.ngrok-free.dev` host only when both that URL and `NARYADAI_ALLOW_DEMO_TUNNEL=1` are explicitly configured. All other tunnel hosts remain blocked; HTTPS, credentials, root-path, query, port, and IP checks remain in force. This is a fixed hostname allowlist and performs no DNS lookup.
- `/orders [page]`, «Мои наряды», «Предыдущая страница» and «Следующая страница» return five rows at a time. Worker results use direct assignments; master results use current responsible-master assignment; manager results match the existing read-only all-orders access.
- Telegram buttons contain no callback payloads. Each click is a fresh read, and the current access scope is checked again immediately before delivery. Assignment-set changes invalidate queued list responses; role, active-account or chat changes also cancel them.
- No Telegram command changes an order. The master still makes the final acceptance decision through the web panel.
- Intake applies a limit of 120 private updates/minute per shared SQLite database, a cap of 100 pending command/help messages, and a hard budget of 20,000 accepted private update IDs. At the inbox cap the webhook acknowledges but ignores new updates until database maintenance. Dedupe markers are not automatically removed.
- Tests use a loopback fake webhook and fake send function. No Bot API token, real webhook registration or external message was used.

## Checks

- `python -m unittest -q` - 63 tests passed, including bootstrap/read-vs-write and stale-queue races, P0/Telegram regressions, and exact demo-host opt-in validation with lookalike, suffix, trailing-dot, empty/nonempty userinfo, redirect-path, scheme, port, ambiguous/private IP, and other-tunnel rejections.
- `node --test tests/test_frontend_races.js` — 30 tests passed, including one-request unscheduled creation with compressed before photo, no-photo rejection, and single-flight queue moves.
- python tests/run_streamlit_apptest.py - 6 tests passed, including a real delayed WidgetStates event captured at revision N and delivered after the five-second fragment rerender at N+1; the revision-specific widget ID is discarded, with no reorder request or audit event. An immediate stale click still shows the handled 409 warning.
- `python -m py_compile server.py streamlit_app.py tests/test_app.py tests/run_streamlit_apptest.py`, `node --check static/app.js`, `node --check tests/test_frontend_races.js` and `git diff --check` passed; PWA shell smoke is included in the Python suite. Service-worker cache name is `naryadai-shell-v12`. Streamlit keeps the unscheduled photo picker visible before the first submit; PWA templates synchronize its visibility and required state.

## QA artifact
- New isolated demo-site guard patch candidate: `deliverables/NaryadAI-demo-site-guard-20261005.zip`, a full 36-file archive based on the queue QA snapshot; it preserves the queue race code/tests and adds only the exact demo-host URL guard and its regression coverage.

- Separate 36-file source archive: `deliverables/NaryadAI-manual-queue-20261005.zip`. Its adjacent manifest records the archive SHA-256, every source-entry hash, and the CRC verification result.
- The earlier criteria snapshot remains byte-identical with SHA-256 `401f43e84f32dbe1df58ba866cef4a28914cefe6c4a37ada406e255e74a142ec`; it was not overwritten.

## Snapshot limits

This is a verified local MVP snapshot, not a production deployment. The finite inbox budget has no automatic cleanup policy; maintenance must preserve replay protection when resetting it. Actual Telegram delivery, Android-device rendering, external LLM operation, public hosting, visual browser/device rendering and real plant data have not been verified.
