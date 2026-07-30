---
type: run
title: Memory Stargraph Capture Link Drain SG-0173 route readback failure run - 2026-07-30 .85
date: '2026-07-30'
automation_id: memory-stargraph-capture-link-drain
invocation_id: capture-link-drain-20260730t103212-0700-sg0173-routefail-85
mode: route_gate_failure
status: failed
linked_goal: goals/memory-stargraph-continuous-learning-local-knowledge-os
report_slug: reports/memory-stargraph-capture-link-drain-2026-07-30-sg0173-route-readback-failure-85
product_owner_notification_status: delivered_observed_without_exact_payload_echo
product_owner_notification_pending: false
---

# Memory Stargraph Capture Link Drain SG-0173 route readback failure run - 2026-07-30 .85

## Invocation Evidence

- invocation_id: capture-link-drain-20260730t103212-0700-sg0173-routefail-85
- automation_id: memory-stargraph-capture-link-drain
- worker_task_id: 019facae-11ea-7521-ab27-e36e5cac5fbd
- goal_slug: goals/memory-stargraph-continuous-learning-local-knowledge-os
- start_time: 2026-07-30T10:32:12-07:00 America/Los_Angeles
- workspace_path: `/Users/toddy/memory-stargraph`
- branch: `main`
- local_head: 01d95eb5eb27cd9b3eb8bbc7dcf5cf81bab95b27
- upstream_ref: origin/main
- upstream_head: 01d95eb5eb27cd9b3eb8bbc7dcf5cf81bab95b27
- dirty_state: clean before local evidence files
- divergent_state: false
- deployed_service_version: V1.0.174
- source_sync_preflight: current
- source_sync_action: use_workspace
- required_script_existence: passed; `scripts/automation/yoda_gap_evaluator.py` present
- selected_source_surface: clean/current workspace at SG-0173 commit and dashboard-managed TLS service
- service_health: `https://100.100.126.85:8788/api/health` returned `ok=true`, `loaded=true`, `ui_version=V1.0.174`, non-null `source`, non-null `stats`
- active_gate: `/Users/toddy/.bun/bin/gbrain list --tag active` returned `No pages found`

## Acceptance Failure

- route_command: `python3 scripts/automation/worker_persistence.py routes --json`
- route_result: failed before returning JSON route readback.
- error: `WorkerPersistenceError: configured non-loopback worker API routes were unavailable; refusing loopback fallback`
- required_route: `https://100.100.126.85:8788` from private config
- route_readback_proved_required_url: false
- terminal_status: failed_sg0173_acceptance_non_loopback_route_unavailable
- safety_decision: stopped immediately before compaction, authoritative snapshot, active Run persistence, capture drain, enrichment candidate listing, reservation, mutation, terminal save/readback, final compaction, or tag mutation.
- direct_gbrain_used: false
- approval_requested: false
- queue_mutation: none

## Results

- compaction_ran: false
- authoritative_snapshot_taken: false
- frozen_items: not_inspected
- captures_completed: 0
- captures_failed: 0
- enrichments_attempted: 0
- reservations_saved: false
- active_run_saved: false
- terminal_run_saved: false
- report_saved: false
- final_compaction_ran: false
- explicit_active_tag_release: no active Run was persisted; active-tag gate before failure showed `No pages found`
- product_owner_notification_status: delivered_observed_without_exact_payload_echo
- product_owner_notification_pending: false
- product_owner_delivery_destination_task_id: 019faa62-6058-7643-b9cc-a2627083af07
- product_owner_delivery_attempt: `codex_app.send_message_to_thread` returned success for destination task `019faa62-6058-7643-b9cc-a2627083af07`.
- product_owner_delivery_readback: exact compact payload echo was not separately visible in recent task readback, but Product Owner commentary in the active turn stated that SG-0173 canonical Curator was rejected and identified the same `worker_persistence.py routes` Python-subprocess network boundary.
