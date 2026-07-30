---
type: report
title: Memory Stargraph Capture Link Drain SG-0177 host runner nonterminal processing failure report - 2026-07-30 .85
date: '2026-07-30'
automation_id: memory-stargraph-capture-link-drain
invocation_id: capture-link-drain-20260730t132639-0700-sg0177-hostrunner-85
mode: host_runner_spool
status: failed
linked_goal: goals/memory-stargraph-continuous-learning-local-knowledge-os
product_owner_notification_status: delivered_readback_confirmed
product_owner_notification_pending: false
---

# Memory Stargraph Capture Link Drain SG-0177 host runner nonterminal processing failure report - 2026-07-30 .85

## Outcome

- Terminal status: `failed_sg0177_acceptance_host_runner_nonterminal_processing`.
- Source-sync passed: clean `main`, local and `origin/main` both at `dca51050bd1e69428126eacef3ca1fca55bdefc2`.
- This Curator task used only offline spool submit/status/result reads.
- Task-local network, curl, dashboard/API, direct gbrain, PostgreSQL, browser, capture/enrichment mutation, nested helper network, and approval fallback were not used.
- Exactly one fresh request was submitted for this invocation.
- The `.85` daemon owned and atomically claimed the request; `.102` was reported disabled.
- The request remained nonterminal in `processing` with no terminal result file for this invocation inside the acceptance timebox.

## Request And Result Paths

- request_file_initial: `/Users/toddy/memory-stargraph/var/capture-link-runner/incoming/sg0177-20260730t132639-0700-canonical-curator.json`
- request_file_current: `/Users/toddy/memory-stargraph/var/capture-link-runner/processing/sg0177-20260730t132639-0700-canonical-curator.json`
- result_file_expected: `/Users/toddy/memory-stargraph/var/capture-link-runner/results/capture-link-drain-20260730t132639-0700-sg0177-hostrunner-85.json`
- nonce: `sg0177-20260730t132639-0700-canonical-curator`
- expected_commit: `dca51050bd1e69428126eacef3ca1fca55bdefc2`

## Runner Ownership

- runner_host_role: .85-authoritative
- runner_enabled: true
- runner_instance_id: 00e250d3aad34eedaafb42a5532d3295
- runner_pid: 93500
- runner_started_at: 2026-07-30T13:16:29-07:00
- configured_remote_runner_disabled: true
- remote_role: .102
- remote_disabled_method: disabled_by_default_without_launchd_enablement
- request_claim_atomic: true
- claim_state: incoming_renamed_to_processing
- claimed_at: 2026-07-30T13:26:49-07:00
- claimed_by_pid: 93500

## Missing Terminal Evidence

- terminal_result_present: false
- source_revision_validation_present: false
- first_compaction_present: false
- authoritative_snapshot_count_present: false
- snapshot_rows_present: false
- run_slug_present: false
- report_slug_present: false
- durable_active_run_persistence_present: false
- candidate_selection_version_present: false
- complete_selection_scope_present: false
- candidate_ordering_present: false
- exclusion_counts_reasons_present: false
- reservation_readback_present: false
- enrichment_outcomes_present: false
- no_eligible_candidate_evidence_present: false
- inspection_truncated_semantics_auditable: false
- final_compaction_present: false
- lifecycle_tag_release_present: false

## Changed Metrics

- compaction_ran: unknown_not_terminal
- authoritative_snapshot_taken: unknown_not_terminal
- authoritative_snapshot_count: missing
- snapshot_rows: missing
- capture_outcomes: missing
- enrichments_attempted: missing
- reservations_saved: missing
- final_compaction_ran: missing
- lifecycle_tags_released: missing

## Product Owner Delivery

- status: delivered_readback_confirmed
- destination_task_id: 019faa62-6058-7643-b9cc-a2627083af07
- readback_evidence: `codex_app.read_thread` showed Product Owner task item `731` contains the exact SG-0177 Curator compact payload.
