# Archive Report: trade-journal-postgres

**Change**: trade-journal-postgres
**Date archived**: 2026-07-01
**Verdict**: SHIP (verify-report was SHIP-WITH-FIXES; the flagged fix W-01 was resolved by the follow-up change `close-source-by-price`, now archived)
**Artifact store**: openspec + engram

## Summary

Postgres trade journal with a separate reconciler process, delivered as a single PR
(size:exception). Two ports (ISP): `TradeJournalPort` (record_entry, record_result,
open_entries) and `TradeHistoryPort` (closed_trade by deal_id). Postgres adapter writes
disjoint columns (entry vs result) so the operator and reconciler never conflict. Schema
migrations run idempotently on startup. docker-compose + Makefile bring the DB up with
`make up`.

## Fix trail

The verify-report verdict was SHIP-WITH-FIXES. The single blocking finding, W-01
(`close_source` persisted with an ambiguous/incorrect value because Capital's
`/history/activity` `source` field cannot distinguish SL from TP), was NOT patched inside
this change. It was resolved definitively by the subsequent SDD change
`close-source-by-price`, which derives the close source by nearest price level and is
already archived at `archive/2026-07-01-close-source-by-price`. With that change in place
the full suite is green.

## Test evidence at archive

`cd operator && .venv/bin/python3 -m pytest` → 113 passed, 8 skipped (skips are the
`EURUSD_FIXTURE_PATH`- and `DATABASE_URL`-gated integration tests).

## Artifacts

- proposal.md, spec.md, design.md, tasks.md, apply-progress.md, verify-report.md
- Engram observations for this change (proposal/spec/design/tasks/apply-progress/verify-report)

## Manual deployment gate (user responsibility)

- Empirically verify what Capital returns on a real TP close via `/history/activity`
  (not done autonomously — no real orders placed).
- Backfill any pre-existing mislabeled `close_source` rows if desired (deferred).
