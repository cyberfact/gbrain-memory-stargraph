# OpenClaw profile activation runbook

Memory Stargraph is the sole activation authority for the three declared
OpenClaw profiles. GTasks must call the authenticated internal endpoint; it
must not write the profile pages or relationships directly.

## Private deployment configuration

Provisioning remains disabled unless all of these private environment settings
are supplied outside this repository:

- `MEMORY_STARGRAPH_OC_PROVISION_ENABLED=1`
- `MEMORY_STARGRAPH_OC_PROVISION_TOKEN`
- `MEMORY_STARGRAPH_OC_NATS_SERVERS`
- `MEMORY_STARGRAPH_OC_NATS_CREDENTIALS_FILE`
- `MEMORY_STARGRAPH_OC_NATS_KV_BUCKET`
- `MEMORY_STARGRAPH_OC_NATS_JOURNAL_SUBJECT`
- `MEMORY_STARGRAPH_OC_LEASE_SECONDS` (optional, default `120`, minimum `30`)
- `MEMORY_STARGRAPH_OC_CLOCK_SKEW_SECONDS` (optional, default `5`)
- `MEMORY_STARGRAPH_OC_NATS_CONNECT_TIMEOUT_SECONDS` (optional, default `5`, maximum `30`)
- `MEMORY_STARGRAPH_OC_NATS_REQUEST_TIMEOUT_SECONDS` (optional, default and maximum `2`)

The NATS credentials file, bucket, and journal stream are pre-provisioned by
the operator. The service never creates a KV bucket or stream. The same bearer
token is required by GTasks as `MEMORY_STARGRAPH_OC_PROVISION_TOKEN`; GTasks
also needs `MEMORY_STARGRAPH_URL` for the service URL.

The dashboard-managed Memory Stargraph Python runtime must declare and install
`nats-py==2.15.0` before enabling this endpoint. Its setup check is
`<dashboard-runtime-python> -c 'import nats; print(nats.__version__)'`.
Absence of that dependency is a fail-closed activation error; do not fall back
to a different process Python or install it ad hoc in the repository.

## Activation protocol

1. GTasks creates and durably saves an `operation_id` and request owner before
   submitting. `POST /api/internal/openclaw-profiles/provision` returns `202`
   with `accepted`; retrying the same request uses that same operation and does
   not allocate another generation. The request only persists durable state and
   wakes the process-level executor. At service startup and on each scan, that
   executor adopts durable `accepted`, stale `running`, and
   `recovery_required` records, so execution is not owned by an HTTP request
   thread.
2. GTasks polls
   `GET /api/internal/openclaw-profiles/operations/<operation_id>`. The durable
   status is one of `accepted`, `running`, `completed`, `failed`, or
   `recovery_required`. A completed operation includes its immutable manifest
   receipt plus a receipt schema version and SHA-256 digest in the durable
   operation record. The worker performs exact canonical receipt/graph
   verification before writing `completed`; terminal status polling validates
   only that durable schema and digest and performs no GBrain reads. Every
   terminal or nonterminal status request performs exactly one bounded operation
   KV read; the executor, not GET, detects expired or ambiguous execution. The
   recovery endpoint persists a monotonically increasing recovery-request
   generation and wakes the executor. Every operation response exposes both
   `recovery_request_generation` and `recovery_processed_generation`. If the
   requested generation is already greater than the processed generation, a
   repeated recovery POST returns that same pending generation without a CAS or
   revision change. GTasks POSTs once, then uses only status GETs until that
   exact generation is processed and a terminal result is visible. All
   lifecycle endpoints require the same bearer token.
3. The control record uses a single JetStream KV key containing the lease,
   monotonic fence generation, expiry, state, and active manifest pointer. A
   unique session owner must claim the fence before the operation can become
   `running`. The holder revalidates and renews ownership immediately before
   every page, link, manifest, and activation-CAS mutation, and stops mutating
   before the configured clock-skew boundary. Claiming re-samples the clock
   after prior-completion reconciliation and again immediately before the lease
   expiry is calculated and the control CAS is attempted.
4. The holder stages generation-namespaced pages and typed links under
   `system/openclaw-profile-staging/...`, verifies exact GBrain readback, and
   writes an immutable generation manifest.
5. Only a successful CAS on that same control key changes the active manifest.
   An expired or stale lease cannot activate.
6. Worker validation double-reads the control revision around the manifest and
   requires the exact manifest schema, digest, approved page/link hashes, and
   immutable link sets. It durably stores the resulting last-known-good
   projection with its exact control revision, manifest digest, projection
   digest, and validation timestamp. `GET /active` performs only one bounded
   control read and a process-cache lookup. It returns `200 ready` only when the
   cached revision, manifest, generation, and digest still match; otherwise it
   returns `202 validation_pending` and queues canonical validation. The
   executor validates on demand and periodically every 60 seconds, independently
   of whether that cycle scans, completes, or fails activation operations. Each
   operation adoption is exception-isolated so one damaged operation cannot
   starve later IDs. A ready generation greater than zero requires a non-null
   manifest slug whose `gNNNNNN-<operation_id>` identity exactly embeds that
   generation and a valid operation ID, plus a lowercase 64-character SHA-256
   digest. Only generation zero may have no manifest. GTasks projects only
   records selected by a ready projection and ignores all staged identities
   during normal GBrain directory scans.

## Profile field authority and canonical-page guard

The CAS-selected immutable generation metadata is the presentation authority
for an activated profile. GTasks must take the profile title/name, summary,
runtime, chat URL when present, and any future generation-owned presentation
fields from that verified metadata. Generation metadata is bound to its staged
Agent page hash and cannot be replaced by similarly named fields on the stable
logical Agent page.

The stable logical Agent is the authority only for its current mutable avatar
and canonical outgoing relationships, including Tony-assigned
`default_agent_for` Goal edges. Its slug, type, `runtime: openclaw`, and
`logical_anchor: true` fields remain immutable identity evidence rather than
editable presentation fields. Logical task and Artifact collections likewise
retain their exact slug/type/collection identity and declared `for_agent` and
`part_of` relationships. GTasks may mutate a logical OC anchor only through the
supported avatar and default-Goal methods. It must not edit logical title,
summary, runtime, task/Artifact identity fields, invariant provisioning links,
generation pages, or generation-owned presentation metadata.

Every activation-envelope read compares the current outer canonical GBrain page
with the embedded activation payload before trusting the payload. Logical pages
must still match the immutable identity fields above; staged generation pages
must match their outer slug, type, title, and staged frontmatter. A stale payload
cannot hide an outer runtime, collection owner, or staging-identity change.
Canonical link readback is verified separately against the exact invariant
`for_agent`/`part_of` set, while the explicitly mutable Agent
`default_agent_for` edges are allowed only after initial zero-Goal activation.

On canonical projection failure, the process atomically removes the current
LKG from its serving cache before any projection-store I/O. The failed serving
revision takes priority over an older private invalidation target and retains
its exact control revision, manifest digest, projection digest, full projection
payload, and original validation error. A projection-store read, CAS, or
transport failure does not erase that target or restore serving; the
executor's requested validation cycle retries until the matching durable
record is marked `invalid`. The target is also resolved when the durable store
has a strictly greater control revision, which proves a newer validated
projection superseded it. A same-revision manifest, projection digest, or
payload change is not newer and remains a conflict.

Process startup validates the durable projection-record schema but treats a
durable `ready` record only as a non-serving revalidation candidate.
`GET /active` remains `validation_pending` until a fresh canonical/control
validation succeeds and stores the validated record. If that validation
fails, the candidate supplies the exact durable invalidation identity; a
transport failure retains it for retry. Successfully storing a strictly newer
validated projection clears a local pending target for an older control
revision before the new projection is served. Therefore restart cannot replay
a durable `ready` record whose invalidation was interrupted.

The asynchronous contract is the durable `202 accepted` plus status-polling
protocol. A caller may expose that protocol through a bounded synchronous
client wrapper; it does not have to expose Python coroutine methods.

The server constructs one activation service and one NATS connection/event
loop for its entire process lifetime. Handlers and the executor reuse it; they
never connect or drain per request. HTTP request threads are non-daemon and
`server_close()` blocks until every live handler completes. Only after that
join does shutdown stop the executor and drain the singleton session exactly
once, so a handler cannot use a closed activation service. Every connect, KV,
publish, drain, and close wait remains bounded. A connection created before a
startup failure is drained or closed on that same live worker loop before the
loop closes; cleanup cannot replace the original startup error. Journal
identities contain operation, fence, step, resource, and phase, with `before`
and `after` evidence around each ambiguous mutation. An authorized caller may
invoke
`POST /api/internal/openclaw-profiles/operations/<operation_id>/recover` only
for the same durable operation. That request schedules recovery; the durable
executor verifies journal, control, and exact canonical GBrain state, resumes
the same fence when safe, and proves an already-completed activation without
allocating a successor. Before a successor may claim the control key, any prior
control receipt is verified and durably terminalized, so later activation cannot
erase its completion evidence. Any known missing
`activate/control/after` audit event is reconciled before that terminal CAS, and
explicit recovery performs the same reconciliation idempotently for an already
terminal operation. Recovery requests for both `completed` and `failed`
operations remain durable work: the executor includes the flagged terminal
record, rechecks its receipt, current control outcome, complete journal, and
exact canonical graph, and records the processed generation, verification
timestamp, verification digest, and truthful result. Canonical tampering can
therefore change a formerly completed operation to `failed`; transient or
ambiguous evidence remains `recovery_required`. Deterministic declaration,
exact-content/link, or authorization conflicts become terminal `failed`.
Transient GBrain, NATS, and transport errors before a claim remain `accepted`;
live-lease contention is retryable; only claimed ambiguous interruption or
expired ownership remains `recovery_required`. Abandoned staged records are not
deleted or made visible.

## Endpoint budgets

The NATS request ceiling is 2 seconds. With status and active limited to one KV
read, their aggregate server budget is 2.5 seconds. Provision allows 6.5 seconds
for read/create/race readback, and recovery-request persistence allows 4.5
seconds for one read/CAS attempt; the durable caller can retry the same
operation after a CAS conflict. A repeated request for an already-pending
generation performs only the read and returns without CAS. GTasks uses 4-second
status/active deadlines and 8-second provision/recovery deadlines, leaving
explicit transport margin while retaining the 180-second total polling
deadline.

## Non-live verification

```bash
python3 -W error::RuntimeWarning -m unittest \
  tests.test_openclaw_profile_activation tests.test_api_endpoints
```

Do not enable the endpoint, create NATS infrastructure, write GBrain profiles,
or deploy this change until the operational configuration and review are
explicitly approved.
