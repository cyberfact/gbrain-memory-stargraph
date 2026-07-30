---
type: run
title: Memory Stargraph Capture Link Drain SG-0177 host runner nonterminal processing failure run - 2026-07-30 .85
date: '2026-07-30'
automation_id: memory-stargraph-capture-link-drain
invocation_id: capture-link-drain-20260730t132639-0700-sg0177-hostrunner-85
mode: host_runner_spool
status: failed
linked_goal: goals/memory-stargraph-continuous-learning-local-knowledge-os
product_owner_notification_status: delivered_readback_confirmed
product_owner_notification_pending: false
---

# Memory Stargraph Capture Link Drain SG-0177 host runner nonterminal processing failure run - 2026-07-30 .85

## Invocation Evidence

- invocation_id: capture-link-drain-20260730t132639-0700-sg0177-hostrunner-85
- automation_id: memory-stargraph-capture-link-drain
- worker_task_id: 019facae-11ea-7521-ab27-e36e5cac5fbd
- source_sync_preflight: current
- workspace_path: `/Users/toddy/memory-stargraph`
- branch: `main`
- local_head: dca51050bd1e69428126eacef3ca1fca55bdefc2
- upstream_ref: origin/main
- upstream_head: dca51050bd1e69428126eacef3ca1fca55bdefc2
- dirty_state: clean before local evidence files
- divergent_state: false
- expected_commit: dca51050bd1e69428126eacef3ca1fca55bdefc2
- task_local_network_used: false
- task_local_curl_or_api_used: false
- task_local_direct_gbrain_or_postgresql_used: false
- task_local_browser_or_capture_mutation_used: false
- approval_requested: false

## Spool Request

- submit_command: `python3 scripts/automation/capture_link_host_runner.py submit --invocation-id capture-link-drain-20260730t132639-0700-sg0177-hostrunner-85 --expected-commit dca51050bd1e69428126eacef3ca1fca55bdefc2 --mode auto --nonce sg0177-20260730t132639-0700-canonical-curator --json`
- request_file_initial: `/Users/toddy/memory-stargraph/var/capture-link-runner/incoming/sg0177-20260730t132639-0700-canonical-curator.json`
- request_file_current: `/Users/toddy/memory-stargraph/var/capture-link-runner/processing/sg0177-20260730t132639-0700-canonical-curator.json`
- result_file_expected: `/Users/toddy/memory-stargraph/var/capture-link-runner/results/capture-link-drain-20260730t132639-0700-sg0177-hostrunner-85.json`
- nonce: sg0177-20260730t132639-0700-canonical-curator
- operation: capture_link_drain
- mode: auto
- request_version: 1

## Runner Ownership Evidence

- runner_host_role: .85-authoritative
- runner_enabled: true
- runner_instance_id: 00e250d3aad34eedaafb42a5532d3295
- runner_pid: 93500
- runner_started_at: 2026-07-30T13:16:29-07:00
- configured_remote_runner_disabled: true
- remote_role: .102
- remote_disabled_method: disabled_by_default_without_launchd_enablement
- remote_disabled_verification: `.102 code deployed; MEMORY_STARGRAPH_CAPTURE_RUNNER_ENABLED is not set by default`
- atomic_claim: true
- claim_state: incoming_renamed_to_processing
- claimed_at: 2026-07-30T13:26:49-07:00
- claimed_by_pid: 93500
- active_invocation_id: capture-link-drain-20260730t132639-0700-sg0177-hostrunner-85

## Acceptance Failure

- terminal_status: failed_sg0177_acceptance_host_runner_nonterminal_processing
- final_status_read: pending
- daemon_status: processing
- terminal_result_file_present: false
- final_observed_at: 2026-07-30T13:28:17-07:00
- failure_reason: The SG-0177 hard contract requires a terminal host-runner result proving source revision validation, compaction, exactly one authoritative snapshot, durable Run/report persistence/readback, empty-queue enrichment or valid no-candidate evidence, final compaction, and lifecycle tag release. This invocation remained pending with the request stuck in `processing`, so none of those terminal result fields exist for this invocation.
- source_revision_validation_present: false
- first_compaction_present: false
- authoritative_snapshot_count_present: false
- active_run_persistence_present: false
- empty_queue_selection_evidence_present: false
- terminal_run_report_persistence_present: false
- final_compaction_present: false
- lifecycle_tag_release_present: false
- candidate_scope_completeness_auditable: false
- no_eligible_candidate_claim_present: false
- truncation_semantics_auditable: false

## Product Owner Delivery

- product_owner_notification_status: delivered_readback_confirmed
- product_owner_notification_pending: false
- product_owner_delivery_destination_task_id: 019faa62-6058-7643-b9cc-a2627083af07
- product_owner_delivery_readback: confirmed via `codex_app.read_thread`; Product Owner task item `731` contained the exact SG-0177 Curator compact payload.
