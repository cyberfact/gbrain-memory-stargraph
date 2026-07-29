---
type: report
title: Memory Stargraph Divergent Product Discovery Manual Run 2026-07-28 .85
run: runs/memory-stargraph-divergent-product-discovery-manual-20260728t161121-0700-85
goal: goals/memory-stargraph-continuous-learning-local-knowledge-os
status: completed
product: products/memory-stargraph
learning: learnings/memory-stargraph-discovery-20260728-avoid-promoting-strategy-parents-while-p1-runtime-blocker-open
timezone: America/Los_Angeles
started_at: '2026-07-28T16:11:21-07:00'
completed_at: '2026-07-28T16:24:00-07:00'
automation_id: memory-stargraph-divergent-product-discovery
invocation_id: memory-stargraph-divergent-product-discovery-manual-20260728T161121-0700-85
worker_task_id: 019fab04-dfca-7f61-b23c-9c7a6d15bee9
source_thread_id: 019faa62-6058-7643-b9cc-a2627083af07
promoted_todo_ids: []
source_sync_preflight: current
product_owner_notification_status: pending_unacknowledged_delivery
product_owner_notification_pending: true
tags:
  - memory-stargraph
  - product-discovery
  - report
  - manual
---

# Memory Stargraph Divergent Product Discovery Manual Run 2026-07-28 .85

Run: [[runs/memory-stargraph-divergent-product-discovery-manual-20260728t161121-0700-85]]
Goal: [[goals/memory-stargraph-continuous-learning-local-knowledge-os]]
Product: [[products/memory-stargraph]]
Learning: [[learnings/memory-stargraph-discovery-20260728-avoid-promoting-strategy-parents-while-p1-runtime-blocker-open]]

## Terminal Outcome

Completed product-discovery run on the .85 mirror. No product code was written, no deploy occurred, no TODO was moved to implementing, no resolver proposal was approved, and no destructive or privacy-sensitive operation was performed.

No new implementation TODO was promoted. The strongest currently actionable implementation blocker is already represented by SG-0167, and the broader product opportunities are already represented as strategy parents in [[notes/memory-stargraph-product-strategy-todo-list]]. This run keeps those ideas as scored discovery proposals until the current Ask Yoda model-runner blocker is resolved or a Product Owner chooses a strategy parent for conversion.

## Source-Sync Preflight

- workspace_path: `/Users/toddy/memory-stargraph`
- branch: `main`
- local_head: `d4d309baa8bc88daff0f3925666d4d0491bcddf4`
- upstream_ref: `origin/main`
- upstream_head: `d4d309baa8bc88daff0f3925666d4d0491bcddf4`
- dirty_state: untracked local `reports/` directory only; preserved as local generated evidence
- divergent_state: none; local HEAD matched upstream HEAD
- deployed_service_version: `V1.0.168`
- required_script_existence: `scripts/automation/yoda_gap_evaluator.py` and `automations/memory-stargraph-divergent-product-discovery/prompt.md` present
- selected_source_path: `/Users/toddy/memory-stargraph`
- selected_source_surface: workspace checkout plus dashboard-managed local Memory Stargraph API at `https://127.0.0.1:8788`
- action_taken: `use_workspace`; no fast-forward required

Canonical helper payload:

```json
{
  "_schema": "memory-stargraph-source-sync-preflight-v1",
  "action": "use_workspace",
  "checkout_head": "d4d309baa8bc88daff0f3925666d4d0491bcddf4",
  "dashboard_ui_version": "V1.0.168",
  "missing_paths": [],
  "origin_main": "d4d309baa8bc88daff0f3925666d4d0491bcddf4",
  "reason": "checkout HEAD matches origin/main and required scripts exist",
  "script_path": "scripts/automation/yoda_gap_evaluator.py",
  "status": "current",
  "sync_applied": false
}
```

## Evidence Inspected

- Prompt: `automations/memory-stargraph-divergent-product-discovery/prompt.md`.
- Product, project, goal: [[products/memory-stargraph]], [[projects/memory-stargraph-ai-memory-visualizer]], [[goals/memory-stargraph-continuous-learning-local-knowledge-os]].
- Backlog: [[notes/memory-starmap-todo-list]] shows SG-0166 failed after partial V1.0.168 deployment and SG-0167 planned P1.
- SG-0167 node: [[notes/memory-starmap-todo-list/resolve-ask-yoda-openclaw-provider-timeout-after-node-runtime-fix]] already captures the supported OpenClaw provider/model/agent follow-up.
- Strategy backlog: [[notes/memory-stargraph-product-strategy-todo-list]] already covers activation, evidence search, graph-quality cockpit, evidence-first answers, task home, vertical workflow pack, customer preflight/repair, share/export receipts, and packaging boundary as strategy parents.
- Service health: `https://127.0.0.1:8788/api/health` returned `ok=true`, `ui_version=V1.0.168`, `source.mode=gbrain`, `source.status=lazy-root`, durable attachment storage available, `nodes=75`, `edges=24`.
- Yoda model config: backend `openclaw`; Node runtime fixed at `/Users/toddy/.cache/memory-stargraph-runtimes/node-v24.15.0-darwin-x64/bin/node`, `node_runtime_status=ok`, API key env unavailable, timeout `45s`.
- Ask Yoda logs: latest classified probes still use fallback. One default OpenClaw probe timed out after 180s; one model override probe failed because `nvidia/nvidia/gpt-5.2` was not allowed for `memory-stargraph-ask-yoda`.
- Resolver health: `events_24h=252`, `production_events_24h=228`, `synthetic_test_events_24h=24`, pending proposals `0`, last dream run completed with proposals_created `0`.
- Yoda feedback: production `0`, test `0`.
- Activation funnel: `mode=live-ready`, sample brain available and privacy-safe, live GBrain ready, progress `1/6` with next step `sample_brain_opened`.
- Memory value digest: planned `1`, completed `15`, failed `1`; learned items include source-sync as runtime evidence and current operational state reconciliation.
- Search probe for `SG-0167 Ask Yoda OpenClaw provider timeout`: top search slug was SG-0167, followed by related Ask Yoda timeout learnings, SG-0166 run/report, and prior broad-graph timeout records.
- Graph/backlinks probe for [[products/memory-stargraph]] showed strong runbook/product/project/goal linkage, but also confirms graph quality remains a strategic surface rather than a single small implementation gap.
- Governance check: `/Users/toddy/.codex/automations/memory-stargraph-wish-to-reallity/deployment-targets.env` is missing on this host; this remains a deployment-governance gap.
- Agent Reach: no direct Agent Reach tool was callable in this worker. External research used primary-source web fallback. Resolver events show agent-reach activity in prior production Codex hooks, but this run could not invoke Agent Reach directly.

## External Primary-Source Comparison

- Mem0 documentation emphasizes a quickstart that stores a first memory within minutes and has an agent-oriented signup/API-key path: https://docs.mem0.ai/platform/quickstart
- Letta documentation positions stateful agents as agents that learn from experience and improve with use: https://docs.letta.com/
- Graphiti/Zep primary sources emphasize temporal knowledge graphs, provenance, changing facts, and fused semantic/full-text/graph retrieval: https://github.com/getzep/graphiti and https://help.getzep.com/graphiti/getting-started/overview

Inference: Memory Stargraph's differentiated lane is not just "memory exists"; it is local-first inspectability, provenance, human authority, and workflow receipts. The product gap is making that proof visible faster and in a repeatable professional workflow.

## Discovery Exercises

- First-time customer walkthrough: activation API says live-ready and privacy-safe, but browser progress is only `1/6`; a new customer still needs guided proof of sample-to-live value and setup confidence.
- Daily user audit: natural-language evidence search now finds SG-0167 and recent Ask Yoda records, so SG-0165 appears effective for the current query. Recurring value is blocked less by search and more by Ask Yoda model-backed answer availability.
- Power user/agent builder audit: route map exposes useful APIs for model config, logs, feedback, resolver proposals, backlinks, graph query, activation, and digest. Evidence-first answer cards remain a strategy parent, not a new TODO while Ask Yoda is not model-backed.
- Operator review: service healthy over TLS; deployment-targets governance gap persists; resolver loop healthy; no pending resolver proposals.
- Product owner review: current P1 must restore Ask Yoda model-backed answers before strategy-level answer-surface or vertical-workflow investments can be fairly validated.

## Opportunity Scores

1. Resolve model-backed Ask Yoda configuration before answer-surface expansion - score 91.
   Target user: daily user, Product Owner, agent builder.
   Problem/job: Ask Yoda should return grounded model-backed answers, not only fallback diagnostics.
   Evidence: SG-0167 is planned P1; logs show OpenClaw timeout and unsupported model override after Node runtime was fixed.
   Capability/experiment: complete SG-0167 with supported provider/model/agent config and run the 10-question evaluator.
   Expected value: restores the core memory Q&A loop and unlocks reliable evaluation of evidence-first answer UX.
   Success metric: evaluator has model-backed non-fallback answers while `context_degraded=false` remains intact.
   Smallest validation step: configure one allowed OpenClaw model/provider and run one classified probe before the full evaluator.
   Risks/privacy: provider configuration may involve credentials and model routing; keep synthetic/test flags and no private prompt leakage.
   Deduplication: already covered by SG-0167; no new TODO promoted.

2. Customer setup confidence and repair path - score 82.
   Target user: first-time customer/operator.
   Problem/job: setup spans GBrain, dashboard, backend, attachment storage, model path, and deployment targets.
   Evidence: activation is live-ready, but missing deployment targets config remains; model config shows fixed Node runtime plus missing API key/env and broken host `/usr/local/bin/node`.
   Capability/experiment: bounded first slice under ST-0008: customer-readable preflight report with safe repair suggestions and authority display.
   Expected value: lowers support burden and time-to-trust.
   Success metric: a clean-machine user can identify live GBrain, model, Node, storage, and deployment authority without reading operator runbooks.
   Smallest validation step: draft/read-only API response shape from existing health/model/digest data, no repair execution.
   Risks/privacy: avoid exposing hostnames, secrets, private paths beyond local-owner diagnostics.
   Deduplication: strategy parent ST-0008 exists; not promoted while SG-0167 is active.

3. Graph-quality cockpit first metrics - score 78.
   Target user: power user/operator/Product Owner.
   Problem/job: stored knowledge can outrun usable relationships and extraction coverage.
   Evidence: product teardown identified graph fidelity as a large risk; strategy parent ST-0003 and subtask idea already exist; backlinks prove many docs connect to product, but no cockpit summarizes extraction/orphan/duplicate/attachment health in one place.
   Capability/experiment: first metrics only: orphan count, extraction coverage, duplicate candidates, stale cache, attachment verification, and next cleanup action.
   Expected value: makes memory quality measurable and actionable.
   Success metric: daily digest or settings surface shows quality deltas and one recommended cleanup target.
   Smallest validation step: read-only metric prototype from existing GBrain/API commands.
   Risks/privacy: quality metrics must avoid surfacing private page text by default.
   Deduplication: ST-0003-SUB-001 already exists; no new TODO promoted.

4. Evidence card for Ask Yoda answers - score 74.
   Target user: trust-sensitive daily user.
   Problem/job: users need supporting nodes, freshness, truncation, and correction actions next to answers.
   Evidence: ST-0004-SUB-001 exists; Graphiti/Zep sources emphasize provenance; Memory Stargraph already logs rich diagnostics.
   Capability/experiment: answer evidence card after model-backed answers are restored.
   Expected value: turns AI output into inspectable memory receipts.
   Success metric: every Ask Yoda answer shows cited nodes, broad-graph status, freshness, and correction affordance.
   Smallest validation step: design/read-only rendering for fallback and model-backed states.
   Risks/privacy: avoid overexposing hidden raw context or private graph snippets.
   Deduplication: strategy parent and subtask already exist; blocked behind SG-0167 quality validation.

5. First vertical workflow pack scope - score 69.
   Target user: product owner and first commercial segment.
   Problem/job: generic personal graph is too broad to package or price.
   Evidence: product teardown recommends a repeatable professional workflow; ST-0006-SUB-001 exists.
   Capability/experiment: define one workflow pack, likely client renewal prep or compliance evidence review, with activation and recurring value metrics.
   Expected value: clarifies positioning, onboarding, retention, and willingness-to-pay hypotheses.
   Success metric: one workflow can be demoed end to end with sample data, evidence receipts, and measurable time saved.
   Smallest validation step: written scope and sample data requirements, no product code.
   Risks/privacy: vertical data may be sensitive; sample pack must be synthetic or explicitly authorized.
   Deduplication: ST-0006 and subtask already exist; not promoted as SG implementation yet.

## Required Lenses

Make it easier for a new customer: customer setup confidence and repair path under ST-0008. Current activation is live-ready, but environment/model/deployment authority still reads like an operator cockpit.

Maximize recurring user value: complete SG-0167 first. Recurring value depends on Ask Yoda returning model-backed, evidence-grounded answers; evidence cards and workflow packs are less useful until that loop is healthy.

## Duplicates Suppressed

- SG-0167 already covers supported Ask Yoda OpenClaw provider/model/agent configuration.
- ST-0008 already covers customer preflight and safe repair.
- ST-0003 and ST-0003-SUB-001 already cover graph-quality cockpit first metrics.
- ST-0004 and ST-0004-SUB-001 already cover Ask Yoda evidence cards.
- ST-0006 and ST-0006-SUB-001 already cover vertical workflow pack scope.
- SG-0164 already delivered activation funnel; this run does not reopen it.
- SG-0165 already improved natural-language evidence retrieval; the SG-0167 search probe confirms the relevant current query is now findable.

## TODO Decision

No new TODOs created or updated. Promoted TODO ids: none.

Reason: with SG-0167 planned P1 and broad strategy parents already present, creating another SG implementation TODO would add backlog noise rather than improve focus. Product Owner should finish or explicitly reprioritize SG-0167, then choose whether ST-0008 or ST-0003 is the next conversion candidate.

## Productization Insight

Memory Stargraph's moat is increasingly "customer-controlled memory with evidence and operations receipts." Competitors make memory easy to start; Memory Stargraph can win trust by making memory inspectable, repairable, and workflow-specific. The next product step should package proof and recovery, not expand the feature surface.

## Missing Evidence

- No authenticated browser journey was run in this worker; read-only APIs were sufficient for this discovery pass.
- No clean-machine customer observation is available.
- No direct Agent Reach tool was callable in this worker.
- Direct Product Owner messaging was unavailable; only `codex_app.read_thread` was exposed after tool search, not `send_message_to_thread`.

## Product Owner Compact Payload

```yaml
worker_task_id: 019fab04-dfca-7f61-b23c-9c7a6d15bee9
source_thread_id: 019faa62-6058-7643-b9cc-a2627083af07
automation_id: memory-stargraph-divergent-product-discovery
invocation_id: memory-stargraph-divergent-product-discovery-manual-20260728T161121-0700-85
terminal_status: completed
run_slug: runs/memory-stargraph-divergent-product-discovery-manual-20260728t161121-0700-85
report_slug: reports/memory-stargraph-divergent-product-discovery-manual-20260728t161121-0700-85
learning_slug: learnings/memory-stargraph-discovery-20260728-avoid-promoting-strategy-parents-while-p1-runtime-blocker-open
proposed_opportunities:
  - SG-0167 completion before answer-surface expansion
  - customer setup confidence and safe repair path under ST-0008
  - graph-quality cockpit first metrics under ST-0003
  - Ask Yoda evidence card under ST-0004 after model-backed answers return
  - vertical workflow pack scope under ST-0006
promoted_todo_ids: []
changed_metrics:
  service_version: V1.0.168
  todo_movement: planned=1 implementing=0 completed=15 failed=1
  resolver_pending_proposals: 0
  yoda_feedback_production: 0
blockers:
  - SG-0167 remains planned P1
  - Ask Yoda fallback persists after Node runtime fix
  - deployment-targets.env missing on .85
  - direct Product Owner delivery unavailable from worker
approvals_needed:
  - Product Owner/SRE/model-owner approval for Ask Yoda OpenClaw provider/model/agent configuration
requested_product_owner_follow_up:
  - prioritize SG-0167 before converting strategy parents into new SG TODOs
  - after SG-0167, choose ST-0008 customer preflight or ST-0003 graph-quality cockpit as next conversion candidate
product_owner_notification_status: pending_unacknowledged_delivery
product_owner_notification_pending: true
destination_task_id: 019f707d-cad0-7d70-be3e-d78a3f7c78b2
attempted_at: 2026-07-28T16:24:00-07:00
no_tool_no_ack_evidence: tool_search exposed codex_app.read_thread only; send_message_to_thread was not callable, so delivery could not be attempted or read back
```
