---
type: report
title: Memory Stargraph Capture Link Drain SG-0175 explicit curl health failure report - 2026-07-30 .85
date: '2026-07-30'
automation_id: memory-stargraph-capture-link-drain
invocation_id: capture-link-drain-20260730t112556-0700-sg0175-curl-healthfail-85
mode: route_gate_failure
status: failed
run_slug: runs/memory-stargraph-capture-link-drain-2026-07-30-sg0175-explicit-curl-health-failure-85
linked_goal: goals/memory-stargraph-continuous-learning-local-knowledge-os
product_owner_notification_status: delivered_readback_confirmed
product_owner_notification_pending: false
---

# Memory Stargraph Capture Link Drain SG-0175 explicit curl health failure report - 2026-07-30 .85

## Outcome

- Terminal status: `failed_sg0175_acceptance_explicit_top_level_curl_health_unavailable`.
- Source-sync passed: clean `main`, local and `origin/main` both at `7d0da1b8fb1cc8af21f47887bfa4c37e5f91f637`.
- Active-tag gate passed: `gbrain list --tag active` returned `No pages found`.
- Offline prepare proved the required route source and emitted the required top-level curl command material.
- The emitted explicit top-level curl health command failed before compaction or snapshot.
- No approval was requested.
- No Python-spawned curl, shell-wrapper network call, loopback persistence, direct GBrain, or PostgreSQL fallback was used.
- No queue inspection or mutation occurred after the route failure.

## Route Evidence

- Prepare command: `python3 scripts/automation/worker_persistence.py prepare health --json`
- Prepared route: `base_url=https://100.100.126.85:8788`
- Prepared route loopback: false
- Prepared route source: `/Users/toddy/.codex/automations/memory-stargraph-wish-to-reallity/deployment-targets.env:MEMORY_STARGRAPH_DASHBOARD_URL`
- Prepared curl flags: `-k`
- Emitted command: `curl -sS --fail -k --max-time 8 https://100.100.126.85:8788/api/health`

## Acceptance Failure Evidence

- Command: `curl -sS --fail -k --max-time 8 https://100.100.126.85:8788/api/health`
- Exit: `7`
- Error: `curl: (7) Failed to connect to 100.100.126.85 port 8788 after 2 ms: Couldn't connect to server`
- SG-0175 acceptance required the explicit top-level curl route health/readback boundary before continuing. Because the emitted curl failed, the worker stopped immediately.

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
- readback_evidence: `codex_app.read_thread` showed Product Owner task item `688` contains the exact SG-0175 Curator compact payload.
