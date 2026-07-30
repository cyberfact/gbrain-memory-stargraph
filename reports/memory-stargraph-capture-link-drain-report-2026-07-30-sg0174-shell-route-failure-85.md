---
type: report
title: Memory Stargraph Capture Link Drain SG-0174 shell route failure report - 2026-07-30 .85
date: '2026-07-30'
automation_id: memory-stargraph-capture-link-drain
invocation_id: capture-link-drain-20260730t110617-0700-sg0174-shell-routefail-85
mode: route_gate_failure
status: failed
run_slug: runs/memory-stargraph-capture-link-drain-2026-07-30-sg0174-shell-route-failure-85
linked_goal: goals/memory-stargraph-continuous-learning-local-knowledge-os
product_owner_notification_status: delivered_readback_confirmed
product_owner_notification_pending: false
---

# Memory Stargraph Capture Link Drain SG-0174 shell route failure report - 2026-07-30 .85

## Outcome

- Terminal status: `failed_sg0174_acceptance_shell_route_unavailable`.
- Source-sync passed: clean `main`, local and `origin/main` both at `2a9ee17d0fc20d99f0b806864e58159b7c9cf459`.
- Dashboard TLS health passed through required non-loopback URL using top-level curl: `https://100.100.126.85:8788/api/health` returned `ok=true`, `loaded=true`, `ui_version=V1.0.174`, non-null `source`, non-null `stats`.
- Active-tag gate passed: `gbrain list --tag active` returned `No pages found`.
- Required shell-helper route readback failed before compaction or snapshot.
- No approval was requested.
- No Python-spawned curl, direct GBrain, or PostgreSQL fallback was used for persistence.
- No queue inspection or mutation occurred after the route failure.

## Acceptance Failure Evidence

- Command: `bash scripts/automation/worker_persistence.sh routes --json`
- Exit: `1`
- Required proof: route readback must prove `base_url=https://100.100.126.85:8788`, `loopback=false`, and source private `deployment-targets.env:MEMORY_STARGRAPH_DASHBOARD_URL`.
- Proof obtained: false.
- Error lines:
  - `curl: (7) Failed to connect to 100.100.126.85 port 8788 after 2 ms: Couldn't connect to server`
  - `curl: (7) Failed to connect to 127.0.0.1 port 8788 after 0 ms: Couldn't connect to server`
  - `curl: (6) Could not resolve host: default_loopback`
  - `curl: (7) Failed to connect to 127.0.0.1 port 8788 after 0 ms: Couldn't connect to server`
  - `configured non-loopback worker API routes were unavailable; refusing loopback fallback`
- SG-0174 acceptance required route readback before continuing. Because route readback failed, the worker stopped immediately.

## Changed Metrics

- compaction_ran: false
- authoritative_snapshot_taken: false
- frozen_items: not_inspected
- captures_completed: 0
- captures_failed: 0
- enrichments_attempted: 0
- reservations_saved: false
- queue_mutation: false
- active_run_saved: false
- terminal_run_saved: false
- report_saved: false
- final_compaction_ran: false

## Product Owner Delivery

- status: delivered_readback_confirmed
- destination_task_id: 019faa62-6058-7643-b9cc-a2627083af07
- readback_evidence: `codex_app.read_thread` showed Product Owner task item `676` contains the exact SG-0174 Curator compact payload.
