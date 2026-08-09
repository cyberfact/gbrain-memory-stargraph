---
type: report
title: Memory Stargraph Divergent Product Discovery 2026-08-09
goal: goals/memory-stargraph-continuous-learning-local-knowledge-os
product: products/memory-stargraph
status: completed
automation_id: memory-stargraph-divergent-product-discovery
invocation_id: memory-stargraph-divergent-product-discovery-20260809t040110-0700-85
run_slug: runs/memory-stargraph-divergent-product-discovery-20260809t040110-0700-85
learning_slug: learnings/memory-stargraph-discovery-20260809-loaded-search-is-a-proof-surface
created_todo_ids:
  - SG-0195
updated_todo_ids: []
product_owner_notification_status: delivered_read_back
product_owner_notification_pending: false
product_owner_acknowledgement_status: in_progress
product_owner_delivery_thread_id: 019faa62-6058-7643-b9cc-a2627083af07
product_owner_delivery_turn_id: 019fe636-122e-7071-9ebc-3a6e4c276228
tags:
  - completed
  - discovery
  - memory-stargraph
  - product-strategy
---

# Memory Stargraph Divergent Product Discovery - 2026-08-09

## Executive Decision

The scheduled bounded strategy review completed on the .85 automation mirror. Source-sync was current, the dashboard-managed service was healthy at V1.0.187, and no product code, deployment, resolver approval, destructive action, or implementation-status change was performed.

One planned SG TODO was promoted because the evidence crossed from strategy proposal into current product defect: loaded `/api/search` returned `ok=true` but zero results and no `search_slugs` for exact TODO IDs and known product terms while raw entity reads and health were good. This undermines the proof surfaces completed over the last week because users and agents cannot reliably rediscover them by search.

Promoted: SG-0195, "Restore loaded-search discoverability for exact IDs and known terms."

## Source-Sync Preflight

- workspace_path: `/Users/toddy/memory-stargraph`
- branch: `main`
- local_head: `7b3298897a2d657c81752be672035cc63a5d663f`
- upstream_ref: `origin/main`
- upstream_head: `7b3298897a2d657c81752be672035cc63a5d663f`
- dirty_state: clean before report artifact creation
- divergent_state: none
- deployed_service_version: V1.0.187
- required_script_existence: `scripts/automation/yoda_gap_evaluator.py` present; `automations/memory-stargraph-divergent-product-discovery/prompt.md` present
- selected_source_path: `/Users/toddy/memory-stargraph`
- selected_source_surface: dashboard-managed local TLS service plus current checkout
- action_taken: `use_workspace`; sync_applied=false
- source-sync schema: `memory-stargraph-source-sync-preflight-v1`
- local deployment artifacts preserved: no changes under `config/tailscale-certs/`; generated local report evidence preserved.

## Evidence Inspected

- Product, project, persistent goal, canonical SG backlog, and strategy backlog.
- Health: `https://127.0.0.1:8788/api/health` returned ok=true, loaded=true, ui_version=V1.0.187, durable attachment storage available/writable, 75 lazy-root listed nodes, 24 edges.
- Current weekly digest: verified memory outcomes pass 7/7 gates, completed delta=9, current unresolved blockers=[], historical SG-0166 failure explicitly superseded by SG-0167.
- Current day digest: no `verified_memory_outcomes` block in the day-window response; TODO movement reported completed=43, failed=1, planned=0 before SG-0195 promotion.
- Customer readiness: ok=true, status=degraded only because configured-target evidence is `no_activity`; 6 of 7 checks ready; safe next step is read-only deployment verification.
- Activation: live-ready/privacy-safe, but client progress remains 1/6 with only `live_gbrain_readiness_checked` complete.
- Ask Yoda config: backend `gbrain_think`, model `openai:gpt-5.2`, `node_runtime.status=not_used`, `api_key_available=false`.
- Ask Yoda feedback endpoint: no items returned in the observed response.
- Resolver: pending proposals=0, latest dream run completed, no auto-apply.
- Active tags: `gbrain list --tag active -n 50` returned no pages.
- Product Owner 2026-08-08 report: SG-0191 exposed Settings weekly outcomes and readiness cards; Product Owner created SG-0192 for repeated Capture Link terminal tag leaks; goal progress 89%.
- SG evidence readback: SG-0186 weekly outcomes, SG-0188 customer readiness, and SG-0192 Capture Link lifecycle tag clearing are completed; SG-0194 completed V1.0.187 natural-language reranking.
- Search probes: `/api/search?q=SG-0162`, `SG-0186`, `SG-0188`, `SG-0191`, `SG-0192`, `memory stargraph`, `Ask Yoda`, `weekly verified memory outcomes`, and `customer readiness` each returned ok=true but results_len=0, empty `search_slugs`, and source=null. Raw entity reads for the corresponding completed SG child pages succeeded.
- External research / Agent Reach: not used. Fresh local first-party evidence was sufficient for the bounded strategy decision.

## Perspective Walkthrough

- First-time customer: readiness and weekly proof cards now exist, but activation progress is still 1/6 and configured-target readiness degrades to `no_activity`. A new user needs clearer explanation of "safe but not multi-target-proven" and a guided first-value checkpoint.
- Daily user: the weekly outcomes card says memory value is passing, but global search returning zero for known IDs and product terms breaks everyday retrieval and trust.
- Power user / agent builder: raw entity reads, digest endpoints, readiness endpoints, and resolver health are available, but search cannot be relied on as a stable composition primitive.
- Operator: active tags and resolver pending state are clean; SG-0192 addressed lifecycle tag leaks, but configured-target readiness is intentionally unavailable in process and SRE numeric baselines remain shallow.
- Product Owner: last week's ST-0007 and ST-0008 ideas were converted and completed. The next highest-leverage product move is not another proof card; it is making the proof surfaces findable and trustworthy under loaded service state.

## Ranked Opportunities

| Rank | Opportunity | Score | Target user | Decision |
| ---: | --- | ---: | --- | --- |
| 1 | Restore loaded-search discoverability for exact IDs and known terms | 94 | Daily user, agent builder, Product Owner | Promoted as SG-0195 |
| 2 | Explain configured-target readiness without leaking target details | 84 | First-time customer, operator | Proposal only |
| 3 | Convert activation 1/6 into a guided first-value checkpoint | 81 | First-time customer | Proposal only |
| 4 | Normalize verified outcomes across day/week digest surfaces | 76 | Daily user, Product Owner | Proposal only |
| 5 | Expand SRE numeric evidence into customer-readable reliability proof | 74 | Operator, Product Owner | Proposal only |

## Opportunity Details

### 1. Restore Loaded-Search Discoverability For Exact IDs And Known Terms

- Target user: daily user, agent builder, Product Owner.
- JTBD: "When the graph is loaded, search should find exact IDs, known slugs, and obvious product terms, or truthfully explain why the search index is unavailable."
- Evidence: health loaded=true at V1.0.187; raw entity reads for SG-0186, SG-0188, and SG-0192 succeeded; `/api/search` returned ok=true with zero results for exact IDs and broad known terms. SG-0194 recently fixed a specific ranking query, so this is a broader discoverability/readiness failure, not the same slice.
- Capability/experiment: repair the loaded search path or return an explicit degraded/index-unavailable terminal state with evidence; cover exact ID, slug, product-name, and Ask Yoda queries.
- Expected value: restores the user's primary retrieval loop and makes weekly outcomes/readiness proof findable.
- Success metric: exact SG IDs and known product terms return relevant slugs or a truthful terminal degraded state under loaded service health, with deployed browser proof.
- Smallest validation: focused API tests for `SG-0162`, SG-0186/SG-0188/SG-0192, `memory stargraph`, and `Ask Yoda`, plus one deployed UI smoke.
- Risks/privacy: do not expose private snippets while repairing search; preserve partial-timeout behavior and no resolver auto-approval.
- Why not already covered: SG-0194 covered a specific natural-language re-ranking regression; SG-0195 covers loaded zero-result search for exact and known queries.

### 2. Explain Configured-Target Readiness Without Leaking Target Details

- Target user: first-time customer and operator.
- JTBD: "Tell me why readiness is degraded and what safe proof I can run without exposing host coordinates or mutating anything."
- Evidence: `/api/customer-readiness` has 6/7 ready checks and one `configured_targets=no_activity`, making overall readiness degraded. The safe next step is deployment verification, but the user does not get a customer-friendly explanation of what is withheld versus actually unhealthy.
- Capability/experiment: add a short redacted explanation and optional evidence receipt contract for configured-target readiness.
- Expected value: prevents "degraded" from reading like product failure when it is a privacy/scope boundary.
- Success metric: readiness UI distinguishes unavailable evidence, unhealthy target, and intentionally withheld target details.
- Smallest validation: add copy/metadata only after SG-0195 restores search; no repair button.
- Risks/privacy: must not reveal target coordinates, secrets, private paths, or perform remote mutation.
- Why not already covered: SG-0188 added readiness card; this is a next-level explanation of one degraded check.

### 3. Convert Activation 1/6 Into A Guided First-Value Checkpoint

- Target user: first-time customer.
- JTBD: "Help me finish one sample-to-live workflow without guessing which Settings card to open next."
- Evidence: activation remains live-ready and privacy-safe, but progress is 1/6; ST-0001 and SG-0164 created the funnel, and SG-0188 added readiness, yet user progress is still not moving through the sample steps.
- Capability/experiment: add one guided checkpoint that links sample brain, search, View, Ask Yoda, setup diagnostics, and live readiness into one sequence.
- Expected value: improves first successful outcome and onboarding confidence.
- Success metric: activation progress can move beyond 1/6 in a browser smoke without production data mutation.
- Smallest validation: client-side state/checkpoint proof only; no backend mutation.
- Risks/privacy: sample/live source labeling must remain explicit.
- Why not already covered: SG-0164 added the funnel, but it did not prove step progression after readiness cards landed.

### 4. Normalize Verified Outcomes Across Day/Week Digest Surfaces

- Target user: daily user and Product Owner.
- JTBD: "Show the same core proof concepts whether I ask for day or week, with honest empty/no-activity semantics."
- Evidence: week digest includes `verified_memory_outcomes`; day digest does not expose that block in the observed response, even though it reports TODO movement and next_action.
- Capability/experiment: make day-window digest either expose a day-scoped verified outcomes block or explicitly say outcomes are weekly-only.
- Expected value: reduces confusion for daily review and automation consumers.
- Success metric: day and week digest schemas are documented and tested.
- Smallest validation: schema metadata/test; no UI expansion until search works.
- Risks/privacy: avoid increasing endpoint latency or duplicating heavy evidence gathering.
- Why not already covered: SG-0186 built the weekly surface; day-window semantics remain ambiguous.

### 5. Expand SRE Numeric Evidence Into Customer-Readable Reliability Proof

- Target user: operator and Product Owner.
- JTBD: "Show not just that the service is healthy, but the numeric reliability/capacity evidence behind that claim."
- Evidence: Product Owner and SRE notes continue to identify missing daily numeric capacity, queue, backup-freshness, and restore-recency baselines.
- Capability/experiment: extend safe read-only SRE evidence with bounded numeric baselines and customer-readable summary.
- Expected value: supports productization, support, and managed/local appliance confidence.
- Success metric: daily/weekly reports include redacted numeric trend gates with thresholds and no mutation.
- Smallest validation: SRE-side schema addition; no real fault injection without explicit approval.
- Risks/privacy: capacity/host details must be redacted; destructive drills remain gated.
- Why not already covered: weekly SRE covers safe checks, but numeric trend evidence remains shallow.

## Required Product Opportunities

- Make it easier for a new customer: explain configured-target readiness and move activation beyond 1/6 with one guided first-value checkpoint.
- Maximize recurring user value: restore search discoverability so completed proof surfaces, TODOs, reports, and Learnings are findable from the primary retrieval loop.

## TODO Decision

Created one planned P1 TODO:

- SG-0195: `notes/memory-starmap-todo-list/restore-loaded-search-discoverability-for-exact-ids-and-known-terms`

Verification:

- helper returned ok=true, status=planned, todo_id=SG-0195.
- parent row readback contains SG-0195.
- child node readback status=planned.
- graph depth-1 readback includes the child slug.
- raw API readback for the child slug succeeded.

No other TODOs were created because the remaining opportunities are strategy refinements, evidence semantics, or owned SRE/Product Owner follow-ups.

## Duplicates Suppressed

- ST-0007 and SG-0186 already cover weekly verified memory outcomes.
- ST-0008 and SG-0188 already cover customer readiness and safe next-step card.
- SG-0191 already exposes Settings weekly outcomes/readiness cards.
- SG-0192 and SG-0193 already cover Capture Link terminal lifecycle tag readback/clearing.
- SG-0194 already covers re-ranking one natural-language query after lifecycle-tag corpus growth; it does not cover loaded zero-result search for exact IDs and broad known terms.
- ST-0001/SG-0164 already cover the first-run activation funnel; the activation checkpoint proposal is intentionally not promoted today.
- SRE numeric baseline gaps remain known; no duplicate product-strategy TODO was created.

## Productization Insight

Proof is now product surface. That raises the bar: if users cannot find the proof by search, or if readiness says degraded without clear privacy-aware explanation, trust erodes even when the underlying gates pass. The next product layer should make evidence findable, explainable, and honest under degraded states.

## Missing Evidence

- No successful production Ask Yoda feedback items in the observed feedback endpoint.
- No browser walkthrough was run in this strategy task because API evidence was sufficient and no UI mutation was authorized.
- No Agent Reach external scan was run; local service evidence was more current and directly actionable.
- Configured-target evidence remains intentionally absent from `/api/customer-readiness`.
- Search zero-result behavior needs implementation-time root-cause diagnosis; this run only establishes product evidence and acceptance requirements.

## Product Owner Delivery Payload

Delivery status after task readback: `delivered_read_back`; Product Owner acknowledgement/routing is `in_progress`. Readback found Product Owner turn `019fe636-122e-7071-9ebc-3a6e4c276228` actively checking quiescence and SG-0195 before routing exactly that regression to the canonical Developer task.

Compact payload: Product Strategy 2026-08-09 completed on .85 at V1.0.187 / commit `7b3298897a2d657c81752be672035cc63a5d663f`; source-sync current; no code/deploy/resolver approval/destructive action; created planned P1 SG-0195 for loaded search returning ok=true but zero results for exact IDs and known product terms; top non-promoted opportunities are configured-target readiness explanation, activation first-value checkpoint, day/week digest schema clarity, and SRE numeric proof; report `reports/memory-stargraph-divergent-product-discovery-20260809t040110-0700-85`; run `runs/memory-stargraph-divergent-product-discovery-20260809t040110-0700-85`; learning `learnings/memory-stargraph-discovery-20260809-loaded-search-is-a-proof-surface`; Product Owner follow-up: acknowledge SG-0195 and route it through normal Wish-to-Reallity implementation sequencing.
