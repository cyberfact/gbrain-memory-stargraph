# OpenClaw Final P1 Race and Lifecycle Remediation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make recovery requests generation-idempotent, keep executor work fair, enforce exact active-manifest identities, and prove activation shutdown waits for live HTTP handlers.

**Architecture:** Memory Stargraph owns the durable recovery generations, canonical projection validation, executor scheduling, and HTTP resource lifecycle. GTasks consumes the strict operation-generation protocol and holds one recovery generation open while it GET-polls, so a retry cannot advance the durable revision underneath canonical verification.

**Tech Stack:** Python 3 standard library, `unittest`, in-memory durable-store test doubles, `ThreadingHTTPServer`, and existing Memory Stargraph/GTasks modules.

## Global Constraints

- Do not call live NATS, GBrain, Memory Stargraph services, configuration endpoints, or deployment helpers.
- Write each regression test first and verify the expected RED before production edits.
- Keep status and active handlers bounded; canonical graph verification remains worker-owned.
- Append final RED/GREEN and command evidence to `.superpowers/sdd/task-2a-report.md`.
- Commit each repository independently only after focused, full, and static verification.

---

### Task 1: Recovery generation idempotency and cross-repository polling

**Files:**
- Modify: `tests/test_openclaw_profile_activation.py`
- Modify: `tests/test_api_endpoints.py`
- Modify: `openclaw_profile_activation.py`
- Modify: `/Users/tony/.codex/worktrees/openclaw-agent-delegation/gtasks/tests/test_openclaw_profile_activation_client.py`
- Modify: `/Users/tony/.codex/worktrees/openclaw-agent-delegation/gtasks/gtasks/gbrain.py`

**Interfaces:**
- Produces: operation responses with integer `recovery_request_generation` and `recovery_processed_generation`.
- Consumes: `request_recovery(operation_id)` and `MemoryStargraphOpenClawProfileClient.wait(...)`.

- [ ] **Step 1: Write the failing Memory race test**

Block terminal canonical verification after generation 1 is queued, issue repeated recovery requests, and assert both responses report generation 1 while the operation-store revision does not change.

- [ ] **Step 2: Run the Memory test and verify RED**

Run: `python3 -m unittest tests.test_openclaw_profile_activation.OpenClawProfileActivationTests.test_pending_recovery_request_is_revision_idempotent_during_terminal_verification`

Expected: FAIL because the repeated request increments the generation or conflicts with the terminal CAS.

- [ ] **Step 3: Implement the minimal Memory contract**

Return the existing operation view before CAS when `_recovery_pending(operation)` is true. Include exact requested/processed generations in every operation view and retain compare-and-set only for a newly requested generation.

- [ ] **Step 4: Write and run the failing GTasks polling test**

Use a deterministic client double whose recovery POST returns request generation 1, whose GET returns generation 1 pending twice, and whose final GET returns processed generation 1 terminal. Assert one POST and only GET polling after it.

Run: `python3 -m unittest tests.test_openclaw_profile_activation_client.OpenClawProfileActivationClientTests.test_recovery_generation_is_posted_once_then_get_polled_to_exact_completion`

Expected: FAIL because the current loop POSTs every `recovery_required` response.

- [ ] **Step 5: Implement and verify the GTasks generation state machine**

Track the exact generation returned by POST. While its processed generation is lower, sleep and GET status; never POST again. Once processed, handle the terminal response or allow a later distinct recovery generation.

---

### Task 2: Executor isolation and projection-validation fairness

**Files:**
- Modify: `tests/test_openclaw_profile_activation.py`
- Modify: `openclaw_profile_activation.py`

**Interfaces:**
- Consumes: `OpenClawProfileActivationExecutor.run_once()`.
- Produces: per-operation exception isolation plus independent requested/periodic projection validation each cycle.

- [ ] **Step 1: Write failing starvation and time-advance tests**

Use a service double with two operation IDs where the first adoption raises and the second succeeds. Keep a stuck operation visible while advancing the executor clock through the validation interval and separately request immediate validation.

- [ ] **Step 2: Verify RED**

Run the named executor tests and confirm the first exception blocks the second operation and processed work suppresses projection validation.

- [ ] **Step 3: Implement minimal independent lanes**

Catch each adoption exception independently, continue later operation IDs, then evaluate the projection request/deadline unconditionally. Preserve a useful `last_error` when either lane fails.

- [ ] **Step 4: Verify GREEN**

Run the named tests and the complete activation-focused test module.

---

### Task 3: Exact generation-positive active response

**Files:**
- Modify: `tests/test_openclaw_profile_activation.py`
- Modify: `openclaw_profile_activation.py`
- Modify: `/Users/tony/.codex/worktrees/openclaw-agent-delegation/gtasks/tests/test_openclaw_profile_activation_client.py`
- Modify: `/Users/tony/.codex/worktrees/openclaw-agent-delegation/gtasks/gtasks/gbrain.py`

**Interfaces:**
- Consumes: ready projection fields `generation`, `active_manifest`, and `manifest_digest`.
- Produces: exact manifest slug `system/openclaw-profile-manifests/gNNNNNN-<operation_id>` and lowercase SHA-256 enforcement for generation greater than zero.

- [ ] **Step 1: Write failing producer and consumer validation tests**

Cover generation-positive null manifest, wrong-generation slug, invalid operation suffix, uppercase digest, and valid generation-zero empty state.

- [ ] **Step 2: Verify RED in each repository**

Run only the new active-response tests and confirm invalid producer/cache or client responses are currently accepted.

- [ ] **Step 3: Implement exact invariants**

Validate the canonical producer before storing a projection, validate durable cached projections on load/use, and reject invalid ready responses in GTasks before profiles are consumed.

- [ ] **Step 4: Verify GREEN**

Run the active projection focused tests in both repositories.

---

### Task 4: HTTP handler shutdown ordering

**Files:**
- Modify: `tests/test_api_endpoints.py`
- Modify: `server.py`

**Interfaces:**
- Produces: `MemoryStargraphHTTPServer` with `daemon_threads = False` and `block_on_close = True`.
- Consumes: main shutdown ordering `server_close()` before `stop_openclaw_profile_activation_runtime()`.

- [ ] **Step 1: Write a failing live-handler shutdown test**

Start a real loopback HTTP server with a status handler blocked inside the activation service. Begin shutdown and assert runtime close has not happened. Release the handler, then assert the response completes, the handler joins, and service close occurs afterward without warnings.

- [ ] **Step 2: Verify RED**

Run the named endpoint test and confirm the current daemon server closes activation while the handler is still live.

- [ ] **Step 3: Implement the non-daemon server class**

Subclass `ThreadingHTTPServer`, set `daemon_threads = False` and `block_on_close = True`, and construct this class in `main()`.

- [ ] **Step 4: Verify GREEN**

Run the shutdown test and all endpoint tests with `RuntimeWarning` promoted to errors.

---

### Task 5: Documentation, report, verification, and commits

**Files:**
- Modify: `docs/openclaw-profile-activation-runbook.md`
- Modify: `/Users/tony/.codex/worktrees/openclaw-agent-delegation/gtasks/.superpowers/sdd/task-2a-report.md`

**Interfaces:**
- Produces: durable audit of requirements, RED/GREEN evidence, exact commands, and commit hashes.

- [ ] **Step 1: Update the runbook and append the report**

Document generation-idempotent POST/GET polling, independent executor lanes, active identity invariants, and non-daemon handler shutdown ordering.

- [ ] **Step 2: Run focused and full tests**

Memory focused: `python3 -W error::RuntimeWarning -m unittest tests.test_openclaw_profile_activation tests.test_api_endpoints`

Memory full: `python3 -W error::RuntimeWarning -m unittest discover -s tests -q`

GTasks focused: `python3 -m unittest tests.test_openclaw_profile_activation_client`

GTasks full: `python3 -m unittest discover -s tests -q`

- [ ] **Step 3: Run static checks**

Memory: `python3 -m py_compile openclaw_profile_activation.py server.py`, `node --check public/app.js`, and `git diff --check`.

GTasks: `python3 -m compileall -q gtasks scripts/provision_openclaw_agent_profiles.py`, `node --check static/app.js`, and `git diff --check`.

- [ ] **Step 4: Commit each repository and read back clean state**

Commit Memory and GTasks separately, append the final hashes to the ignored report, and verify each tracked worktree is clean.
