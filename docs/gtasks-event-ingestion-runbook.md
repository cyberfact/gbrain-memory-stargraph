# Unified GTasks Event Ingestion Runbook

This runbook defines the client-neutral asynchronous contract for applications
that report durable facts for GTasks and canonical GBrain handling. It applies
to Career Path Tuning Up and future producers. It is not a Career Path-specific
API.

GBrain remains the canonical knowledge store. Producers own and commit their
local state before publishing an event. A separately managed durable queue owns
message persistence and delivery. GTasks is one consumer: it leases supported
events, performs explicit handler-owned GBrain/task mutations, verifies those
effects, and acknowledges the message only after successful readback.

## Current implementation status

**Tested local NATS JetStream binding as of 2026-07-30:** official
`nats-server` v2.14.4 and `nats-py` v2.15.0 provide the independently managed
durable queue. GBrain remains the downstream knowledge system, not the broker.
All Things Codex Dashboard manages the broker as `gtasks-events` and the
asynchronous worker as `gtasks-event-consumer`.

The deployed binding is loopback-only. Its generated owner-only runtime is:

`/Users/tony/.codex/services/all-things-codex-dashboard/state/gtasks-events`

The reader has no quota-task map or static task mapping. Starting or testing
the queue therefore does not select a live Tony task or mutate live GBrain
data. A real `job_applied` event can succeed only after exactly one existing
active task opts in through the canonical per-task metadata documented below.

## Architecture and ownership

```text
Producer local commit
        |
        v
durable producer outbox
        |
        v
protected queue ingress -> durable broker storage
                                |
                                v
                     lease to registered consumer
                                |
                                v
                         GTasks handler
                                |
                                v
                    canonical GBrain readback
```

- Producers publish only to one protected queue-ingress boundary. They do not
  call GTasks or individual GBrain mutation routes.
- Queue acceptance means the event is durably stored for asynchronous delivery.
  It does not mean GTasks has processed it or GBrain is already updated.
- The queue/broker is managed separately from producer and consumer processes.
  Restarting either side must not lose an accepted event.
- Consumers lease messages, process them asynchronously, and acknowledge only
  after their terminal result is durably recorded.
- GTasks owns downstream canonical GBrain/task effects for the event types it
  consumes. Producers cannot choose GBrain commands, slugs, relationships, or
  counters.
- Each event type/version maps to an explicit registered consumer handler.
- GTasks must not create a second task database or treat a transient cache as
  the GBrain source of truth.

There is no direct producer-to-GTasks consumer dependency. GTasks may be stopped,
restarted, upgraded, or temporarily unavailable after queue acceptance without
making the producer's already committed local fact fail.

The inverse dependency is also forbidden: the queue reader is an independent
Dashboard-managed background service, not part of the main GTasks process.
Reader initialization, broker connection, durable-consumer binding, receive,
acknowledgement, processing, or recovery failures must not prevent the GTasks
UI or its task, goal, refresh, and GBrain operations from starting or
succeeding. Broker or reader health is never a fatal readiness dependency of
the main GTasks service.

### Tested NATS JetStream binding

- Broker: `nats://127.0.0.1:4222`; monitoring and JetStream health:
  `http://127.0.0.1:8222/healthz?js-enabled-only=true`.
- Main stream: `GTASKS_EVENTS`, file storage, limits retention, subject
  `gtasks.events.>`, 30-day maximum age, 512 MiB maximum bytes, 64 KiB maximum
  message, two-hour broker duplicate window.
- First producer subject: `gtasks.events.job_applied.v1`.
- Durable pull consumer: `GTASKS_JOB_EVENTS`, filter
  `gtasks.events.job_applied.v1`, explicit acknowledgement, one in-flight
  message, five maximum deliveries.
- `BackOff` is `[30s, 60s, 5m, 15m, 1h]`. In JetStream the first BackOff value
  is the effective `AckWait`, so the tested initial lease is 30 seconds.
  The worker sends progress acknowledgements during processing.
- Dead-letter stream: `GTASKS_EVENTS_DLQ`, file storage, subject
  `gtasks.deadletter.>`, 365-day maximum age, 128 MiB maximum bytes, 8 KiB
  maximum terminal record.

The Dashboard successfully starts, stops, and restarts both processes. Isolated
real-broker tests prove durable PubAck, duplicate PubAck, broker-restart
persistence, unacknowledged lease redelivery after consumer restart, bounded
retry, DLQ acceptance, and explicit redrive.

## Versioned event envelope

The queue message is a strict JSON object with this logical shape:

```json
{
  "event_id": "producer-generated globally unique event identifier",
  "idempotency_key": "stable logical-operation identifier reused on every retry",
  "event_type": "job_applied",
  "schema_version": 1,
  "source": {
    "client_id": "registered producer identity",
    "instance_id": "stable local installation identity"
  },
  "occurred_at": "2026-07-30T09:42:00-07:00",
  "timezone": "America/Los_Angeles",
  "payload": {}
}
```

Envelope rules:

- `event_id` is immutable and globally unique. Publish and delivery retries reuse
  it.
- `idempotency_key` identifies the real-world operation. A producer reuses it
  across retries and never generates a new key to bypass an uncertain result.
- `event_type` and `schema_version` select a registered consumer handler.
- `source.client_id` is the authenticated, authorized producer identity.
  `source.instance_id` distinguishes installations without naming a human.
- `occurred_at` is an offset-aware RFC 3339 timestamp for when the fact occurred,
  not when it was published or delivered.
- `timezone` is an IANA timezone used for deterministic local-day behavior.
- `payload` contains only event-handler-defined factual fields.

The tested producer binding validates strictly before publication, and the
consumer validates independently after leasing. Missing required fields,
unknown top-level fields, invalid timestamps or timezones, oversized values,
source mismatches, unsupported schema versions, and undeclared payload fields
are rejected. The broker authentication/subject policy is the wire ingress
boundary; it does not parse JSON. A credential holder bypassing the tested
producer binding can therefore store an invalid message, but the consumer will
terminalize it without invoking a handler. Payload strings are never coerced
into commands or arbitrary GBrain content.

## Queue ingress and producer contract

The producer sequence is:

1. Commit the factual change in the producer's local canonical store.
2. Persist the complete event envelope in a durable local outbox.
3. Publish the same envelope until the queue confirms durable acceptance.
4. Mark the outbox item delivered only after that durable acceptance.
5. Continue without waiting for GTasks or GBrain processing.

The primary local commit is the user operation and is authoritative for the
producer. Once it succeeds, a queue publish failure, unavailable broker,
timeout, or rejection must not roll it back, block completion, or turn it into
a failed user operation. The producer must:

- preserve the complete event in durable retry state with the same `event_id`
  and `idempotency_key`;
- record only safe correlation and error metadata;
- surface a non-blocking warning that downstream synchronization is delayed;
- retry later according to the tested NATS policy, without requiring the user
  to repeat the primary operation.

There is no synchronous direct-to-GTasks fallback. Such a fallback would
re-couple the producer to the consumer, create a second delivery path, and make
idempotency and failure recovery ambiguous.

JetStream deduplicates repeated publication of the same `event_id` through the
`Nats-Msg-Id` header for two hours. Durable consumer receipts independently
detect reuse of `(source.client_id, idempotency_key)` with materially different
content. Repeated publication of the identical envelope is successful and
creates no second queued message during the broker window; a later duplicate
still produces no second business effect.

The tested producer binding distinguishes:

| Queue-ingress outcome | Meaning | Producer action |
| --- | --- | --- |
| Durably accepted | JetStream returned a `PubAck` for `GTASKS_EVENTS`. | Mark outbox delivery complete. |
| Duplicate accepted | JetStream returned the same stream acceptance with `duplicate: true`. | Treat as durable acceptance. |
| Rejected | Authentication or strict envelope/type/version validation failed. | Preserve the durable outbox item, surface a non-blocking warning, and require configuration or payload correction before retrying the same IDs. |
| Unavailable or unknown | Durability was not confirmed. | Retry the same IDs with bounded backoff. |

Queue acceptance never claims that a consumer returned `accepted` or that GBrain
already reflects the event.

## Consumer leases, dispatch, and acknowledgement

The broker leases an event to a consumer rather than transferring ownership
permanently. A crash, timeout, or negative acknowledgement makes the event
eligible for redelivery according to the configured retry policy.

GTasks maintains an explicit registry keyed by `(event_type, schema_version)`.
Each registry entry declares:

- authorized producer identities;
- a strict payload schema and size bounds;
- one deterministic handler;
- handler idempotency and readback rules;
- permitted canonical GBrain effects;
- retry and terminal-failure classification;
- safe result and observability fields.

For each lease, GTasks:

1. Authenticates the broker/consumer connection and validates the envelope.
2. Checks its durable processing receipt for `event_id` and logical operation.
3. Resolves one registry entry without fuzzy matching or LLM routing.
4. Executes only that handler's bounded canonical writes.
5. Reads back every required page, relationship, evidence, and progress effect.
6. Durably records the handler result.
7. Acknowledges the lease only after verified success or an explicitly recorded
   terminal disposition.

Unknown event types or unsupported schema versions never reach a fallback
handler. They receive a terminal `rejected_unknown_type` disposition and remain
observable for producer/consumer contract correction.

## Consumer handler results

Consumer results are asynchronous processing state, not the producer's publish
response. Each includes safe correlation fields such as `event_id`,
`event_type`, `schema_version`, consumer/handler version, and:

| Status | Meaning | Queue action |
| --- | --- | --- |
| `accepted` | Handler effects completed and exact canonical readback passed. | Record result and acknowledge. |
| `duplicate` | The same event/logical operation already has the same verified effect. | Record duplicate and acknowledge. |
| `rejected_unknown_type` | No authorized handler exists for this type/version. | Record terminal failure; do not retry unchanged. |
| `failed` | Validation, dependency, mutation, or readback failed. | Retry or terminalize according to safe classification. |

A `failed` result includes a safe `error_code` and `retriable` flag, never
secrets, raw payloads, private document text, or stack traces. Retriable failures
return to the queue after bounded backoff. Non-retriable failures move to the
broker's tested dead-letter or terminal-failure path.

## Idempotency and restart safety

This architecture assumes at-least-once delivery. Exactly-once business effects
come from idempotency and verified canonical state, not from assuming the broker
delivers once.

- Queue ingress deduplicates publish retries by event and logical-operation ID.
- Consumer processing receipts survive GTasks restarts.
- Handlers use deterministic natural keys for canonical entities and progress.
- Repeating an accepted event returns `duplicate` and makes no new graph write.
- Reusing an idempotency key with changed material content is terminal conflict.
- A handler acknowledges only after exact GBrain readback.
- Partial writes return retriable `failed`; redelivery resumes or reconciles the
  same operation without deleting already verified canonical data.
- Lease expiry after a consumer crash causes redelivery, not event loss.
- Broker restart preserves accepted events, retry state, and terminal records.
- Progress is successful only when the factual record and once-only progress
  marker are both verified.

The durable broker storage is JetStream file storage. GTasks processing
receipts use an owner-only SQLite database with full synchronous commits and a
unique logical-operation key; neither is an in-memory set or disposable cache.

## Ordering and eventual consistency

- There is no global event-order guarantee.
- No narrower ordering key has been tested. Consumers must tolerate
  out-of-order and repeated delivery.
- Any future per-entity ordering scope must be deterministic, documented by the
  handler, and stable across producers. Producers must not infer ordering from
  this single-stream binding.
- `occurred_at` and handler-specific version facts help reconcile out-of-order
  events; arrival order alone must not overwrite newer canonical state.
- A handler that cannot safely reconcile order returns a retryable or terminal
  failure rather than guessing.

Producer UI and local state are eventually consistent with GBrain. After durable
queue acceptance, downstream GBrain/task updates may be delayed by backlog,
consumer downtime, retries, or operator review. Clients may show `queued`,
`processing`, `completed`, or `failed` only when those states come from real
queue/consumer evidence; they must not equate publish success with completion.

## Retry, dead-letter, and terminal-failure operations

- Producers retry only when durable enqueue was not confirmed, using the same
  envelope and bounded exponential backoff with jitter.
- Consumers retry only `retriable: true` failures.
- Retry attempts are bounded and observable; a message cannot loop silently.
- Exhausted retries and non-retriable failures move to a durable dead-letter or
  terminal-failure record with event ID, type/version, producer identity, safe
  error code, attempt count, and timestamps.
- Dead-letter records exclude payload bodies, credentials, private evidence,
  signed URLs, and raw exception traces.
- Redrive requires an explicit operator action after correcting the cause and
  reuses the original event and idempotency IDs.
- Acknowledging or deleting a terminal record without verified resolution is
  forbidden.

The tested retry ceiling is five deliveries with `[30s, 60s, 5m, 15m, 1h]`
delays. A terminal record contains only safe identifiers, the original stream
sequence, safe error code, attempts, and timestamp. It never contains the
original payload.

After correcting the terminal cause, an operator explicitly redrives with:

```bash
cd /Users/tony/.codex/services/all-things-codex-dashboard/services/gtasks-event-consumer
/Users/tony/.codex/services/all-things-codex-dashboard/state/gtasks-events/venv/bin/python \
  -m gtasks.event_queue redrive \
  --event-id '<original-event-id>' \
  --confirm
```

Redrive reads the original message by its recorded `GTASKS_EVENTS` stream
sequence, verifies the body still has the same `event_id`, and republishes the
unchanged body. The logical `event_id` and `idempotency_key` remain unchanged.
The operator redrive uses a distinct broker deduplication message ID so a
corrected event can be delivered before the two-hour publish-dedup window ends.
The terminal record is retained as audit history.

## Authentication and least privilege

- Give each producer its own revocable publish credential and allowed event
  types. Producers cannot lease, acknowledge, inspect other producers' events,
  or access GBrain through this integration.
- Give each consumer its own credential and only the queue operations needed to
  lease, renew, acknowledge, reject, and terminalize its authorized event types.
- Give GTasks handlers only their documented GBrain mutations. Do not expose
  general-purpose shell or graph-write capability.
- Keep credentials in local secret storage, never Git, URLs, payloads, GBrain,
  or logs.
- Authenticate before logging event details, compare credentials safely,
  rate-limit failures, and support independent rotation/revocation.
- Broader-than-loopback or multi-host broker exposure requires transport
  protection and an explicit threat review.

Runtime setup generates three distinct random password credentials:

- `gtasks-admin` can provision and operate the two bounded streams and consumer;
- `career-path-producer` can publish only
  `gtasks.events.job_applied.v1` and subscribe only to its private inbox prefix;
- `gtasks-event-consumer` can request/inspect only
  `GTASKS_JOB_EVENTS`, publish its acknowledgements and safe DLQ subject, and
  subscribe only to its private inbox prefix.

The server configuration and credential JSON files are mode `0600`; their
parent runtime is mode `0700`. The non-secret Career Path binding file contains
only the broker URL, subject, stream, credential-file location, message-ID
header, timeout, and enqueue-only result semantics. The broker is plaintext
only on loopback; any non-loopback exposure still requires TLS and a threat
review.

## Safe observability

Correlate the producer outbox, broker receipt, delivery attempts, consumer
result, and GBrain readback using safe identifiers. Record only:

- event and idempotency IDs;
- authenticated producer and consumer IDs, never credentials;
- event type/schema and handler version;
- enqueue, lease, attempt, acknowledgement, and terminal timestamps;
- accepted, duplicate, rejected, retriable-failed, or terminal-failed outcome;
- safe error code, attempt count, queue age, and processing durations;
- counts of attempted and verified GBrain effects;
- a schema fingerprint or content hash needed for idempotency conflicts.

Do not log payload bodies, resume/application text, contact details, credentials,
evidence contents, signed URLs, arbitrary GBrain content, or raw stack traces.

### Deployed Queue Reader observability boundary

The tested read-only boundary is:

- current health: `http://127.0.0.1:4181/api/health`;
- health plus bounded safe history:
  `http://127.0.0.1:4181/api/observability`;
- persisted snapshot:
  `/Users/tony/.codex/services/all-things-codex-dashboard/state/gtasks-events/reader-observability.json`.

The observability response is schema version 1:

```json
{
  "schema_version": 1,
  "health": {
    "status": "ok",
    "broker_connected": true,
    "stream": "GTASKS_EVENTS",
    "durable_consumer": "GTASKS_JOB_EVENTS",
    "pending": 0,
    "ack_pending": 0,
    "redelivered": 0,
    "processing": 0,
    "accepted": 0,
    "terminal": 0,
    "dead_letter": 0,
    "last_error_code": null
  },
  "events": [
    {
      "timestamp": "2026-07-30T20:57:55.382882+00:00",
      "component": "queue_reader",
      "severity": "info",
      "message": "Queue reader recovered."
    }
  ],
  "retention": {
    "max_events": 100,
    "order": "newest_first",
    "storage": "atomic_file"
  }
}
```

Every history message comes from a fixed allowlist owned by the reader. The
reader never interpolates exception text, credentials, broker reply subjects,
raw envelopes, job fields, event payloads, URLs, or GBrain content. It records
initialization, connection, durable-consumer binding, disconnect/receive
failure, processing failure, and recovery transitions. Repeated adjacent
messages are collapsed.

History is newest-first and bounded to 100 records. On restart the reader loads
only records whose four exact fields and fixed message tuple pass the allowlist.
Each update is written to a mode-`0600` temporary file in the mode-`0700`
runtime directory, flushed and `fsync`ed, then atomically replaces the snapshot.
The HTTP response and persisted artifact use the same schema.

The reader starts its health surface in a degraded state and retries broker
connection with bounded backoff. A receive-loop failure closes only that broker
session and retries; a received event is acknowledged only through the existing
accepted/duplicate or durable-terminal path, so failures retain NAK,
redelivery, and DLQ behavior.

On 2026-07-30 a Dashboard-managed broker stop made the reader health report
`degraded` while both the main GTasks `/api/health` and read-only `/api/tasks`
continued returning HTTP 200 from the same GTasks process. The reader health
surface also remained HTTP 200 from the same reader process. Restarting the
broker restored `broker_connected: true` without restarting either GTasks or
the reader. Automated fake-adapter tests additionally prove that core GTasks
reads and writes remain available during broker-unavailable startup and a
post-start receive failure. No live GBrain mutation was used for this
verification.
Alert on growing queue age, repeated lease expiry, retry exhaustion,
dead-letter growth, consumer unavailability, and readback failures.

## First consumer example: `job_applied`

`job_applied` is the first planned event. Career Path Tuning Up is its first
producer. GTasks is the consumer that owns downstream canonical application,
evidence, quota-task, and progress updates.

### Required sequence

1. Career Path commits its local application status as `Applied`.
2. Career Path saves the `job_applied` envelope in its durable outbox.
3. Career Path publishes the envelope to the broker.
4. After durable queue acceptance, Career Path marks outbox delivery complete
   and does not wait for GTasks.
5. GTasks asynchronously leases and validates the event.
6. The registered handler creates or updates one canonical GBrain application
   record.
7. The handler attaches or links declared evidence using the approved GBrain
   attachment/reference contract.
8. The handler deterministically resolves the existing daily application-quota
   task and links verified application evidence to it.
9. The handler records progress exactly once for the logical application.
10. The handler reads back the application, evidence association, quota task,
    and once-only progress effect, records `accepted`, then acknowledges.

Publish retry, lease expiry, and consumer retry never create a second application
or increment progress twice. If GTasks is offline, the accepted event waits
durably and GBrain remains temporarily behind Career Path's local Applied state.

### Factual payload boundary

The payload may carry only facts needed to identify the application, job,
applied timestamp, and durable evidence references. It must not carry Markdown,
a requested GBrain slug, relationship names, task search text, queue routing,
or instructions to increment a chosen counter.

The tested `job_applied` v1 payload has exactly four objects/fields:
`application_identity` (`job_source`, `job_id`), `job_snapshot` (`title`,
`company`, `location`, `url`), `applied_local_date`, and `status_evidence`
(`status`, `committed_at`, `source`). Unknown fields are rejected.

The application slug is derived only from normalized `(job_source, job_id)` and
a 12-hex SHA-256 prefix. GTasks writes one `job_application` page, an
application-to-task `evidence_for` edge, and a reciprocal task-to-application
`has_evidence` edge.

At processing time GTasks uses the current America/Los_Angeles task day and
scans only active task members with an explicit opt-in. There is no
`quota-task-map.json` lookup, configured task slug, or static mapping:

```yaml
progress_metric:
  kind: count
  label: Five applications today # optional display text; preserved, never matched
  unit: job_application
  target: 5
  current: 0
  event_binding: job_applied
  auto_complete: true
  task_day: YYYY-MM-DD
  timezone: America/Los_Angeles
event_progress:
  evidence_slugs: []
  receipt_ids: []
```

For a bound metric, every field other than `label` is required and matched
exactly. `label`, when present, is a nonempty display string of at most 160
characters; the consumer preserves it. Evidence slugs and receipt IDs are
unique, sorted deterministic identities, have equal cardinality, and
`current` equals their cardinality. On the fifth distinct accepted event,
GTasks changes the selected task through the canonical lifecycle mutation path
to `completed`, then exact-readback verifies its status, progress, and
evidence.

An ordinary manual count metric has no `event_binding` and may omit
`task_day`, `timezone`, and `event_progress`. It is ignored by this
consumer and is never auto-completed merely because `current == target` at
creation. Completed or cancelled tasks, including prior-day tasks, are never
eligible.

Zero or multiple eligible tasks, a malformed explicit `job_applied` binding,
or invalid progress fails closed and is retryable (then subject to the tested
consumer retry/DLQ policy); the reader records a privacy-safe actionable Logs
event. GTasks never searches task titles, guesses or creates a quota task, or
accepts a producer-selected slug/relationship. Accepted effects require exact
page, reciprocal-edge, and task-progress readback. SQLite processing receipts
under the owner-only runtime survive restart, lease one logical operation,
detect changed-content conflicts, and contain no application payload. No live
GBrain quota task was mutated to verify this binding.

## Implementation acceptance status

- [x] A separately managed durable broker and one protected ingress are tested.
- [x] Producer and consumer credentials enforce least privilege.
- [x] The envelope and `job_applied` payload reject unknown fields.
- [x] Identical `event_id` publish retries deduplicate during the broker window.
- [x] Accepted events survive broker, producer, and GTasks restarts.
- [x] Lease expiry/redelivery and bounded retry are tested.
- [x] Registry dispatch rejects unknown type/version without fallback.
- [x] Durable consumer receipts survive restart and detect conflicts.
- [x] Duplicate/concurrent delivery produces one canonical GBrain effect.
- [x] Partial-write retry converges without a second progress increment.
- [ ] Ordering scope and out-of-order reconciliation are tested.
- [ ] Alert thresholds and notification delivery are configured and tested.
- [x] Dead-letter/terminal failure and explicit redrive are tested.
- [x] Missing or ambiguous quota-task association fails closed.
- [x] Exact GBrain pages, evidence, relationships, and progress pass fake-adapter
      and fake-runner readback without live mutation.
- [x] Logs and errors are reviewed for sensitive-data leakage.
- [ ] Career Path commits local `Applied` before durable outbox publication.
- [x] This runbook is updated with tested broker, transport, auth, schemas,
      relationship types, retry policy, and verification commands.
