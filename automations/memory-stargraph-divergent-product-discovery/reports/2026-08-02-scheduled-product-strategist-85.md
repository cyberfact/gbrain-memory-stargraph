---
type: report
title: Memory Stargraph Divergent Product Discovery 2026-08-02
goal: goals/memory-stargraph-continuous-learning-local-knowledge-os
product: products/memory-stargraph
status: completed
automation_id: memory-stargraph-divergent-product-discovery
invocation_id: memory-stargraph-divergent-product-discovery-20260802t040053-0700-85
run_slug: runs/memory-stargraph-divergent-product-discovery-20260802t040053-0700-85
learning_slug: learnings/memory-stargraph-discovery-20260802-package-proof-before-expanding-surface
created_todo_ids: []
updated_todo_ids: []
product_owner_delivery_status: delivered_read_back
product_owner_acknowledgement_status: acknowledged
product_owner_selected_strategy: ST-0007
product_owner_promoted_todo: SG-0186
product_owner_delivery_thread_id: 019faa62-6058-7643-b9cc-a2627083af07
product_owner_delivery_item_id: item-904
tags:
  - completed
  - discovery
  - memory-stargraph
  - product-strategy
---

# Memory Stargraph Divergent Product Discovery - 2026-08-02

## Executive Decision

The scheduled bounded strategy review completed on the .85 automation mirror. No product code was written, no deployment was attempted, no resolver proposal was approved, and no implementation TODO was promoted from strategy-candidate rows.

The strongest product opportunity is to package the proof that now exists. SG-0184 and SG-0185 moved Memory Stargraph from "we think retrieval is improving" to "we can produce a benchmark receipt and keep UI/API search focus aligned." The next product step should make that proof visible as recurring value and customer readiness, not widen the feature surface.

## Source-Sync Preflight

- workspace: `/Users/toddy/memory-stargraph`
- dashboard health: `https://127.0.0.1:8788/api/health` returned ok=true, loaded=true, ui_version=V1.0.179, source mode gbrain, local durable attachment root available and writable, process source `/Users/toddy/memory-stargraph`.
- git state: local HEAD and origin/main both `7be8f77bd476e7da9a289f225d9655297883c187`; branch `main`; clean worktree at kickoff.
- source-sync schema: `memory-stargraph-source-sync-preflight-v1`
- source-sync action: `use_workspace`
- source-sync status: `current`
- sync_applied: false
- missing_paths: []
- required scripts verified: `scripts/automation/yoda_gap_evaluator.py`, `automations/memory-stargraph-divergent-product-discovery/prompt.md`
- local deployment artifacts preserved: no changes under `config/tailscale-certs/`; generated local evidence under `reports/` preserved.

## Current Product Evidence

- Product and goal are active: Memory Stargraph is a local-first visual knowledge base/OS with Ask Yoda, capture/search/traversal/media/automation, reliability, backup/restore, privacy, and productization goals.
- Backlog state: `notes/memory-starmap-todo-list` shows planned=0, implementing=0, completed=34, failed=1. SG-0166 remains historical failed after partial V1.0.168 deployment, but SG-0167 completed in V1.0.169 and restored supported Ask Yoda provider/model/agent configuration.
- Ask Yoda config: backend `gbrain_think`, model `openai:gpt-5.2`, timeout 120, `node_runtime.status=not_used`. Recent SG-0167 evaluator logs show model-backed non-fallback, non-degraded answers; latest unit-test logs intentionally include synthetic fallback entries.
- SG-0184: completed retrieval-quality benchmark with 10/10 answer success, 10/10 recall success, 9/9 expected-source coverage, source_coverage=1.0, stale contradiction pruning verified, no fallback/degraded state, no production mutation, and resolver abstention without approval.
- SG-0185: completed V1.0.179 search UI/API parity so natural-language UI focus follows the top available API search slug even under partial_timeout.
- Memory value digest: ok=true, graph nodes=75, edges=24, collapsed_reports=1, unresolved blockers includes `failed: 1`, next_action says to pick the next evidence-backed planned TODO or run Product Owner prioritization if no planned work remains.
- Activation funnel: privacy_safe read-only API is live-ready, sample_state available, live_state ready, but progress is 1/6 with `live_gbrain_readiness_checked` as the only complete step.
- Resolver health: ok=true, pending proposals=0; no automatic approval performed.
- Product Owner 2026-08-01 review: goal progress 87%; productization/adoption score 86; highest leverage then was SG-0184. That work is now complete and fed into Learning/SRE evidence.
- Daily Learning 2026-08-02 schema-refresh recovery: no_action; retrieval-quality benchmark present and complete; no distinct bounded actionable gap found in that recovery bundle.
- SRE Daily 2026-08-02: healthy V1.0.179; retrieval baseline passed all exposed gates; capacity/long-window numeric telemetry remains less precise but was not classified as an incident.
- UX Dogfood 2026-08-01: SG-0185 was promoted because API search and UI focus diverged; the follow-up is now complete.
- Deployment-governance gap: missing `/Users/toddy/.codex/automations/memory-stargraph-wish-to-reallity/deployment-targets.env` remains an external governance gap from Product Owner context; this run did not write outside `/Users/toddy/memory-stargraph`.
- Agent Reach: not used in this run. Local first-party evidence was sufficient and fresher than external product-pattern research for the bounded strategy decision.

## Perspective Walkthrough

- First-time customer: the app can report live readiness and offer a sample brain, but the setup path still reads like internal system status. A customer needs one short proof path: "your local memory is ready, Ask Yoda can answer with evidence, retrieval benchmark passed, here is the next safe step."
- Daily user: search and navigation are better after SG-0183/SG-0185, but the recurring value loop is still scattered across reports, logs, and benchmarks. A daily user should see remembered outcomes, not hunt for evidence receipts.
- Power user / agent builder: the system now has route-level primitives for health, model config, resolver, activation, digest, search, and benchmark-backed worker evidence. The missing layer is a stable value contract agents can cite without scraping many report pages.
- Operator: SRE and Daily Learning consume the benchmark, but capacity/resource windows and customer readiness are not yet summarized in one operator-safe view.
- Product Owner: no planned SG work remains. Strategy candidates ST-0001 through ST-0010 should drive prioritization, but they should not be treated as implementation-ready without a bounded conversion decision.

## Ranked Opportunities

| Rank | Opportunity | Score | Target user | Why now |
| ---: | --- | ---: | --- | --- |
| 1 | Weekly verified memory outcomes surface | 90 | Daily user, Product Owner | SG-0184 created reliable proof; SG-0185 made search proof visible; the product lacks a recurring value metric/card. |
| 2 | Customer readiness and safe next-step card | 86 | First-time customer, operator | Activation is live-ready but only 1/6 complete; readiness signals remain fragmented across health/model/digest/run evidence. |
| 3 | Graph-quality cockpit first metrics | 80 | Power user, curator, operator | Product strategy already calls for graph quality; current digest exposes basic graph stats but not orphan/extraction/duplicate/attachment health. |
| 4 | Evidence-first Ask Yoda answer card | 78 | Daily user, analyst | Ask Yoda is model-backed again, but answer trust is still better proven in logs than in a default answer surface. |
| 5 | One vertical workflow pack | 70 | Product Owner, first customer | Useful for packaging, but should follow proof/readiness because the current wedge needs stronger outcome instrumentation. |

## Opportunity Details

### 1. Weekly Verified Memory Outcomes Surface

- Target user: daily user and Product Owner.
- JTBD: "Show me what the memory system verified this week so I trust it is compounding."
- Evidence: SG-0184 benchmark passed 10/10 answer and recall checks with full expected-source coverage; SRE/Daily Learning can ingest it; memory digest still mostly reports system state and TODO movement, not customer-facing outcome value.
- Capability/experiment: add a read-only weekly outcomes surface that summarizes verified retrieval outcomes, model-backed Ask Yoda success, search parity, contradiction pruning, capture/enrichment outcomes, and unresolved blockers with source slugs.
- Expected value: turns reliability artifacts into recurring product value and gives Product Owner a North Star proxy.
- Success metric: weekly digest contains a stable `verified_memory_outcomes` block with counts, pass/fail gates, deltas, and evidence links for at least retrieval quality, Ask Yoda, search parity, and worker-produced learnings.
- Smallest validation: extend `/api/memory-value-digest?window=week` or add a sibling read-only endpoint, then render one compact card without mutating production data.
- Risks/privacy: avoid exposing private content snippets; show counts, slugs, and redacted source categories only.
- Why not already covered: ST-0007 exists as strategy input and SG-0184 covers benchmark generation, but no SG TODO currently packages weekly verified outcomes for the user.

### 2. Customer Readiness And Safe Next-Step Card

- Target user: first-time customer and operator.
- JTBD: "Tell me whether my local Memory Stargraph is safe and useful right now, and what one step remains."
- Evidence: activation API is live-ready/privacy-safe but reports 1/6 progress; health/model/digest evidence is scattered; deployment-governance gap still exists outside this repo.
- Capability/experiment: compose health, activation, model config, storage, benchmark, resolver-pending, and optional deployment-authority checks into one customer-readable readiness card with safe next actions and no auto-repair.
- Expected value: reduces support burden and improves first-value confidence without requiring a full packaging project.
- Success metric: a clean-machine/operator review can answer "ready, degraded, or blocked" from one UI surface with no runbook spelunking.
- Smallest validation: read-only JSON endpoint plus Settings/Home card; no repair buttons in the first slice.
- Risks/privacy: do not expose secrets, host-private paths beyond the authorized local workspace evidence, or actionable mutation controls.
- Why not already covered: ST-0008 exists as strategy input and SG-0164 delivered activation, but current activation does not provide a complete readiness proof.

### 3. Graph-Quality Cockpit First Metrics

- Target user: curator, power user, operator.
- JTBD: "Show whether my graph is healthy enough to trust before I build workflows on it."
- Evidence: graph has 75 nodes/24 edges and collapsed_reports=1; strategy backlog already identifies graph-quality cockpit; product value depends on relationship and extraction fidelity.
- Capability/experiment: show orphan count, duplicate candidates, attachment/media extraction coverage, collapsed-report count, and stale index/cache state in one read-only cockpit.
- Expected value: makes invisible data-quality problems actionable before they degrade search or Ask Yoda.
- Success metric: cockpit surfaces at least five quality metrics with links to evidence and no production mutation.
- Smallest validation: compute metrics from existing graph/index APIs and display in an operator-safe panel.
- Risks/privacy: metrics must stay aggregate-first and not leak private raw content.
- Why not already covered: ST-0003 and prior subtask ideas exist, but no planned SG implementation row remains.

### 4. Evidence-First Ask Yoda Answer Card

- Target user: daily user, analyst, agent builder.
- JTBD: "When Yoda answers, show me what evidence and confidence path it used."
- Evidence: Ask Yoda SG-0167 is model-backed again; logs expose fallback/context/degraded state; SG-0184 measures answer quality, but the user-facing answer experience still does not default to a compact evidence receipt.
- Capability/experiment: add a concise answer receipt card with cited slugs, context status, fallback/degraded flags, and contradiction-pruning note when relevant.
- Expected value: increases trust and makes answer failures easier to report.
- Success metric: every Ask Yoda answer can be audited from the UI without opening raw logs.
- Smallest validation: read-only expansion under existing Ask Yoda response, using existing logs/answer metadata.
- Risks/privacy: avoid exposing prompt internals or raw private snippets beyond selected citations.
- Why not already covered: ST-0004 exists as strategy input; SG-0167 restored runtime but did not productize the answer receipt.

### 5. One Vertical Workflow Pack

- Target user: Product Owner and first customer.
- JTBD: "Show Memory Stargraph solving one repeated professional workflow end-to-end."
- Evidence: strategy backlog includes ST-0006; product teardown direction favors repeatable workflows; current proof surfaces are not yet packaged enough to make a vertical wedge compelling.
- Capability/experiment: choose one wedge such as client renewal prep or compliance evidence review, then bundle capture, retrieval, Ask Yoda, evidence receipt, and export.
- Expected value: turns a platform into a repeatable adoption story.
- Success metric: one target workflow can be completed from start to evidence-backed output in a bounded time.
- Smallest validation: define a scripted workflow pack using sample/local-safe content.
- Risks/privacy: workflow must avoid sharing private data by default and must distinguish sample from live sources.
- Why not already covered: ST-0006 exists, but this should wait until the proof/readiness surfaces are visible.

## Required Product Opportunities

- Make it easier for a new customer: Customer readiness and safe next-step card under ST-0008.
- Maximize recurring user value: Weekly verified memory outcomes surface under ST-0007.

## Deduplication And TODO Decision

No SG TODOs were promoted in this run.

Reason: the Product Owner context explicitly says `strategy_candidate` and `subtask_idea` rows are strategy input and not implementation-ready SG TODOs. The best opportunities are bounded enough for conversion, but they inherit existing strategy parents and should be selected by the Product Owner rather than silently promoted by this scheduled discovery run.

Duplicates suppressed:

- ST-0001 already covers sample-to-live first-run activation funnel.
- ST-0002 already covers natural-language evidence retrieval for Runs/reports/Learnings; SG-0185 recently fixed UI/API search-focus parity.
- ST-0003 already covers graph-quality cockpit.
- ST-0004 already covers evidence-default answer surface.
- ST-0005 already covers task-oriented home screen.
- ST-0006 already covers vertical workflow pack.
- ST-0007 already covers weekly verified memory outcomes.
- ST-0008 already covers customer preflight and safe repair.
- ST-0009 already covers controlled share/export receipts.
- ST-0010 already covers managed/local appliance packaging boundary.
- SG-0184 already covers cross-session retrieval-quality benchmark/evidence receipts.
- SG-0185 already covers natural-language UI selection aligned with top API search slug.

## Productization Insight

Memory Stargraph's differentiated product promise is no longer just local memory plus graph search. The sharper promise is customer-controlled memory that can prove what it remembered, how it answered, and whether it is ready today. The next product moves should package proof and readiness as the default experience.

## Missing Evidence

- No clean-machine first-customer observation.
- No production Ask Yoda feedback items in the observed feedback endpoint.
- No 7-day/30-day customer-visible outcome trend yet, even though the benchmark can now supply a seed signal.
- Product Owner selected ST-0007 and promoted SG-0186 after delivery; ST-0008 remains unselected strategy input.
- Agent Reach/external competitor scan was skipped because local evidence was fresh and sufficient for this bounded review.

## Product Owner Delivery Payload

Delivery status after task readback: `delivered_read_back`; Product Owner acknowledgement is `acknowledged`. Product Owner selected ST-0007 and promoted it as SG-0186, "Add a weekly verified memory outcomes surface." ST-0008 remains the next strategy candidate after verified outcomes are packaged. Readback found delivery item `item-904` in Product Owner task `019faa62-6058-7643-b9cc-a2627083af07`.

Compact payload: Product Strategy 2026-08-02 completed on .85 at V1.0.179 / commit `7be8f77bd476e7da9a289f225d9655297883c187`; source-sync current; no code/deploy/resolver approval; no SG TODOs promoted because strategy rows are inputs, not implementation authority; top opportunity is weekly verified memory outcomes surface under ST-0007; second is customer readiness and safe next-step card under ST-0008; report `reports/memory-stargraph-divergent-product-discovery-20260802t040053-0700-85`; run `runs/memory-stargraph-divergent-product-discovery-20260802t040053-0700-85`; learning `learnings/memory-stargraph-discovery-20260802-package-proof-before-expanding-surface`; Product Owner should choose whether to convert ST-0007 or ST-0008 next.
