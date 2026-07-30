---
type: report
title: Memory Stargraph Capture Link Drain SG-0173 route readback failure report - 2026-07-30 .85
date: '2026-07-30'
automation_id: memory-stargraph-capture-link-drain
invocation_id: capture-link-drain-20260730t103212-0700-sg0173-routefail-85
mode: route_gate_failure
status: failed
run_slug: runs/memory-stargraph-capture-link-drain-2026-07-30-sg0173-route-readback-failure-85
linked_goal: goals/memory-stargraph-continuous-learning-local-knowledge-os
product_owner_notification_status: delivered_observed_without_exact_payload_echo
product_owner_notification_pending: false
---

# Memory Stargraph Capture Link Drain SG-0173 route readback failure report - 2026-07-30 .85

## Outcome

- Terminal status: `failed_sg0173_acceptance_non_loopback_route_unavailable`.
- Source-sync passed: clean `main`, local and `origin/main` both at `01d95eb5eb27cd9b3eb8bbc7dcf5cf81bab95b27`.
- Dashboard TLS health passed through required non-loopback URL `https://100.100.126.85:8788/api/health`: `ok=true`, `loaded=true`, `ui_version=V1.0.174`, non-null `source`, non-null `stats`.
- Active-tag gate passed: `gbrain list --tag active` returned `No pages found`.
- Required route readback failed before compaction or snapshot.
- No approval was requested and no direct GBrain/PostgreSQL fallback was used.
- No queue inspection or mutation occurred after the route failure.

## Acceptance Failure Evidence

- Command: `python3 scripts/automation/worker_persistence.py routes --json`
- Exit: `1`
- Error: `WorkerPersistenceError: configured non-loopback worker API routes were unavailable; refusing loopback fallback`
- Required proof: route readback must prove `https://100.100.126.85:8788` from private config.
- Proof obtained: false.
- SG-0173 acceptance required route readback before continuing. Because route readback failed, the worker stopped immediately.

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

- status: delivered_observed_without_exact_payload_echo
- destination_task_id: 019faa62-6058-7643-b9cc-a2627083af07
- send_evidence: `codex_app.send_message_to_thread` returned success for destination task `019faa62-6058-7643-b9cc-a2627083af07`.
- readback_evidence: recent Product Owner task readback did not expose this exact compact payload as a separate newest user item, but did show Product Owner commentary acting on this SG-0173 canonical Curator failure and identifying the same route/subprocess network boundary.
