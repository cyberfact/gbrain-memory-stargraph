---
type: report
title: Memory Stargraph SRE Weekly Resilience Manual - 2026-07-28 .85
date: '2026-07-28'
mode: weekly_resilience
run_slug: runs/memory-stargraph-sre-weekly-resilience-manual-20260728t162739-0700-85
report_slug: reports/memory-stargraph-sre-weekly-resilience-manual-2026-07-28-162739-85
automation_id: memory-stargraph-sre-weekly-resilience
invocation_id: weekly-resilience-manual-20260728t162739-0700-85
classification: healthy_with_telemetry_gaps
terminal_status: completed_with_skips
product_owner_notification_status: delivered_read_back
product_owner_notification_pending: false
product_owner_notification_thread_id: 019faa62-6058-7643-b9cc-a2627083af07
---

# Memory Stargraph SRE Weekly Resilience Manual - 2026-07-28 .85

## Terminal Status

- Status: completed_with_skips
- Classification: healthy_with_telemetry_gaps
- Remediation: none; no verified outage and no authorized service-impacting remediation
- Real fault injection: skipped as `chaos_skipped_no_safe_target`
- Safe-fault target exercised: `synthetic-noop-fault-harness` only
- Production impact: none; no restart, throttle, delete, mutation, redirect, failover, resolver E2E probe, backup mutation, or product code change

## Source-Sync Preflight

- workspace_path: `/Users/toddy/memory-stargraph`
- branch: `main`
- local_head: `d4d309baa8bc88daff0f3925666d4d0491bcddf4`
- upstream_ref: `origin/main`
- upstream_head: `d4d309baa8bc88daff0f3925666d4d0491bcddf4`
- dirty_state: dirty due existing untracked generated report artifacts: `automations/memory-stargraph-divergent-product-discovery/reports/`, `reports/`; preserved.
- divergent_state: false
- deployed_service_version: `V1.0.168`
- required_script_existence: `automations/memory-stargraph-sre/prompt.md` and `scripts/automation/yoda_gap_evaluator.py` present
- selected_source_path: `/Users/toddy/memory-stargraph`
- selected_source_surface: workspace source, current with preserved generated artifacts
- action_taken: `source_sync_preflight=current`; no fast-forward, no overwrite

## Quiet-Time Evidence

- Initial task inspection showed this weekly SRE task active and the canonical Product Owner task active as launcher/watcher; recent Product Strategist, Developer, daily SRE, Daily Learning Intake, X Intelligence, Capture Link, and UX tasks were idle or notLoaded.
- Broad active Run searches for active leases timed out or returned empty under bounded 20s windows; recorded as a telemetry gap.
- Active SRE Run lease was created, then task state was rechecked before health/load and again before the no-op fault phase. No competing worker appeared.

## Health And Configuration

- Local TLS health: HTTP 200, ok=true, ui_version=`V1.0.168`, loaded=true, source.mode=`gbrain`, attachment_storage.available=true.
- Final post-probe TLS health: HTTP 200 in 0.119s, ui_version=`V1.0.168`, source.status=`lazy-search`, attachment storage still available.
- Resolver health: HTTP 200; events_24h=252, production_events_24h=228, synthetic_test_events_24h=24, pending proposals=0, active resolver distribution observed.
- Process identity: PID 34451 listening on TCP 8788 from `/Users/toddy/memory-stargraph/server.py` with `config/tailscale-certs/...` TLS cert/key paths preserved.
- GBrain backend config: Primary only, gbrain path `/Users/toddy/.bun/bin/gbrain`, write_authority=`primary`.
- Yoda model config: backend=`openclaw`, configured Node runtime ok at `/Users/toddy/.cache/memory-stargraph-runtimes/node-v24.15.0-darwin-x64/bin/node`; API reports `api_key_available=false` for the public config endpoint, while recent SG-0166 logs show OpenClaw/provider timeout and disallowed model override as the current blocker.
- Preflight script: `scripts/automation/preflight.sh` completed but classified local service/dashboard/remote targets as unverified through helper routes because `/Users/toddy/.codex/automations/memory-stargraph-wish-to-reallity/deployment-targets.env` is missing.

## Bounded Synthetic Read-Only Load

Load shape used read-only HTTP endpoints with hard aborts and no mutation.

| phase | endpoint | concurrency | result |
| --- | --- | ---: | --- |
| baseline | `/api/health` | 1 | HTTP 200 in 1437 ms |
| baseline | `/api/resolver/health` | 1 | HTTP 200 in 3349 ms |
| baseline | `/api/entity-raw/notes%2Fmemory-starmap-todo-list` | 1 | HTTP 200 in 3767 ms |
| gradual-read | `/api/health` x2 plus `/api/yoda-logs?limit=3` | 3 | HTTP 200 in 465-607 ms |
| search-read | `/api/search?q=SG-0167` | 2 | HTTP 200 in 19434 ms |
| search-read | `/api/search?q=weekly%20resilience` | 2 | HTTP 200 in 20939 ms |

Abort gates did not trip. No user impact was observed. Search latency is the first expected bottleneck under concurrent read load.

## Restore Rehearsal

- Rehearsed restore only into isolated temporary storage: `/tmp/memory-stargraph-sre-restore.dolMhq`.
- `data/yoda_logs.json` copied to isolated storage and sha256 matched: `a3ca83c0c3200a42e7ca989513e07219c89afe5f7537209b45ce1a216f0ed633`; source and copy were both 51130 bytes.
- Attempted local resolver event file rehearsal using source constant name `data/resolver_dispatch_events.json`, but no such file exists in this checkout. Resolver events are reachable via `/api/resolver/events`, so local-file restore coverage is partial and this remains a telemetry/storage-location gap.
- No production restore was executed.

## Synthetic No-Op Fault Harness

- Target classification: `synthetic-noop-fault-harness`, report-only, explicitly non-production.
- Abort gates: user impact, unexpected saturation, verification loss, rollback uncertainty, worker activity.
- Fault action: simulated classification and rollback evidence only; no service process, routing, storage, resolver, backup, dashboard, or remote target was changed.
- Rollback evidence: harness state was in-memory/report-only; rollback is preserving the terminal report and making no production change.
- Real fault status: `chaos_skipped_no_safe_target`.

## Resolver Isolation

- Read-only resolver health and recent event readback confirmed test/synthetic fields exist in recent SG-0166 events.
- Weekly end-to-end resolver probe was skipped as `resolver_probe_skipped_isolation_unverified` because the run could not prove exclusion from production metrics, proposal generation, learning intake, resolver decisions, and user-quality scoring for a fresh probe without adding new Ask Yoda/resolver traffic.
- No resolver proposals were generated, accepted, applied, or auto-approved.

## Capacity And Comparison

- Disk: 234G total, 112G used, 122G available, 48% used.
- File descriptor limit: 1048575.
- Service RSS: about 23 MB; process cwd/path evidence matches `/Users/toddy/memory-stargraph`.
- Compared with prior weekly report `reports/memory-stargraph-sre-weekly-resilience-recovery-2026-07-28-f62a12e`, local service advanced from V1.0.163 to V1.0.168 and remains healthy, but search latency under bounded load worsened from prior max about 6.0s sequential search to 19-21s with concurrency 2.
- Current safe scale: light read-only health/raw/yoda-log bursts are safe; concurrent search is the practical bottleneck and should stay low until search latency baselines improve.
- Smallest evidence-backed mitigation: add/maintain a 7-day search latency baseline and consider search result caching/indexing work only after SG-0167 resolves the current P1 Ask Yoda provider/model blocker.

## Incidents, TODOs, And Approvals

- Incidents: none confirmed.
- TODO decisions: no SRE TODO mutation. SG-0167 remains the planned P1 Product Owner/Developer blocker for Ask Yoda OpenClaw provider/model/agent configuration.
- Blockers: missing `/Users/toddy/.codex/automations/memory-stargraph-wish-to-reallity/deployment-targets.env`; no approved real disposable/redundant fault target; resolver-probe isolation not fully verified for fresh E2E; local resolver event file location not available for file-level restore rehearsal.
- Approvals needed: Product Owner approval for any real disposable/redundant safe-fault target before restart drill, failover drill, resource fault, provisioning, or production-impacting resilience exercise.

## Compact Product Owner Payload

```json
{
  "worker_task_id": "019fab0d-918f-7312-be20-3fa03ec8ac31",
  "automation_id": "memory-stargraph-sre-weekly-resilience",
  "invocation_id": "weekly-resilience-manual-20260728t162739-0700-85",
  "mode": "weekly_resilience",
  "terminal_status": "completed_with_skips",
  "run_slug": "runs/memory-stargraph-sre-weekly-resilience-manual-20260728t162739-0700-85",
  "report_slug": "reports/memory-stargraph-sre-weekly-resilience-manual-2026-07-28-162739-85",
  "incidents": [],
  "remediation": "none; no verified outage and no authorized service-impacting action",
  "changed_reliability_capacity_metrics": {
    "local_service": "healthy over TLS at V1.0.168",
    "resolver": "healthy; pending proposals 0; events_24h 252; production_events_24h 228; synthetic_test_events_24h 24",
    "load": "health/resolver/raw/yoda-log reads passed; concurrent search took 19.4s and 20.9s",
    "disk": "48% used; 122G available",
    "restore_rehearsal": "isolated yoda_logs copy checksum matched; resolver local file missing"
  },
  "todo_decisions": "No SRE TODO mutation; SG-0167 remains planned P1 blocker",
  "blockers": [
    "No Product Owner approval for real disposable/redundant safe-fault target; real chaos skipped.",
    "Missing .85 deployment-target config blocks helper-managed dashboard/remote/backup verification.",
    "Resolver E2E probe skipped because full isolation from production metrics/proposals/learning/user-quality scoring was not proven.",
    "Search latency under concurrency 2 is the first observed bottleneck."
  ],
  "approvals_needed": [
    "Approve/provision a real disposable or redundant safe-fault target before future restart/failover/resource-fault drills."
  ],
  "requested_product_owner_follow_up": "Acknowledge Run/report, preserve SG-0167 as current P1 provider/model blocker, restore .85 deployment-target config, and decide whether to approve a real safe-fault target.",
  "product_owner_notification_status": "delivered_read_back",
  "product_owner_notification_pending": false,
  "product_owner_destination_task_id": "019faa62-6058-7643-b9cc-a2627083af07"
}
```
