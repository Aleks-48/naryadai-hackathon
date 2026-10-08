# Acceptance archive merge notes — 2026-10-07

## Input and scope

The local acceptance archive was naryadai-hackathon-dcc73dd519fef484adb19330c373136f57510b47.zip, SHA-256 c95434a329f199ca7b94165cf4f82942f977d5e7380179b6efd77fad2395975f. It passed ZIP CRC and safe-path checks before extraction. The pinned r3 source archive retained as the baseline has SHA-256 163dd2f059879ecfd77bf76445b6997457068842221b56cf33df21a77c0a9280.

Only the isolated Temp working copy was changed. The main project tree, pinned r3 archive, and running preview were not changed. The input ZIP has no .git metadata; the private GitHub repository returned 404, so the archive bytes are verified but their relationship to a remote commit cannot be independently confirmed.

## Integrated behavior

- Optional, length-bounded master issuance comment is persisted and audited. It is excluded from LLM review context.
- LLM text review has a strict separate report_score and reason. Rules-only never invents an AI score; semantic matching remains explicitly unverified and requires master review.
- The master must submit a human 1–5 rating and comment when closing. Later rating edits preserve previous score/reason in the audit log.
- Reports use event-time windows for shifts and refusals, separate issued/completed/closed counts, retain current workload independently from the report window, clip pauses/downtime to the selected period, and support explicit worker/equipment/area filters.
- Equipment downtime may be linked to an order with equipment consistency, role checks, and idempotent duplicate handling. Legacy unlinked downtime rows remain valid.
- Order cards and report intervals expose their linked downtime information.

## Preserved r3 safeguards

- Photo rows used as evidence remain filtered to active=1.
- Duplicate photo detection and audit behavior remain in place, including atomic duplicate-before-photo rejection, the five-unique-photo cap, legacy duplicate retirement, and superseding stale after-photos when work returns for rework.
- Accessibility cascade tests and the r3 mobile CSS remain present.
- The new issuance and reporting fields do not alter the order state machine or grant the AI authority to approve work, safety, or permits.
- All seeded work, users, equipment, references, and report patterns are synthetic. Photos are not proof of repair correctness or capture freshness.