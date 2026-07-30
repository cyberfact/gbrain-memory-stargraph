---
type: report
title: Memory Stargraph SRE Weekly Resilience Manual - 2026-07-29 .85
date: '2026-07-29'
mode: weekly_resilience
run_slug: runs/memory-stargraph-sre-weekly-resilience-manual-20260729t164528-0700-85
report_slug: reports/memory-stargraph-sre-weekly-resilience-manual-2026-07-29-164528-85
automation_id: memory-stargraph-sre-weekly-resilience
invocation_id: weekly-resilience-manual-20260729t164528-0700-85
classification: healthy_with_telemetry_gaps
terminal_status: completed_with_skips
product_owner_notification_status: delivered_read_back
product_owner_notification_pending: false
product_owner_notification_delivered_at: '2026-07-29T16:57:57-07:00'
product_owner_destination_task_id: 019faa62-6058-7643-b9cc-a2627083af07
---

# Memory Stargraph SRE Weekly Resilience Manual - 2026-07-29 .85

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
- local_head: `888f272a2a24933260d82853709848ccd6edc812`
- upstream_ref: `origin/main`
- upstream_head: `888f272a2a24933260d82853709848ccd6edc812`
- dirty_state: clean
- divergent_state: false
- deployed_service_version: `V1.0.172`
- required_script_existence: `automations/memory-stargraph-sre/prompt.md` and `scripts/automation/yoda_gap_evaluator.py` present
- selected_source_path: `/Users/toddy/memory-stargraph`
- selected_source_surface: workspace source, current
- action_taken: `source_sync_preflight=current`; no fast-forward, no overwrite

## Quiet-Time Evidence

- Initial GBrain active tag readback: `No pages found.`
- Initial Codex task inspection: this weekly SRE task active; Product Owner task active as coordinator/watcher; Daily SRE task idle; X Intelligence idle; Developer/UX/Curator/Learning/Strategist tasks idle or notLoaded.
- Dashboard API Run save attempt returned HTTP 502 after a backend `gbrain put` timeout; direct `gbrain put` succeeded for the active lease.
- Post-lease GBrain active tag readback showed only this SRE Run.
- Pre-load and pre-fault rechecks again showed only this SRE Run active in GBrain.

## Health And Configuration

- `scripts/automation/preflight.sh`: local service healthy, dashboard healthy, one configured remote target healthy, Chrome CDP available, source sync current.
- Local TLS health: HTTP 200, ok=true, ui_version=`V1.0.172`, loaded=true, source.mode=`gbrain`, attachment_storage.available=true.
- Final post-probe TLS health: HTTP 200 in 2.211s, ui_version=`V1.0.172`, source.status=`lazy-search-partial`, search_status=`partial_timeout` for the backup/restore query.
- Resolver health: first 25s read was transport-unverified; retry succeeded with HTTP 200 in 13.288s. Final resolver health succeeded in 9.819s with events_24h=347, production_events_24h=322, synthetic_test_events_24h=25, pending proposals=0.
- Process identity: Python `server.py` listening on TCP 8788 from `/Users/toddy/memory-stargraph` with dashboard TLS cert/key paths under `config/tailscale-certs/`.
- Disk/headroom: root volume 9% used with 119Gi available; data volume 44% used with 119Gi available; file descriptor limit 1048575; service RSS about 21 MB.
- GBrain backend config: Primary only, write_authority=`primary`; Secondary/test/custom are not active write authorities.
- Yoda model config: backend=`gbrain_think`, model=`openai:gpt-5.2`, Node runtime not used; public config endpoint reports `api_key_available=false`.

## Bounded Synthetic Read-Only Load

Load shape used read-only HTTP endpoints with hard aborts and no mutation.

| phase | endpoint | concurrency | result |
| --- | --- | ---: | --- |
| baseline | `/api/health` | 1 | HTTP 200 in 0.165s |
| baseline | `/api/resolver/health` | 1 | HTTP 200 in 2.506s |
| baseline | `/api/entity-raw/notes%2Fmemory-starmap-todo-list` | 1 | HTTP 200 in 2.901s |
| gradual-read | `/api/health` x2, `/api/yoda-logs?limit=3`, `/api/gbrain-backend-config` | 4 | HTTP 200 in 0.033-0.219s |
| search-read | `/api/search?q=SG-0167` | 2 | HTTP 200 in 16.742s |
| search-read | `/api/search?q=weekly%20resilience` | 2 | HTTP 200 in 16.758s |

Abort gates did not trip. No user impact was observed. Concurrent search remains the first expected bottleneck, but the bound improved from the prior weekly manual run's 19-21s concurrent search sample.

## Backup And Restore Evidence

- `_backups/backup-latest` readback succeeded but is stale: title `GBrain Daily GitHub Backup - 2026-07-27`, run timestamp `2026-07-27T10:00:00Z`, resolver events exported=2236, resolver proposals exported=7, resolver releases exported=5.
- No same-day backup readback was verified during this run; backup freshness is a telemetry/follow-up gap.
- Isolated restore rehearsal used temporary storage only: `/tmp/memory-stargraph-sre-restore-20260729.iW7o7o`.
- `data/yoda_logs.json` copy checksum matched: `66de0651cf866e5d71b0864a60f8cfb9195813890d82464df1e3e4837dfc01ce`; source and copy were both 103475 bytes.
- `data/graph_cache.json` copy checksum matched: `86e38cab04e20580db7cb4cedd7cb48f24951b40aa2a44fb927ac0034ffb3f61`; source and copy were both 47099 bytes.
- No production restore was executed.

## Warm-Standby And Fault Eligibility

- `.102` is treated as warm standby, not disposable.
- The warm-standby runbook requires Primary/Secondary readiness, fresh restore, switch command, and fleet verification for promotion; it forbids split brain and automatic failback.
- The failover helper status path can refresh and write standby state if private readiness commands are configured, so this weekly run did not use it as a casual read probe.
- Real fault injection was not eligible because no explicitly disposable/redundant target approval was proven, and current backup freshness/readiness for safe destructive exercise was not proven.
- Synthetic no-op target classification: `synthetic-noop-fault-harness`, report-only, explicitly non-production.
- Fault action: simulated classification, abort gates, rollback evidence, and post-probe health verification only.
- Rollback evidence: harness state was in-memory/report-only; rollback is preserving this terminal report and making no production change.

## Resolver Isolation

- Code inspection confirmed Ask Yoda logs and resolver event submissions carry `environment`, `synthetic`, `test_run`, and `pair_id` fields.
- Recent resolver events show production hook traffic occurring outside the SRE probe path during this run.
- Fresh weekly resolver E2E probe was skipped as `resolver_probe_skipped_isolation_unverified` because the run could not prove exclusion from production metrics, proposal generation, learning intake, resolver decisions, and user-quality scoring for a new probe while production hook traffic was active.
- No resolver proposals were generated, accepted, applied, or auto-approved.

## TODO Decisions

- No SRE TODO mutation.
- SG-0167 is completed as of V1.0.169 with `gbrain_think` / `openai:gpt-5.2`.
- SG-0168 is completed as of V1.0.170 and already covers bounded natural-language search latency and terminal feedback, so this SRE run did not create a duplicate search-latency TODO.

## Blockers And Follow-Up

- Backup freshness gap: latest backup readback is 2026-07-27, not current to 2026-07-29.
- No approved real disposable/redundant safe-fault target; real restart/failover/resource fault remains skipped.
- Resolver E2E probe isolation was not fully verified for fresh traffic.
- Search remains the first capacity bottleneck under concurrency 2, even with SG-0168 bounds.

## Compact Product Owner Payload

```json
{
  "worker_task_id": "019fab0d-918f-7312-be20-3fa03ec8ac31",
  "automation_id": "memory-stargraph-sre-weekly-resilience",
  "invocation_id": "weekly-resilience-manual-20260729t164528-0700-85",
  "mode": "weekly_resilience",
  "terminal_status": "completed_with_skips",
  "run_slug": "runs/memory-stargraph-sre-weekly-resilience-manual-20260729t164528-0700-85",
  "report_slug": "reports/memory-stargraph-sre-weekly-resilience-manual-2026-07-29-164528-85",
  "incidents": [],
  "remediation": "none; no verified outage and no authorized service-impacting action",
  "changed_reliability_capacity_metrics": {
    "local_service": "healthy over TLS at V1.0.172",
    "remote_target": "one configured remote route healthy in preflight; .102 treated as warm standby, not disposable",
    "resolver": "healthy on retry; pending proposals 0; final events_24h 347; production_events_24h 322; synthetic_test_events_24h 25",
    "load": "health/resolver/raw/yoda/backend reads passed; concurrent search took 16.742s and 16.758s",
    "disk": "root 9% used, data 44% used, 119Gi available",
    "restore_rehearsal": "isolated yoda_logs and graph_cache copy checksum matched",
    "backup_freshness": "latest backup readback is 2026-07-27T10:00:00Z, stale for 2026-07-29"
  },
  "todo_decisions": "No SRE TODO mutation; SG-0167 and SG-0168 are already completed",
  "blockers": [
    "No Product Owner approval/proof for real disposable/redundant safe-fault target; real chaos skipped.",
    "Latest backup readback is stale at 2026-07-27T10:00:00Z.",
    "Resolver E2E probe skipped because full isolation from production metrics/proposals/learning/user-quality scoring was not proven.",
    "Search remains the first observed bottleneck under concurrency 2."
  ],
  "approvals_needed": [
    "Approve/provision a real disposable or redundant safe-fault target before future restart/failover/resource-fault drills."
  ],
  "requested_product_owner_follow_up": "Acknowledge Run/report, investigate backup freshness, decide whether to approve a real safe-fault target, and keep SG-0168 search-latency evidence in future baselines.",
  "product_owner_notification_status": "delivered_read_back",
  "product_owner_notification_pending": false,
  "product_owner_notification_delivered_at": "2026-07-29T16:57:57-07:00",
  "product_owner_destination_task_id": "019faa62-6058-7643-b9cc-a2627083af07"
}
```
