---
type: run
title: Memory Stargraph Capture Link Drain SG-0170 empty queue enrichment run - 2026-07-30 .85
date: '2026-07-30'
automation_id: memory-stargraph-capture-link-drain
invocation_id: capture-link-drain-20260730t091617-0700-a3bd5427-85
snapshot_invocation_id: a3bd5427-9477-4fbf-866c-509d71004179
mode: empty_queue_enrichment
status: failed
linked_goal: goals/memory-stargraph-continuous-learning-local-knowledge-os
report_slug: reports/memory-stargraph-capture-link-drain-2026-07-30-sg0170-empty-queue-enrichment-85
product_owner_notification_status: delivered_readback_confirmed
product_owner_notification_pending: false
---

# Memory Stargraph Capture Link Drain SG-0170 empty queue enrichment run - 2026-07-30 .85

## Active Run Evidence

- invocation_id: capture-link-drain-20260730t091617-0700-a3bd5427-85
- snapshot_invocation_id: a3bd5427-9477-4fbf-866c-509d71004179
- automation_id: memory-stargraph-capture-link-drain
- worker_task_id: 019facae-11ea-7521-ab27-e36e5cac5fbd
- goal_slug: goals/memory-stargraph-continuous-learning-local-knowledge-os
- start_time: 2026-07-30T09:16:17-07:00 America/Los_Angeles
- workspace_path: `/Users/toddy/memory-stargraph`
- branch: `main`
- local_head: f144d115e4f2422ec838d9aed8096492c9b4d240
- upstream_ref: origin/main
- upstream_head: f144d115e4f2422ec838d9aed8096492c9b4d240
- dirty_state: clean
- divergent_state: false
- deployed_service_version: V1.0.174
- source_sync_preflight: current
- selected_source_surface: clean/current workspace, SG-0170 bounded dashboard HTTP fallback, and dashboard-managed TLS service
- direct_gbrain_health: mixed; `gbrain list --tag active` returned `No pages found`, but one raw direct `gbrain get` hit `ECONNREFUSED 127.0.0.1:5433`.
- sg0170_acceptance:
  - compaction_normal_restricted_context: passed
  - snapshot_normal_restricted_context: passed exactly once
- initial_compaction: active_rows=11, failed_rows=0, created_archives=[], resumed_archives=[]
- first_authoritative_snapshot: rows=[]
- invocation_mode: empty_queue_enrichment
- status: active file created before candidate listing, selection, reservation, or enrichment mutation, but active Run persistence/readback failed before any candidate listing.

## Persistence Failure

- dashboard_entity_save_attempts:
  - 2026-07-30T09:17:00-07:00: `POST /api/entity-save/runs%2Fmemory-stargraph-capture-link-drain-2026-07-30-sg0170-empty-queue-enrichment-85` failed with `curl: (7) Failed to connect to 127.0.0.1 port 8788`.
  - 2026-07-30T09:18:00-07:00: retry failed with `curl: (7) Failed to connect to 127.0.0.1 port 8788`.
- dashboard_entity_raw_readback: reached server between save attempts and returned `Unknown entity`, confirming the active Run was not persisted.
- direct_gbrain_put_fallback: failed in restricted context with `Cannot connect to database: connect ECONNREFUSED 127.0.0.1:5433`.
- terminal_status: failed_empty_queue_active_run_persistence_unavailable
- safety_decision: stopped before candidate listing or enrichment mutation because reservation/active-Run readback contract could not be satisfied.

## Reservations

- none yet

## Results

- attempted_entities: 0
- enrichment_result: not_attempted
- final_compaction: active_rows=11, failed_rows=0, created_archives=[], resumed_archives=[]
- product_owner_notification_status: delivered_readback_confirmed
- product_owner_delivery:
  - target_task_id: 019faa62-6058-7643-b9cc-a2627083af07
  - send_status: accepted by Codex app
  - readback_status: confirmed
  - readback_evidence: Product Owner task showed Curator payload as `item-625`.
