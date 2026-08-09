import asyncio
import copy
import hashlib
import inspect
import json
import tempfile
import threading
import unittest
from collections import UserString
from contextlib import contextmanager
from unittest.mock import patch
from pathlib import Path

import openclaw_profile_activation as activation_module

from openclaw_profile_activation import (
    ActivationConflict,
    ActivationError,
    GBrainToolBrain,
    JetStreamControlStore,
    JetStreamJournal,
    NatsJetStreamSession,
    OpenClawProfileActivation,
)


DECLARATIONS = (
    {
        "slug": "agents/tammy-oc",
        "name": "Tammy-OC",
        "runtime": "openclaw",
        "route": "hosts/tammy",
        "task_collection": "collections/tammy-oc-tasks",
        "artifact_collection": "collections/tammy-oc-artifacts",
    },
    {
        "slug": "agents/timmy-oc",
        "name": "Timmy-OC",
        "runtime": "openclaw",
        "route": "hosts/timmy",
        "task_collection": "collections/timmy-oc-tasks",
        "artifact_collection": "collections/timmy-oc-artifacts",
    },
    {
        "slug": "agents/toddy-oc",
        "name": "Toddy-OC",
        "runtime": "openclaw",
        "route": "hosts/toddy",
        "task_collection": "collections/toddy-oc-tasks",
        "artifact_collection": "collections/toddy-oc-artifacts",
    },
)


VALID_NATS_CREDS = """-----BEGIN NATS USER JWT-----
unit.jwt
------END NATS USER JWT------

-----BEGIN USER NKEY SEED-----
SUUNIT
------END USER NKEY SEED------
"""


def write_private_nats_creds(path: Path) -> Path:
    path.write_text(VALID_NATS_CREDS, encoding="utf-8")
    path.chmod(0o600)
    return path


def write_private_user_password(path: Path, **overrides) -> Path:
    payload = {
        "schema": "memory-stargraph.nats-credentials",
        "version": 1,
        "mode": "user_password",
        "user": "oc-activation",
        "password": "unit-secret-password",
    }
    payload.update(overrides)
    path.write_text(json.dumps(payload), encoding="utf-8")
    path.chmod(0o600)
    return path


class FakeControl:
    def __init__(self):
        self.revision = 1
        self.record = {
            "state": "idle",
            "generation": 0,
            "active_manifest": None,
            "lease_owner": None,
            "operation_id": None,
            "lease_expires_at": 0,
        }

    def read(self):
        return self.revision, copy.deepcopy(self.record)

    def compare_and_set(self, revision, record):
        if revision != self.revision:
            raise ActivationConflict("control revision changed")
        self.revision += 1
        self.record = copy.deepcopy(record)
        return self.revision


class FakeJournal:
    def __init__(self):
        self.events = []
        self.fail_once = None
        self.identities = {}

    def append(self, event):
        marker = (event.get("step"), event.get("phase"))
        if marker == self.fail_once:
            self.fail_once = None
            raise ActivationError(f"simulated journal failure at {marker[0]} {marker[1]}")
        identity = (
            event.get("operation_id"),
            event.get("fence_generation"),
            event.get("step"),
            event.get("resource"),
            event.get("phase"),
        )
        prior = self.identities.get(identity)
        if prior is not None and prior != event:
            raise ActivationError("journal event identity collision")
        self.identities[identity] = copy.deepcopy(event)
        self.events.append(copy.deepcopy(event))

    def read(self, operation_id):
        return [
            copy.deepcopy(event)
            for event in self.events
            if event.get("operation_id") == operation_id
        ]


class FakeOperationStore:
    def __init__(self):
        self.records = {}
        self.create_count = 0

    def read(self, operation_id):
        stored = self.records.get(operation_id)
        if stored is None:
            return 0, None
        revision, record = stored
        return revision, copy.deepcopy(record)

    def create(self, operation_id, record):
        if operation_id in self.records:
            raise ActivationConflict("operation already exists")
        self.create_count += 1
        self.records[operation_id] = (1, copy.deepcopy(record))
        return 1

    def compare_and_set(self, operation_id, revision, record):
        current_revision, _current = self.records[operation_id]
        if revision != current_revision:
            raise ActivationConflict("operation revision changed")
        next_revision = current_revision + 1
        self.records[operation_id] = (next_revision, copy.deepcopy(record))
        return next_revision

    def list_records(self, statuses):
        return [
            copy.deepcopy(record)
            for _revision, record in self.records.values()
            if record.get("status") in statuses
        ]


class FakeKeyValue:
    def __init__(self):
        self.entries = {}
        self.published = []

    def get(self, key):
        if key not in self.entries:
            raise KeyError(key)
        revision, value = self.entries[key]
        return type("Entry", (), {"revision": revision, "value": value})()

    def create(self, key, value):
        if key in self.entries:
            raise RuntimeError("wrong last sequence")
        self.entries[key] = (1, value)
        return 1

    def update(self, key, value, last):
        revision, _prior = self.entries[key]
        if revision != last:
            raise RuntimeError("wrong last sequence")
        self.entries[key] = (revision + 1, value)
        return revision + 1

    def keys(self):
        return list(self.entries)

    def publish(self, subject, value, headers):
        self.published.append((subject, json.loads(value.decode("utf-8")), headers))


class CanonicalGBrainToolStore:
    """Faithful outer-page boundary for GBrainToolBrain activation tests."""

    def __init__(self):
        self.pages = {
            "collections/mission-control-artifacts": {
                "slug": "collections/mission-control-artifacts",
                "type": "collection",
                "title": "Mission Control Artifacts",
                "frontmatter": {"collection_kind": "mission_control_artifacts"},
                "compiled_truth": "Artifact root.",
            }
        }
        self.links = {}

    def call(self, tool, payload):
        if tool == "put_page":
            content = payload["content"]
            line = next(
                line
                for line in content.splitlines()
                if line.startswith("activation_payload: ")
            )
            encoded = json.loads(line.split(": ", 1)[1])
            record = json.loads(encoded)
            self.pages[payload["slug"]] = {
                "slug": payload["slug"],
                "type": record["type"],
                "title": record.get("title"),
                "frontmatter": {
                    **copy.deepcopy(record.get("frontmatter", {})),
                    "activation_payload": encoded,
                },
                "compiled_truth": record.get("compiled_truth", ""),
            }
            return {"status": "ok"}
        if tool == "get_page":
            page = self.pages.get(payload["slug"])
            if page is None:
                raise RuntimeError("Page not found")
            return copy.deepcopy(page)
        if tool == "add_link":
            self.links.setdefault(payload["from"], []).append(
                {
                    "from_slug": payload["from"],
                    "to_slug": payload["to"],
                    "link_type": payload["link_type"],
                    "context": payload["context"],
                }
            )
            return {"status": "ok"}
        if tool == "get_links":
            return copy.deepcopy(self.links.get(payload["slug"], []))
        raise AssertionError(tool)


class JetStreamAdapterTests(unittest.TestCase):
    def test_environment_builds_durable_operation_store_and_bounded_shared_session(self):
        store_class = getattr(activation_module, "JetStreamOperationStore")
        with tempfile.TemporaryDirectory() as temp_dir:
            credentials = write_private_nats_creds(Path(temp_dir) / "nats.creds")
            environment = {
                "MEMORY_STARGRAPH_OC_PROVISION_ENABLED": "1",
                "MEMORY_STARGRAPH_OC_NATS_SERVERS": "nats://127.0.0.1:4222",
                "MEMORY_STARGRAPH_OC_NATS_CREDENTIALS_FILE": str(credentials),
                "MEMORY_STARGRAPH_OC_NATS_KV_BUCKET": "oc-control",
                "MEMORY_STARGRAPH_OC_NATS_JOURNAL_SUBJECT": "oc.journal",
                "MEMORY_STARGRAPH_OC_LEASE_SECONDS": "180",
                "MEMORY_STARGRAPH_OC_CLOCK_SKEW_SECONDS": "7",
                "MEMORY_STARGRAPH_OC_NATS_CONNECT_TIMEOUT_SECONDS": "3",
                "MEMORY_STARGRAPH_OC_NATS_REQUEST_TIMEOUT_SECONDS": "2",
            }
            with patch.dict("os.environ", environment, clear=True):
                service = activation_module.activation_from_environment(
                    lambda _tool, _params: None
                )

        self.assertIsInstance(service.operations, store_class)
        self.assertEqual(service.lease_seconds, 180)
        self.assertEqual(service.clock_skew_seconds, 7)
        self.assertTrue(callable(service.operation_context))
        self.assertEqual(service.operations.key_value.session.connect_timeout_seconds, 3)
        self.assertEqual(service.operations.key_value.session.request_timeout_seconds, 2)

        with (
            patch.dict(
                "os.environ",
                {
                    **environment,
                    "MEMORY_STARGRAPH_OC_NATS_REQUEST_TIMEOUT_SECONDS": "2.01",
                },
                clear=True,
            ),
            self.assertRaisesRegex(ActivationError, "not configured"),
        ):
            activation_module.activation_from_environment(
                lambda _tool, _params: None
            )

    def test_operation_store_persists_isolated_records_with_revision_cas(self):
        store_class = getattr(activation_module, "JetStreamOperationStore", None)
        self.assertIsNotNone(store_class)
        store = store_class(FakeKeyValue(), "openclaw-profiles/operations")

        self.assertEqual(store.read("op-a"), (0, None))
        self.assertEqual(store.create("op-a", {"status": "accepted"}), 1)
        self.assertEqual(store.create("op-b", {"status": "accepted"}), 1)
        revision, record = store.read("op-a")
        self.assertEqual(record, {"status": "accepted"})
        self.assertEqual(
            store.compare_and_set("op-a", revision, {"status": "completed"}), 2
        )
        self.assertEqual(store.read("op-a")[1]["status"], "completed")
        self.assertEqual(store.read("op-b")[1]["status"], "accepted")
        self.assertEqual(
            [record["status"] for record in store.list_records({"completed"})],
            ["completed"],
        )

    def test_gbrain_adapter_reads_an_ordinary_canonical_page_without_activation_envelope(self):
        page = {"slug": "collections/mission-control-artifacts", "type": "collection", "title": "Mission Control Artifacts", "frontmatter": {"collection_kind": "mission_control_artifacts"}}
        brain = GBrainToolBrain(lambda tool, _payload: page if tool == "get_page" else [])

        self.assertEqual(brain.get_page(page["slug"]), page)

    def test_control_uses_kv_create_and_revision_compare_and_set(self):
        kv = FakeKeyValue()
        control = JetStreamControlStore(kv, "openclaw-profiles/control")

        revision, record = control.read()
        self.assertEqual(revision, 0)
        self.assertEqual(record["state"], "idle")
        self.assertEqual(control.compare_and_set(0, {"state": "leased"}), 1)
        with self.assertRaises(ActivationConflict):
            control.compare_and_set(0, {"state": "active"})

    def test_control_treats_the_nats_missing_key_error_as_an_empty_record(self):
        class MissingKeyValue:
            def get(self, _key):
                raise type("KeyNotFoundError", (Exception,), {})()

        revision, record = JetStreamControlStore(MissingKeyValue(), "openclaw-profiles/control").read()

        self.assertEqual(revision, 0)
        self.assertEqual(record["generation"], 0)

    def test_journal_uses_idempotency_key_per_operation_event(self):
        kv = FakeKeyValue()
        journal = JetStreamJournal(kv, "oc.provision.journal")

        journal.append(
            {
                "operation_id": "op-a",
                "fence_generation": 7,
                "step": "lease",
                "resource": "control",
                "phase": "before",
            }
        )

        self.assertEqual(kv.published[0][0], "oc.provision.journal")
        self.assertEqual(
            kv.published[0][2]["Nats-Msg-Id"],
            "op-a:7:lease:control:before",
        )

    def test_journal_persists_events_for_operation_recovery_when_supported(self):
        class DurablePublisher(FakeKeyValue):
            def __init__(self):
                super().__init__()
                self.events = {}

            def write_journal_event(self, event_id, event):
                self.events[event_id] = copy.deepcopy(event)

            def read_journal_events(self, operation_id):
                return [
                    copy.deepcopy(event)
                    for event in self.events.values()
                    if event["operation_id"] == operation_id
                ]

        publisher = DurablePublisher()
        journal = JetStreamJournal(publisher, "oc.provision.journal")
        event = {
            "operation_id": "op-durable",
            "fence_generation": 3,
            "step": "manifest",
            "resource": "system/manifest",
            "phase": "after",
        }

        journal.append(event)

        self.assertEqual(journal.read("op-durable"), [event])

    def test_nats_session_uses_exact_jwt_credentials_connect_kwargs(self):
        calls = []

        class JetStream:
            async def key_value(self, _bucket):
                return object()

        class Connection:
            def jetstream(self):
                return JetStream()

            async def drain(self):
                return None

        async def connect(**kwargs):
            calls.append(kwargs)
            return Connection()

        with tempfile.TemporaryDirectory() as temp_dir:
            credentials = write_private_nats_creds(Path(temp_dir) / "nats.creds")
            session = NatsJetStreamSession(
                servers=("nats://127.0.0.1:4222",),
                credentials_file=credentials,
                bucket="oc-control",
                connect=connect,
                connect_timeout_seconds=0.1,
                request_timeout_seconds=0.1,
            )
            with session.operation():
                pass

        self.assertEqual(len(calls), 1)
        self.assertEqual(calls[0]["servers"], ["nats://127.0.0.1:4222"])
        self.assertEqual(calls[0]["connect_timeout"], 0.1)
        captured_credentials = calls[0]["user_credentials"]
        self.assertIsInstance(captured_credentials, UserString)
        self.assertEqual(captured_credentials.data, VALID_NATS_CREDS)
        self.assertNotIn("unit.jwt", str(captured_credentials))
        self.assertNotIn("SUUNIT", repr(captured_credentials))
        with self.assertRaises(AttributeError):
            captured_credentials.data = "replacement"

    def test_nats_jwt_credentials_never_reopen_a_replaced_path_on_reconnect(self):
        replacement = VALID_NATS_CREDS.replace("unit.jwt", "replacement.jwt")
        with tempfile.TemporaryDirectory() as temp_dir:
            credentials = write_private_nats_creds(Path(temp_dir) / "nats.creds")
            session = NatsJetStreamSession(
                servers=("nats://127.0.0.1:4222",),
                credentials_file=credentials,
                bucket="oc-control",
                connect=lambda **_kwargs: None,
            )
            initial = session._connection_auth_kwargs()["user_credentials"]
            replacement_path = Path(temp_dir) / "replacement.creds"
            replacement_path.write_text(replacement, encoding="utf-8")
            replacement_path.chmod(0o600)
            replacement_path.replace(credentials)
            reconnect = session._connection_auth_kwargs()["user_credentials"]

        self.assertIsInstance(initial, UserString)
        self.assertIsInstance(reconnect, UserString)
        self.assertEqual(initial.data, VALID_NATS_CREDS)
        self.assertEqual(reconnect.data, VALID_NATS_CREDS)
        self.assertNotEqual(reconnect.data, replacement)

    def test_nats_session_uses_exact_static_user_password_connect_kwargs(self):
        calls = []

        class JetStream:
            async def key_value(self, _bucket):
                return object()

        class Connection:
            def jetstream(self):
                return JetStream()

            async def drain(self):
                return None

        async def connect(**kwargs):
            calls.append(kwargs)
            return Connection()

        with tempfile.TemporaryDirectory() as temp_dir:
            credentials = write_private_user_password(
                Path(temp_dir) / "nats-user-password.json"
            )
            session = NatsJetStreamSession(
                servers=("nats://127.0.0.1:4222",),
                credentials_file=credentials,
                bucket="oc-control",
                connect=connect,
                connect_timeout_seconds=0.1,
                request_timeout_seconds=0.1,
            )
            with session.operation():
                pass

        self.assertEqual(
            calls,
            [
                {
                    "servers": ["nats://127.0.0.1:4222"],
                    "user": "oc-activation",
                    "password": "unit-secret-password",
                    "connect_timeout": 0.1,
                }
            ],
        )

    def test_nats_credentials_fail_closed_on_unsafe_or_ambiguous_files(self):
        secret = "do-not-disclose-this-password"
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            cases = []

            loose = write_private_user_password(root / "loose.json")
            loose.chmod(0o640)
            cases.append(loose)

            target = write_private_user_password(root / "target.json")
            symlink = root / "symlink.json"
            symlink.symlink_to(target)
            cases.append(symlink)

            missing = write_private_user_password(root / "missing.json")
            payload = json.loads(missing.read_text(encoding="utf-8"))
            payload.pop("password")
            missing.write_text(json.dumps(payload), encoding="utf-8")
            cases.append(missing)

            unknown_key = write_private_user_password(
                root / "unknown-key.json", extra="not-allowed"
            )
            cases.append(unknown_key)

            unknown_mode = write_private_user_password(
                root / "unknown-mode.json", mode="jwt"
            )
            cases.append(unknown_mode)

            wrong_version = write_private_user_password(
                root / "wrong-version.json", version=2
            )
            cases.append(wrong_version)

            mixed = write_private_user_password(
                root / "mixed.json", user_credentials="nats.creds"
            )
            cases.append(mixed)

            malformed = root / "malformed.json"
            malformed.write_text("{not-json", encoding="utf-8")
            malformed.chmod(0o600)
            cases.append(malformed)

            duplicate = root / "duplicate.json"
            duplicate.write_text(
                '{"schema":"memory-stargraph.nats-credentials",'
                '"version":1,"mode":"user_password",'
                '"user":"first","user":"second","password":"secret"}',
                encoding="utf-8",
            )
            duplicate.chmod(0o600)
            cases.append(duplicate)

            empty_password = write_private_user_password(
                root / "empty-password.json", password=""
            )
            cases.append(empty_password)

            secret_bad_schema = write_private_user_password(
                root / "bad-schema.json",
                schema="wrong-schema",
                password=secret,
            )
            cases.append(secret_bad_schema)

            invalid_creds = root / "invalid.creds"
            invalid_creds.write_text("not-a-nats-creds-file", encoding="utf-8")
            invalid_creds.chmod(0o600)
            cases.append(invalid_creds)

            unknown_suffix = write_private_user_password(root / "credentials.txt")
            cases.append(unknown_suffix)

            for credentials in cases:
                with self.subTest(credentials=credentials.name):
                    with self.assertRaises(ActivationError) as captured:
                        NatsJetStreamSession(
                            servers=("nats://127.0.0.1:4222",),
                            credentials_file=credentials,
                            bucket="oc-control",
                        )
                    self.assertNotIn(secret, str(captured.exception))

    def test_nats_credentials_reject_nonregular_files(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            credentials = Path(temp_dir) / "credentials.json"
            credentials.mkdir()
            credentials.chmod(0o600)
            with self.assertRaises(ActivationError):
                NatsJetStreamSession(
                    servers=("nats://127.0.0.1:4222",),
                    credentials_file=credentials,
                    bucket="oc-control",
                )

    def test_nats_connect_failure_does_not_disclose_static_password(self):
        secret = "connect-error-secret"

        async def connect(**_kwargs):
            raise RuntimeError(f"broker rejected {secret}")

        with tempfile.TemporaryDirectory() as temp_dir:
            credentials = write_private_user_password(
                Path(temp_dir) / "credentials.json", password=secret
            )
            session = NatsJetStreamSession(
                servers=("nats://127.0.0.1:4222",),
                credentials_file=credentials,
                bucket="oc-control",
                connect=connect,
                connect_timeout_seconds=0.1,
                request_timeout_seconds=0.1,
            )
            with self.assertRaises(ActivationError) as captured:
                with session.operation():
                    pass

        self.assertEqual(str(captured.exception), "NATS connect failed")
        self.assertNotIn(secret, str(captured.exception))
        self.assertIsNone(captured.exception.__cause__)

    def test_nats_session_pools_one_bounded_connection_for_an_operation(self):
        calls = []
        caller_thread = threading.get_ident()

        class AsyncKeyValue:
            async def get(self, key):
                calls.append(("get", key, threading.get_ident()))
                return f"value:{key}"

        class JetStream:
            async def key_value(self, bucket):
                calls.append(("key_value", bucket, threading.get_ident()))
                return AsyncKeyValue()

            async def publish(self, subject, payload, headers):
                calls.append(
                    ("publish", subject, payload, headers, threading.get_ident())
                )
                return "ack"

        class Connection:
            def jetstream(self):
                return JetStream()

            async def drain(self):
                calls.append(("drain", threading.get_ident()))

        async def connect(**kwargs):
            calls.append(("connect", kwargs, threading.get_ident()))
            return Connection()

        with tempfile.TemporaryDirectory() as temp_dir:
            credentials = write_private_nats_creds(Path(temp_dir) / "nats.creds")
            session = NatsJetStreamSession(
                servers=("nats://127.0.0.1:4222",),
                credentials_file=credentials,
                bucket="oc-control",
                connect=connect,
                connect_timeout_seconds=0.1,
                request_timeout_seconds=0.1,
            )
            self.assertTrue(callable(getattr(session, "operation", None)))

            with session.operation():
                self.assertEqual(session.key_value("get", "a"), "value:a")
                self.assertEqual(session.key_value("get", "b"), "value:b")
                self.assertEqual(session.publish("journal", b"{}", {}), "ack")

        self.assertEqual(len([call for call in calls if call[0] == "connect"]), 1)
        self.assertEqual(len([call for call in calls if call[0] == "key_value"]), 1)
        self.assertEqual(len([call for call in calls if call[0] == "drain"]), 1)
        operation_thread_ids = {
            call[-1]
            for call in calls
            if call[0] in {"connect", "key_value", "get", "publish", "drain"}
        }
        self.assertEqual(len(operation_thread_ids), 1)
        self.assertNotIn(caller_thread, operation_thread_ids)

    def test_started_service_reuses_one_nats_session_until_idempotent_close(self):
        calls = []

        class AsyncKeyValue:
            def __init__(self):
                self.entries = {}

            async def get(self, key):
                calls.append(("get", key))
                if key not in self.entries:
                    raise type("KeyNotFoundError", (Exception,), {})(key)
                revision, value = self.entries[key]
                return type(
                    "Entry", (), {"revision": revision, "value": value}
                )()

            async def create(self, key, value):
                if key in self.entries:
                    raise RuntimeError("wrong last sequence")
                self.entries[key] = (1, value)
                return 1

            async def update(self, key, value, last):
                revision, _prior = self.entries[key]
                if revision != last:
                    raise RuntimeError("wrong last sequence")
                self.entries[key] = (revision + 1, value)
                return revision + 1

            async def keys(self):
                return list(self.entries)

        key_value = AsyncKeyValue()

        class JetStream:
            async def key_value(self, _bucket):
                return key_value

            async def publish(self, _subject, _payload, _headers):
                return None

        class Connection:
            def jetstream(self):
                return JetStream()

            async def drain(self):
                calls.append(("drain",))

        async def connect(**_kwargs):
            calls.append(("connect",))
            return Connection()

        with tempfile.TemporaryDirectory() as temp_dir:
            credentials = write_private_nats_creds(Path(temp_dir) / "nats.creds")
            session = NatsJetStreamSession(
                servers=("nats://127.0.0.1:4222",),
                credentials_file=credentials,
                bucket="oc-control",
                connect=connect,
                connect_timeout_seconds=0.1,
                request_timeout_seconds=0.1,
            )
            proxy = activation_module.NatsJetStreamKeyValue(session)
            service = OpenClawProfileActivation(
                control=JetStreamControlStore(
                    proxy, "openclaw-profiles/control"
                ),
                journal=JetStreamJournal(session, "oc.journal"),
                brain=FakeBrain(),
                now=lambda: 1000.0,
                operations=activation_module.JetStreamOperationStore(
                    proxy, "openclaw-profiles/operations"
                ),
                projections=activation_module.JetStreamProjectionStore(
                    proxy, "openclaw-profiles/active-projection"
                ),
                operation_context=session.operation,
            )

            self.assertTrue(callable(getattr(service, "start", None)))
            service.start()
            service.submit(
                DECLARATIONS, owner="worker-a", operation_id="op-singleton"
            )
            service.status("op-singleton")
            service.status("op-singleton")
            service.close()
            service.close()

        self.assertEqual(calls.count(("connect",)), 1)
        self.assertEqual(calls.count(("drain",)), 1)

    def test_nats_connect_timeout_is_bounded_and_truthful(self):
        async def connect(**_kwargs):
            await asyncio.sleep(0.05)

        with tempfile.TemporaryDirectory() as temp_dir:
            credentials = write_private_nats_creds(Path(temp_dir) / "nats.creds")
            session = NatsJetStreamSession(
                servers=("nats://127.0.0.1:4222",),
                credentials_file=credentials,
                bucket="oc-control",
                connect=connect,
                connect_timeout_seconds=0.001,
                request_timeout_seconds=0.01,
            )

            with self.assertRaisesRegex(ActivationError, "connect timed out"):
                with session.operation():
                    pass

    def test_nats_kv_startup_failure_cleans_up_on_worker_without_warning(self):
        cleanup_calls = []
        caller_thread = threading.get_ident()

        class JetStream:
            async def key_value(self, _bucket):
                raise RuntimeError("simulated KV startup failure")

        class Connection:
            def jetstream(self):
                return JetStream()

            async def drain(self):
                cleanup_calls.append(("drain", threading.get_ident()))
                raise RuntimeError("simulated drain failure")

            async def close(self):
                cleanup_calls.append(("close", threading.get_ident()))

        async def connect(**_kwargs):
            return Connection()

        with tempfile.TemporaryDirectory() as temp_dir:
            credentials = write_private_nats_creds(Path(temp_dir) / "nats.creds")
            session = NatsJetStreamSession(
                servers=("nats://127.0.0.1:4222",),
                credentials_file=credentials,
                bucket="oc-control",
                connect=connect,
                connect_timeout_seconds=0.1,
                request_timeout_seconds=0.1,
            )

            with self.assertRaisesRegex(ActivationError, "KV lookup failed"):
                with session.operation():
                    pass

        self.assertEqual(
            [method for method, _thread in cleanup_calls], ["drain", "close"]
        )
        self.assertEqual(len({thread for _method, thread in cleanup_calls}), 1)
        self.assertNotEqual(cleanup_calls[0][1], caller_thread)

    def test_nats_session_preserves_cas_conflict_classification(self):
        class AsyncKeyValue:
            def __init__(self):
                self.entries = {}

            async def create(self, key, value):
                if key in self.entries:
                    raise RuntimeError("wrong last sequence")
                self.entries[key] = value
                return 1

        key_value = AsyncKeyValue()

        class JetStream:
            async def key_value(self, _bucket):
                return key_value

        class Connection:
            def jetstream(self):
                return JetStream()

            async def drain(self):
                return None

        async def connect(**_kwargs):
            return Connection()

        with tempfile.TemporaryDirectory() as temp_dir:
            credentials = write_private_nats_creds(Path(temp_dir) / "nats.creds")
            session = NatsJetStreamSession(
                servers=("nats://127.0.0.1:4222",),
                credentials_file=credentials,
                bucket="oc-control",
                connect=connect,
            )
            store = activation_module.JetStreamOperationStore(
                activation_module.NatsJetStreamKeyValue(session),
                "openclaw-profiles/operations",
            )
            with session.operation():
                store.create("op-a", {"status": "accepted"})
                with self.assertRaises(ActivationConflict):
                    store.create("op-a", {"status": "accepted"})

    def test_nats_session_preserves_wrapped_missing_key_and_empty_journal_errors(self):
        class AsyncKeyValue:
            async def get(self, _key):
                raise type("KeyNotFoundError", (Exception,), {})()

            async def keys(self):
                raise type("NoKeysError", (Exception,), {})()

        class JetStream:
            async def key_value(self, _bucket):
                return AsyncKeyValue()

        class Connection:
            def jetstream(self):
                return JetStream()

            async def drain(self):
                return None

        async def connect(**_kwargs):
            return Connection()

        with tempfile.TemporaryDirectory() as temp_dir:
            credentials = write_private_nats_creds(Path(temp_dir) / "nats.creds")
            session = NatsJetStreamSession(
                servers=("nats://127.0.0.1:4222",),
                credentials_file=credentials,
                bucket="oc-control",
                connect=connect,
            )
            key_value = activation_module.NatsJetStreamKeyValue(session)
            control = JetStreamControlStore(key_value, "openclaw-profiles/control")
            operations = activation_module.JetStreamOperationStore(
                key_value, "openclaw-profiles/operations"
            )

            with session.operation():
                self.assertEqual(control.read()[0], 0)
                self.assertEqual(operations.read("op-missing"), (0, None))
                self.assertEqual(session.read_journal_events("op-missing"), [])

    def test_gbrain_adapter_round_trips_activation_payload_and_typed_link(self):
        store = CanonicalGBrainToolStore()
        brain = GBrainToolBrain(store.call)
        page = {"slug": "system/staged", "type": "agent", "title": "Staged", "frontmatter": {"staged": True}}
        brain.put_page("system/staged", page)
        brain.add_link("system/staged", "collections/root", "for_agent", "test")

        self.assertEqual(brain.get_page("system/staged"), page)
        self.assertEqual(brain.get_links("system/staged")[0]["link_type"], "for_agent")

    def test_active_projection_rejects_outer_anchor_runtime_tampering_hidden_by_payload(
        self,
    ):
        store = CanonicalGBrainToolStore()
        service = OpenClawProfileActivation(
            control=FakeControl(),
            journal=FakeJournal(),
            brain=GBrainToolBrain(store.call),
            now=lambda: 1000,
            lease_seconds=30,
            operations=FakeOperationStore(),
        )
        service.provision(
            DECLARATIONS,
            owner="worker-a",
            operation_id="op-outer-identity",
        )
        store.pages["agents/tammy-oc"]["frontmatter"]["runtime"] = "codex"

        with self.assertRaisesRegex(
            ActivationError,
            "outer.*activation payload|identity",
        ):
            service.revalidate_active_projection()

    def test_active_projection_rejects_outer_collection_identity_tampering_hidden_by_payload(
        self,
    ):
        store = CanonicalGBrainToolStore()
        service = OpenClawProfileActivation(
            control=FakeControl(),
            journal=FakeJournal(),
            brain=GBrainToolBrain(store.call),
            now=lambda: 1000,
            lease_seconds=30,
            operations=FakeOperationStore(),
        )
        service.provision(
            DECLARATIONS,
            owner="worker-a",
            operation_id="op-outer-collection",
        )
        store.pages["collections/tammy-oc-tasks"]["frontmatter"]["agent"] = (
            "agents/timmy-oc"
        )

        with self.assertRaisesRegex(
            ActivationError,
            "outer.*activation payload|identity",
        ):
            service.revalidate_active_projection()


class FakeBrain:
    def __init__(self):
        self.pages = {
            "collections/mission-control-artifacts": {
                "slug": "collections/mission-control-artifacts",
                "type": "collection",
                "title": "Mission Control Artifacts",
                "content": "artifact-root",
            }
        }
        self.links = {}
        self.fail_after_puts = None
        self.puts = 0
        self.before_manifest = None
        self.on_put = None

    def put_page(self, slug, content):
        self.puts += 1
        if self.on_put is not None:
            self.on_put(slug)
        if self.fail_after_puts is not None and self.puts > self.fail_after_puts:
            raise ActivationError("simulated write interruption")
        self.pages[slug] = copy.deepcopy(content)

    def get_page(self, slug):
        page = self.pages.get(slug)
        return copy.deepcopy(page) if page else None

    def add_link(self, source, target, link_type, context):
        if source not in self.pages or target not in self.pages:
            raise ActivationError("link endpoint is missing")
        self.links.setdefault(source, []).append(
            {
                "from_slug": source,
                "to_slug": target,
                "link_type": link_type,
                "context": context,
            }
        )

    def get_links(self, slug):
        return copy.deepcopy(self.links.get(slug, []))


class OpenClawProfileActivationTests(unittest.TestCase):
    def test_operation_lifecycle_is_an_explicit_public_contract(self):
        constructor = inspect.signature(OpenClawProfileActivation.__init__)
        recover = inspect.signature(OpenClawProfileActivation.recover)

        self.assertIn("operations", constructor.parameters)
        self.assertTrue(callable(getattr(OpenClawProfileActivation, "submit", None)))
        self.assertTrue(callable(getattr(OpenClawProfileActivation, "status", None)))
        self.assertTrue(callable(getattr(OpenClawProfileActivation, "run", None)))
        self.assertIn("operation_id", recover.parameters)

    def setUp(self):
        self.clock = [1000]
        self.control = FakeControl()
        self.journal = FakeJournal()
        self.operations = FakeOperationStore()
        self.brain = FakeBrain()
        self.service = OpenClawProfileActivation(
            control=self.control,
            journal=self.journal,
            brain=self.brain,
            now=lambda: self.clock[0],
            lease_seconds=30,
            operations=self.operations,
        )

    def provision(self, owner="worker-a", operation_id="op-a"):
        return self.service.provision(
            DECLARATIONS, owner=owner, operation_id=operation_id
        )

    def reseal_manifest(self, receipt, mutate):
        manifest = self.brain.pages[receipt["manifest_slug"]]
        mutate(manifest)
        digest = hashlib.sha256(
            json.dumps(manifest, sort_keys=True, separators=(",", ":")).encode("utf-8")
        ).hexdigest()
        revision, control = self.control.read()
        control["active_manifest_digest"] = digest
        if isinstance(control.get("completed_receipt"), dict):
            control["completed_receipt"]["manifest_digest"] = digest
        self.control.compare_and_set(revision, control)

    def assert_journal_pairs_closed(self, operation_id):
        phases = {}
        for event in self.journal.read(operation_id):
            if event.get("phase") not in {"before", "after"}:
                continue
            phases.setdefault(
                (
                    event["fence_generation"],
                    event["step"],
                    event["resource"],
                ),
                set(),
            ).add(event["phase"])
        self.assertTrue(phases)
        self.assertTrue(all(value == {"before", "after"} for value in phases.values()))

    def test_submit_persists_accepted_before_allocating_a_generation(self):
        accepted = self.service.submit(
            DECLARATIONS, owner="worker-a", operation_id="op-accepted"
        )

        self.assertEqual(accepted["status"], "accepted")
        self.assertEqual(accepted["operation_id"], "op-accepted")
        self.assertEqual(self.service.status("op-accepted"), accepted)
        self.assertEqual(self.control.read()[1]["generation"], 0)

    def test_fence_is_claimed_before_operation_is_published_running(self):
        self.service.submit(
            DECLARATIONS, owner="worker-a", operation_id="op-claim-order"
        )
        observed_statuses = []
        original_append = self.journal.append

        def observe_lease_after(event):
            if event.get("step") == "lease" and event.get("phase") == "after":
                observed_statuses.append(
                    self.operations.read("op-claim-order")[1]["status"]
                )
            original_append(event)

        self.journal.append = observe_lease_after

        completed = self.service.run("op-claim-order")

        self.assertEqual(observed_statuses, ["accepted"])
        self.assertEqual(completed["status"], "completed")

    def test_submit_uses_one_shared_operation_context_for_durable_acceptance(self):
        lifecycle = []

        @contextmanager
        def operation_context():
            lifecycle.append("enter")
            try:
                yield
            finally:
                lifecycle.append("exit")

        service = OpenClawProfileActivation(
            control=self.control,
            journal=self.journal,
            brain=self.brain,
            now=lambda: self.clock[0],
            lease_seconds=30,
            operations=self.operations,
            operation_context=operation_context,
        )

        service.submit(DECLARATIONS, owner="worker-a", operation_id="op-context")

        self.assertEqual(lifecycle, ["enter", "exit"])

    def test_durable_executor_scans_and_runs_an_accepted_operation(self):
        executor_class = getattr(
            activation_module, "OpenClawProfileActivationExecutor", None
        )
        self.assertIsNotNone(executor_class)
        self.service.submit(
            DECLARATIONS, owner="worker-a", operation_id="op-durable-executor"
        )
        executor = executor_class(lambda: self.service)

        processed = executor.run_once()

        self.assertEqual(processed, ["op-durable-executor"])
        self.assertEqual(
            self.service.status("op-durable-executor")["status"], "completed"
        )

    def test_executor_isolates_each_adoption_and_still_runs_requested_projection_validation(self):
        calls = []

        class Service:
            def pending_operation_ids(self):
                return ["op-broken", "op-healthy"]

            def adopt(self, operation_id):
                calls.append(("adopt", operation_id))
                if operation_id == "op-broken":
                    raise ActivationError("op-broken canonical read failed")

            def revalidate_active_projection(self):
                calls.append(("projection", 0))

            def invalidate_cached_projection(self, error):
                calls.append(("invalidate", str(error)))

        executor = activation_module.OpenClawProfileActivationExecutor(Service)

        processed = executor.run_once()

        self.assertEqual(processed, ["op-healthy"])
        self.assertEqual(
            calls,
            [
                ("adopt", "op-broken"),
                ("adopt", "op-healthy"),
                ("projection", 0),
            ],
        )
        self.assertIn("op-broken canonical read failed", executor.last_error)

    def test_executor_periodic_and_requested_projection_validation_is_not_starved_by_operations(self):
        executor_clock = [0.0]
        validations = []

        class Service:
            def pending_operation_ids(self):
                return ["op-always-visible"]

            def adopt(self, _operation_id):
                return None

            def revalidate_active_projection(self):
                validations.append(executor_clock[0])

            def invalidate_cached_projection(self, _error):
                raise AssertionError("successful validation was invalidated")

        executor = activation_module.OpenClawProfileActivationExecutor(
            Service,
            projection_validation_interval_seconds=60,
            clock=lambda: executor_clock[0],
        )

        self.assertEqual(executor.run_once(), ["op-always-visible"])
        executor_clock[0] = 59.0
        executor.run_once()
        executor_clock[0] = 60.0
        executor.run_once()
        executor_clock[0] = 61.0
        executor.request_projection_validation()
        executor.run_once()

        self.assertEqual(validations, [0.0, 60.0, 61.0])

    def test_executor_does_not_preempt_an_accepted_operation_with_a_live_claim(self):
        self.service.submit(
            DECLARATIONS, owner="worker-a", operation_id="op-accepted-live"
        )
        control_revision, control = self.control.read()
        control.update(
            {
                "state": "leased",
                "generation": 3,
                "fence_generation": 3,
                "lease_owner": "live-session",
                "operation_id": "op-accepted-live",
                "lease_expires_at": self.clock[0] + self.service.lease_seconds,
            }
        )
        self.control.compare_and_set(control_revision, control)
        claimed_revision = self.control.read()[0]

        processed = activation_module.OpenClawProfileActivationExecutor(
            lambda: self.service
        ).run_once()

        self.assertEqual(processed, ["op-accepted-live"])
        self.assertEqual(
            self.operations.read("op-accepted-live")[1]["status"], "accepted"
        )
        self.assertEqual(self.control.read()[0], claimed_revision)
        self.assertEqual(self.brain.puts, 0)

    def test_losing_the_accepted_claim_race_keeps_the_other_live_holder(self):
        service = OpenClawProfileActivation(
            control=self.control,
            journal=self.journal,
            brain=self.brain,
            now=lambda: self.clock[0],
            lease_seconds=30,
            operations=self.operations,
            session_owner_factory=lambda _owner: "losing-session",
        )
        service.submit(
            DECLARATIONS, owner="worker-a", operation_id="op-accepted-race"
        )

        def lose_claim(**_kwargs):
            revision, control = self.control.read()
            control.update(
                {
                    "state": "leased",
                    "generation": 3,
                    "fence_generation": 3,
                    "lease_owner": "winning-session",
                    "operation_id": "op-accepted-race",
                    "lease_expires_at": self.clock[0] + service.lease_seconds,
                }
            )
            self.control.compare_and_set(revision, control)
            raise activation_module.ActivationLeaseHeld("claim race lost")

        service._claim = lose_claim

        observed = service.run("op-accepted-race")

        self.assertEqual(observed["status"], "accepted")
        self.assertEqual(
            self.control.read()[1]["lease_owner"], "winning-session"
        )
        self.assertEqual(self.brain.puts, 0)

    def test_executor_adopts_an_expired_accepted_claim_on_the_same_fence(self):
        self.service.submit(
            DECLARATIONS, owner="worker-a", operation_id="op-accepted-expired"
        )
        control_revision, control = self.control.read()
        control.update(
            {
                "state": "leased",
                "generation": 3,
                "fence_generation": 3,
                "lease_owner": "dead-session",
                "operation_id": "op-accepted-expired",
                "lease_expires_at": self.clock[0]
                - self.service.clock_skew_seconds
                - 1,
            }
        )
        self.control.compare_and_set(control_revision, control)

        activation_module.OpenClawProfileActivationExecutor(
            lambda: self.service
        ).run_once()

        completed = self.service.status("op-accepted-expired")
        self.assertEqual(completed["status"], "completed")
        self.assertEqual(completed["receipt"]["generation"], 3)
        self.assertEqual(self.control.read()[1]["fence_generation"], 3)

    def test_durable_executor_adopts_an_expired_running_operation_on_same_fence(self):
        executor_class = activation_module.OpenClawProfileActivationExecutor
        self.service.submit(
            DECLARATIONS, owner="worker-a", operation_id="op-expired-executor"
        )
        operation_revision, operation = self.operations.read("op-expired-executor")
        operation.update({"status": "running", "fence_generation": 3})
        self.operations.compare_and_set(
            "op-expired-executor", operation_revision, operation
        )
        control_revision, control = self.control.read()
        control.update(
            {
                "state": "leased",
                "generation": 3,
                "fence_generation": 3,
                "lease_owner": "dead-session",
                "operation_id": "op-expired-executor",
                "lease_expires_at": self.clock[0]
                - self.service.clock_skew_seconds
                - 1,
            }
        )
        self.control.compare_and_set(control_revision, control)
        executor = executor_class(lambda: self.service)

        processed = executor.run_once()

        completed = self.service.status("op-expired-executor")
        self.assertEqual(processed, ["op-expired-executor"])
        self.assertEqual(completed["status"], "completed")
        self.assertEqual(completed["fence_generation"], 3)

    def test_same_id_submit_retry_reuses_the_operation_and_completed_generation(self):
        first = self.service.submit(
            DECLARATIONS, owner="worker-a", operation_id="op-repeat"
        )
        retried = self.service.submit(
            DECLARATIONS, owner="worker-a", operation_id="op-repeat"
        )
        completed = self.service.run("op-repeat")
        terminal_retry = self.service.submit(
            DECLARATIONS, owner="worker-a", operation_id="op-repeat"
        )

        self.assertEqual(first, retried)
        self.assertEqual(self.operations.create_count, 1)
        self.assertEqual(completed["status"], "completed")
        self.assertEqual(terminal_retry, completed)
        self.assertEqual(completed["receipt"]["generation"], 1)

    def test_terminal_operation_cannot_regress_from_a_late_recovery_transition(self):
        receipt = self.provision(operation_id="op-terminal-monotonic")

        late = self.service._update_operation(
            "op-terminal-monotonic",
            status="recovery_required",
            fence_generation=receipt["generation"],
            receipt=None,
            error="late worker",
        )

        self.assertEqual(late["status"], "completed")
        self.assertEqual(late["receipt"], receipt)
        self.assertIsNone(late["error"])

    def test_invalid_terminal_attestation_is_rejected_before_operation_cas(self):
        self.service.submit(
            DECLARATIONS, owner="worker-a", operation_id="op-invalid-terminal-cas"
        )

        with self.assertRaisesRegex(ActivationError, "completed activation operation"):
            self.service._transition_operation(
                "op-invalid-terminal-cas",
                expected_statuses={"accepted"},
                status="completed",
                fence_generation=1,
                receipt={
                    "generation": 1,
                    "manifest_slug": "system/openclaw-profile-manifests/"
                    "g000001-op-invalid-terminal-cas",
                    "manifest_digest": "0" * 64,
                    "default_goal_link_count": 0,
                },
                receipt_version=1,
                receipt_digest="f" * 64,
                error=None,
            )

        self.assertEqual(
            self.operations.read("op-invalid-terminal-cas")[1]["status"],
            "accepted",
        )

    def test_duplicate_worker_for_running_operation_never_allocates_a_generation(self):
        self.service.submit(
            DECLARATIONS, owner="worker-a", operation_id="op-already-running"
        )
        revision, record = self.operations.read("op-already-running")
        record["status"] = "running"
        self.operations.compare_and_set("op-already-running", revision, record)

        duplicate = self.service.run("op-already-running")

        self.assertEqual(duplicate["status"], "running")
        self.assertEqual(self.control.read()[1]["generation"], 0)
        self.assertEqual(self.brain.puts, 0)

    def test_different_operation_ids_have_isolated_status_and_generations(self):
        self.service.submit(DECLARATIONS, owner="worker-a", operation_id="op-a")
        self.service.submit(DECLARATIONS, owner="worker-b", operation_id="op-b")

        first = self.service.run("op-a")
        still_accepted = self.service.status("op-b")
        second = self.service.run("op-b")

        self.assertEqual(first["receipt"]["generation"], 1)
        self.assertEqual(still_accepted["status"], "accepted")
        self.assertIsNone(still_accepted["receipt"])
        self.assertEqual(second["receipt"]["generation"], 2)

    def test_running_and_failed_are_truthful_pollable_statuses(self):
        observed = []
        self.service.submit(DECLARATIONS, owner="worker-a", operation_id="op-running")
        self.brain.on_put = lambda _slug: observed.append(
            self.service.status("op-running")["status"]
        )

        self.service.run("op-running")

        self.assertIn("running", observed)

        failing = OpenClawProfileActivation(
            control=FakeControl(),
            journal=FakeJournal(),
            brain=FakeBrain(),
            now=lambda: self.clock[0],
            lease_seconds=30,
            operations=FakeOperationStore(),
        )
        failing.brain.pages.pop("collections/mission-control-artifacts")
        failing.submit(DECLARATIONS, owner="worker-b", operation_id="op-failed")

        failed = failing.run("op-failed")

        self.assertEqual(failed["status"], "failed")
        self.assertIsNone(failed["receipt"])
        self.assertEqual(failing.control.read()[1]["generation"], 0)

    def test_transient_gbrain_failure_before_claim_stays_accepted_for_retry(self):
        self.service.submit(
            DECLARATIONS, owner="worker-a", operation_id="op-transient-before-claim"
        )
        original_get_page = self.brain.get_page
        fail_once = [True]

        def transient_get_page(slug):
            if fail_once[0]:
                fail_once[0] = False
                raise RuntimeError("temporary GBrain transport failure")
            return original_get_page(slug)

        self.brain.get_page = transient_get_page

        retryable = self.service.run("op-transient-before-claim")
        activation_module.OpenClawProfileActivationExecutor(
            lambda: self.service
        ).run_once()
        completed = self.service.status("op-transient-before-claim")

        self.assertEqual(retryable["status"], "accepted")
        self.assertIn("temporary GBrain", retryable["error"])
        self.assertEqual(completed["status"], "completed")
        self.assertEqual(completed["receipt"]["generation"], 1)

    def test_every_ambiguous_mutation_has_unique_before_and_after_journal_ids(self):
        self.service.submit(DECLARATIONS, owner="worker-a", operation_id="op-journal")

        completed = self.service.run("op-journal")

        self.assertEqual(completed["status"], "completed")
        mutation_events = [
            event
            for event in self.journal.events
            if event.get("phase") in {"before", "after"}
        ]
        identities = [
            (
                event.get("operation_id"),
                event.get("fence_generation"),
                event.get("step"),
                event.get("resource"),
                event.get("phase"),
            )
            for event in mutation_events
        ]
        self.assertEqual(len(identities), len(set(identities)))
        self.assertTrue(all(identity[0] == "op-journal" for identity in identities))
        self.assertTrue(all(identity[1] == 1 for identity in identities))
        phases_by_step = {}
        phases_by_mutation = {}
        for event in mutation_events:
            phases_by_step.setdefault(event["step"], set()).add(event["phase"])
            phases_by_mutation.setdefault(
                (event["step"], event["resource"]), set()
            ).add(event["phase"])
        self.assertTrue(phases_by_mutation)
        self.assertTrue(
            all(phases == {"before", "after"} for phases in phases_by_mutation.values())
        )
        for step in {
            "lease",
            "lease_renewal",
            "anchor_page",
            "anchor_link",
            "generation_page",
            "generation_link",
            "manifest",
            "activate",
        }:
            self.assertEqual(phases_by_step.get(step), {"before", "after"})

    def test_journal_failure_after_lease_cas_is_recovery_required_then_same_fence_completes(self):
        self.service.submit(DECLARATIONS, owner="worker-a", operation_id="op-lease-crash")
        self.journal.fail_once = ("lease", "after")

        interrupted = self.service.run("op-lease-crash")
        recovered = self.service.recover("op-lease-crash")

        self.assertEqual(interrupted["status"], "recovery_required")
        self.assertEqual(interrupted["fence_generation"], 1)
        self.assertEqual(recovered["status"], "completed")
        self.assertEqual(recovered["receipt"]["generation"], 1)
        self.assertEqual(self.control.read()[1]["fence_generation"], 1)
        self.assert_journal_pairs_closed("op-lease-crash")

    def test_journal_failure_after_activation_cas_recovers_completed_without_new_generation(self):
        self.service.submit(DECLARATIONS, owner="worker-a", operation_id="op-activate-crash")
        self.journal.fail_once = ("activate", "after")

        interrupted = self.service.run("op-activate-crash")
        puts_after_activation = self.brain.puts
        recovered = self.service.recover("op-activate-crash")

        self.assertEqual(interrupted["status"], "recovery_required")
        self.assertEqual(self.control.read()[1]["completed_operation_id"], "op-activate-crash")
        self.assertEqual(recovered["status"], "completed")
        self.assertEqual(recovered["receipt"]["generation"], 1)
        self.assertEqual(self.brain.puts, puts_after_activation)
        self.assert_journal_pairs_closed("op-activate-crash")

    def test_recovery_terminalizes_a_deterministic_active_page_conflict(self):
        self.service.submit(
            DECLARATIONS, owner="worker-a", operation_id="op-active-conflict"
        )
        self.journal.fail_once = ("activate", "after")
        interrupted = self.service.run("op-active-conflict")
        receipt = self.control.read()[1]["completed_receipt"]
        manifest = self.brain.get_page(receipt["manifest_slug"])
        staged_agent = manifest["profiles"][0]["staged_agent_slug"]
        self.brain.pages[staged_agent]["title"] = "tampered after activation"

        failed = self.service.recover("op-active-conflict")

        self.assertEqual(interrupted["status"], "recovery_required")
        self.assertEqual(failed["status"], "failed")
        self.assertIn("hash mismatch", failed["error"])

    def test_successor_cannot_erase_a_prior_post_activation_journal_gap(self):
        self.service.submit(
            DECLARATIONS, owner="worker-a", operation_id="op-prior-gap"
        )
        self.journal.fail_once = ("activate", "after")
        interrupted = self.service.run("op-prior-gap")

        successor = self.provision(
            owner="worker-b", operation_id="op-after-prior-gap"
        )
        recovered = self.service.recover("op-prior-gap")

        self.assertEqual(interrupted["status"], "recovery_required")
        self.assertEqual(successor["generation"], 2)
        self.assertEqual(recovered["status"], "completed")
        self.assertEqual(recovered["fence_generation"], 1)
        self.assertEqual(recovered["receipt"]["generation"], 1)

    def test_successor_closes_prior_activation_audit_before_terminal_cas(self):
        operation_id = "op-prior-audit-gap"
        self.service.submit(
            DECLARATIONS, owner="worker-a", operation_id=operation_id
        )
        self.journal.fail_once = ("activate", "after")
        interrupted = self.service.run(operation_id)
        terminal_audit_observations = []
        original_cas = self.operations.compare_and_set

        def observe_terminal_cas(target, revision, record):
            if target == operation_id and record.get("status") == "completed":
                phases = {
                    (event.get("step"), event.get("resource"), event.get("phase"))
                    for event in self.journal.read(operation_id)
                }
                terminal_audit_observations.append(
                    ("activate", "control", "after") in phases
                )
            return original_cas(target, revision, record)

        self.operations.compare_and_set = observe_terminal_cas

        successor = self.provision(
            owner="worker-b", operation_id="op-after-prior-audit-gap"
        )

        self.assertEqual(interrupted["status"], "recovery_required")
        self.assertEqual(successor["generation"], 2)
        self.assertEqual(terminal_audit_observations, [True])

    def test_terminal_recover_closes_a_known_activation_audit_gap_idempotently(self):
        operation_id = "op-terminal-audit-gap"
        self.provision(operation_id=operation_id)
        identity = (operation_id, 1, "activate", "control", "after")
        self.journal.events = [
            event
            for event in self.journal.events
            if (
                event.get("operation_id"),
                event.get("fence_generation"),
                event.get("step"),
                event.get("resource"),
                event.get("phase"),
            )
            != identity
        ]
        self.journal.identities.pop(identity)

        first = self.service.recover(operation_id)
        second = self.service.recover(operation_id)
        activation_afters = [
            event
            for event in self.journal.read(operation_id)
            if event.get("fence_generation") == 1
            and event.get("step") == "activate"
            and event.get("resource") == "control"
            and event.get("phase") == "after"
        ]

        self.assertEqual(first["status"], "completed")
        self.assertEqual(second, first)
        self.assertEqual(len(activation_afters), 1)

    def test_requested_terminal_recovery_detects_graph_tampering_and_records_evidence(self):
        operation_id = "op-terminal-recovery-tamper"
        receipt = self.provision(operation_id=operation_id)
        identity = (operation_id, 1, "activate", "control", "after")
        self.journal.events = [
            event
            for event in self.journal.events
            if (
                event.get("operation_id"),
                event.get("fence_generation"),
                event.get("step"),
                event.get("resource"),
                event.get("phase"),
            )
            != identity
        ]
        self.journal.identities.pop(identity)
        manifest = self.brain.pages[receipt["manifest_slug"]]
        staged_agent = manifest["profiles"][0]["staged_agent_slug"]
        self.brain.pages[staged_agent]["title"] = "Tampered after completion"

        requested = self.service.request_recovery(operation_id)
        _revision, queued = self.operations.read(operation_id)
        self.assertEqual(requested["status"], "recovery_required")
        self.assertTrue(queued["recovery_requested"])
        self.assertEqual(queued["recovery_request_generation"], 1)

        processed = activation_module.OpenClawProfileActivationExecutor(
            lambda: self.service
        ).run_once()
        failed = self.service.status(operation_id)
        active = self.service.cached_active_projection()
        restarted = OpenClawProfileActivation(
            control=self.control,
            journal=self.journal,
            brain=self.brain,
            now=lambda: self.clock[0],
            operations=self.operations,
            projections=self.service.projections,
        ).start()
        try:
            restarted_active = restarted.cached_active_projection()
        finally:
            restarted.close()
        _revision, verified = self.operations.read(operation_id)
        activation_afters = [
            event
            for event in self.journal.read(operation_id)
            if event.get("fence_generation") == 1
            and event.get("step") == "activate"
            and event.get("resource") == "control"
            and event.get("phase") == "after"
        ]

        self.assertEqual(processed, [operation_id])
        self.assertEqual(failed["status"], "failed")
        self.assertIn("hash mismatch", failed["error"])
        self.assertEqual(active["status"], "validation_pending")
        self.assertEqual(restarted_active["status"], "validation_pending")
        self.assertFalse(verified["recovery_requested"])
        self.assertEqual(verified["recovery_processed_generation"], 1)
        self.assertEqual(verified["recovery_result"], "failed")
        self.assertIsInstance(verified["recovery_verified_at"], float)
        self.assertRegex(verified["recovery_verification_digest"], r"^[0-9a-f]{64}$")
        self.assertEqual(len(activation_afters), 1)

    def test_pending_recovery_request_is_revision_idempotent_during_terminal_verification(self):
        operation_id = "op-terminal-recovery-race"
        self.provision(operation_id=operation_id)
        first = self.service.request_recovery(operation_id)
        queued_revision = self.operations.read(operation_id)[0]
        verification_started = threading.Event()
        release_verification = threading.Event()
        original_active_projection = self.service.active_projection
        active_projection_calls = 0

        def blocking_active_projection():
            nonlocal active_projection_calls
            active_projection_calls += 1
            if active_projection_calls == 1:
                verification_started.set()
                if not release_verification.wait(2):
                    raise AssertionError("terminal verification was not released")
            return original_active_projection()

        self.service.active_projection = blocking_active_projection
        executor = activation_module.OpenClawProfileActivationExecutor(
            lambda: self.service
        )
        outcome = []
        errors = []

        def run_executor():
            try:
                outcome.extend(executor.run_once())
            except Exception as error:  # Captured for deterministic thread readback.
                errors.append(error)

        thread = threading.Thread(target=run_executor)
        thread.start()
        self.assertTrue(verification_started.wait(2))
        second = self.service.request_recovery(operation_id)
        third = self.service.request_recovery(operation_id)
        repeated_revision = self.operations.read(operation_id)[0]
        release_verification.set()
        thread.join(2)

        self.assertFalse(thread.is_alive())
        self.assertEqual(errors, [])
        self.assertEqual(outcome, [operation_id])
        self.assertEqual(first["recovery_request_generation"], 1)
        self.assertEqual(second["recovery_request_generation"], 1)
        self.assertEqual(third["recovery_request_generation"], 1)
        self.assertEqual(repeated_revision, queued_revision)
        terminal = self.service.status(operation_id)
        self.assertEqual(terminal["status"], "completed")
        self.assertEqual(terminal["recovery_request_generation"], 1)
        self.assertEqual(terminal["recovery_processed_generation"], 1)

    def test_failed_terminal_recovery_is_generation_stamped_and_executor_verified(self):
        operation_id = "op-failed-terminal-recovery"
        self.service.submit(
            DECLARATIONS, owner="worker-a", operation_id=operation_id
        )
        self.service.session_owner_factory = lambda _owner: "invalid owner"
        initially_failed = self.service.run(operation_id)

        queued = self.service.request_recovery(operation_id)
        processed = activation_module.OpenClawProfileActivationExecutor(
            lambda: self.service
        ).run_once()
        verified_view = self.service.status(operation_id)
        _revision, verified = self.operations.read(operation_id)

        self.assertEqual(initially_failed["status"], "failed")
        self.assertEqual(queued["status"], "recovery_required")
        self.assertEqual(processed, [operation_id])
        self.assertEqual(verified_view["status"], "failed")
        self.assertEqual(verified["recovery_request_generation"], 1)
        self.assertEqual(verified["recovery_processed_generation"], 1)
        self.assertEqual(verified["recovery_result"], "failed")
        self.assertFalse(verified["recovery_requested"])

    def test_nonterminal_recovery_completion_consumes_its_request_generation(self):
        operation_id = "op-nonterminal-recovery-generation"
        self.service.submit(
            DECLARATIONS, owner="worker-a", operation_id=operation_id
        )
        queued = self.service.request_recovery(operation_id)

        processed = activation_module.OpenClawProfileActivationExecutor(
            lambda: self.service
        ).run_once()
        completed = self.service.status(operation_id)
        _revision, stored = self.operations.read(operation_id)

        self.assertEqual(queued["status"], "recovery_required")
        self.assertEqual(processed, [operation_id])
        self.assertEqual(completed["status"], "completed")
        self.assertFalse(stored["recovery_requested"])
        self.assertEqual(stored["recovery_request_generation"], 1)
        self.assertEqual(stored["recovery_processed_generation"], 1)
        self.assertEqual(stored["recovery_result"], "completed")

    def test_terminal_status_rejects_a_non_boolean_recovery_request_flag(self):
        operation_id = "op-invalid-recovery-flag"
        self.provision(operation_id=operation_id)
        revision, operation = self.operations.read(operation_id)
        operation["recovery_requested"] = "false"
        self.operations.compare_and_set(operation_id, revision, operation)

        with self.assertRaisesRegex(ActivationError, "recovery request flag"):
            self.service.status(operation_id)

    def test_journal_failure_after_renewal_cas_replays_same_fence_idempotently(self):
        self.service.submit(DECLARATIONS, owner="worker-a", operation_id="op-renew-crash")
        self.journal.fail_once = ("lease_renewal", "after")

        interrupted = self.service.run("op-renew-crash")
        recovered = self.service.recover("op-renew-crash")

        self.assertEqual(interrupted["status"], "recovery_required")
        self.assertEqual(recovered["status"], "completed")
        self.assertEqual(recovered["receipt"]["generation"], 1)
        self.assertEqual(self.control.read()[1]["fence_generation"], 1)
        self.assert_journal_pairs_closed("op-renew-crash")

    def test_lease_renewal_checkpoints_keep_a_long_operation_inside_its_holder_window(self):
        self.brain.on_put = lambda _slug: self.clock.__setitem__(
            0, self.clock[0] + 2
        )
        self.service.submit(
            DECLARATIONS, owner="worker-a", operation_id="op-long-running"
        )

        completed = self.service.run("op-long-running")

        self.assertEqual(completed["status"], "completed")
        renewal_afters = [
            event
            for event in self.journal.read("op-long-running")
            if event.get("step") == "lease_renewal"
            and event.get("phase") == "after"
        ]
        renewal_resources = {event["resource"] for event in renewal_afters}
        self.assertTrue(
            {"control-anchors", "control-generation", "control-manifest"}.issubset(
                renewal_resources
            )
        )
        self.assertIn("control-before-activation-cas", renewal_resources)

    def test_recovery_closes_page_journal_after_from_exact_forward_readback(self):
        self.service.submit(DECLARATIONS, owner="worker-a", operation_id="op-page-crash")
        self.journal.fail_once = ("generation_page", "after")

        interrupted = self.service.run("op-page-crash")
        recovered = self.service.recover("op-page-crash")

        self.assertEqual(interrupted["status"], "recovery_required")
        self.assertEqual(recovered["status"], "completed")
        self.assertEqual(recovered["receipt"]["generation"], 1)
        self.assert_journal_pairs_closed("op-page-crash")

    def test_repeated_recovery_failure_keeps_the_canonical_error_not_a_journal_collision(self):
        self.brain.fail_after_puts = 2
        self.service.submit(DECLARATIONS, owner="worker-a", operation_id="op-repeat-fail")

        interrupted = self.service.run("op-repeat-fail")
        retried = self.service.recover("op-repeat-fail")

        self.assertEqual(interrupted["status"], "recovery_required")
        self.assertEqual(retried["status"], "recovery_required")
        self.assertIn("simulated write interruption", retried["error"])
        self.assertNotIn("journal event identity collision", retried["error"])

    def test_deterministic_declaration_conflict_is_failed_not_recovery_required(self):
        self.service.submit(
            DECLARATIONS, owner="worker-a", operation_id="op-bad-declaration"
        )
        operation_revision, operation = self.operations.read("op-bad-declaration")
        operation["status"] = "recovery_required"
        operation["fence_generation"] = 3
        operation["declarations"][0]["name"] = "Wrong Agent"
        self.operations.compare_and_set(
            "op-bad-declaration", operation_revision, operation
        )
        control_revision, control = self.control.read()
        control.update(
            {
                "state": "leased",
                "generation": 3,
                "fence_generation": 3,
                "lease_owner": "expired-session",
                "operation_id": "op-bad-declaration",
                "lease_expires_at": self.clock[0]
                - self.service.clock_skew_seconds
                - 1,
            }
        )
        self.control.compare_and_set(control_revision, control)

        failed = self.service.recover("op-bad-declaration")

        self.assertEqual(failed["status"], "failed")
        self.assertIn("declaration", failed["error"])

    def test_deterministic_auth_conflict_is_failed_not_recovery_required(self):
        self.service.submit(
            DECLARATIONS, owner="worker-a", operation_id="op-auth-conflict"
        )
        operation_revision, operation = self.operations.read("op-auth-conflict")
        operation.update({"status": "recovery_required", "fence_generation": 3})
        self.operations.compare_and_set(
            "op-auth-conflict", operation_revision, operation
        )
        control_revision, control = self.control.read()
        control.update(
            {
                "state": "leased",
                "generation": 3,
                "fence_generation": 3,
                "lease_owner": "expired-session",
                "operation_id": "op-auth-conflict",
                "lease_expires_at": self.clock[0]
                - self.service.clock_skew_seconds
                - 1,
            }
        )
        self.control.compare_and_set(control_revision, control)
        self.brain.get_page = lambda _slug: (_ for _ in ()).throw(
            RuntimeError("GBrain unauthorized")
        )

        failed = self.service.recover("op-auth-conflict")

        self.assertEqual(failed["status"], "failed")
        self.assertIn("unauthorized", failed["error"])

    def test_lease_uses_unique_session_owner_and_clock_skew_quarantine(self):
        owners = iter(("worker-a-session-1", "worker-a-session-2"))
        service = OpenClawProfileActivation(
            control=self.control,
            journal=self.journal,
            brain=self.brain,
            now=lambda: self.clock[0],
            lease_seconds=30,
            clock_skew_seconds=5,
            operations=self.operations,
            session_owner_factory=lambda _owner: next(owners),
        )
        revision, record = self.control.read()
        record.update(
            {
                "state": "leased",
                "fence_generation": 4,
                "generation": 4,
                "lease_owner": "other-session",
                "operation_id": "op-other",
                "lease_expires_at": self.clock[0] - 1,
            }
        )
        self.control.compare_and_set(revision, record)
        service.submit(DECLARATIONS, owner="worker-a", operation_id="op-skew")

        quarantined = service.run("op-skew")

        self.assertEqual(quarantined["status"], "accepted")
        self.assertIn("leased", quarantined["error"])
        self.clock[0] += 7
        observed_lease_owners = []
        self.brain.on_put = lambda _slug: observed_lease_owners.append(
            self.control.read()[1]["lease_owner"]
        )
        completed = service.run("op-skew")
        self.assertEqual(completed["status"], "completed")
        self.assertEqual(completed["receipt"]["generation"], 5)
        self.assertTrue(observed_lease_owners)
        self.assertEqual(set(observed_lease_owners), {"worker-a-session-2"})
        self.assertNotEqual(observed_lease_owners[0], "worker-a")

    def test_claim_resamples_clock_after_completion_finalization_before_cas(self):
        revision, control = self.control.read()
        control.update(
            {
                "state": "leased",
                "generation": 4,
                "fence_generation": 4,
                "lease_owner": "expired-during-finalization",
                "operation_id": "op-prior-holder",
                "lease_expires_at": self.clock[0] + 1,
            }
        )
        self.control.compare_and_set(revision, control)
        self.service.submit(
            DECLARATIONS, owner="worker-a", operation_id="op-fresh-clock"
        )
        original_finalize = self.service._finalize_control_completion
        observed_claim_expiry = []
        original_append = self.journal.append

        def finalize_and_advance(prior):
            result = original_finalize(prior)
            self.clock[0] += 10
            return result

        def observe_claim(event):
            if event.get("step") == "lease" and event.get("phase") == "before":
                self.clock[0] += 7
            if event.get("step") == "lease" and event.get("phase") == "after":
                observed_claim_expiry.append(
                    self.control.read()[1]["lease_expires_at"]
                )
            original_append(event)

        self.service._finalize_control_completion = finalize_and_advance
        self.journal.append = observe_claim

        completed = self.service.run("op-fresh-clock")

        self.assertEqual(completed["status"], "completed")
        self.assertEqual(completed["receipt"]["generation"], 5)
        self.assertEqual(
            observed_claim_expiry,
            [self.clock[0] + self.service.lease_seconds],
        )

    def test_maximum_request_owner_still_gets_a_valid_unique_session_owner(self):
        request_owner = "w" * 128
        self.service.submit(
            DECLARATIONS, owner=request_owner, operation_id="op-long-owner"
        )

        completed = self.service.run("op-long-owner")

        self.assertEqual(completed["status"], "completed")

    def test_activates_only_one_immutable_generation_manifest_after_exact_readback(self):
        receipt = self.provision()

        revision, control = self.control.read()
        self.assertEqual(control["state"], "active")
        self.assertEqual(control["generation"], 1)
        self.assertEqual(control["active_manifest"], receipt["manifest_slug"])
        self.assertEqual(receipt["generation"], 1)
        self.assertEqual(
            set(receipt),
            {
                "generation",
                "manifest_slug",
                "manifest_digest",
                "default_goal_link_count",
            },
        )
        manifest = self.brain.get_page(receipt["manifest_slug"])
        self.assertEqual(manifest["generation"], 1)
        self.assertEqual(len(manifest["profiles"]), 3)
        self.assertEqual(manifest["default_goal_link_count"], 0)
        self.assertTrue(all("/staged/" in profile["staged_agent_slug"] for profile in manifest["profiles"]))
        self.assertTrue(any(event["event"] == "activated" for event in self.journal.events))
        self.assertGreater(revision, 1)

    def test_partial_staging_never_becomes_visible(self):
        self.brain.fail_after_puts = 2

        with self.assertRaisesRegex(ActivationError, "simulated write interruption"):
            self.provision()

        _revision, control = self.control.read()
        self.assertIsNone(control["active_manifest"])
        self.assertEqual(control["generation"], 1)
        self.assertTrue(all(self.brain.pages[slug].get("frontmatter", {}).get("logical_anchor") for slug in self.brain.pages if slug.startswith("agents/") and slug.endswith("-oc")))
        self.assertTrue(any(event["event"] == "staging_failed" for event in self.journal.events))

    def test_lock_contention_rejects_an_unexpired_other_owner(self):
        revision, record = self.control.read()
        record.update(
            {
                "state": "leased",
                "generation": 7,
                "lease_owner": "worker-other",
                "operation_id": "op-other",
                "lease_expires_at": self.clock[0] + 1,
            }
        )
        self.control.compare_and_set(revision, record)

        with self.assertRaisesRegex(ActivationConflict, "leased"):
            self.provision()

        self.assertEqual(self.brain.puts, 0)

    def test_expired_lease_fences_the_successor_with_a_higher_generation(self):
        revision, record = self.control.read()
        record.update(
            {
                "state": "leased",
                "generation": 7,
                "lease_owner": "worker-other",
                "operation_id": "op-other",
                "lease_expires_at": self.clock[0] - self.service.clock_skew_seconds - 1,
            }
        )
        self.control.compare_and_set(revision, record)

        receipt = self.provision(owner="worker-b", operation_id="op-b")

        self.assertEqual(receipt["generation"], 8)
        self.assertEqual(self.control.read()[1]["active_manifest"], receipt["manifest_slug"])

    def test_stale_holder_cannot_activate_after_a_successor_claim_changes_control_revision(self):
        revision, record = self.control.read()
        record.update(
            {
                "state": "leased",
                "generation": 1,
                "lease_owner": "worker-a",
                "operation_id": "op-a",
                "lease_expires_at": self.clock[0] - 1,
            }
        )
        self.control.compare_and_set(revision, record)
        stale_revision, stale_record = self.control.read()
        successor = dict(stale_record)
        successor.update(
            {
                "generation": 2,
                "lease_owner": "worker-b",
                "operation_id": "op-b",
                "lease_expires_at": self.clock[0] + 30,
            }
        )
        self.control.compare_and_set(stale_revision, successor)

        stale_record["active_manifest"] = "system/openclaw-profile-manifests/g000001-op-a"
        stale_record["state"] = "active"
        with self.assertRaises(ActivationConflict):
            self.control.compare_and_set(stale_revision, stale_record)

    def test_lease_owner_is_revalidated_before_every_ambiguous_page_write(self):
        original_put = self.brain.put_page

        def steal_after_first_write(slug, content):
            original_put(slug, content)
            if self.brain.puts == 1:
                revision, control = self.control.read()
                control["lease_owner"] = "successor-session"
                self.control.compare_and_set(revision, control)

        self.brain.put_page = steal_after_first_write
        self.service.submit(
            DECLARATIONS, owner="worker-a", operation_id="op-write-fence"
        )

        interrupted = self.service.run("op-write-fence")

        self.assertEqual(interrupted["status"], "recovery_required")
        self.assertEqual(self.brain.puts, 1)
        self.assertIsNone(self.control.read()[1].get("active_manifest"))

    def test_rejects_any_default_agent_for_link_before_manifest_activation(self):
        original = self.brain.get_links

        def links_with_goal(slug):
            links = original(slug)
            if "/staged/" in slug and slug.endswith("/agents/tammy-oc"):
                links.append(
                    {
                        "from_slug": slug,
                        "to_slug": "goals/unapproved",
                        "link_type": "default_agent_for",
                        "context": "invalid",
                    }
                )
            return links

        self.brain.get_links = links_with_goal
        with self.assertRaisesRegex(ActivationError, "default_agent_for"):
            self.provision()
        self.assertIsNone(self.control.read()[1]["active_manifest"])

    def test_rogue_anchor_link_is_terminal_failed_before_activation_cas(self):
        original_put = self.brain.put_page

        def put_with_rogue_link(slug, content):
            original_put(slug, content)
            if slug == "agents/tammy-oc":
                self.brain.links.setdefault(slug, []).append(
                    {
                        "from_slug": slug,
                        "to_slug": "collections/mission-control-artifacts",
                        "link_type": "related_to",
                        "context": "rogue concurrent mutation",
                    }
                )

        self.brain.put_page = put_with_rogue_link
        self.service.submit(
            DECLARATIONS, owner="worker-a", operation_id="op-rogue-anchor"
        )

        failed = self.service.run("op-rogue-anchor")

        self.assertEqual(failed["status"], "failed")
        self.assertIn("anchor", failed["error"])
        self.assertIsNone(failed["receipt"])
        self.assertIsNone(self.control.read()[1].get("active_manifest"))

    def test_active_projection_double_reads_control_and_retries_on_generation_change(self):
        receipt = self.provision()
        reads = 0
        original_read = self.control.read

        def changing_read():
            nonlocal reads
            reads += 1
            result = original_read()
            if reads == 1:
                revision, record = original_read()
                self.control.compare_and_set(revision, record)
            return result

        self.control.read = changing_read
        projection = self.service.active_projection()

        self.assertEqual(projection["generation"], receipt["generation"])
        self.assertGreaterEqual(reads, 3)

    def test_active_projection_double_reads_an_empty_control_before_returning(self):
        receipt = self.provision()
        active_revision, active_control = self.control.read()
        idle_control = FakeControl().read()[1]
        reads = 0

        def activating_read():
            nonlocal reads
            reads += 1
            if reads == 1:
                return 1, copy.deepcopy(idle_control)
            return active_revision, copy.deepcopy(active_control)

        self.control.read = activating_read

        projection = self.service.active_projection()

        self.assertEqual(projection["generation"], receipt["generation"])
        self.assertGreaterEqual(reads, 4)

    def test_active_projection_requires_a_manifest_digest(self):
        self.provision()
        revision, control = self.control.read()
        control["active_manifest_digest"] = None
        self.control.compare_and_set(revision, control)

        with self.assertRaisesRegex(ActivationError, "digest"):
            self.service.active_projection()

    def test_active_projection_rejects_generation_positive_control_without_a_manifest(self):
        revision, control = self.control.read()
        control.update(
            {
                "generation": 1,
                "active_generation": 1,
                "active_manifest": None,
                "active_manifest_digest": None,
            }
        )
        self.control.compare_and_set(revision, control)

        with self.assertRaisesRegex(ActivationError, "manifest"):
            self.service.active_projection()

    def test_durable_active_projection_rejects_a_manifest_slug_for_another_generation(self):
        operation_id = "op-invalid-cache-manifest"
        self.provision(operation_id=operation_id)
        projection_revision, record = self.service.projections.read()
        record["projection"]["active_manifest"] = (
            "system/openclaw-profile-manifests/"
            f"g000002-{operation_id}"
        )
        record["projection_digest"] = hashlib.sha256(
            json.dumps(
                record["projection"],
                sort_keys=True,
                separators=(",", ":"),
            ).encode("utf-8")
        ).hexdigest()
        self.service.projections.compare_and_set(projection_revision, record)

        restarted = OpenClawProfileActivation(
            control=self.control,
            journal=self.journal,
            brain=self.brain,
            now=lambda: self.clock[0],
            operations=self.operations,
            projections=self.service.projections,
        )
        with self.assertRaisesRegex(ActivationError, "projection cache"):
            restarted.start()

    def test_generation_zero_active_projection_has_no_manifest(self):
        projection = self.service.active_projection()

        self.assertEqual(projection["generation"], 0)
        self.assertIsNone(projection["active_manifest"])
        self.assertIsNone(projection["manifest_digest"])
        self.assertEqual(projection["profiles"], [])

    def test_active_projection_rejects_boolean_zero_in_exact_manifest_schema(self):
        receipt = self.provision()
        self.reseal_manifest(
            receipt,
            lambda manifest: manifest.update({"default_goal_link_count": False}),
        )

        with self.assertRaisesRegex(ActivationError, "default goal|control fields"):
            self.service.active_projection()

    def test_active_projection_rejects_non_integer_manifest_counters(self):
        receipt = self.provision(operation_id="op-noninteger-counters")

        def corrupt_counters(manifest):
            manifest["fence_generation"] = True
            manifest["staged_page_count"] = float(
                manifest["staged_page_count"]
            )

        self.reseal_manifest(receipt, corrupt_counters)

        with self.assertRaisesRegex(ActivationError, "operation or control"):
            self.service.active_projection()

    def test_active_projection_rejects_manifest_schema_extensions_even_when_resealed(self):
        receipt = self.provision()
        self.reseal_manifest(receipt, lambda manifest: manifest.update({"unexpected": True}))

        with self.assertRaisesRegex(ActivationError, "schema"):
            self.service.active_projection()

    def test_active_projection_rejects_mismatched_operation_metadata_when_resealed(self):
        receipt = self.provision()

        def corrupt_metadata(manifest):
            manifest["operation_id"] = "op-other"
            manifest["profiles"][0]["metadata"] = {"slug": "wrong"}

        self.reseal_manifest(receipt, corrupt_metadata)

        with self.assertRaisesRegex(ActivationError, "operation|metadata"):
            self.service.active_projection()

    def test_active_projection_requires_exact_page_and_link_hash_maps(self):
        receipt = self.provision()

        def remove_hash(manifest):
            manifest["generation_page_hashes"].pop(
                next(iter(manifest["generation_page_hashes"]))
            )
            manifest["generation_link_hashes"]["extra"] = "0" * 64

        self.reseal_manifest(receipt, remove_hash)

        with self.assertRaisesRegex(ActivationError, "hash map"):
            self.service.active_projection()

    def test_active_projection_rejects_undeclared_links_on_immutable_sources(self):
        receipt = self.provision()
        staged_agent = self.brain.get_page(receipt["manifest_slug"])["profiles"][0][
            "staged_agent_slug"
        ]
        self.brain.links.setdefault(staged_agent, []).append(
            {
                "from_slug": staged_agent,
                "to_slug": "collections/mission-control-artifacts",
                "link_type": "part_of",
                "context": "undeclared",
            }
        )

        with self.assertRaisesRegex(ActivationError, "declared immutable link set"):
            self.service.active_projection()

    def test_active_projection_revalidates_mutable_logical_profile_state(self):
        receipt = self.provision()
        logical_agent = "agents/tammy-oc"
        goal_slug = "goals/help-tony-ship"
        self.brain.pages[logical_agent]["title"] = "Tammy OpenClaw"
        self.brain.pages[logical_agent]["frontmatter"]["avatar"] = {
            "kind": "attachment",
            "value": "/media/tammy.png",
        }
        self.brain.pages[goal_slug] = {
            "slug": goal_slug,
            "type": "goal",
            "title": "Help Tony ship",
        }
        self.brain.add_link(
            logical_agent,
            goal_slug,
            "default_agent_for",
            "Current user-selected default goal.",
        )

        projection = self.service.revalidate_active_projection()

        self.assertEqual(projection["active_manifest"], receipt["manifest_slug"])
        manifest = self.brain.get_page(receipt["manifest_slug"])
        self.assertNotEqual(
            manifest["anchor_page_hashes"][logical_agent],
            activation_module._digest(self.brain.pages[logical_agent]),
        )

    def test_active_projection_still_rejects_logical_anchor_identity_tampering(self):
        self.provision()
        self.brain.pages["agents/tammy-oc"]["frontmatter"]["runtime"] = "codex"

        with self.assertRaisesRegex(ActivationError, "anchor|hash mismatch"):
            self.service.revalidate_active_projection()

    def test_active_projection_rejects_a_resealed_manifest_that_declares_a_rogue_link(self):
        receipt = self.provision()
        manifest = self.brain.pages[receipt["manifest_slug"]]
        source = manifest["profiles"][0]["staged_agent_slug"]
        rogue = {
            "from_slug": source,
            "to_slug": "collections/mission-control-artifacts",
            "link_type": "part_of",
            "context": "not part of the approved declaration",
        }
        self.brain.links.setdefault(source, []).append(copy.deepcopy(rogue))

        def declare_rogue_link(item):
            digest = hashlib.sha256(
                json.dumps(rogue, sort_keys=True, separators=(",", ":")).encode(
                    "utf-8"
                )
            ).hexdigest()
            item["generation_links"].append(copy.deepcopy(rogue))
            item["generation_link_hashes"][digest] = digest
            item["staged_link_count"] += 1

        self.reseal_manifest(receipt, declare_rogue_link)

        with self.assertRaisesRegex(ActivationError, "declared immutable link set"):
            self.service.active_projection()

    def test_recovery_returns_only_the_cas_activated_manifest(self):
        receipt = self.provision()
        self.brain.put_page(
            "system/openclaw-profile-manifests/g000002-crashed",
            {"generation": 2, "profiles": [], "default_goal_link_count": 0},
        )

        recovered = self.service.recover("op-a")

        self.assertEqual(recovered["receipt"]["manifest_slug"], receipt["manifest_slug"])
        self.assertEqual(recovered["fence_generation"], 1)

    def test_executor_recovers_a_completed_control_receipt_left_running_in_operation_store(self):
        receipt = self.provision(operation_id="op-terminal-store-gap")
        revision, record = self.operations.read("op-terminal-store-gap")
        record.update({"status": "running", "receipt": None, "error": "store interrupted"})
        self.operations.compare_and_set("op-terminal-store-gap", revision, record)

        pending = self.service.status("op-terminal-store-gap")
        activation_module.OpenClawProfileActivationExecutor(
            lambda: self.service
        ).run_once()
        recovered = self.service.status("op-terminal-store-gap")

        self.assertEqual(pending["status"], "running")
        self.assertEqual(recovered["status"], "completed")
        self.assertEqual(recovered["receipt"]["manifest_slug"], receipt["manifest_slug"])

    def test_status_reports_completion_gap_without_control_or_canonical_reads(self):
        self.provision(operation_id="op-cheap-status")
        revision, operation = self.operations.read("op-cheap-status")
        operation.update({"status": "running", "receipt": None, "error": None})
        self.operations.compare_and_set("op-cheap-status", revision, operation)
        self.brain.get_page = lambda _slug: (_ for _ in ()).throw(
            AssertionError("status performed a canonical read")
        )
        self.control.read = lambda: (_ for _ in ()).throw(
            AssertionError("status performed a control read")
        )

        status = self.service.status("op-cheap-status")

        self.assertEqual(status["status"], "running")
        self.assertIsNone(status["error"])

    def test_completed_status_is_a_bounded_durable_store_read(self):
        self.provision(operation_id="op-cheap-terminal-status")
        canonical_reads = []
        original_get_page = self.brain.get_page
        original_get_links = self.brain.get_links

        def count_page(slug):
            canonical_reads.append(("page", slug))
            return original_get_page(slug)

        def count_links(slug):
            canonical_reads.append(("links", slug))
            return original_get_links(slug)

        self.brain.get_page = count_page
        self.brain.get_links = count_links

        status = self.service.status("op-cheap-terminal-status")

        self.assertEqual(status["status"], "completed")
        self.assertEqual(canonical_reads, [])

    def test_nonterminal_status_is_one_durable_operation_read_only(self):
        self.service.submit(
            DECLARATIONS, owner="worker-a", operation_id="op-cheap-accepted"
        )
        original_read = self.operations.read
        operation_reads = []

        def count_operation_read(operation_id):
            operation_reads.append(operation_id)
            return original_read(operation_id)

        self.operations.read = count_operation_read
        self.control.read = lambda: (_ for _ in ()).throw(
            AssertionError("status read the control store")
        )
        self.brain.get_page = lambda _slug: (_ for _ in ()).throw(
            AssertionError("status read a canonical page")
        )

        status = self.service.status("op-cheap-accepted")

        self.assertEqual(status["status"], "accepted")
        self.assertEqual(operation_reads, ["op-cheap-accepted"])

    def test_completed_operation_stores_an_exact_receipt_attestation(self):
        receipt = self.provision(operation_id="op-receipt-attestation")

        _revision, operation = self.operations.read("op-receipt-attestation")
        expected_digest = hashlib.sha256(
            json.dumps(
                receipt, sort_keys=True, separators=(",", ":")
            ).encode("utf-8")
        ).hexdigest()

        self.assertEqual(operation["receipt_version"], 1)
        self.assertEqual(operation["receipt_digest"], expected_digest)

    def test_active_projection_endpoint_read_uses_only_the_validated_cache(self):
        self.provision(operation_id="op-cached-active-projection")
        _cache_revision, durable_cache = self.service.projections.read()
        canonical_reads = []
        original_get_page = self.brain.get_page
        original_get_links = self.brain.get_links

        def count_page(slug):
            canonical_reads.append(("page", slug))
            return original_get_page(slug)

        def count_links(slug):
            canonical_reads.append(("links", slug))
            return original_get_links(slug)

        self.brain.get_page = count_page
        self.brain.get_links = count_links

        self.assertTrue(
            callable(getattr(self.service, "cached_active_projection", None))
        )
        cached = self.service.cached_active_projection()

        self.assertEqual(cached["status"], "ready")
        self.assertEqual(cached["generation"], 1)
        self.assertEqual(len(cached["profiles"]), 3)
        self.assertEqual(canonical_reads, [])
        self.assertEqual(
            durable_cache["control_revision"], self.control.revision
        )
        self.assertEqual(
            durable_cache["manifest_digest"], cached["manifest_digest"]
        )
        self.assertEqual(
            durable_cache["projection_digest"],
            hashlib.sha256(
                json.dumps(
                    durable_cache["projection"],
                    sort_keys=True,
                    separators=(",", ":"),
                ).encode("utf-8")
            ).hexdigest(),
        )

    def test_active_projection_revision_mismatch_queues_bounded_revalidation(self):
        self.provision(operation_id="op-stale-active-projection")
        revision, control = self.control.read()
        self.control.compare_and_set(revision, control)
        self.assertIn(
            "projection_validation_interval_seconds",
            inspect.signature(
                activation_module.OpenClawProfileActivationExecutor.__init__
            ).parameters,
        )
        executor = activation_module.OpenClawProfileActivationExecutor(
            lambda: self.service,
            projection_validation_interval_seconds=60,
        )

        pending = self.service.cached_active_projection()
        executor.request_projection_validation()
        executor.run_once()
        ready = self.service.cached_active_projection()

        self.assertEqual(pending["status"], "validation_pending")
        self.assertNotIn("profiles", pending)
        self.assertEqual(ready["status"], "ready")
        self.assertEqual(ready["control_revision"], self.control.revision)
        self.assertEqual(len(ready["profiles"]), 3)

    def test_started_service_requires_fresh_validation_before_serving_durable_projection(self):
        self.provision(operation_id="op-durable-projection-restart")
        restarted = OpenClawProfileActivation(
            control=self.control,
            journal=self.journal,
            brain=self.brain,
            now=lambda: self.clock[0],
            operations=self.operations,
            projections=self.service.projections,
            session_owner_factory=lambda owner: f"{owner}-restart-session",
        )

        restarted.start()
        try:
            pending = restarted.cached_active_projection()
            refreshed = restarted.revalidate_active_projection()
            ready = restarted.cached_active_projection()
        finally:
            restarted.close()

        self.assertEqual(pending["status"], "validation_pending")
        self.assertNotIn("profiles", pending)
        self.assertEqual(refreshed["generation"], 1)
        self.assertEqual(ready["status"], "ready")
        self.assertEqual(ready["control_revision"], self.control.revision)
        self.assertEqual(len(ready["profiles"]), 3)

    def test_executor_retries_fail_once_projection_invalidation_before_restart(self):
        operation_id = "op-invalidation-cas-retry"
        receipt = self.provision(operation_id=operation_id)
        manifest = self.brain.pages[receipt["manifest_slug"]]
        staged_agent = manifest["profiles"][0]["staged_agent_slug"]
        self.brain.pages[staged_agent]["title"] = "Known-bad after validation"
        original_compare_and_set = self.service.projections.compare_and_set
        fail_once = [True]

        def fail_first_compare_and_set(revision, record):
            if fail_once[0]:
                fail_once[0] = False
                raise ActivationError("projection CAS failed once")
            return original_compare_and_set(revision, record)

        self.service.projections.compare_and_set = fail_first_compare_and_set
        executor = activation_module.OpenClawProfileActivationExecutor(
            lambda: self.service
        )

        executor.run_once()
        _first_revision, after_failed_cas = self.service.projections.read()
        executor.run_once()
        _second_revision, after_retry = self.service.projections.read()
        restarted = OpenClawProfileActivation(
            control=self.control,
            journal=self.journal,
            brain=self.brain,
            now=lambda: self.clock[0],
            operations=self.operations,
            projections=self.service.projections,
        ).start()
        try:
            restarted_projection = restarted.cached_active_projection()
        finally:
            restarted.close()

        self.assertEqual(after_failed_cas["status"], "ready")
        self.assertEqual(after_retry["status"], "invalid")
        self.assertEqual(
            after_retry["control_revision"],
            after_failed_cas["control_revision"],
        )
        self.assertEqual(
            after_retry["manifest_digest"],
            after_failed_cas["manifest_digest"],
        )
        self.assertEqual(
            after_retry["projection_digest"],
            after_failed_cas["projection_digest"],
        )
        self.assertEqual(
            after_retry["projection"], after_failed_cas["projection"]
        )
        self.assertEqual(restarted_projection["status"], "validation_pending")

    def test_executor_invalidates_tampered_successor_in_one_cycle_after_old_cas_failure(self):
        first = self.provision(operation_id="op-invalidation-superseded")
        original_compare_and_set = self.service.projections.compare_and_set
        fail_once = [True]

        def fail_first_compare_and_set(revision, record):
            if fail_once[0]:
                fail_once[0] = False
                raise ActivationError("projection CAS failed once")
            return original_compare_and_set(revision, record)

        self.service.projections.compare_and_set = fail_first_compare_and_set
        with self.assertRaisesRegex(ActivationError, "failed once"):
            self.service.invalidate_cached_projection("old projection invalid")

        second = self.provision(
            owner="worker-b", operation_id="op-invalidation-successor"
        )
        manifest = self.brain.pages[second["manifest_slug"]]
        staged_agent = manifest["profiles"][0]["staged_agent_slug"]
        self.brain.pages[staged_agent]["title"] = "Known-bad successor"
        executor = activation_module.OpenClawProfileActivationExecutor(
            lambda: self.service
        )

        executor.run_once()
        _revision, durable = self.service.projections.read()
        active = self.service.cached_active_projection()
        restarted = OpenClawProfileActivation(
            control=self.control,
            journal=self.journal,
            brain=self.brain,
            now=lambda: self.clock[0],
            operations=self.operations,
            projections=self.service.projections,
        ).start()
        try:
            restarted_active = restarted.cached_active_projection()
        finally:
            restarted.close()

        self.assertEqual(first["generation"], 1)
        self.assertEqual(second["generation"], 2)
        self.assertEqual(durable["status"], "invalid")
        self.assertEqual(durable["projection"]["generation"], 2)
        self.assertEqual(active["status"], "validation_pending")
        self.assertEqual(active["generation"], 2)
        self.assertEqual(restarted_active["status"], "validation_pending")
        self.assertEqual(restarted_active["generation"], 2)

    def test_storing_newer_projection_clears_older_pending_invalidation(self):
        self.provision(operation_id="op-pending-clear-old")
        original_compare_and_set = self.service.projections.compare_and_set
        fail_once = [True]

        def fail_first_compare_and_set(revision, record):
            if fail_once[0]:
                fail_once[0] = False
                raise ActivationError("projection CAS failed once")
            return original_compare_and_set(revision, record)

        self.service.projections.compare_and_set = fail_first_compare_and_set
        with self.assertRaisesRegex(ActivationError, "failed once"):
            self.service.invalidate_cached_projection("old projection invalid")

        second = self.provision(
            owner="worker-b", operation_id="op-pending-clear-new"
        )
        _revision, durable = self.service.projections.read()
        with self.service._projection_lock:
            pending = copy.deepcopy(
                self.service._pending_projection_invalidation
            )

        self.assertEqual(second["generation"], 2)
        self.assertIsNone(pending)
        self.assertEqual(durable["status"], "ready")
        self.assertEqual(durable["projection"]["generation"], 2)

    def test_cross_worker_stale_target_read_failure_never_serves_tampered_successor(self):
        first = self.provision(operation_id="op-cross-worker-old")
        _first_revision, first_record = self.service.projections.read()
        writer = OpenClawProfileActivation(
            control=self.control,
            journal=self.journal,
            brain=self.brain,
            now=lambda: self.clock[0],
            lease_seconds=30,
            operations=self.operations,
            projections=self.service.projections,
        )
        second = writer.provision(
            DECLARATIONS,
            owner="worker-b",
            operation_id="op-cross-worker-new",
        )
        self.service.revalidate_active_projection()
        with self.service._projection_lock:
            self.service._pending_projection_invalidation = {
                "target": copy.deepcopy(first_record),
                "validation_error": "stale gen1 validation failure",
            }
        manifest = self.brain.pages[second["manifest_slug"]]
        staged_agent = manifest["profiles"][0]["staged_agent_slug"]
        self.brain.pages[staged_agent]["title"] = "Known-bad cross-worker successor"
        original_read = self.service.projections.read
        fail_once = [True]

        def fail_first_read():
            if fail_once[0]:
                fail_once[0] = False
                raise ActivationError("projection read failed once")
            return original_read()

        self.service.projections.read = fail_first_read
        executor = activation_module.OpenClawProfileActivationExecutor(
            lambda: self.service
        )

        executor.run_once()
        active_after_read_failure = self.service.cached_active_projection()
        with self.service._projection_lock:
            pending_after_read_failure = copy.deepcopy(
                self.service._pending_projection_invalidation
            )
        _revision, durable_after_read_failure = self.service.projections.read()
        restarted = OpenClawProfileActivation(
            control=self.control,
            journal=self.journal,
            brain=self.brain,
            now=lambda: self.clock[0],
            operations=self.operations,
            projections=self.service.projections,
        ).start()
        try:
            restarted_after_read_failure = restarted.cached_active_projection()
            activation_module.OpenClawProfileActivationExecutor(
                lambda: restarted
            ).run_once()
            _revision, durable_after_retry = self.service.projections.read()
            active_after_retry = restarted.cached_active_projection()
        finally:
            restarted.close()

        self.assertEqual(first["generation"], 1)
        self.assertEqual(second["generation"], 2)
        self.assertEqual(durable_after_read_failure["status"], "ready")
        self.assertEqual(
            durable_after_read_failure["projection"]["generation"], 2
        )
        self.assertEqual(
            pending_after_read_failure["target"]["projection"]["generation"],
            2,
        )
        self.assertEqual(
            pending_after_read_failure["target"]["projection_digest"],
            durable_after_read_failure["projection_digest"],
        )
        self.assertEqual(
            active_after_read_failure["status"], "validation_pending"
        )
        self.assertEqual(active_after_read_failure["generation"], 2)
        self.assertEqual(
            restarted_after_read_failure["status"], "validation_pending"
        )
        self.assertEqual(restarted_after_read_failure["generation"], 2)
        self.assertEqual(durable_after_retry["status"], "invalid")
        self.assertEqual(durable_after_retry["projection"]["generation"], 2)
        self.assertEqual(active_after_retry["status"], "validation_pending")
        self.assertEqual(active_after_retry["generation"], 2)

    def test_executor_periodically_revalidates_a_stale_active_projection(self):
        self.provision(operation_id="op-periodic-projection")
        executor_clock = [0.0]
        executor = activation_module.OpenClawProfileActivationExecutor(
            lambda: self.service,
            projection_validation_interval_seconds=60,
            clock=lambda: executor_clock[0],
        )
        executor.run_once()
        revision, control = self.control.read()
        self.control.compare_and_set(revision, control)

        executor_clock[0] = 59.0
        executor.run_once()
        before_interval = self.service.cached_active_projection()
        executor_clock[0] = 60.0
        executor.run_once()
        after_interval = self.service.cached_active_projection()

        self.assertEqual(before_interval["status"], "validation_pending")
        self.assertEqual(after_interval["status"], "ready")
        self.assertEqual(
            after_interval["control_revision"], self.control.revision
        )

    def test_completed_status_rejects_a_tampered_receipt_digest_without_graph_reads(self):
        operation_id = "op-tampered-receipt-digest"
        self.provision(operation_id=operation_id)
        revision, operation = self.operations.read(operation_id)
        operation["receipt"]["manifest_digest"] = "f" * 64
        self.operations.compare_and_set(operation_id, revision, operation)
        self.brain.get_page = lambda _slug: (_ for _ in ()).throw(
            AssertionError("terminal status performed a canonical page read")
        )
        self.brain.get_links = lambda _slug: (_ for _ in ()).throw(
            AssertionError("terminal status performed a canonical link read")
        )

        with self.assertRaisesRegex(ActivationError, "receipt digest"):
            self.service.status(operation_id)

    def test_recovery_terminalizes_a_non_exact_terminal_control_receipt(self):
        self.provision(operation_id="op-invalid-receipt")
        revision, operation = self.operations.read("op-invalid-receipt")
        operation.update({"status": "running", "receipt": None})
        self.operations.compare_and_set("op-invalid-receipt", revision, operation)
        control_revision, control = self.control.read()
        control["completed_receipt"]["unexpected"] = True
        self.control.compare_and_set(control_revision, control)

        failed = self.service.recover("op-invalid-receipt")

        self.assertEqual(failed["status"], "failed")
        self.assertIn("terminal receipt", failed["error"])

    def test_same_id_submit_revalidates_the_stored_terminal_operation(self):
        self.provision(operation_id="op-submit-terminal-validation")
        revision, operation = self.operations.read(
            "op-submit-terminal-validation"
        )
        operation["error"] = "corrupt terminal error"
        self.operations.compare_and_set(
            "op-submit-terminal-validation", revision, operation
        )

        with self.assertRaisesRegex(ActivationError, "completed activation operation"):
            self.service.submit(
                DECLARATIONS,
                owner="worker-a",
                operation_id="op-submit-terminal-validation",
            )

    def test_stored_failed_terminal_rejects_a_boolean_fence(self):
        self.service.submit(
            DECLARATIONS, owner="worker-a", operation_id="op-failed-fence"
        )
        revision, operation = self.operations.read("op-failed-fence")
        operation.update(
            {
                "status": "failed",
                "fence_generation": False,
                "receipt": None,
                "error": "deterministic failure",
            }
        )
        self.operations.compare_and_set("op-failed-fence", revision, operation)

        with self.assertRaisesRegex(ActivationError, "failed activation operation"):
            self.service.status("op-failed-fence")

    def test_stored_completed_terminal_rejects_a_float_zero_receipt_count(self):
        self.provision(operation_id="op-float-zero-receipt")
        revision, operation = self.operations.read("op-float-zero-receipt")
        operation["receipt"]["default_goal_link_count"] = 0.0
        self.operations.compare_and_set(
            "op-float-zero-receipt", revision, operation
        )

        with self.assertRaisesRegex(ActivationError, "terminal receipt"):
            self.service.status("op-float-zero-receipt")

    def test_executor_not_status_adopts_an_expired_running_holder(self):
        self.service.submit(DECLARATIONS, owner="worker-a", operation_id="op-expired-runner")
        revision, operation = self.operations.read("op-expired-runner")
        operation.update({"status": "running", "fence_generation": 3})
        self.operations.compare_and_set("op-expired-runner", revision, operation)
        control_revision, control = self.control.read()
        control.update(
            {
                "state": "leased",
                "fence_generation": 3,
                "generation": 3,
                "lease_owner": "dead-session",
                "operation_id": "op-expired-runner",
                "lease_expires_at": self.clock[0]
                - self.service.clock_skew_seconds
                - 1,
            }
        )
        self.control.compare_and_set(control_revision, control)

        status = self.service.status("op-expired-runner")
        activation_module.OpenClawProfileActivationExecutor(
            lambda: self.service
        ).run_once()
        recovered = self.service.status("op-expired-runner")

        self.assertEqual(status["status"], "running")
        self.assertEqual(status["fence_generation"], 3)
        self.assertEqual(recovered["status"], "completed")
        self.assertEqual(recovered["fence_generation"], 3)

    def test_recover_does_not_preempt_a_live_running_holder(self):
        self.service.submit(DECLARATIONS, owner="worker-a", operation_id="op-live")
        revision, operation = self.operations.read("op-live")
        operation.update({"status": "running", "fence_generation": 3})
        self.operations.compare_and_set("op-live", revision, operation)
        control_revision, control = self.control.read()
        control.update(
            {
                "state": "leased",
                "fence_generation": 3,
                "generation": 3,
                "lease_owner": "live-session",
                "operation_id": "op-live",
                "lease_expires_at": self.clock[0] + self.service.lease_seconds,
            }
        )
        self.control.compare_and_set(control_revision, control)
        claimed_revision = self.control.read()[0]

        status = self.service.recover("op-live")

        self.assertEqual(status["status"], "running")
        self.assertEqual(status["fence_generation"], 3)
        self.assertEqual(self.control.read()[0], claimed_revision)
        self.assertEqual(self.brain.puts, 0)

    def test_recovery_proves_an_older_completed_operation_after_a_successor_activates(self):
        first = self.provision(operation_id="op-first-gap")
        revision, record = self.operations.read("op-first-gap")
        record.update({"status": "running", "receipt": None, "error": "store interrupted"})
        self.operations.compare_and_set("op-first-gap", revision, record)
        second = self.provision(owner="worker-b", operation_id="op-successor")

        recovered = self.service.recover("op-first-gap")

        self.assertEqual(recovered["status"], "completed")
        self.assertEqual(recovered["receipt"]["manifest_slug"], first["manifest_slug"])
        self.assertEqual(recovered["receipt"]["generation"], 1)
        self.assertEqual(self.service.active_projection()["active_manifest"], second["manifest_slug"])
        self.assertEqual(self.control.read()[1]["fence_generation"], 2)

    def test_same_operation_retry_returns_the_completed_generation(self):
        first = self.provision(operation_id="op-repeat")
        second = self.provision(operation_id="op-repeat")

        self.assertEqual(second["generation"], first["generation"])
        self.assertEqual(second["manifest_slug"], first["manifest_slug"])

    def test_active_projection_rejects_a_tampered_generation_page(self):
        receipt = self.provision()
        profile = self.brain.get_page(receipt["manifest_slug"])["profiles"][0]
        staged = profile["staged_agent_slug"]
        self.brain.pages[staged]["title"] = "tampered"

        with self.assertRaisesRegex(ActivationError, "hash mismatch"):
            self.service.active_projection()

    def test_failed_successor_keeps_the_prior_active_manifest(self):
        first = self.provision(operation_id="op-first")
        self.brain.fail_after_puts = self.brain.puts + 1

        with self.assertRaises(ActivationError):
            self.provision(owner="worker-b", operation_id="op-second")

        self.assertEqual(self.service.active_projection()["active_manifest"], first["manifest_slug"])
