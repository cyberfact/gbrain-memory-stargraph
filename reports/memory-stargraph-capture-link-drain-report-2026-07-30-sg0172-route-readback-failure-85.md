---
type: report
title: Memory Stargraph Capture Link Drain SG-0172 route readback failure report - 2026-07-30 .85
date: '2026-07-30'
automation_id: memory-stargraph-capture-link-drain
invocation_id: capture-link-drain-20260730t101514-0700-sg0172-routefail-85
mode: route_gate_failure
status: failed
run_slug: runs/memory-stargraph-capture-link-drain-2026-07-30-sg0172-route-readback-failure-85
linked_goal: goals/memory-stargraph-continuous-learning-local-knowledge-os
product_owner_notification_status: delivered_readback_confirmed
product_owner_notification_pending: false
---

# Memory Stargraph Capture Link Drain SG-0172 route readback failure report - 2026-07-30 .85

## Outcome

- Terminal status: `failed_sg0172_acceptance_non_loopback_route_unavailable`.
- Source-sync passed: clean `main`, local and `origin/main` both at `13d309968aeb11e9674074f6bbd3daa9d21ebb65`.
- Dashboard TLS health passed through non-loopback `https://100.100.126.85:8788/api/health`: `ok=true`, `loaded=true`, `ui_version=V1.0.174`, non-null `source`, non-null `stats`.
- Active-tag gate passed: `gbrain list --tag active` returned `No pages found`.
- Required route readback failed before compaction or snapshot.
- No approval was requested and no direct GBrain/PostgreSQL fallback was used.
- No queue inspection or mutation occurred after the route failure.

## Acceptance Failure Evidence

- Command: `python3 scripts/automation/worker_persistence.py routes --json`
- Exit: `1`
- Error: `WorkerPersistenceError: configured non-loopback worker API routes were unavailable; refusing loopback fallback`
- SG-0172 acceptance required route readback showing non-loopback dashboard URL source before continuing. Because route readback failed, the worker stopped immediately.

## Changed Metrics

- compaction_ran: false
- authoritative_snapshot_taken: false
- frozen_items: not_inspected
- captures_completed: 0
- captures_failed: 0
- enrichments_attempted: 0
- queue_mutation: false
- active_run_saved: false
- terminal_run_saved: false
- report_saved: false

## Product Owner Delivery

- status: delivered_readback_confirmed
- destination_task_id: 019faa62-6058-7643-b9cc-a2627083af07
- readback_evidence: `codex_app.read_thread` showed the newest Product Owner turn includes this worker payload with invocation_id `capture-link-drain-20260730t101514-0700-sg0172-routefail-85`.
