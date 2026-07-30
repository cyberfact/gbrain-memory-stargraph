---
type: run
title: Memory Stargraph Capture Link Drain compaction failed run - 2026-07-30 .85
date: '2026-07-30'
automation_id: memory-stargraph-capture-link-drain
invocation_id: capture-link-drain-20260730t071509-0700-85
mode: pre_snapshot_compaction
status: failed
linked_goal: goals/memory-stargraph-continuous-learning-local-knowledge-os
report_slug: reports/memory-stargraph-capture-link-drain-2026-07-30-compaction-failed-85
product_owner_notification_status: pending_unacknowledged_delivery
product_owner_notification_pending: true
---

# Memory Stargraph Capture Link Drain compaction failed run - 2026-07-30 .85

## Source-Sync Evidence

- invocation_id: capture-link-drain-20260730t071509-0700-85
- automation_id: memory-stargraph-capture-link-drain
- worker_task_id: 019facae-11ea-7521-ab27-e36e5cac5fbd
- start_time: 2026-07-30T07:15:09-07:00 America/Los_Angeles
- workspace_path: `/Users/toddy/memory-stargraph`
- branch: `main`
- local_head: 365194e736c66beac675f3c9edc351ffc05f442f
- upstream_ref: origin/main
- upstream_head: 365194e736c66beac675f3c9edc351ffc05f442f
- dirty_state: clean
- divergent_state: false
- divergence_counts: `0 0`
- deployed_service_version: V1.0.174
- service_health: dashboard-managed TLS `/api/health` returned `ok=true`, `loaded=true`, non-null `source`, and non-null `stats`.
- required_script_existence: source-sync helper reported `missing_paths=[]` and `script_path=scripts/automation/yoda_gap_evaluator.py`.
- selected_source_path: `/Users/toddy/memory-stargraph`
- selected_source_surface: clean/current workspace and dashboard-managed TLS service.
- action_taken: attempted required pre-snapshot compaction; terminalized when compaction failed before snapshot.

## Coordination Evidence

- direct_active_gate_attempt: `/Users/toddy/.bun/bin/gbrain list --tag active` failed with `Cannot connect to database: connect ECONNREFUSED 127.0.0.1:5433`.
- dashboard_active_gate_fallback: `/api/search?q=active` and `/api/graph` returned no active Run pages; returned only old learning pages containing active-tag text.
- capture_list_raw_read: `/api/entity-raw/notes%2Fmemory-starmap-capture-list` succeeded and showed the visible parent capture rows were completed.

## Failure

- attempted_command: `python3 scripts/automation/manage_capture_backlog.py compact --apply --json`
- result: failed before snapshot.
- stderr: `error: Cannot connect to database: connect ECONNREFUSED 127.0.0.1:5433. Fix: Check your connection URL in ~/.gbrain/config.json`
- gbrain_persistence: dashboard HTTP `POST /api/entity-save/...` attempted for Run and report after terminalization; both failed with `curl: (7) Failed to connect to 127.0.0.1 port 8788`.
- terminal_status: `failed_pre_snapshot_compaction_gbrain_db_unavailable`

## Worker Actions Not Performed

- authoritative snapshot: not taken
- frozen request ids: none established
- transitions to `capturing`: none
- captures completed: 0
- captures failed: 0
- enrichment reservations: none
- enrichments attempted: 0
- post-snapshot ids: none established because no snapshot was taken

## Product Owner Delivery

- status: pending_unacknowledged_delivery
- destination_task_id: 019faa62-6058-7643-b9cc-a2627083af07
- attempted_timestamp: 2026-07-30T07:17:00-07:00 America/Los_Angeles
- send_status: Codex app accepted `send_message_to_thread`.
- readback_status: not verified; `read_thread` returned older Product Owner turns and `wait_threads timeoutMs=0` showed a new in-progress turn with no visible assistant message.
- compact_payload: Product Owner delivery from Memory Stargraph Knowledge Curator (.85), `terminal_status=failed_pre_snapshot_compaction_gbrain_db_unavailable`, source-sync clean/current at `365194e736c66beac675f3c9edc351ffc05f442f`, health V1.0.174 loaded true, compaction failed with `ECONNREFUSED 127.0.0.1:5433`, no snapshot or queue mutation, intended Run/report slugs not GBrain-persisted due dashboard `curl: (7)`.
