---
type: run
title: Memory Stargraph Capture Link Drain SG-0175 explicit curl health failure run - 2026-07-30 .85
date: '2026-07-30'
automation_id: memory-stargraph-capture-link-drain
invocation_id: capture-link-drain-20260730t112556-0700-sg0175-curl-healthfail-85
mode: route_gate_failure
status: failed
linked_goal: goals/memory-stargraph-continuous-learning-local-knowledge-os
report_slug: reports/memory-stargraph-capture-link-drain-2026-07-30-sg0175-explicit-curl-health-failure-85
product_owner_notification_status: delivered_readback_confirmed
product_owner_notification_pending: false
---

# Memory Stargraph Capture Link Drain SG-0175 explicit curl health failure run - 2026-07-30 .85

## Invocation Evidence

- invocation_id: capture-link-drain-20260730t112556-0700-sg0175-curl-healthfail-85
- automation_id: memory-stargraph-capture-link-drain
- worker_task_id: 019facae-11ea-7521-ab27-e36e5cac5fbd
- goal_slug: goals/memory-stargraph-continuous-learning-local-knowledge-os
- start_time: 2026-07-30T11:25:56-07:00 America/Los_Angeles
- workspace_path: `/Users/toddy/memory-stargraph`
- branch: `main`
- local_head: 7d0da1b8fb1cc8af21f47887bfa4c37e5f91f637
- upstream_ref: origin/main
- upstream_head: 7d0da1b8fb1cc8af21f47887bfa4c37e5f91f637
- dirty_state: clean before local evidence files
- divergent_state: false
- source_sync_preflight: current
- source_sync_action: use_workspace
- required_script_existence: passed; `scripts/automation/yoda_gap_evaluator.py` present
- active_gate: `/Users/toddy/.bun/bin/gbrain list --tag active` returned `No pages found`

## Route And Command Boundary Evidence

- offline_prepare_command: `python3 scripts/automation/worker_persistence.py prepare health --json`
- offline_prepare_result: ok
- route_base_url: `https://100.100.126.85:8788`
- route_loopback: false
- route_source: `/Users/toddy/.codex/automations/memory-stargraph-wish-to-reallity/deployment-targets.env:MEMORY_STARGRAPH_DASHBOARD_URL`
- route_curl_flags: `-k`
- emitted_top_level_curl: `curl -sS --fail -k --max-time 8 https://100.100.126.85:8788/api/health`
- transport_contract: explicit visible top-level curl only; no Python-spawned curl, shell wrapper, loopback, direct gbrain, PostgreSQL, or approval fallback.

## Acceptance Failure

- explicit_curl_command: `curl -sS --fail -k --max-time 8 https://100.100.126.85:8788/api/health`
- explicit_curl_exit: 7
- explicit_curl_result: `curl: (7) Failed to connect to 100.100.126.85 port 8788 after 2 ms: Couldn't connect to server`
- terminal_status: failed_sg0175_acceptance_explicit_top_level_curl_health_unavailable
- safety_decision: stopped immediately before compaction, authoritative snapshot, active Run persistence, capture drain, enrichment candidate listing, reservation, mutation, terminal save/readback, final compaction, or tag mutation.
- python_spawned_curl_used: false
- shell_wrapper_network_used: false
- loopback_persistence_used: false
- direct_gbrain_used: false
- postgresql_fallback_used: false
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
- product_owner_notification_status: delivered_readback_confirmed
- product_owner_notification_pending: false
- product_owner_delivery_destination_task_id: 019faa62-6058-7643-b9cc-a2627083af07
- product_owner_delivery_readback: confirmed via `codex_app.read_thread`; Product Owner task item `688` contained the exact SG-0175 Curator compact payload.
