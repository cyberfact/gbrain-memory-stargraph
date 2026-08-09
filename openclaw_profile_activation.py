"""Crash-safe staged activation for the three declared OpenClaw profiles.

The NATS-backed control key is the activation authority. GBrain pages are
generation-namespaced staging data until an immutable manifest is selected by a
successful compare-and-set of that key.
"""
from __future__ import annotations

import asyncio
import copy
import hashlib
import inspect
import json
import os
import re
import stat
import sys
import threading
import time
import uuid
from collections import UserString
from concurrent.futures import TimeoutError as FutureTimeoutError
from contextlib import contextmanager, nullcontext
from pathlib import Path
from typing import Any, Callable, Mapping, Protocol, Sequence


ARTIFACTS_ROOT = "collections/mission-control-artifacts"
MANIFEST_PREFIX = "system/openclaw-profile-manifests"
STAGING_PREFIX = "system/openclaw-profile-staging"
APPROVED_DECLARATIONS = {
    "agents/tammy-oc": ("Tammy-OC", "hosts/tammy", "collections/tammy-oc-tasks", "collections/tammy-oc-artifacts"),
    "agents/timmy-oc": ("Timmy-OC", "hosts/timmy", "collections/timmy-oc-tasks", "collections/timmy-oc-artifacts"),
    "agents/toddy-oc": ("Toddy-OC", "hosts/toddy", "collections/toddy-oc-tasks", "collections/toddy-oc-artifacts"),
}
NATS_USER_PASSWORD_SCHEMA = "memory-stargraph.nats-credentials"
NATS_USER_PASSWORD_FIELDS = frozenset(
    {"schema", "version", "mode", "user", "password"}
)
NATS_CREDENTIALS_MAX_BYTES = 64 * 1024


class _SealedNatsRawCredentials(UserString):
    """In-memory nats-py credentials whose seed never appears in repr/str."""

    def __init__(self, data: str) -> None:
        object.__setattr__(self, "_sealed", False)
        super().__init__(data)
        object.__setattr__(self, "_sealed", True)

    def __setattr__(self, name: str, value: Any) -> None:
        if getattr(self, "_sealed", False):
            raise AttributeError("NATS credentials are immutable")
        object.__setattr__(self, name, value)

    def __str__(self) -> str:
        return "<redacted NATS credentials>"

    def __repr__(self) -> str:
        return "_SealedNatsRawCredentials(<redacted>)"
MANIFEST_FIELDS = frozenset(
    {
        "slug",
        "type",
        "title",
        "fence_generation",
        "generation",
        "active_generation",
        "operation_id",
        "profiles",
        "default_goal_link_count",
        "staged_page_count",
        "staged_link_count",
        "anchor_page_hashes",
        "anchor_link_hashes",
        "generation_page_hashes",
        "generation_link_hashes",
        "anchor_links",
        "generation_links",
    }
)
PROFILE_FIELDS = frozenset(
    {
        "canonical_agent_slug",
        "canonical_task_collection",
        "canonical_artifact_collection",
        "staged_agent_slug",
        "staged_task_collection",
        "staged_artifact_collection",
        "metadata",
        "page_hashes",
    }
)
LINK_FIELDS = frozenset({"from_slug", "to_slug", "link_type", "context"})
RECEIPT_FIELDS = frozenset(
    {
        "generation",
        "manifest_slug",
        "manifest_digest",
        "default_goal_link_count",
    }
)
RECEIPT_VERSION = 1
SHA256_PATTERN = re.compile(r"[0-9a-f]{64}")
OPERATION_ID_PATTERN = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]{0,127}")
NATS_REQUEST_TIMEOUT_MAX_SECONDS = 2.0
STATUS_ENDPOINT_BUDGET_SECONDS = 2.5
PROVISION_ENDPOINT_BUDGET_SECONDS = 6.5
RECOVERY_REQUEST_ENDPOINT_BUDGET_SECONDS = 4.5


def _active_projection_identity_is_valid(
    generation: Any, manifest_slug: Any, manifest_digest: Any
) -> bool:
    if (
        isinstance(generation, bool)
        or not isinstance(generation, int)
        or generation < 0
    ):
        return False
    if generation == 0:
        return manifest_slug is None and manifest_digest is None
    if (
        not isinstance(manifest_slug, str)
        or not isinstance(manifest_digest, str)
        or SHA256_PATTERN.fullmatch(manifest_digest) is None
    ):
        return False
    prefix = f"{MANIFEST_PREFIX}/g{generation:06d}-"
    if not manifest_slug.startswith(prefix):
        return False
    return OPERATION_ID_PATTERN.fullmatch(manifest_slug[len(prefix) :]) is not None


def _exception_contains(error: BaseException, *markers: str) -> bool:
    expected = tuple(marker.lower() for marker in markers)
    current: BaseException | None = error
    seen: set[int] = set()
    while current is not None and id(current) not in seen:
        seen.add(id(current))
        message = str(current).lower()
        error_type = type(current).__name__.lower()
        if any(marker in message or marker in error_type for marker in expected):
            return True
        current = current.__cause__ or current.__context__
    return False


def _is_deterministic_activation_failure(error: BaseException) -> bool:
    return isinstance(error, ActivationContentConflict) or _exception_contains(
        error,
        "unauthorized",
        "forbidden",
        "authentication failed",
        "authorization violation",
        "permission denied",
    )


class ActivationError(RuntimeError):
    pass


class ActivationConflict(ActivationError):
    pass


class ActivationLeaseHeld(ActivationConflict):
    """Another live session already owns the requested activation lease."""

    pass


class ActivationContentConflict(ActivationError):
    """Deterministic declaration or canonical-content mismatch."""

    pass


class ControlStore(Protocol):
    def read(self) -> tuple[int, dict[str, Any]]: ...

    def compare_and_set(self, revision: int, record: Mapping[str, Any]) -> int: ...


class Journal(Protocol):
    def append(self, event: Mapping[str, Any]) -> None: ...

    def read(self, operation_id: str) -> list[Mapping[str, Any]]: ...


class OperationStore(Protocol):
    def read(self, operation_id: str) -> tuple[int, dict[str, Any] | None]: ...

    def create(self, operation_id: str, record: Mapping[str, Any]) -> int: ...

    def compare_and_set(
        self, operation_id: str, revision: int, record: Mapping[str, Any]
    ) -> int: ...

    def list_records(self, statuses: set[str]) -> list[dict[str, Any]]: ...


class ProjectionStore(Protocol):
    def read(self) -> tuple[int, dict[str, Any] | None]: ...

    def compare_and_set(self, revision: int, record: Mapping[str, Any]) -> int: ...


class InMemoryOperationStore:
    """Process-local fallback used only by direct unit construction."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._records: dict[str, tuple[int, dict[str, Any]]] = {}

    def read(self, operation_id: str) -> tuple[int, dict[str, Any] | None]:
        with self._lock:
            stored = self._records.get(operation_id)
            if stored is None:
                return 0, None
            revision, record = stored
            return revision, copy.deepcopy(record)

    def create(self, operation_id: str, record: Mapping[str, Any]) -> int:
        with self._lock:
            if operation_id in self._records:
                raise ActivationConflict("operation already exists")
            self._records[operation_id] = (1, copy.deepcopy(dict(record)))
            return 1

    def compare_and_set(
        self, operation_id: str, revision: int, record: Mapping[str, Any]
    ) -> int:
        with self._lock:
            current = self._records.get(operation_id)
            if current is None or current[0] != revision:
                raise ActivationConflict("operation revision changed")
            next_revision = revision + 1
            self._records[operation_id] = (next_revision, copy.deepcopy(dict(record)))
            return next_revision

    def list_records(self, statuses: set[str]) -> list[dict[str, Any]]:
        with self._lock:
            return [
                copy.deepcopy(record)
                for _revision, record in self._records.values()
                if record.get("status") in statuses
            ]


class InMemoryProjectionStore:
    """Durable-cache shape used by direct construction and deterministic tests."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._revision = 0
        self._record: dict[str, Any] | None = None

    def read(self) -> tuple[int, dict[str, Any] | None]:
        with self._lock:
            return self._revision, copy.deepcopy(self._record)

    def compare_and_set(self, revision: int, record: Mapping[str, Any]) -> int:
        with self._lock:
            if revision != self._revision:
                raise ActivationConflict("active projection revision changed")
            self._revision += 1
            self._record = copy.deepcopy(dict(record))
            return self._revision


class Brain(Protocol):
    def put_page(self, slug: str, content: Mapping[str, Any]) -> None: ...

    def get_page(self, slug: str) -> Mapping[str, Any] | None: ...

    def add_link(self, source: str, target: str, link_type: str, context: str) -> None: ...

    def get_links(self, slug: str) -> list[Mapping[str, Any]]: ...


class JetStreamControlStore:
    """Small synchronous facade over a pre-provisioned JetStream KV client.

    The caller owns connection lifecycle. No bucket is created here: deployment
    must provision the private bucket and credentials explicitly.
    """

    def __init__(self, key_value: Any, key: str) -> None:
        self.key_value = key_value
        self.key = key

    @staticmethod
    def _default() -> dict[str, Any]:
        return {
            "state": "idle",
            "fence_generation": 0,
            "generation": 0,
            "active_generation": 0,
            "active_manifest": None,
            "active_manifest_digest": None,
            "lease_owner": None,
            "operation_id": None,
            "lease_expires_at": 0,
            "completed_operation_id": None,
            "completed_receipt": None,
        }

    def read(self) -> tuple[int, dict[str, Any]]:
        try:
            entry = self.key_value.get(self.key)
        except (KeyError, LookupError):
            return 0, self._default()
        except ActivationError as error:
            if _exception_contains(error, "keynotfounderror", "keydeletederror"):
                return 0, self._default()
            raise
        except Exception as error:
            if _exception_contains(error, "keynotfounderror", "keydeletederror"):
                return 0, self._default()
            raise ActivationError("JetStream control read failed") from error
        try:
            record = json.loads(bytes(entry.value).decode("utf-8"))
        except (TypeError, ValueError, json.JSONDecodeError) as error:
            raise ActivationError("JetStream control record is invalid") from error
        if not isinstance(record, dict):
            raise ActivationError("JetStream control record is not an object")
        return int(entry.revision), record

    def compare_and_set(self, revision: int, record: Mapping[str, Any]) -> int:
        value = json.dumps(dict(record), sort_keys=True, separators=(",", ":")).encode("utf-8")
        try:
            if revision == 0:
                return int(self.key_value.create(self.key, value))
            return int(self.key_value.update(self.key, value, last=revision))
        except Exception as error:  # nats-py exposes a version-specific CAS exception.
            if _exception_contains(error, "sequence", "revision"):
                raise ActivationConflict("JetStream control revision changed") from error
            raise ActivationError("JetStream control compare-and-set failed") from error


class JetStreamOperationStore:
    """Generation-independent operation receipts stored in the configured KV."""

    def __init__(self, key_value: Any, prefix: str) -> None:
        self.key_value = key_value
        self.prefix = prefix.rstrip("/")

    def _key(self, operation_id: str) -> str:
        if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]{0,127}", operation_id or ""):
            raise ActivationError("operation_id is invalid")
        return f"{self.prefix}/{operation_id}"

    def read(self, operation_id: str) -> tuple[int, dict[str, Any] | None]:
        try:
            entry = self.key_value.get(self._key(operation_id))
        except (KeyError, LookupError):
            return 0, None
        except ActivationError as error:
            if _exception_contains(error, "keynotfounderror", "keydeletederror"):
                return 0, None
            raise
        except Exception as error:
            if _exception_contains(error, "keynotfounderror", "keydeletederror"):
                return 0, None
            raise ActivationError("JetStream operation read failed") from error
        try:
            record = json.loads(bytes(entry.value).decode("utf-8"))
        except (TypeError, ValueError, json.JSONDecodeError) as error:
            raise ActivationError("JetStream operation record is invalid") from error
        if not isinstance(record, dict):
            raise ActivationError("JetStream operation record is not an object")
        return int(entry.revision), record

    def create(self, operation_id: str, record: Mapping[str, Any]) -> int:
        value = json.dumps(dict(record), sort_keys=True, separators=(",", ":")).encode(
            "utf-8"
        )
        try:
            return int(self.key_value.create(self._key(operation_id), value))
        except Exception as error:
            if _exception_contains(error, "sequence", "exist"):
                raise ActivationConflict("operation already exists") from error
            raise ActivationError("JetStream operation create failed") from error

    def compare_and_set(
        self, operation_id: str, revision: int, record: Mapping[str, Any]
    ) -> int:
        value = json.dumps(dict(record), sort_keys=True, separators=(",", ":")).encode(
            "utf-8"
        )
        try:
            return int(
                self.key_value.update(
                    self._key(operation_id), value, last=revision
                )
            )
        except Exception as error:
            if _exception_contains(error, "sequence", "revision"):
                raise ActivationConflict("operation revision changed") from error
            raise ActivationError("JetStream operation compare-and-set failed") from error

    def list_records(self, statuses: set[str]) -> list[dict[str, Any]]:
        prefix = f"{self.prefix}/"
        try:
            keys = self.key_value.keys()
        except Exception as error:
            if _exception_contains(error, "no keys", "nokeyserror"):
                return []
            raise ActivationError("JetStream operation listing failed") from error
        records: list[dict[str, Any]] = []
        for key in sorted(str(item) for item in keys if str(item).startswith(prefix)):
            operation_id = key[len(prefix) :]
            _revision, record = self.read(operation_id)
            if record is not None and record.get("status") in statuses:
                records.append(record)
        return records


class JetStreamProjectionStore:
    """Last-known-good active projection stored under one dedicated KV key."""

    def __init__(self, key_value: Any, key: str) -> None:
        self.key_value = key_value
        self.key = key

    def read(self) -> tuple[int, dict[str, Any] | None]:
        try:
            entry = self.key_value.get(self.key)
        except (KeyError, LookupError):
            return 0, None
        except Exception as error:
            if _exception_contains(error, "keynotfounderror", "keydeletederror"):
                return 0, None
            raise ActivationError("JetStream active projection read failed") from error
        try:
            record = json.loads(bytes(entry.value).decode("utf-8"))
        except (TypeError, ValueError, json.JSONDecodeError) as error:
            raise ActivationError("JetStream active projection is invalid") from error
        if not isinstance(record, dict):
            raise ActivationError("JetStream active projection is not an object")
        return int(entry.revision), record

    def compare_and_set(self, revision: int, record: Mapping[str, Any]) -> int:
        value = json.dumps(
            dict(record), sort_keys=True, separators=(",", ":")
        ).encode("utf-8")
        try:
            if revision == 0:
                return int(self.key_value.create(self.key, value))
            return int(self.key_value.update(self.key, value, last=revision))
        except Exception as error:
            if _exception_contains(error, "sequence", "revision", "exist"):
                raise ActivationConflict(
                    "active projection revision changed"
                ) from error
            raise ActivationError(
                "JetStream active projection compare-and-set failed"
            ) from error


class JetStreamJournal:
    """Append-only operation records with deterministic JetStream dedup IDs."""

    def __init__(self, publisher: Any, subject: str) -> None:
        self.publisher = publisher
        self.subject = subject

    def append(self, event: Mapping[str, Any]) -> None:
        item = dict(event)
        operation_id = str(item.get("operation_id") or "")
        step = str(item.get("step") or "")
        fence = str(item.get("fence_generation") or "0")
        resource = str(item.get("resource") or "")
        phase = str(item.get("phase") or "")
        if not operation_id or not step or not resource or phase not in {
            "before",
            "after",
            "event",
        }:
            raise ActivationError("journal event identity is incomplete")
        payload = json.dumps(item, sort_keys=True, separators=(",", ":")).encode("utf-8")
        event_id = f"{operation_id}:{fence}:{step}:{resource}:{phase}"
        writer = getattr(self.publisher, "write_journal_event", None)
        if writer is not None:
            writer(event_id, item)
        self.publisher.publish(
            self.subject,
            payload,
            headers={
                "Nats-Msg-Id": event_id
            },
        )

    def read(self, operation_id: str) -> list[Mapping[str, Any]]:
        reader = getattr(self.publisher, "read_journal_events", None)
        if reader is None:
            return []
        events = reader(operation_id)
        if not isinstance(events, list) or any(
            not isinstance(event, Mapping) for event in events
        ):
            raise ActivationError("activation journal readback is invalid")
        return [dict(event) for event in events]


class GBrainToolBrain:
    """Adapter over Memory Stargraph's already-scoped GBrain tool caller.

    Activation records are stored as a JSON scalar in frontmatter so each
    staging page can be read back and compared byte-for-byte with the in-memory
    manifest model. It deliberately uses only the existing page/link tools.
    """

    def __init__(self, call_tool: Callable[[str, Mapping[str, Any]], Any]) -> None:
        self.call_tool = call_tool

    @staticmethod
    def _markdown(page: Mapping[str, Any]) -> str:
        payload = json.dumps(dict(page), sort_keys=True, separators=(",", ":"))
        title = str(page.get("title") or page.get("slug") or "OpenClaw staging record")
        page_type = str(page.get("type") or "note")
        frontmatter = page.get("frontmatter") if isinstance(page.get("frontmatter"), Mapping) else {}
        fields = ["---", f"type: {json.dumps(page_type)}", f"title: {json.dumps(title)}"]
        fields.extend(f"{key}: {json.dumps(value)}" for key, value in sorted(frontmatter.items()) if key not in {"type", "title"})
        fields.extend((f"activation_payload: {json.dumps(payload)}", "---", "", f"# {title}", "", "Internal OpenClaw activation staging record.", ""))
        return "\n".join(fields)

    def put_page(self, slug: str, content: Mapping[str, Any]) -> None:
        if str(content.get("slug") or slug) != slug:
            raise ActivationError("staged page slug does not match its record")
        self.call_tool("put_page", {"slug": slug, "content": self._markdown(content)})

    @staticmethod
    def _outer_identity_matches_payload(
        outer: Mapping[str, Any], payload: Mapping[str, Any]
    ) -> bool:
        payload_frontmatter = payload.get("frontmatter")
        payload_frontmatter = (
            dict(payload_frontmatter)
            if isinstance(payload_frontmatter, Mapping)
            else {}
        )
        if payload_frontmatter.get("logical_anchor") is True:
            if payload.get("type") == "agent":
                frontmatter_fields = ("runtime", "logical_anchor")
            elif payload.get("type") == "collection":
                frontmatter_fields = (
                    "collection_kind",
                    "agent",
                    "logical_anchor",
                )
            else:
                return False
            include_title = False
        else:
            frontmatter_fields = tuple(sorted(payload_frontmatter))
            include_title = True

        def identity(page: Mapping[str, Any]) -> dict[str, Any]:
            frontmatter = page.get("frontmatter")
            values = dict(frontmatter) if isinstance(frontmatter, Mapping) else {}
            result: dict[str, Any] = {
                "slug": page.get("slug"),
                "type": page.get("type"),
                "frontmatter": {
                    field: values.get(field) for field in frontmatter_fields
                },
            }
            if include_title:
                result["title"] = page.get("title")
            return result

        return identity(outer) == identity(payload)

    def get_page(self, slug: str) -> Mapping[str, Any] | None:
        try:
            page = self.call_tool("get_page", {"slug": slug})
        except RuntimeError as error:
            if "not found" in str(error).lower():
                return None
            raise
        if not isinstance(page, Mapping):
            raise ActivationError(f"GBrain returned an invalid page for {slug}")
        frontmatter = page.get("frontmatter")
        encoded = frontmatter.get("activation_payload") if isinstance(frontmatter, Mapping) else None
        if not isinstance(encoded, str):
            return dict(page)
        try:
            value = json.loads(encoded)
        except json.JSONDecodeError as error:
            raise ActivationError(f"GBrain activation payload is invalid for {slug}") from error
        if not isinstance(value, Mapping) or value.get("slug") != slug:
            raise ActivationError(f"GBrain activation payload has the wrong slug for {slug}")
        if not self._outer_identity_matches_payload(page, value):
            raise ActivationError(
                f"GBrain outer page identity does not match activation payload for {slug}"
            )
        return dict(value)

    def add_link(self, source: str, target: str, link_type: str, context: str) -> None:
        self.call_tool(
            "add_link",
            {"from": source, "to": target, "link_type": link_type, "context": context},
        )

    def get_links(self, slug: str) -> list[Mapping[str, Any]]:
        value = self.call_tool("get_links", {"slug": slug})
        if not isinstance(value, list):
            raise ActivationError(f"GBrain returned invalid links for {slug}")
        result = []
        for item in value:
            if not isinstance(item, Mapping):
                raise ActivationError(f"GBrain returned a malformed link for {slug}")
            source = item.get("from_slug", item.get("from"))
            target = item.get("to_slug", item.get("to"))
            link_type = item.get("link_type", "")
            context = item.get("context", "")
            if not all(isinstance(part, str) for part in (source, target, link_type, context)):
                raise ActivationError(f"GBrain returned a malformed link for {slug}")
            result.append(
                {
                    "from_slug": source,
                    "to_slug": target,
                    "link_type": link_type,
                    "context": context,
                }
            )
        return result


class NatsJetStreamSession:
    """Synchronous bridge over nats-py for the small activation surface.

    The server owns one process-long connection and one continuously running
    event loop on a dedicated thread. Direct callers may still use a bounded
    outer operation context. Synchronous callers submit bounded coroutines to
    that loop. The bridge only obtains an *existing* KV bucket; it never calls
    create_key_value/create_stream or manages credentials.
    """

    def __init__(
        self,
        *,
        servers: Sequence[str],
        credentials_file: Path,
        bucket: str,
        connect: Callable[..., Any] | None = None,
        connect_timeout_seconds: float = 5,
        request_timeout_seconds: float = NATS_REQUEST_TIMEOUT_MAX_SECONDS,
    ) -> None:
        if (
            not servers
            or not bucket
            or connect_timeout_seconds <= 0
            or request_timeout_seconds <= 0
            or connect_timeout_seconds > 30
            or request_timeout_seconds > NATS_REQUEST_TIMEOUT_MAX_SECONDS
        ):
            raise ActivationError("OpenClaw NATS session is not configured")
        self.servers = tuple(servers)
        self.credentials_file = credentials_file
        self.bucket = bucket
        self.connect = connect
        self.connect_timeout_seconds = connect_timeout_seconds
        self.request_timeout_seconds = request_timeout_seconds
        (
            self._auth_mode,
            self._auth_values,
            self._credentials_signature,
        ) = self._load_credentials(credentials_file)
        self._loop: asyncio.AbstractEventLoop | None = None
        self._connection: Any | None = None
        self._jetstream: Any | None = None
        self._key_value: Any | None = None
        self._operation_depth = 0
        self._thread: threading.Thread | None = None
        self._ready: threading.Event | None = None
        self._startup_error: BaseException | None = None

    @staticmethod
    def _read_private_credentials(path: Path) -> tuple[str, tuple[Any, ...]]:
        """Read one stable mode-0600 regular file without following symlinks."""
        try:
            before = path.lstat()
            if (
                stat.S_ISLNK(before.st_mode)
                or not stat.S_ISREG(before.st_mode)
                or stat.S_IMODE(before.st_mode) != 0o600
            ):
                raise ActivationError("OpenClaw NATS credentials file is unsafe")
            flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0)
            descriptor = os.open(path, flags)
            try:
                current = os.fstat(descriptor)
                file_identity = (
                    current.st_dev,
                    current.st_ino,
                    current.st_mode,
                    current.st_size,
                    current.st_mtime_ns,
                )
                expected = (
                    before.st_dev,
                    before.st_ino,
                    before.st_mode,
                    before.st_size,
                    before.st_mtime_ns,
                )
                if (
                    file_identity != expected
                    or current.st_size > NATS_CREDENTIALS_MAX_BYTES
                ):
                    raise ActivationError("OpenClaw NATS credentials file is unsafe")
                chunks = []
                remaining = NATS_CREDENTIALS_MAX_BYTES + 1
                while remaining:
                    chunk = os.read(descriptor, remaining)
                    if not chunk:
                        break
                    chunks.append(chunk)
                    remaining -= len(chunk)
                raw = b"".join(chunks)
                if len(raw) > NATS_CREDENTIALS_MAX_BYTES:
                    raise ActivationError("OpenClaw NATS credentials file is unsafe")
                after = os.fstat(descriptor)
                after_identity = (
                    after.st_dev,
                    after.st_ino,
                    after.st_mode,
                    after.st_size,
                    after.st_mtime_ns,
                )
                if after_identity != file_identity:
                    raise ActivationError("OpenClaw NATS credentials file is unsafe")
            finally:
                os.close(descriptor)
            signature = (*file_identity, hashlib.sha256(raw).hexdigest())
            return raw.decode("utf-8"), signature
        except ActivationError:
            raise
        except (OSError, UnicodeError) as error:
            raise ActivationError("OpenClaw NATS credentials file is unsafe") from error

    @classmethod
    def _load_credentials(
        cls, path: Path
    ) -> tuple[str, tuple[str, ...], tuple[Any, ...]]:
        text, signature = cls._read_private_credentials(path)
        if path.suffix == ".creds":
            jwt = re.search(
                r"-----BEGIN NATS USER JWT-----\s*(\S+)\s*"
                r"------END NATS USER JWT------",
                text,
            )
            seed = re.search(
                r"-----BEGIN USER NKEY SEED-----\s*(\S+)\s*"
                r"------END USER NKEY SEED------",
                text,
            )
            if (
                jwt is None
                or seed is None
                or text.count("-----BEGIN NATS USER JWT-----") != 1
                or text.count("------END NATS USER JWT------") != 1
                or text.count("-----BEGIN USER NKEY SEED-----") != 1
                or text.count("------END USER NKEY SEED------") != 1
            ):
                raise ActivationError("OpenClaw NATS credentials file is invalid")
            return "user_credentials", (text,), signature
        if path.suffix != ".json":
            raise ActivationError("OpenClaw NATS credentials file is invalid")
        try:
            def reject_duplicate_keys(pairs):
                result = {}
                for key, value in pairs:
                    if key in result:
                        raise ValueError("duplicate key")
                    result[key] = value
                return result

            payload = json.loads(text, object_pairs_hook=reject_duplicate_keys)
        except (TypeError, ValueError):
            raise ActivationError("OpenClaw NATS credentials file is invalid") from None
        if (
            not isinstance(payload, dict)
            or set(payload) != NATS_USER_PASSWORD_FIELDS
            or payload.get("schema") != NATS_USER_PASSWORD_SCHEMA
            or type(payload.get("version")) is not int
            or payload.get("version") != 1
            or payload.get("mode") != "user_password"
            or not isinstance(payload.get("user"), str)
            or not payload["user"]
            or payload["user"].strip() != payload["user"]
            or not isinstance(payload.get("password"), str)
            or not payload["password"]
        ):
            raise ActivationError("OpenClaw NATS credentials file is invalid")
        return "user_password", (payload["user"], payload["password"]), signature

    def _connection_auth_kwargs(self) -> dict[str, Any]:
        if self._auth_mode == "user_credentials":
            return {
                "user_credentials": _SealedNatsRawCredentials(
                    self._auth_values[0]
                )
            }
        user, password = self._auth_values
        return {"user": user, "password": password}

    def _connect(self) -> Any:
        if self.connect is not None:
            return self.connect
        try:
            import nats  # type: ignore[import-not-found]
        except ImportError as error:
            raise ActivationError("nats-py is required for OpenClaw provisioning") from error
        return nats.connect

    def _await(
        self, awaitable_factory: Callable[[], Any], *, timeout: float, action: str
    ) -> Any:
        if (
            self._loop is None
            or self._loop.is_closed()
            or self._thread is None
            or not self._thread.is_alive()
        ):
            raise ActivationError("NATS operation context is not active")
        try:
            awaitable = awaitable_factory()
        except Exception as error:
            raise ActivationError(f"NATS {action} failed") from error
        try:
            future = asyncio.run_coroutine_threadsafe(awaitable, self._loop)
        except Exception as error:
            if inspect.iscoroutine(awaitable):
                awaitable.close()
            raise ActivationError(f"NATS {action} failed") from error
        try:
            return future.result(timeout=timeout)
        except FutureTimeoutError as error:
            future.cancel()
            raise ActivationError(f"NATS {action} timed out") from error
        except ActivationError:
            raise
        except Exception as error:
            raise ActivationError(f"NATS {action} failed") from error

    async def _cleanup_connection(self, connection: Any) -> None:
        for method_name in ("drain", "close"):
            method = getattr(connection, method_name, None)
            if not callable(method):
                continue
            try:
                result = method()
                if inspect.isawaitable(result):
                    await asyncio.wait_for(
                        result, timeout=self.request_timeout_seconds
                    )
                return
            except Exception:
                continue

    def _thread_main(self) -> None:
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        self._loop = loop
        try:
            try:
                self._connection = loop.run_until_complete(
                    asyncio.wait_for(
                        self._connect()(
                            servers=list(self.servers),
                            **self._connection_auth_kwargs(),
                            connect_timeout=self.connect_timeout_seconds,
                        ),
                        timeout=self.connect_timeout_seconds,
                    )
                )
            except asyncio.TimeoutError as error:
                raise ActivationError("NATS connect timed out") from error
            except Exception:
                raise ActivationError("NATS connect failed") from None
            self._jetstream = self._connection.jetstream()
            try:
                self._key_value = loop.run_until_complete(
                    asyncio.wait_for(
                        self._jetstream.key_value(self.bucket),
                        timeout=self.request_timeout_seconds,
                    )
                )
            except asyncio.TimeoutError as error:
                raise ActivationError("NATS KV lookup timed out") from error
            except Exception as error:
                raise ActivationError("NATS KV lookup failed") from error
        except BaseException as error:
            connection = self._connection
            if connection is not None:
                try:
                    loop.run_until_complete(
                        self._cleanup_connection(connection)
                    )
                except BaseException:
                    pass
                self._connection = None
                self._jetstream = None
                self._key_value = None
            self._startup_error = error
            if self._ready is not None:
                self._ready.set()
            loop.close()
            return
        if self._ready is not None:
            self._ready.set()
        try:
            loop.run_forever()
        finally:
            loop.close()

    @contextmanager
    def operation(self):
        if self._operation_depth:
            self._operation_depth += 1
            try:
                yield self
            finally:
                self._operation_depth -= 1
            return
        self._ready = threading.Event()
        self._startup_error = None
        self._thread = threading.Thread(
            target=self._thread_main,
            daemon=True,
            name="openclaw-nats-operation-loop",
        )
        self._thread.start()
        try:
            startup_deadline = (
                self.connect_timeout_seconds
                + self.request_timeout_seconds * 3
                + 0.1
            )
            if not self._ready.wait(startup_deadline):
                raise ActivationError("NATS operation loop startup timed out")
            if self._startup_error is not None:
                if isinstance(self._startup_error, ActivationError):
                    raise self._startup_error
                raise ActivationError("NATS operation loop startup failed") from self._startup_error
            self._operation_depth = 1
            yield self
        finally:
            self._operation_depth = 0
            if self._connection is not None and self._loop is not None:
                connection = self._connection
                try:
                    self._await(
                        lambda: self._cleanup_connection(connection),
                        timeout=self.request_timeout_seconds * 2 + 0.1,
                        action="drain",
                    )
                except ActivationError:
                    pass
            if self._thread is not None and self._thread.is_alive():
                if self._loop is not None and not self._loop.is_closed():
                    self._loop.call_soon_threadsafe(self._loop.stop)
                self._thread.join(
                    self.connect_timeout_seconds
                    + self.request_timeout_seconds * 3
                    + 0.1
                )
                if self._thread.is_alive():
                    raise ActivationError("NATS operation loop did not stop")
            self._loop = None
            self._connection = None
            self._jetstream = None
            self._key_value = None
            self._thread = None
            self._ready = None
            self._startup_error = None

    def key_value(self, method: str, *args: Any, **kwargs: Any) -> Any:
        if not self._operation_depth:
            with self.operation():
                return self.key_value(method, *args, **kwargs)
        if self._key_value is None:
            raise ActivationError("NATS KV is unavailable")
        return self._await(
            lambda: getattr(self._key_value, method)(*args, **kwargs),
            timeout=self.request_timeout_seconds,
            action=f"KV {method}",
        )

    def publish(self, subject: str, payload: bytes, headers: Mapping[str, str]) -> Any:
        if not self._operation_depth:
            with self.operation():
                return self.publish(subject, payload, headers)
        if self._jetstream is None:
            raise ActivationError("NATS JetStream is unavailable")
        return self._await(
            lambda: self._jetstream.publish(
                subject, payload, headers=dict(headers)
            ),
            timeout=self.request_timeout_seconds,
            action="journal publish",
        )

    @staticmethod
    def _journal_key(operation_id: str, event_id: str) -> str:
        digest = hashlib.sha256(event_id.encode("utf-8")).hexdigest()
        return f"openclaw-profiles/journal/{operation_id}/{digest}"

    def write_journal_event(
        self, event_id: str, event: Mapping[str, Any]
    ) -> None:
        operation_id = str(event.get("operation_id") or "")
        key = self._journal_key(operation_id, event_id)
        payload = json.dumps(dict(event), sort_keys=True, separators=(",", ":")).encode(
            "utf-8"
        )
        try:
            self.key_value("create", key, payload)
        except ActivationError as error:
            if not _exception_contains(error, "sequence", "exist"):
                raise
            entry = self.key_value("get", key)
            if bytes(entry.value) != payload:
                raise ActivationConflict("journal event identity collision") from error

    def read_journal_events(self, operation_id: str) -> list[Mapping[str, Any]]:
        prefix = f"openclaw-profiles/journal/{operation_id}/"
        try:
            keys = self.key_value("keys")
        except ActivationError as error:
            if _exception_contains(error, "no keys", "nokeyserror"):
                return []
            raise
        events: list[Mapping[str, Any]] = []
        for key in sorted(str(key) for key in keys if str(key).startswith(prefix)):
            entry = self.key_value("get", key)
            try:
                event = json.loads(bytes(entry.value).decode("utf-8"))
            except (TypeError, ValueError, json.JSONDecodeError) as error:
                raise ActivationError("activation journal record is invalid") from error
            if not isinstance(event, Mapping) or event.get("operation_id") != operation_id:
                raise ActivationError("activation journal record has the wrong operation")
            events.append(dict(event))
        return events


class NatsJetStreamKeyValue:
    """KV-shaped proxy used by :class:`JetStreamControlStore`."""

    def __init__(self, session: NatsJetStreamSession) -> None:
        self.session = session

    def get(self, key: str) -> Any:
        return self.session.key_value("get", key)

    def create(self, key: str, value: bytes) -> Any:
        return self.session.key_value("create", key, value)

    def update(self, key: str, value: bytes, last: int) -> Any:
        return self.session.key_value("update", key, value, last=last)

    def keys(self) -> Any:
        return self.session.key_value("keys")


def activation_from_environment(
    call_tool: Callable[[str, Mapping[str, Any]], Any],
    *,
    now: Callable[[], float] = time.time,
) -> "OpenClawProfileActivation":
    """Build the enabled service from private environment-only settings.

    Provisioning is disabled by default. The deployment operator must point to
    a pre-created credentials file, KV bucket, and journal subject; this code
    will never bootstrap any of those resources.
    """

    if os.environ.get("MEMORY_STARGRAPH_OC_PROVISION_ENABLED") != "1":
        raise ActivationError("OpenClaw provisioning is disabled")
    servers = tuple(item.strip() for item in os.environ.get("MEMORY_STARGRAPH_OC_NATS_SERVERS", "").split(",") if item.strip())
    credentials_text = os.environ.get("MEMORY_STARGRAPH_OC_NATS_CREDENTIALS_FILE", "").strip()
    bucket = os.environ.get("MEMORY_STARGRAPH_OC_NATS_KV_BUCKET", "").strip()
    journal_subject = os.environ.get("MEMORY_STARGRAPH_OC_NATS_JOURNAL_SUBJECT", "").strip()
    if not journal_subject:
        raise ActivationError("OpenClaw NATS journal subject is not configured")
    try:
        lease_seconds = int(
            os.environ.get("MEMORY_STARGRAPH_OC_LEASE_SECONDS", "120")
        )
        clock_skew_seconds = int(
            os.environ.get("MEMORY_STARGRAPH_OC_CLOCK_SKEW_SECONDS", "5")
        )
        connect_timeout_seconds = float(
            os.environ.get(
                "MEMORY_STARGRAPH_OC_NATS_CONNECT_TIMEOUT_SECONDS", "5"
            )
        )
        request_timeout_seconds = float(
            os.environ.get(
                "MEMORY_STARGRAPH_OC_NATS_REQUEST_TIMEOUT_SECONDS", "2"
            )
        )
    except ValueError as error:
        raise ActivationError("OpenClaw activation timeout configuration is invalid") from error
    session = NatsJetStreamSession(
        servers=servers,
        credentials_file=Path(credentials_text).expanduser(),
        bucket=bucket,
        connect_timeout_seconds=connect_timeout_seconds,
        request_timeout_seconds=request_timeout_seconds,
    )
    key_value = NatsJetStreamKeyValue(session)
    return OpenClawProfileActivation(
        control=JetStreamControlStore(key_value, "openclaw-profiles/control"),
        journal=JetStreamJournal(session, journal_subject),
        brain=GBrainToolBrain(call_tool),
        now=now,
        lease_seconds=lease_seconds,
        clock_skew_seconds=clock_skew_seconds,
        operations=JetStreamOperationStore(
            key_value, "openclaw-profiles/operations"
        ),
        projections=JetStreamProjectionStore(
            key_value, "openclaw-profiles/active-projection"
        ),
        operation_context=session.operation,
    )


def _digest(value: Mapping[str, Any]) -> str:
    return hashlib.sha256(
        json.dumps(value, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()


def _logical_anchor_identity(page: Mapping[str, Any]) -> dict[str, Any]:
    """Return only the immutable identity asserted by profile activation."""
    frontmatter = page.get("frontmatter")
    fields: tuple[str, ...]
    if page.get("type") == "agent":
        fields = ("runtime", "logical_anchor")
    elif page.get("type") == "collection":
        fields = ("collection_kind", "agent", "logical_anchor")
    else:
        fields = ()
    values = dict(frontmatter) if isinstance(frontmatter, Mapping) else {}
    return {
        "slug": page.get("slug"),
        "type": page.get("type"),
        "frontmatter": {field: values.get(field) for field in fields},
    }


def _edge(source: str, target: str, link_type: str, context: str) -> dict[str, str]:
    return {
        "from_slug": source,
        "to_slug": target,
        "link_type": link_type,
        "context": context,
    }


class OpenClawProfileActivation:
    """Stages profiles in GBrain and activates one generation through CAS."""

    def __init__(
        self,
        *,
        control: ControlStore,
        journal: Journal,
        brain: Brain,
        now: Callable[[], float],
        lease_seconds: int = 120,
        clock_skew_seconds: int = 5,
        operations: OperationStore | None = None,
        projections: ProjectionStore | None = None,
        session_owner_factory: Callable[[str], str] | None = None,
        operation_context: Callable[[], Any] | None = None,
    ) -> None:
        if lease_seconds < 30:
            raise ValueError("lease_seconds must be at least thirty seconds")
        if clock_skew_seconds < 0 or clock_skew_seconds > 30:
            raise ValueError("clock_skew_seconds must be between zero and thirty")
        if lease_seconds <= clock_skew_seconds * 2 + 5:
            raise ValueError("lease_seconds must exceed the clock-skew quarantine")
        self.control = control
        self.journal = journal
        self.brain = brain
        self.now = now
        self.lease_seconds = lease_seconds
        self.clock_skew_seconds = clock_skew_seconds
        self.operations: OperationStore = operations or InMemoryOperationStore()
        self.projections: ProjectionStore = (
            projections or InMemoryProjectionStore()
        )
        self.session_owner_factory = session_owner_factory or (
            lambda owner: f"{owner[:95]}-{uuid.uuid4().hex}"
        )
        self.operation_context = operation_context or nullcontext
        self._projection_lock = threading.Lock()
        self._cached_projection: dict[str, Any] | None = None
        self._startup_projection_candidate: dict[str, Any] | None = None
        self._pending_projection_invalidation: dict[str, Any] | None = None
        self._lifecycle_lock = threading.Lock()
        self._lifecycle_context: Any | None = None

    def start(self) -> "OpenClawProfileActivation":
        """Enter the process context without trusting a durable ready record."""
        with self._lifecycle_lock:
            if self._lifecycle_context is not None:
                return self
            with self._projection_lock:
                self._cached_projection = None
                self._startup_projection_candidate = None
            context = self.operation_context()
            context.__enter__()
            try:
                _revision, cached = self.projections.read()
                if cached is not None:
                    cached = self._validated_projection_record(cached)
                    with self._projection_lock:
                        self._startup_projection_candidate = (
                            copy.deepcopy(cached)
                            if cached["status"] == "ready"
                            else None
                        )
            except BaseException:
                context.__exit__(*sys.exc_info())
                raise
            self._lifecycle_context = context
        return self

    def close(self) -> None:
        """Drain the process-long operation context exactly once."""
        with self._lifecycle_lock:
            context = self._lifecycle_context
            self._lifecycle_context = None
        if context is not None:
            context.__exit__(None, None, None)

    def _journal(
        self,
        *,
        operation_id: str,
        fence_generation: int,
        step: str,
        resource: str,
        phase: str,
        **details: Any,
    ) -> None:
        self.journal.append(
            {
                "event": f"{step}_{phase}",
                "operation_id": operation_id,
                "fence_generation": fence_generation,
                "step": step,
                "resource": resource,
                "phase": phase,
                **details,
            }
        )

    @staticmethod
    def _journal_phases(
        events: Sequence[Mapping[str, Any]], fence_generation: int
    ) -> set[tuple[str, str, str]]:
        return {
            (str(event.get("step")), str(event.get("resource")), str(event.get("phase")))
            for event in events
            if event.get("fence_generation") == fence_generation
            and event.get("phase") in {"before", "after"}
        }

    def _close_verified_journal_after(
        self,
        *,
        phases: set[tuple[str, str, str]],
        operation_id: str,
        fence_generation: int,
        step: str,
        resource: str,
    ) -> None:
        if (
            (step, resource, "before") in phases
            and (step, resource, "after") not in phases
        ):
            self._journal(
                operation_id=operation_id,
                fence_generation=fence_generation,
                step=step,
                resource=resource,
                phase="after",
            )
            phases.add((step, resource, "after"))

    def _reconcile_activation_audit(
        self, operation_id: str, fence_generation: int
    ) -> None:
        phases = self._journal_phases(
            self.journal.read(operation_id), fence_generation
        )
        self._close_verified_journal_after(
            phases=phases,
            operation_id=operation_id,
            fence_generation=fence_generation,
            step="activate",
            resource="control",
        )

    def _reconcile_verified_journal(
        self,
        *,
        operation_id: str,
        fence_generation: int,
        events: Sequence[Mapping[str, Any]],
    ) -> set[tuple[str, str, str]]:
        phases = self._journal_phases(events, fence_generation)
        verified_steps = {
            "lease",
            "lease_recovery",
            "lease_renewal",
            "anchor_page",
            "anchor_link",
            "generation_page",
            "generation_link",
            "manifest",
            "activate",
        }
        for step, resource, phase in tuple(phases):
            if phase == "before" and step in verified_steps:
                self._close_verified_journal_after(
                    phases=phases,
                    operation_id=operation_id,
                    fence_generation=fence_generation,
                    step=step,
                    resource=resource,
                )
        return phases

    @staticmethod
    def _recovery_pending(record: Mapping[str, Any]) -> bool:
        recovery_requested = record.get("recovery_requested", False)
        requested_generation = record.get("recovery_request_generation", 0)
        processed_generation = record.get("recovery_processed_generation", 0)
        if (
            not isinstance(recovery_requested, bool)
        ):
            raise ActivationError("activation recovery request flag is invalid")
        if (
            isinstance(requested_generation, bool)
            or not isinstance(requested_generation, int)
            or requested_generation < 0
            or isinstance(processed_generation, bool)
            or not isinstance(processed_generation, int)
            or processed_generation < 0
            or processed_generation > requested_generation
        ):
            raise ActivationError("activation recovery generation is invalid")
        return recovery_requested and (
            requested_generation > processed_generation
        )

    @staticmethod
    def _operation_view(record: Mapping[str, Any]) -> dict[str, Any]:
        recovery_pending = OpenClawProfileActivation._recovery_pending(record)
        recovery_request_generation = int(
            record.get("recovery_request_generation", 0)
        )
        recovery_processed_generation = int(
            record.get("recovery_processed_generation", 0)
        )
        recovery_fields = {
            "recovery_request_generation": recovery_request_generation,
            "recovery_processed_generation": recovery_processed_generation,
        }
        if recovery_pending:
            return {
                "operation_id": record["operation_id"],
                "status": "recovery_required",
                "fence_generation": record.get("fence_generation"),
                "receipt": None,
                "error": record.get("recovery_error")
                or "durable terminal recovery is queued",
                **recovery_fields,
            }
        return {
            "operation_id": record["operation_id"],
            "status": record["status"],
            "fence_generation": record.get("fence_generation"),
            "receipt": copy.deepcopy(record.get("receipt")),
            "error": record.get("error"),
            **recovery_fields,
        }

    def _validated_terminal_receipt(
        self, receipt: Mapping[str, Any], operation_id: str
    ) -> dict[str, Any]:
        item = dict(receipt)
        generation = item.get("generation")
        if (
            set(item) != RECEIPT_FIELDS
            or isinstance(generation, bool)
            or not isinstance(generation, int)
            or generation < 1
            or item.get("manifest_slug")
            != self._manifest_slug(generation, operation_id)
            or not isinstance(item.get("manifest_digest"), str)
            or SHA256_PATTERN.fullmatch(item["manifest_digest"]) is None
            or isinstance(item.get("default_goal_link_count"), bool)
            or not isinstance(item.get("default_goal_link_count"), int)
            or item.get("default_goal_link_count") != 0
        ):
            raise ActivationContentConflict("activation terminal receipt is invalid")
        return item

    def _verify_completed_receipt(
        self, receipt: Mapping[str, Any], operation_id: str
    ) -> dict[str, Any]:
        item = self._validated_terminal_receipt(receipt, operation_id)
        projection = self.active_projection()
        if (
            projection.get("generation") != item["generation"]
            or projection.get("active_manifest") != item["manifest_slug"]
            or projection.get("manifest_digest") != item["manifest_digest"]
        ):
            raise ActivationContentConflict(
                "completed receipt did not match the exact active projection"
            )
        return item

    def _verify_completed_receipt_graph(
        self, receipt: Mapping[str, Any], operation_id: str
    ) -> dict[str, Any]:
        item = self._validated_terminal_receipt(receipt, operation_id)
        manifest = self.brain.get_page(str(item["manifest_slug"]))
        if not isinstance(manifest, Mapping):
            raise ActivationContentConflict("completed activation manifest is missing")
        if _digest(manifest) != item["manifest_digest"]:
            raise ActivationContentConflict(
                "completed activation manifest digest is invalid"
            )
        self._verify_active_manifest(
            manifest,
            {
                "active_manifest": item["manifest_slug"],
                "active_generation": item["generation"],
            },
        )
        return item

    def _completion_attestation(
        self, receipt: Mapping[str, Any], operation_id: str
    ) -> dict[str, Any]:
        item = self._validated_terminal_receipt(receipt, operation_id)
        return {
            "receipt": item,
            "receipt_version": RECEIPT_VERSION,
            "receipt_digest": _digest(item),
            "error": None,
        }

    def _validated_terminal_operation(
        self, record: Mapping[str, Any]
    ) -> dict[str, Any]:
        item = dict(record)
        status = item.get("status")
        operation_id = item.get("operation_id")
        fence_generation = item.get("fence_generation")
        if (
            not isinstance(operation_id, str)
            or re.fullmatch(
                r"[A-Za-z0-9][A-Za-z0-9._-]{0,127}", operation_id
            )
            is None
            or (
                fence_generation is not None
                and (
                    isinstance(fence_generation, bool)
                    or not isinstance(fence_generation, int)
                    or fence_generation < 1
                )
            )
        ):
            raise ActivationError(f"{status or 'terminal'} activation operation is invalid")
        if status == "completed":
            if (
                item.get("error") is not None
                or not isinstance(item.get("receipt"), Mapping)
                or type(item.get("receipt_version")) is not int
                or item.get("receipt_version") != RECEIPT_VERSION
                or not isinstance(item.get("receipt_digest"), str)
                or SHA256_PATTERN.fullmatch(item["receipt_digest"]) is None
            ):
                raise ActivationError("completed activation operation is invalid")
            receipt = self._validated_terminal_receipt(item["receipt"], operation_id)
            if fence_generation != receipt["generation"]:
                raise ActivationError("completed activation operation fence is invalid")
            if item["receipt_digest"] != _digest(receipt):
                raise ActivationError(
                    "completed activation operation receipt digest is invalid"
                )
            item["receipt"] = receipt
            return item
        if status == "failed":
            if (
                item.get("receipt") is not None
                or item.get("receipt_version") is not None
                or item.get("receipt_digest") is not None
                or not isinstance(item.get("error"), str)
                or not item["error"]
            ):
                raise ActivationError("failed activation operation is invalid")
            return item
        raise ActivationError("activation operation is not terminal")

    def _transition_operation(
        self,
        operation_id: str,
        *,
        expected_statuses: set[str],
        status: str,
        expected_fence: int | None = None,
        **changes: Any,
    ) -> tuple[dict[str, Any], bool]:
        for _attempt in range(3):
            revision, record = self.operations.read(operation_id)
            if record is None:
                raise ActivationError(f"unknown activation operation: {operation_id}")
            current_status = str(record.get("status") or "")
            if current_status in {"completed", "failed"}:
                return self._validated_terminal_operation(record), False
            if current_status not in expected_statuses:
                return dict(record), False
            if (
                expected_fence is not None
                and record.get("fence_generation") not in {None, expected_fence}
            ):
                raise ActivationConflict("activation operation fence changed")
            updated = dict(record)
            updated.update(changes)
            updated["status"] = status
            updated["updated_at"] = self.now()
            if status in {"completed", "failed"}:
                if self._recovery_pending(record):
                    request_generation = int(
                        record.get("recovery_request_generation", 0) or 0
                    )
                    recovery_evidence = {
                        "operation_id": operation_id,
                        "request_generation": request_generation,
                        "status": status,
                        "receipt_digest": updated.get("receipt_digest"),
                        "error": updated.get("error"),
                    }
                    updated.update(
                        {
                            "recovery_requested": False,
                            "recovery_processed_generation": request_generation,
                            "recovery_verified_at": float(self.now()),
                            "recovery_verification_digest": _digest(
                                recovery_evidence
                            ),
                            "recovery_result": status,
                            "recovery_error": updated.get("error"),
                        }
                    )
                updated = self._validated_terminal_operation(updated)
            try:
                self.operations.compare_and_set(operation_id, revision, updated)
            except ActivationConflict:
                continue
            return updated, True
        raise ActivationConflict("activation operation changed during transition")

    def _finalize_control_completion(
        self, control: Mapping[str, Any]
    ) -> dict[str, Any] | None:
        operation_id = control.get("completed_operation_id")
        receipt_value = control.get("completed_receipt")
        if not isinstance(operation_id, str) or not isinstance(
            receipt_value, Mapping
        ):
            return None
        receipt = self._validated_terminal_receipt(receipt_value, operation_id)
        receipt = self._verify_completed_receipt(receipt, operation_id)
        self._reconcile_activation_audit(
            operation_id, int(receipt["generation"])
        )
        finalized, _changed = self._transition_operation(
            operation_id,
            expected_statuses={"accepted", "running", "recovery_required"},
            status="completed",
            expected_fence=receipt["generation"],
            fence_generation=receipt["generation"],
            **self._completion_attestation(receipt, operation_id),
        )
        if (
            finalized.get("status") != "completed"
            or finalized.get("receipt") != receipt
        ):
            raise ActivationConflict(
                "control completion conflicts with the operation terminal state"
            )
        return finalized

    def _update_operation(self, operation_id: str, **changes: Any) -> dict[str, Any]:
        status = str(changes.pop("status"))
        updated, _changed = self._transition_operation(
            operation_id,
            expected_statuses={"accepted", "running", "recovery_required"},
            status=status,
            **changes,
        )
        if updated.get("status") in {"completed", "failed"}:
            return self._validated_terminal_operation(updated)
        return updated

    def submit(
        self,
        declarations: Sequence[Mapping[str, str]],
        *,
        owner: str,
        operation_id: str,
    ) -> dict[str, Any]:
        with self.operation_context():
            return self._submit(
                declarations, owner=owner, operation_id=operation_id
            )

    def _submit(
        self,
        declarations: Sequence[Mapping[str, str]],
        *,
        owner: str,
        operation_id: str,
    ) -> dict[str, Any]:
        items = self._validate_declarations(declarations)
        if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]{0,127}", owner or ""):
            raise ActivationError("owner is invalid")
        if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]{0,127}", operation_id or ""):
            raise ActivationError("operation_id is invalid")
        declarations_digest = _digest({"declarations": list(items)})
        _revision, existing = self.operations.read(operation_id)
        if existing is not None:
            if (
                existing.get("owner") != owner
                or existing.get("declarations_digest") != declarations_digest
            ):
                raise ActivationConflict("operation_id already identifies another request")
            if existing.get("status") in {"completed", "failed"}:
                existing = self._validated_terminal_operation(existing)
            return self._operation_view(existing)
        now = self.now()
        record = {
            "schema_version": 1,
            "operation_id": operation_id,
            "owner": owner,
            "declarations": [dict(item) for item in items],
            "declarations_digest": declarations_digest,
            "status": "accepted",
            "fence_generation": None,
            "receipt": None,
            "receipt_version": None,
            "receipt_digest": None,
            "error": None,
            "recovery_requested": False,
            "recovery_request_generation": 0,
            "recovery_processed_generation": 0,
            "recovery_requested_at": None,
            "recovery_verified_at": None,
            "recovery_verification_digest": None,
            "recovery_result": None,
            "recovery_error": None,
            "created_at": now,
            "updated_at": now,
        }
        try:
            self.operations.create(operation_id, record)
        except ActivationConflict:
            _revision, raced = self.operations.read(operation_id)
            if raced is None:
                raise
            if (
                raced.get("owner") != owner
                or raced.get("declarations_digest") != declarations_digest
            ):
                raise ActivationConflict("operation_id already identifies another request")
            if raced.get("status") in {"completed", "failed"}:
                raced = self._validated_terminal_operation(raced)
            record = raced
        return self._operation_view(record)

    def status(self, operation_id: str) -> dict[str, Any]:
        with self.operation_context():
            _revision, record = self.operations.read(operation_id)
            if record is None:
                raise ActivationError(f"unknown activation operation: {operation_id}")
            if record.get("status") in {"completed", "failed"}:
                return self._operation_view(
                    self._validated_terminal_operation(record)
                )
            if record.get("status") not in {
                "accepted",
                "running",
                "recovery_required",
            }:
                raise ActivationError("activation operation status is invalid")
            return self._operation_view(record)

    def run(self, operation_id: str) -> dict[str, Any]:
        with self.operation_context():
            return self._run(operation_id, recovering=False)

    def pending_operation_ids(self) -> list[str]:
        with self.operation_context():
            records = self.operations.list_records(
                {
                    "accepted",
                    "running",
                    "recovery_required",
                    "completed",
                    "failed",
                }
            )
        operation_ids = [
            str(record.get("operation_id") or "")
            for record in records
            if record.get("status")
            in {"accepted", "running", "recovery_required"}
            or self._recovery_pending(record)
        ]
        if any(
            re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]{0,127}", operation_id)
            is None
            for operation_id in operation_ids
        ):
            raise ActivationError("activation operation listing is invalid")
        return sorted(operation_ids)

    def adopt(self, operation_id: str) -> dict[str, Any]:
        with self.operation_context():
            _revision, record = self.operations.read(operation_id)
            if record is None:
                raise ActivationError(f"unknown activation operation: {operation_id}")
            if record.get("status") in {"completed", "failed"}:
                if self._recovery_pending(record):
                    return self._recover(operation_id)
                return self._operation_view(
                    self._validated_terminal_operation(record)
                )
            if record.get("status") == "accepted":
                _control_revision, control = self.control.read()
                if (
                    control.get("state") == "leased"
                    and control.get("operation_id") == operation_id
                ):
                    fence = int(
                        control.get(
                            "fence_generation", control.get("generation", 0)
                        )
                        or 0
                    )
                    if (
                        float(control.get("lease_expires_at") or 0)
                        - self.clock_skew_seconds
                        > self.now()
                    ):
                        return self._operation_view(record)
                    adopted, changed = self._transition_operation(
                        operation_id,
                        expected_statuses={"accepted"},
                        status="recovery_required",
                        fence_generation=fence,
                        receipt=None,
                        error=(
                            "accepted activation claim expired before running; "
                            "durable recovery adopted it"
                        ),
                    )
                    if not changed:
                        return self._operation_view(adopted)
                    return self._recover(operation_id)
                return self._run(operation_id, recovering=False)
            if record.get("status") == "recovery_required":
                return self._recover(operation_id)
            if record.get("status") != "running":
                raise ActivationError("activation operation status is invalid")
            _control_revision, control = self.control.read()
            valid_lease = (
                control.get("state") == "leased"
                and control.get("operation_id") == operation_id
                and int(
                    control.get("fence_generation", control.get("generation", 0))
                    or 0
                )
                == int(record.get("fence_generation") or 0)
                and float(control.get("lease_expires_at") or 0)
                - self.clock_skew_seconds
                > self.now()
            )
            if valid_lease:
                return self._operation_view(record)
            adopted, _changed = self._transition_operation(
                operation_id,
                expected_statuses={"running"},
                status="recovery_required",
                expected_fence=(
                    int(record["fence_generation"])
                    if record.get("fence_generation") is not None
                    else None
                ),
                fence_generation=(
                    record.get("fence_generation")
                    or control.get("fence_generation")
                    or control.get("generation")
                ),
                receipt=None,
                error="activation execution has no valid lease; durable recovery adopted it",
            )
            if adopted.get("status") in {"completed", "failed"}:
                return self._operation_view(adopted)
            return self._recover(operation_id)

    def _run(self, operation_id: str, *, recovering: bool) -> dict[str, Any]:
        _revision, record = self.operations.read(operation_id)
        if record is None:
            raise ActivationError(f"unknown activation operation: {operation_id}")
        if record.get("status") in {"completed", "failed"}:
            return self._operation_view(
                self._validated_terminal_operation(record)
            )
        if record.get("status") == "running" and not recovering:
            return self._operation_view(record)
        if record.get("status") not in {"accepted", "recovery_required", "running"}:
            raise ActivationError("activation operation status is invalid")
        running = record
        session_owner: str | None = None
        try:
            if self.brain.get_page(ARTIFACTS_ROOT) is None:
                raise ActivationContentConflict("global Artifact root is missing")
            session_owner = self.session_owner_factory(str(running["owner"]))
            if not re.fullmatch(
                r"[A-Za-z0-9][A-Za-z0-9._-]{0,127}", session_owner or ""
            ):
                raise ActivationContentConflict("session owner is invalid")
            receipt = self._provision_operation(
                running["declarations"],
                owner=session_owner,
                operation_id=operation_id,
                expected_fence=(
                    int(running["fence_generation"])
                    if running.get("fence_generation") is not None
                    else None
                ),
                recovering=recovering or record.get("status") == "recovery_required",
            )
            receipt = self._verify_completed_receipt(receipt, operation_id)
        except Exception as error:
            _control_revision, control = self.control.read()
            claimed = int(control.get("fence_generation", control.get("generation", 0)) or 0)
            belongs_to_operation = (
                control.get("operation_id") == operation_id
                or control.get("completed_operation_id") == operation_id
            )
            if (
                isinstance(error, ActivationLeaseHeld)
                and control.get("state") == "leased"
                and control.get("operation_id") == operation_id
                and control.get("lease_owner") != session_owner
                and float(control.get("lease_expires_at") or 0)
                - self.clock_skew_seconds
                > self.now()
            ):
                _latest_revision, latest_operation = self.operations.read(
                    operation_id
                )
                if latest_operation is None:
                    raise ActivationError(
                        f"unknown activation operation: {operation_id}"
                    )
                return self._operation_view(latest_operation)
            status = (
                "failed"
                if _is_deterministic_activation_failure(error)
                else "recovery_required"
                if (
                    claimed and belongs_to_operation
                    or running.get("fence_generation") is not None
                    or running.get("status") in {"running", "recovery_required"}
                )
                else "accepted"
            )
            updated = self._update_operation(
                operation_id,
                status=status,
                fence_generation=claimed if belongs_to_operation else running.get("fence_generation"),
                receipt=None,
                receipt_version=None,
                receipt_digest=None,
                error=str(error),
            )
            return self._operation_view(updated)
        completed = self._update_operation(
            operation_id,
            status="completed",
            fence_generation=int(receipt["generation"]),
            **self._completion_attestation(receipt, operation_id),
        )
        return self._operation_view(completed)

    @staticmethod
    def _validate_declarations(
        declarations: Sequence[Mapping[str, str]],
    ) -> tuple[dict[str, str], ...]:
        required = {
            "slug",
            "name",
            "runtime",
            "route",
            "task_collection",
            "artifact_collection",
        }
        if not isinstance(declarations, Sequence) or isinstance(declarations, (str, bytes)):
            raise ActivationContentConflict("OpenClaw declarations must be a list")
        if any(not isinstance(item, Mapping) for item in declarations):
            raise ActivationContentConflict("OpenClaw declarations must be objects")
        if any(any(not isinstance(key, str) or not isinstance(value, str) for key, value in item.items()) for item in declarations):
            raise ActivationContentConflict("OpenClaw declaration fields must be strings")
        items = tuple(dict(item) for item in declarations)
        if len(items) != 3 or any(set(item) != required for item in items):
            raise ActivationContentConflict("exactly three complete OpenClaw declarations are required")
        if any(not value.strip() for item in items for value in item.values()):
            raise ActivationContentConflict("OpenClaw declarations must not contain empty values")
        if {item["runtime"] for item in items} != {"openclaw"}:
            raise ActivationContentConflict("all declarations must use the openclaw runtime")
        if {item["slug"] for item in items} != set(APPROVED_DECLARATIONS):
            raise ActivationContentConflict("OpenClaw declarations must be the three approved Agents")
        for item in items:
            name, route, task_collection, artifact_collection = APPROVED_DECLARATIONS[item["slug"]]
            if (item["name"], item["route"], item["task_collection"], item["artifact_collection"]) != (name, route, task_collection, artifact_collection):
                raise ActivationContentConflict("OpenClaw declaration does not match the approved contract")
        return tuple(sorted(items, key=lambda item: item["slug"]))

    def _claim(
        self,
        *,
        owner: str,
        operation_id: str,
        expected_fence: int | None = None,
        recovering: bool = False,
    ) -> tuple[int, int, dict[str, Any]]:
        if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]{0,127}", owner or ""):
            raise ActivationError("owner is invalid")
        if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]{0,127}", operation_id or ""):
            raise ActivationError("operation_id is invalid")
        revision, prior = self.control.read()
        self._finalize_control_completion(prior)
        revision, prior = self.control.read()
        lease_check_now = self.now()
        if prior.get("completed_operation_id") == operation_id and isinstance(prior.get("completed_receipt"), Mapping):
            return int(prior["fence_generation"]), revision, dict(prior)
        prior_fence = int(
            prior.get("fence_generation", prior.get("generation", 0)) or 0
        )
        if expected_fence is not None:
            if prior_fence != expected_fence or prior.get("operation_id") != operation_id:
                raise ActivationConflict("activation operation was fenced by another holder")
            if not recovering and float(prior.get("lease_expires_at") or 0) + self.clock_skew_seconds > lease_check_now:
                raise ActivationLeaseHeld("OpenClaw provisioning is already leased; each request needs a unique owner/session")
            generation = expected_fence
            step = "lease_recovery"
        else:
            if (
                prior.get("state") == "leased"
                and float(prior.get("lease_expires_at") or 0)
                + self.clock_skew_seconds
                > lease_check_now
            ):
                raise ActivationLeaseHeld("OpenClaw provisioning is already leased; each request needs a unique owner/session")
            generation = prior_fence + 1
            step = "lease"
        claimed = {
            "state": "leased",
            "fence_generation": generation,
            "generation": generation,
            "active_generation": int(prior.get("active_generation") or 0),
            "active_manifest": prior.get("active_manifest"),
            "active_manifest_digest": prior.get("active_manifest_digest"),
            "lease_owner": owner,
            "operation_id": operation_id,
            "lease_expires_at": 0,
            "completed_operation_id": prior.get("completed_operation_id"),
            "completed_receipt": prior.get("completed_receipt"),
        }
        self._journal(
            operation_id=operation_id,
            fence_generation=generation,
            step=step,
            resource="control",
            phase="before",
        )
        claim_now = self.now()
        if expected_fence is not None:
            if (
                not recovering
                and float(prior.get("lease_expires_at") or 0)
                + self.clock_skew_seconds
                > claim_now
            ):
                raise ActivationLeaseHeld("OpenClaw provisioning is already leased; each request needs a unique owner/session")
        elif (
            prior.get("state") == "leased"
            and float(prior.get("lease_expires_at") or 0)
            + self.clock_skew_seconds
            > claim_now
        ):
            raise ActivationLeaseHeld("OpenClaw provisioning is already leased; each request needs a unique owner/session")
        claimed["lease_expires_at"] = claim_now + self.lease_seconds
        claimed_revision = self.control.compare_and_set(revision, claimed)
        self._journal(
            operation_id=operation_id,
            fence_generation=generation,
            step=step,
            resource="control",
            phase="after",
        )
        return generation, claimed_revision, claimed

    def _renew(
        self,
        *,
        owner: str,
        operation_id: str,
        fence_generation: int,
        checkpoint: str,
    ) -> tuple[int, dict[str, Any]]:
        revision, current = self.control.read()
        if (
            current.get("state") != "leased"
            or current.get("operation_id") != operation_id
            or current.get("lease_owner") != owner
            or int(current.get("fence_generation", current.get("generation", 0)) or 0)
            != fence_generation
            or float(current.get("lease_expires_at") or 0)
            - self.clock_skew_seconds
            <= self.now()
        ):
            raise ActivationConflict("lease was lost before renewal checkpoint")
        renewed = dict(current)
        renewed["lease_expires_at"] = self.now() + self.lease_seconds
        resource = f"control-{checkpoint}"
        self._journal(
            operation_id=operation_id,
            fence_generation=fence_generation,
            step="lease_renewal",
            resource=resource,
            phase="before",
        )
        renewed_revision = self.control.compare_and_set(revision, renewed)
        self._journal(
            operation_id=operation_id,
            fence_generation=fence_generation,
            step="lease_renewal",
            resource=resource,
            phase="after",
        )
        return renewed_revision, renewed

    @staticmethod
    def _staged_slug(generation: int, operation_id: str, canonical: str) -> str:
        return f"{STAGING_PREFIX}/g{generation:06d}-{operation_id}/staged/{canonical}"

    @staticmethod
    def _manifest_slug(generation: int, operation_id: str) -> str:
        return f"{MANIFEST_PREFIX}/g{generation:06d}-{operation_id}"

    def _page_specs(
        self, declarations: Sequence[Mapping[str, str]], generation: int, operation_id: str
    ) -> tuple[list[dict[str, Any]], list[dict[str, str]], list[dict[str, Any]]]:
        pages: list[dict[str, Any]] = []
        edges: list[dict[str, str]] = []
        profiles: list[dict[str, Any]] = []
        for declaration in declarations:
            agent = self._staged_slug(generation, operation_id, declaration["slug"])
            tasks = self._staged_slug(generation, operation_id, declaration["task_collection"])
            artifacts = self._staged_slug(generation, operation_id, declaration["artifact_collection"])
            agent_page = {
                "slug": agent,
                "type": "agent",
                "title": declaration["name"],
                "frontmatter": {
                    "runtime": declaration["runtime"],
                    "route": declaration["route"],
                    "activation_generation": generation,
                    "activation_operation_id": operation_id,
                    "canonical_slug": declaration["slug"],
                    "staged": True,
                },
                "compiled_truth": f"Staged OpenClaw profile for {declaration['name']}.",
            }
            task_page = {
                "slug": tasks,
                "type": "collection",
                "title": f"{declaration['name']} Tasks",
                "frontmatter": {
                    "collection_kind": "mission_control_agent_tasks",
                    "activation_generation": generation,
                    "activation_operation_id": operation_id,
                    "canonical_slug": declaration["task_collection"],
                    "staged": True,
                },
                "compiled_truth": f"Staged task collection for {declaration['name']}.",
            }
            artifact_page = {
                "slug": artifacts,
                "type": "collection",
                "title": f"{declaration['name']} Artifacts",
                "frontmatter": {
                    "collection_kind": "mission_control_artifacts",
                    "activation_generation": generation,
                    "activation_operation_id": operation_id,
                    "canonical_slug": declaration["artifact_collection"],
                    "staged": True,
                },
                "compiled_truth": f"Staged Artifact collection for {declaration['name']}.",
            }
            pages.extend((agent_page, task_page, artifact_page))
            edges.extend(
                (
                    _edge(tasks, agent, "for_agent", "This collection stores canonical work for this Agent."),
                    _edge(artifacts, ARTIFACTS_ROOT, "part_of", "This Agent Artifact collection belongs to Mission Control Artifacts."),
                    _edge(artifacts, agent, "for_agent", "This collection stores durable output from this Agent."),
                )
            )
            profiles.append(
                {
                    "canonical_agent_slug": declaration["slug"],
                    "canonical_task_collection": declaration["task_collection"],
                    "canonical_artifact_collection": declaration["artifact_collection"],
                    "staged_agent_slug": agent,
                    "staged_task_collection": tasks,
                    "staged_artifact_collection": artifacts,
                    "metadata": copy.deepcopy(agent_page),
                    "page_hashes": {
                        agent: _digest(agent_page),
                        tasks: _digest(task_page),
                        artifacts: _digest(artifact_page),
                    },
                }
            )
        return pages, edges, profiles

    @staticmethod
    def _anchor_specs(declarations: Sequence[Mapping[str, str]]) -> tuple[list[dict[str, Any]], list[dict[str, str]]]:
        pages: list[dict[str, Any]] = []
        edges: list[dict[str, str]] = []
        for item in declarations:
            agent, tasks, artifacts = item["slug"], item["task_collection"], item["artifact_collection"]
            pages.extend((
                {"slug": agent, "type": "agent", "title": item["name"], "frontmatter": {"runtime": "openclaw", "logical_anchor": True}, "compiled_truth": "OpenClaw logical identity anchor."},
                {"slug": tasks, "type": "collection", "title": f"{item['name']} Tasks", "frontmatter": {"collection_kind": "mission_control_agent_tasks", "agent": agent, "logical_anchor": True}, "compiled_truth": "OpenClaw logical task collection anchor."},
                {"slug": artifacts, "type": "collection", "title": f"{item['name']} Artifacts", "frontmatter": {"collection_kind": "mission_control_artifacts", "agent": agent, "logical_anchor": True}, "compiled_truth": "OpenClaw logical Artifact collection anchor."},
            ))
            edges.extend((_edge(tasks, agent, "for_agent", "Logical OpenClaw task scope."), _edge(artifacts, ARTIFACTS_ROOT, "part_of", "Logical OpenClaw Artifact scope."), _edge(artifacts, agent, "for_agent", "Logical OpenClaw Artifact owner.")))
        return pages, edges

    @staticmethod
    def _verify_anchor_links(
        page: Mapping[str, Any],
        actual_links: Sequence[Mapping[str, Any]],
        expected_links: Sequence[Mapping[str, str]],
    ) -> None:
        slug = str(page["slug"])
        normalized: list[dict[str, Any]] = []
        for raw_edge in actual_links:
            edge = dict(raw_edge)
            if set(edge) != LINK_FIELDS or not all(
                isinstance(value, str) for value in edge.values()
            ):
                raise ActivationContentConflict(
                    f"logical anchor relationship is malformed: {slug}"
                )
            normalized.append(edge)
        invariant = [
            edge
            for edge in normalized
            if edge["link_type"] in {"for_agent", "part_of"}
        ]
        if sorted(invariant, key=_digest) != sorted(
            [dict(edge) for edge in expected_links], key=_digest
        ):
            raise ActivationContentConflict(
                f"logical anchor invariant links did not read back exactly: {slug}"
            )
        mutable = [edge for edge in normalized if edge not in invariant]
        if any(
            page.get("type") != "agent"
            or edge["from_slug"] != slug
            or edge["link_type"] != "default_agent_for"
            or not edge["to_slug"].startswith("goals/")
            for edge in mutable
        ):
            raise ActivationContentConflict(
                f"logical anchor has an undeclared relationship: {slug}"
            )

    def _ensure_anchors(
        self,
        pages: Sequence[Mapping[str, Any]],
        edges: Sequence[Mapping[str, str]],
        *,
        operation_id: str,
        fence_generation: int,
        owner: str,
        journal_phases: set[tuple[str, str, str]],
    ) -> None:
        by_source: dict[str, list[Mapping[str, str]]] = {}
        for edge in edges:
            by_source.setdefault(edge["from_slug"], []).append(edge)
        for page in pages:
            slug = str(page["slug"])
            existing = self.brain.get_page(slug)
            if existing is None:
                self._renew(
                    owner=owner,
                    operation_id=operation_id,
                    fence_generation=fence_generation,
                    checkpoint=f"before-anchor-page-{_digest({'slug': slug})[:16]}",
                )
                self._journal(operation_id=operation_id, fence_generation=fence_generation, step="anchor_page", resource=slug, phase="before")
                self.brain.put_page(slug, page)
                self._journal(operation_id=operation_id, fence_generation=fence_generation, step="anchor_page", resource=slug, phase="after")
            elif _logical_anchor_identity(existing) != _logical_anchor_identity(page):
                raise ActivationContentConflict(
                    f"logical anchor already exists with different content: {slug}"
                )
            else:
                self._close_verified_journal_after(
                    phases=journal_phases,
                    operation_id=operation_id,
                    fence_generation=fence_generation,
                    step="anchor_page",
                    resource=slug,
                )
            actual = self.brain.get_links(slug)
            for edge in by_source.get(slug, []):
                if not any(all(item.get(key) == edge[key] for key in ("from_slug", "to_slug", "link_type", "context")) for item in actual):
                    resource = _digest(edge)
                    self._renew(
                        owner=owner,
                        operation_id=operation_id,
                        fence_generation=fence_generation,
                        checkpoint=f"before-anchor-link-{resource[:16]}",
                    )
                    self._journal(operation_id=operation_id, fence_generation=fence_generation, step="anchor_link", resource=resource, phase="before")
                    self.brain.add_link(edge["from_slug"], edge["to_slug"], edge["link_type"], edge["context"])
                    self._journal(operation_id=operation_id, fence_generation=fence_generation, step="anchor_link", resource=resource, phase="after")
                else:
                    self._close_verified_journal_after(
                        phases=journal_phases,
                        operation_id=operation_id,
                        fence_generation=fence_generation,
                        step="anchor_link",
                        resource=_digest(edge),
                    )
            stored_page = self.brain.get_page(slug)
            if not isinstance(stored_page, Mapping) or _logical_anchor_identity(
                stored_page
            ) != _logical_anchor_identity(page):
                raise ActivationContentConflict(
                    f"logical anchor identity did not read back exactly: {slug}"
                )
            expected = [dict(edge) for edge in by_source.get(slug, [])]
            self._verify_anchor_links(
                page,
                self.brain.get_links(slug),
                expected,
            )

    def _release_failed(self, claimed_revision: int, claimed: Mapping[str, Any], error: Exception) -> None:
        operation_id = str(claimed.get("operation_id") or "unknown")
        fence_generation = int(
            claimed.get("fence_generation", claimed.get("generation", 0)) or 0
        )
        resource = "failure-" + _digest(
            {"error": str(error), "claimed_control_revision": claimed_revision}
        )
        self._journal(
            operation_id=operation_id,
            fence_generation=fence_generation,
            step="operation_failure",
            resource=resource,
            phase="event",
            claimed_control_revision=claimed_revision,
            error=str(error),
            event="staging_failed",
        )

    def _verify(self, pages: Sequence[Mapping[str, Any]], edges: Sequence[Mapping[str, str]]) -> None:
        expected_by_source: dict[str, list[dict[str, str]]] = {}
        for edge in edges:
            expected_by_source.setdefault(edge["from_slug"], []).append(dict(edge))
        for page in pages:
            slug = str(page["slug"])
            stored_page = self.brain.get_page(slug)
            frontmatter = page.get("frontmatter")
            if isinstance(frontmatter, Mapping) and frontmatter.get("logical_anchor") is True:
                if not isinstance(stored_page, Mapping) or _logical_anchor_identity(
                    stored_page
                ) != _logical_anchor_identity(page):
                    raise ActivationContentConflict(
                        f"logical anchor identity did not read back exactly: {slug}"
                    )
                self._verify_anchor_links(
                    page,
                    self.brain.get_links(slug),
                    expected_by_source.get(slug, []),
                )
                continue
            if stored_page != page:
                raise ActivationContentConflict(
                    f"staged page did not read back exactly: {slug}"
                )
            actual = self.brain.get_links(slug)
            if any(edge.get("link_type") == "default_agent_for" for edge in actual):
                raise ActivationContentConflict(
                    f"default_agent_for relationship is forbidden: {slug}"
                )
            normalized = [dict(edge) for edge in actual]
            if sorted(normalized, key=lambda edge: json.dumps(edge, sort_keys=True)) != sorted(
                expected_by_source.get(slug, []), key=lambda edge: json.dumps(edge, sort_keys=True)
            ):
                raise ActivationContentConflict(
                    f"staged links did not read back exactly: {slug}"
                )

    def _provision_operation(
        self,
        declarations: Sequence[Mapping[str, str]],
        *,
        owner: str,
        operation_id: str,
        expected_fence: int | None = None,
        recovering: bool = False,
    ) -> dict[str, Any]:
        items = self._validate_declarations(declarations)
        _prior_revision, prior = self.control.read()
        if prior.get("completed_operation_id") == operation_id and isinstance(prior.get("completed_receipt"), Mapping):
            return self._validated_terminal_receipt(
                prior["completed_receipt"], operation_id
            )
        generation, claimed_revision, claimed = self._claim(
            owner=owner,
            operation_id=operation_id,
            expected_fence=expected_fence,
            recovering=recovering,
        )
        if claimed.get("completed_operation_id") == operation_id and isinstance(
            claimed.get("completed_receipt"), Mapping
        ):
            return self._validated_terminal_receipt(
                claimed["completed_receipt"], operation_id
            )
        running_record, published = self._transition_operation(
            operation_id,
            expected_statuses={"accepted", "recovery_required"},
            status="running",
            expected_fence=expected_fence,
            fence_generation=generation,
            receipt=None,
            error=None,
            session_owner=owner,
        )
        if not published:
            if running_record.get("status") in {"completed", "failed"}:
                raise ActivationConflict(
                    "activation operation became terminal after lease claim"
                )
            raise ActivationConflict(
                "activation operation was already adopted after lease claim"
            )
        journal_phases = self._journal_phases(
            self.journal.read(operation_id) if recovering else [], generation
        )
        try:
            if self.brain.get_page(ARTIFACTS_ROOT) is None:
                raise ActivationContentConflict("global Artifact root is missing")
            anchors, anchor_edges = self._anchor_specs(items)
            self._ensure_anchors(
                anchors,
                anchor_edges,
                operation_id=operation_id,
                fence_generation=generation,
                owner=owner,
                journal_phases=journal_phases,
            )
            claimed_revision, claimed = self._renew(
                owner=owner,
                operation_id=operation_id,
                fence_generation=generation,
                checkpoint="anchors",
            )
            if not prior.get("active_manifest"):
                for item in items:
                    if any(edge.get("link_type") == "default_agent_for" for edge in self.brain.get_links(item["slug"])):
                        raise ActivationContentConflict(
                            "initial OpenClaw activation requires zero default_agent_for links"
                        )
            pages, edges, profiles = self._page_specs(items, generation, operation_id)
            for page in pages:
                existing = self.brain.get_page(str(page["slug"]))
                if existing is None:
                    self._renew(
                        owner=owner,
                        operation_id=operation_id,
                        fence_generation=generation,
                        checkpoint=f"before-generation-page-{_digest({'slug': str(page['slug'])})[:16]}",
                    )
                    self._journal(operation_id=operation_id, fence_generation=generation, step="generation_page", resource=str(page["slug"]), phase="before")
                    self.brain.put_page(str(page["slug"]), page)
                    self._journal(operation_id=operation_id, fence_generation=generation, step="generation_page", resource=str(page["slug"]), phase="after")
                elif existing != page:
                    raise ActivationContentConflict(
                        "immutable generation page differs"
                    )
                else:
                    self._close_verified_journal_after(
                        phases=journal_phases,
                        operation_id=operation_id,
                        fence_generation=generation,
                        step="generation_page",
                        resource=str(page["slug"]),
                    )
            for edge in edges:
                if not any(dict(item) == edge for item in self.brain.get_links(edge["from_slug"])):
                    resource = _digest(edge)
                    self._renew(
                        owner=owner,
                        operation_id=operation_id,
                        fence_generation=generation,
                        checkpoint=f"before-generation-link-{resource[:16]}",
                    )
                    self._journal(operation_id=operation_id, fence_generation=generation, step="generation_link", resource=resource, phase="before")
                    self.brain.add_link(edge["from_slug"], edge["to_slug"], edge["link_type"], edge["context"])
                    self._journal(operation_id=operation_id, fence_generation=generation, step="generation_link", resource=resource, phase="after")
                else:
                    self._close_verified_journal_after(
                        phases=journal_phases,
                        operation_id=operation_id,
                        fence_generation=generation,
                        step="generation_link",
                        resource=_digest(edge),
                    )
            self._verify([*anchors, *pages], [*anchor_edges, *edges])
            claimed_revision, claimed = self._renew(
                owner=owner,
                operation_id=operation_id,
                fence_generation=generation,
                checkpoint="generation",
            )
            manifest_slug = self._manifest_slug(generation, operation_id)
            manifest = {
                "slug": manifest_slug,
                "type": "openclaw_profile_activation_manifest",
                "title": f"OpenClaw profile activation {generation}",
                "fence_generation": generation,
                "generation": generation,
                "active_generation": generation,
                "operation_id": operation_id,
                "profiles": profiles,
                "default_goal_link_count": 0,
                "staged_page_count": len(pages),
                "staged_link_count": len(edges),
                "anchor_page_hashes": {
                    str(page["slug"]): _digest(_logical_anchor_identity(page))
                    for page in anchors
                },
                "anchor_link_hashes": {_digest(edge): _digest(edge) for edge in anchor_edges},
                "generation_page_hashes": {str(page["slug"]): _digest(page) for page in pages},
                "generation_link_hashes": {_digest(edge): _digest(edge) for edge in edges},
                "anchor_links": [dict(edge) for edge in anchor_edges],
                "generation_links": [dict(edge) for edge in edges],
            }
            stored_manifest = self.brain.get_page(manifest_slug)
            if stored_manifest is None:
                self._renew(
                    owner=owner,
                    operation_id=operation_id,
                    fence_generation=generation,
                    checkpoint="before-manifest-write",
                )
                self._journal(operation_id=operation_id, fence_generation=generation, step="manifest", resource=manifest_slug, phase="before")
                self.brain.put_page(manifest_slug, manifest)
                self._journal(operation_id=operation_id, fence_generation=generation, step="manifest", resource=manifest_slug, phase="after")
                stored_manifest = self.brain.get_page(manifest_slug)
            if stored_manifest != manifest:
                raise ActivationContentConflict(
                    "immutable manifest did not read back exactly"
                )
            self._close_verified_journal_after(
                phases=journal_phases,
                operation_id=operation_id,
                fence_generation=generation,
                step="manifest",
                resource=manifest_slug,
            )
            claimed_revision, claimed = self._renew(
                owner=owner,
                operation_id=operation_id,
                fence_generation=generation,
                checkpoint="manifest",
            )
            self._verify([*anchors, *pages], [*anchor_edges, *edges])
            claimed_revision, claimed = self._renew(
                owner=owner,
                operation_id=operation_id,
                fence_generation=generation,
                checkpoint="before-activation-cas",
            )
            latest_revision, latest = claimed_revision, claimed
            if (
                latest_revision != claimed_revision
                or latest.get("state") != "leased"
                or latest.get("fence_generation", latest.get("generation")) != generation
                or latest.get("lease_owner") != owner
                or latest.get("operation_id") != operation_id
                or float(latest.get("lease_expires_at") or 0)
                - self.clock_skew_seconds
                <= self.now()
            ):
                raise ActivationConflict("lease was lost before manifest activation")
            active = dict(latest)
            active.update(
                {
                    "state": "active",
                    "active_generation": generation,
                    "active_manifest": manifest_slug,
                    "active_manifest_digest": _digest(manifest),
                    "lease_owner": None,
                    "operation_id": None,
                    "lease_expires_at": 0,
                    "completed_operation_id": operation_id,
                }
            )
            receipt = {"generation": generation, "manifest_slug": manifest_slug, "manifest_digest": _digest(manifest), "default_goal_link_count": 0}
            active["completed_receipt"] = receipt
            self._journal(operation_id=operation_id, fence_generation=generation, step="activate", resource="control", phase="before")
            activated_revision = self.control.compare_and_set(latest_revision, active)
            self._journal(operation_id=operation_id, fence_generation=generation, step="activate", resource="control", phase="after")
            self._journal(operation_id=operation_id, fence_generation=generation, step="completed", resource=manifest_slug, phase="event", control_revision=activated_revision, event="activated")
            return dict(receipt)
        except Exception as error:
            self._release_failed(claimed_revision, claimed, error)
            raise

    def provision(
        self,
        declarations: Sequence[Mapping[str, str]],
        *,
        owner: str,
        operation_id: str,
    ) -> dict[str, Any]:
        """Compatibility helper that waits for one in-process operation run."""
        submitted = self.submit(
            declarations, owner=owner, operation_id=operation_id
        )
        result = submitted if submitted["status"] == "completed" else self.run(operation_id)
        if result["status"] != "completed" or not isinstance(result.get("receipt"), Mapping):
            message = str(result.get("error") or "activation did not complete")
            if any(marker in message for marker in ("leased", "fenced", "lease was lost")):
                raise ActivationConflict(message)
            raise ActivationError(message)
        return copy.deepcopy(dict(result["receipt"]))

    def _verify_active_manifest(
        self, manifest: Mapping[str, Any], control: Mapping[str, Any]
    ) -> tuple[list[dict[str, Any]], list[dict[str, str]]]:
        if set(manifest) != MANIFEST_FIELDS:
            raise ActivationContentConflict("active manifest schema is not exact")
        manifest_slug = control.get("active_manifest")
        generation = control.get("active_generation")
        operation_id = manifest.get("operation_id")
        if (
            isinstance(generation, bool)
            or not isinstance(generation, int)
            or generation < 1
            or manifest.get("slug") != manifest_slug
            or manifest.get("type") != "openclaw_profile_activation_manifest"
            or any(
                type(manifest.get(field)) is not int
                for field in (
                    "fence_generation",
                    "generation",
                    "active_generation",
                    "staged_page_count",
                    "staged_link_count",
                )
            )
            or manifest.get("fence_generation") != generation
            or manifest.get("generation") != generation
            or manifest.get("active_generation") != generation
            or isinstance(manifest.get("default_goal_link_count"), bool)
            or not isinstance(manifest.get("default_goal_link_count"), int)
            or manifest.get("default_goal_link_count") != 0
            or not isinstance(operation_id, str)
            or re.fullmatch(
                r"[A-Za-z0-9][A-Za-z0-9._-]{0,127}", operation_id
            )
            is None
            or manifest_slug != self._manifest_slug(int(generation or 0), operation_id)
            or manifest.get("title") != f"OpenClaw profile activation {generation}"
        ):
            raise ActivationContentConflict(
                "active manifest operation or control fields are invalid"
            )
        profiles = manifest.get("profiles")
        if (
            not isinstance(profiles, list)
            or len(profiles) != len(APPROVED_DECLARATIONS)
            or any(not isinstance(profile, Mapping) for profile in profiles)
            or any(set(profile) != PROFILE_FIELDS for profile in profiles)
        ):
            raise ActivationContentConflict(
                "active manifest profile schema is not exact"
            )
        normalized_profiles = [dict(profile) for profile in profiles]
        if {profile["canonical_agent_slug"] for profile in normalized_profiles} != set(
            APPROVED_DECLARATIONS
        ):
            raise ActivationContentConflict(
                "active manifest profile identities are invalid"
            )
        expected_declarations = tuple(
            {
                "slug": slug,
                "name": approved[0],
                "runtime": "openclaw",
                "route": approved[1],
                "task_collection": approved[2],
                "artifact_collection": approved[3],
            }
            for slug, approved in sorted(APPROVED_DECLARATIONS.items())
        )
        expected_anchor_pages, expected_anchor_links = self._anchor_specs(
            expected_declarations
        )
        (
            expected_generation_pages,
            expected_generation_links,
            expected_profiles,
        ) = self._page_specs(
            expected_declarations, int(generation), operation_id
        )
        if sorted(
            normalized_profiles, key=lambda profile: profile["canonical_agent_slug"]
        ) != expected_profiles:
            raise ActivationContentConflict(
                "active manifest profile declaration is not exact"
            )

        map_names = (
            "anchor_page_hashes",
            "anchor_link_hashes",
            "generation_page_hashes",
            "generation_link_hashes",
        )
        hash_maps: dict[str, dict[str, str]] = {}
        for name in map_names:
            value = manifest.get(name)
            if not isinstance(value, Mapping) or any(
                not isinstance(key, str)
                or not isinstance(digest, str)
                or SHA256_PATTERN.fullmatch(digest) is None
                for key, digest in value.items()
            ):
                raise ActivationContentConflict(
                    "active manifest hash map is invalid"
                )
            hash_maps[name] = dict(value)
        expected_hash_maps = {
            "anchor_page_hashes": {
                str(page["slug"]): _digest(_logical_anchor_identity(page))
                for page in expected_anchor_pages
            },
            "anchor_link_hashes": {
                _digest(edge): _digest(edge) for edge in expected_anchor_links
            },
            "generation_page_hashes": {
                str(page["slug"]): _digest(page) for page in expected_generation_pages
            },
            "generation_link_hashes": {
                _digest(edge): _digest(edge) for edge in expected_generation_links
            },
        }
        if any(
            hash_maps[name] != expected_hash_maps[name]
            for name in ("anchor_page_hashes", "generation_page_hashes")
        ):
            raise ActivationContentConflict(
                "active manifest declaration page hash maps are not exact"
            )
        if any(
            hash_maps[name] != expected_hash_maps[name]
            for name in ("anchor_link_hashes", "generation_link_hashes")
        ):
            raise ActivationContentConflict(
                "active declared immutable link set hash maps are not exact"
            )

        anchor_slugs: set[str] = set()
        generation_slugs: set[str] = set()
        for profile in normalized_profiles:
            approved = APPROVED_DECLARATIONS[profile["canonical_agent_slug"]]
            if (
                profile["canonical_task_collection"] != approved[2]
                or profile["canonical_artifact_collection"] != approved[3]
                or not isinstance(profile.get("metadata"), Mapping)
                or not isinstance(profile.get("page_hashes"), Mapping)
            ):
                raise ActivationContentConflict(
                    "active manifest profile declaration is invalid"
                )
            profile_generation_slugs = {
                profile["staged_agent_slug"],
                profile["staged_task_collection"],
                profile["staged_artifact_collection"],
            }
            if any(not isinstance(slug, str) for slug in profile_generation_slugs):
                raise ActivationContentConflict(
                    "active manifest staged identity is invalid"
                )
            generation_slugs.update(profile_generation_slugs)
            anchor_slugs.update(
                {
                    profile["canonical_agent_slug"],
                    profile["canonical_task_collection"],
                    profile["canonical_artifact_collection"],
                }
            )
            expected_generation_slugs = {
                self._staged_slug(
                    int(generation), operation_id, profile["canonical_agent_slug"]
                ),
                self._staged_slug(
                    int(generation),
                    operation_id,
                    profile["canonical_task_collection"],
                ),
                self._staged_slug(
                    int(generation),
                    operation_id,
                    profile["canonical_artifact_collection"],
                ),
            }
            if profile_generation_slugs != expected_generation_slugs:
                raise ActivationContentConflict(
                    "active manifest operation staging paths are invalid"
                )
            if dict(profile["page_hashes"]) != {
                slug: hash_maps["generation_page_hashes"].get(slug)
                for slug in profile_generation_slugs
            }:
                raise ActivationContentConflict(
                    "active manifest profile page hash map is not exact"
                )

        if (
            set(hash_maps["anchor_page_hashes"]) != anchor_slugs
            or set(hash_maps["generation_page_hashes"]) != generation_slugs
            or int(manifest.get("staged_page_count") or -1) != len(generation_slugs)
        ):
            raise ActivationContentConflict(
                "active manifest page hash map is not exact"
            )

        all_links: list[dict[str, str]] = []
        for list_name, map_name, declared_links in (
            ("anchor_links", "anchor_link_hashes", expected_anchor_links),
            (
                "generation_links",
                "generation_link_hashes",
                expected_generation_links,
            ),
        ):
            raw_links = manifest.get(list_name)
            if (
                not isinstance(raw_links, list)
                or any(not isinstance(edge, Mapping) for edge in raw_links)
                or any(set(edge) != LINK_FIELDS for edge in raw_links)
                or any(
                    not all(isinstance(value, str) for value in edge.values())
                    for edge in raw_links
                )
            ):
                raise ActivationContentConflict(
                    "active manifest immutable link schema is invalid"
                )
            links = [dict(edge) for edge in raw_links]
            expected_hashes = {_digest(edge): _digest(edge) for edge in links}
            if hash_maps[map_name] != expected_hashes:
                raise ActivationContentConflict(
                    "active manifest link hash map is not exact"
                )
            if sorted(links, key=_digest) != sorted(declared_links, key=_digest):
                raise ActivationContentConflict(
                    "active declared immutable link set does not match the approved declaration"
                )
            all_links.extend(links)
        if int(manifest.get("staged_link_count") or -1) != len(
            manifest["generation_links"]
        ):
            raise ActivationContentConflict(
                "active manifest staged link count is invalid"
            )

        for slug, digest in hash_maps["anchor_page_hashes"].items():
            page = self.brain.get_page(slug)
            if not isinstance(page, Mapping) or _digest(
                _logical_anchor_identity(page)
            ) != digest:
                raise ActivationContentConflict(
                    f"active logical anchor hash mismatch: {slug}"
                )
        for slug, digest in hash_maps["generation_page_hashes"].items():
            page = self.brain.get_page(slug)
            if not isinstance(page, Mapping) or _digest(page) != digest:
                raise ActivationContentConflict(
                    f"active page hash mismatch: {slug}"
                )
        for profile in normalized_profiles:
            if self.brain.get_page(profile["staged_agent_slug"]) != dict(
                profile["metadata"]
            ):
                raise ActivationContentConflict(
                    "active manifest profile metadata is not exact"
                )

        anchor_page_by_slug = {
            str(page["slug"]): page for page in expected_anchor_pages
        }
        anchor_by_source: dict[str, list[dict[str, str]]] = {
            slug: [] for slug in anchor_slugs
        }
        for edge in expected_anchor_links:
            anchor_by_source.setdefault(edge["from_slug"], []).append(dict(edge))
        for slug, expected in anchor_by_source.items():
            self._verify_anchor_links(
                anchor_page_by_slug[slug],
                self.brain.get_links(slug),
                expected,
            )
        generation_by_source: dict[str, list[dict[str, str]]] = {
            slug: [] for slug in generation_slugs
        }
        for edge in expected_generation_links:
            generation_by_source.setdefault(edge["from_slug"], []).append(dict(edge))
        for slug, expected in generation_by_source.items():
            actual = [dict(edge) for edge in self.brain.get_links(slug)]
            if sorted(actual, key=lambda edge: json.dumps(edge, sort_keys=True)) != sorted(
                expected, key=lambda edge: json.dumps(edge, sort_keys=True)
            ):
                raise ActivationContentConflict(
                    f"active declared immutable link set mismatch: {slug}"
                )
        return normalized_profiles, all_links

    def active_projection(self) -> dict[str, Any]:
        for _attempt in range(3):
            revision, control = self.control.read()
            generation = control.get(
                "active_generation", control.get("generation", 0)
            )
            manifest_slug = control.get("active_manifest")
            manifest_digest = control.get("active_manifest_digest")
            if not manifest_slug:
                if not _active_projection_identity_is_valid(
                    generation, manifest_slug, manifest_digest
                ):
                    raise ActivationContentConflict(
                        "active generation requires an exact manifest and digest"
                    )
                confirm_revision, confirm = self.control.read()
                if confirm_revision == revision and confirm == control:
                    projection = {
                        "generation": generation,
                        "active_manifest": None,
                        "profiles": [],
                        "manifest_digest": None,
                    }
                    self._store_validated_projection(revision, projection)
                    return projection
                continue
            manifest = self.brain.get_page(str(manifest_slug))
            if not isinstance(manifest, Mapping):
                raise ActivationContentConflict("active manifest is missing")
            if (
                not _active_projection_identity_is_valid(
                    generation, manifest_slug, manifest_digest
                )
                or _digest(manifest) != manifest_digest
            ):
                raise ActivationContentConflict(
                    "active manifest digest does not match control"
                )
            if manifest.get("active_generation", manifest.get("generation")) != control.get("active_generation", control.get("generation")):
                raise ActivationContentConflict(
                    "active manifest generation does not match control"
                )
            profiles, _links = self._verify_active_manifest(manifest, control)
            confirm_revision, confirm = self.control.read()
            if confirm_revision == revision and confirm == control:
                projection = {
                    "generation": generation,
                    "active_manifest": manifest_slug,
                    "profiles": copy.deepcopy(profiles),
                    "manifest_digest": manifest_digest,
                }
                self._store_validated_projection(revision, projection)
                return projection
        raise ActivationConflict("active profile projection changed during read")

    def _validated_projection_record(
        self, record: Mapping[str, Any]
    ) -> dict[str, Any]:
        item = dict(record)
        projection = item.get("projection")
        control_revision = item.get("control_revision")
        validated_at = item.get("validated_at")
        if (
            set(item)
            != {
                "schema_version",
                "status",
                "control_revision",
                "manifest_digest",
                "projection",
                "projection_digest",
                "validated_at",
                "invalidated_at",
                "validation_error",
            }
            or item.get("schema_version") != 1
            or item.get("status") not in {"ready", "invalid"}
            or isinstance(control_revision, bool)
            or not isinstance(control_revision, int)
            or control_revision < 0
            or not isinstance(projection, Mapping)
            or set(projection)
            != {"generation", "active_manifest", "profiles", "manifest_digest"}
            or isinstance(projection.get("generation"), bool)
            or not isinstance(projection.get("generation"), int)
            or projection.get("generation") < 0
            or not isinstance(projection.get("profiles"), list)
            or not _active_projection_identity_is_valid(
                projection.get("generation"),
                projection.get("active_manifest"),
                projection.get("manifest_digest"),
            )
            or item.get("manifest_digest") != projection.get("manifest_digest")
            or (
                item.get("manifest_digest") is not None
                and (
                    not isinstance(item.get("manifest_digest"), str)
                    or SHA256_PATTERN.fullmatch(item["manifest_digest"]) is None
                )
            )
            or not isinstance(item.get("projection_digest"), str)
            or SHA256_PATTERN.fullmatch(item["projection_digest"]) is None
            or item["projection_digest"] != _digest(projection)
            or isinstance(validated_at, bool)
            or not isinstance(validated_at, (int, float))
            or validated_at < 0
            or (
                item.get("status") == "ready"
                and (
                    item.get("invalidated_at") is not None
                    or item.get("validation_error") is not None
                )
            )
            or (
                item.get("status") == "invalid"
                and (
                    isinstance(item.get("invalidated_at"), bool)
                    or not isinstance(item.get("invalidated_at"), (int, float))
                    or item.get("invalidated_at") < 0
                    or not isinstance(item.get("validation_error"), str)
                    or not item.get("validation_error")
                )
            )
        ):
            raise ActivationError("validated active projection cache is invalid")
        item["projection"] = copy.deepcopy(dict(projection))
        return item

    def _store_validated_projection(
        self, control_revision: int, projection: Mapping[str, Any]
    ) -> dict[str, Any]:
        record = self._validated_projection_record(
            {
                "schema_version": 1,
                "status": "ready",
                "control_revision": control_revision,
                "manifest_digest": projection.get("manifest_digest"),
                "projection": copy.deepcopy(dict(projection)),
                "projection_digest": _digest(projection),
                "validated_at": self.now(),
                "invalidated_at": None,
                "validation_error": None,
            }
        )
        for _attempt in range(3):
            revision, existing = self.projections.read()
            if existing is not None:
                existing = self._validated_projection_record(existing)
                if existing["control_revision"] > control_revision:
                    self._cache_stored_projection(existing)
                    return existing
            try:
                self.projections.compare_and_set(revision, record)
            except ActivationConflict:
                continue
            self._cache_stored_projection(record)
            return record
        raise ActivationConflict("validated active projection cache changed")

    def _cache_stored_projection(self, record: Mapping[str, Any]) -> None:
        """Adopt a durable record and forget only strictly older invalidations."""
        item = self._validated_projection_record(record)
        with self._projection_lock:
            self._cached_projection = (
                copy.deepcopy(item) if item["status"] == "ready" else None
            )
            self._startup_projection_candidate = None
            pending = self._pending_projection_invalidation
            if (
                pending is not None
                and item["control_revision"]
                > pending["target"]["control_revision"]
            ):
                self._pending_projection_invalidation = None

    @staticmethod
    def _same_projection_identity(
        left: Mapping[str, Any], right: Mapping[str, Any]
    ) -> bool:
        return (
            left.get("control_revision") == right.get("control_revision")
            and left.get("manifest_digest") == right.get("manifest_digest")
            and left.get("projection_digest") == right.get("projection_digest")
            and left.get("projection") == right.get("projection")
        )

    def cached_active_projection(self) -> dict[str, Any]:
        """Bounded control read plus process cache lookup; never reads GBrain."""
        with self.operation_context():
            control_revision, control = self.control.read()
        with self._projection_lock:
            cached = copy.deepcopy(self._cached_projection)
        if cached is not None:
            cached = self._validated_projection_record(cached)
            projection = cached["projection"]
            if (
                cached["status"] == "ready"
                and cached["control_revision"] == control_revision
                and cached["manifest_digest"]
                == control.get("active_manifest_digest")
                and projection.get("active_manifest")
                == control.get("active_manifest")
                and projection.get("generation")
                == int(control.get("active_generation") or 0)
            ):
                return {
                    "status": "ready",
                    "control_revision": control_revision,
                    "validated_at": cached["validated_at"],
                    **copy.deepcopy(projection),
                }
        return {
            "status": "validation_pending",
            "control_revision": control_revision,
            "generation": int(control.get("active_generation") or 0),
            "active_manifest": control.get("active_manifest"),
            "manifest_digest": control.get("active_manifest_digest"),
        }

    def revalidate_active_projection(self) -> dict[str, Any]:
        with self.operation_context():
            return self.active_projection()

    def invalidate_cached_projection(
        self, error: BaseException | str = "canonical validation failed"
    ) -> None:
        """Durably stop serving an LKG while retaining its retry identity."""
        validation_error = str(error) or "canonical validation failed"
        with self._projection_lock:
            failed_cache = copy.deepcopy(self._cached_projection)
            startup_candidate = copy.deepcopy(
                self._startup_projection_candidate
            )
            self._cached_projection = None
            self._startup_projection_candidate = None
            failure_target = failed_cache or startup_candidate
            pending = copy.deepcopy(self._pending_projection_invalidation)
            if failure_target is not None:
                failure_target = self._validated_projection_record(
                    failure_target
                )
                replace_pending = pending is None
                if pending is not None:
                    pending_target = self._validated_projection_record(
                        pending["target"]
                    )
                    replace_pending = (
                        failure_target["control_revision"]
                        > pending_target["control_revision"]
                        or (
                            failure_target["control_revision"]
                            == pending_target["control_revision"]
                            and not self._same_projection_identity(
                                failure_target, pending_target
                            )
                        )
                    )
                if replace_pending:
                    pending = {
                        "target": failure_target,
                        "validation_error": validation_error,
                    }
                    self._pending_projection_invalidation = copy.deepcopy(
                        pending
                    )
            if pending is None:
                return
            pending = copy.deepcopy(self._pending_projection_invalidation)
            target = self._validated_projection_record(pending["target"])

        def resolve_pending(target: Mapping[str, Any]) -> None:
            with self._projection_lock:
                current_pending = self._pending_projection_invalidation
                if (
                    current_pending is not None
                    and self._same_projection_identity(
                        current_pending["target"], target
                    )
                ):
                    self._pending_projection_invalidation = None

        with self.operation_context():
            for _attempt in range(3):
                revision, durable = self.projections.read()
                if durable is None:
                    raise ActivationConflict(
                        "active projection invalidation target disappeared"
                    )
                durable = self._validated_projection_record(durable)
                if durable["control_revision"] > target["control_revision"]:
                    resolve_pending(target)
                    return
                if not self._same_projection_identity(durable, target):
                    raise ActivationConflict(
                        "active projection invalidation target changed "
                        "without a newer control revision"
                    )
                if durable["status"] == "invalid":
                    resolve_pending(target)
                    return
                invalid = dict(durable)
                invalid.update(
                    {
                        "status": "invalid",
                        "invalidated_at": self.now(),
                        "validation_error": pending["validation_error"],
                    }
                )
                invalid = self._validated_projection_record(invalid)
                try:
                    self.projections.compare_and_set(revision, invalid)
                except ActivationConflict:
                    continue
                resolve_pending(target)
                return
        raise ActivationConflict("active projection invalidation changed")

    def recover(self, operation_id: str) -> dict[str, Any]:
        with self.operation_context():
            return self._recover(operation_id)

    def request_recovery(self, operation_id: str) -> dict[str, Any]:
        """Persist a generation-stamped request without performing recovery."""
        with self.operation_context():
            for _attempt in range(1):
                revision, operation = self.operations.read(operation_id)
                if operation is None:
                    raise ActivationError(
                        f"unknown activation operation: {operation_id}"
                    )
                status = operation.get("status")
                if status in {"completed", "failed"}:
                    operation = self._validated_terminal_operation(operation)
                elif status not in {"accepted", "running", "recovery_required"}:
                    raise ActivationError("activation operation status is invalid")
                requested_generation = operation.get(
                    "recovery_request_generation", 0
                )
                processed_generation = operation.get(
                    "recovery_processed_generation", 0
                )
                if (
                    isinstance(requested_generation, bool)
                    or not isinstance(requested_generation, int)
                    or requested_generation < 0
                    or isinstance(processed_generation, bool)
                    or not isinstance(processed_generation, int)
                    or processed_generation < 0
                ):
                    raise ActivationError(
                        "activation recovery generation is invalid"
                    )
                if self._recovery_pending(operation):
                    return self._operation_view(operation)
                updated = dict(operation)
                updated.update(
                    {
                        "recovery_requested": True,
                        "recovery_request_generation": requested_generation + 1,
                        "recovery_processed_generation": processed_generation,
                        "recovery_requested_at": self.now(),
                        "recovery_verified_at": None,
                        "recovery_verification_digest": None,
                        "recovery_result": "pending",
                        "recovery_error": None,
                        "updated_at": self.now(),
                    }
                )
                if status not in {"completed", "failed"}:
                    updated.update(
                        {
                            "status": "recovery_required",
                            "receipt": None,
                            "receipt_version": None,
                            "receipt_digest": None,
                            "error": "durable recovery requested",
                        }
                    )
                try:
                    self.operations.compare_and_set(
                        operation_id, revision, updated
                    )
                except ActivationConflict:
                    continue
                return self._operation_view(updated)
        raise ActivationConflict("activation recovery request changed")

    def _write_terminal_recovery_result(
        self,
        *,
        operation_id: str,
        revision: int,
        operation: Mapping[str, Any],
        status: str,
        receipt: Mapping[str, Any] | None,
        error: str | None,
        result: str,
        evidence: Mapping[str, Any],
    ) -> dict[str, Any]:
        request_generation = int(
            operation.get("recovery_request_generation", 0) or 0
        )
        updated = dict(operation)
        updated.update(
            {
                "status": status,
                "recovery_requested": False,
                "recovery_processed_generation": request_generation,
                "recovery_verified_at": float(self.now()),
                "recovery_verification_digest": _digest(
                    {
                        "operation_id": operation_id,
                        "request_generation": request_generation,
                        "result": result,
                        "evidence": dict(evidence),
                    }
                ),
                "recovery_result": result,
                "recovery_error": error,
                "updated_at": self.now(),
            }
        )
        if status == "completed" and receipt is not None:
            updated.update(
                {
                    "fence_generation": int(receipt["generation"]),
                    **self._completion_attestation(receipt, operation_id),
                }
            )
        elif status == "failed":
            updated.update(
                {
                    "receipt": None,
                    "receipt_version": None,
                    "receipt_digest": None,
                    "error": error or "terminal recovery verification failed",
                }
            )
        updated = self._validated_terminal_operation(updated)
        self.operations.compare_and_set(operation_id, revision, updated)
        return self._operation_view(updated)

    def _mark_terminal_recovery_retry(
        self,
        *,
        operation_id: str,
        revision: int,
        operation: Mapping[str, Any],
        error: BaseException,
    ) -> None:
        if not self._recovery_pending(operation):
            return
        updated = dict(operation)
        updated.update(
            {
                "recovery_requested": True,
                "recovery_result": "recovery_required",
                "recovery_error": str(error),
                "updated_at": self.now(),
            }
        )
        try:
            self.operations.compare_and_set(operation_id, revision, updated)
        except ActivationConflict:
            pass

    def _recover_terminal(
        self,
        operation_id: str,
        revision: int,
        operation: Mapping[str, Any],
    ) -> dict[str, Any]:
        terminal = self._validated_terminal_operation(operation)
        fence_generation = int(terminal.get("fence_generation") or 0)
        events = self.journal.read(operation_id)
        phases = self._journal_phases(events, fence_generation)
        if terminal["status"] == "completed":
            self._reconcile_activation_audit(operation_id, fence_generation)
            events = self.journal.read(operation_id)
            phases = self._journal_phases(events, fence_generation)
        control_revision, control = self.control.read()
        try:
            receipt: dict[str, Any] | None = None
            result = str(terminal["status"])
            if terminal["status"] == "completed":
                receipt = dict(terminal["receipt"])
                if control.get("completed_operation_id") == operation_id:
                    control_receipt = control.get("completed_receipt")
                    if not isinstance(control_receipt, Mapping):
                        raise ActivationContentConflict(
                            "completed control receipt is missing"
                        )
                    control_receipt = self._validated_terminal_receipt(
                        control_receipt, operation_id
                    )
                    if control_receipt != receipt:
                        raise ActivationContentConflict(
                            "completed control receipt conflicts with durable receipt"
                        )
                    receipt = self._verify_completed_receipt(
                        receipt, operation_id
                    )
                else:
                    receipt = self._verify_completed_receipt_graph(
                        receipt, operation_id
                    )
            else:
                if control.get("completed_operation_id") == operation_id:
                    control_receipt = control.get("completed_receipt")
                    if not isinstance(control_receipt, Mapping):
                        raise ActivationContentConflict(
                            "completed control receipt is missing"
                        )
                    receipt = self._verify_completed_receipt(
                        control_receipt, operation_id
                    )
                    result = "completed"
                elif ("activate", "control", "after") in phases:
                    manifest_slug = self._manifest_slug(
                        fence_generation, operation_id
                    )
                    manifest = self.brain.get_page(manifest_slug)
                    if not isinstance(manifest, Mapping):
                        raise ActivationContentConflict(
                            "activated operation manifest is missing"
                        )
                    receipt = self._verify_completed_receipt_graph(
                        {
                            "generation": fence_generation,
                            "manifest_slug": manifest_slug,
                            "manifest_digest": _digest(manifest),
                            "default_goal_link_count": 0,
                        },
                        operation_id,
                    )
                    result = "completed"
                else:
                    incomplete = {
                        (step, resource)
                        for step, resource, phase in phases
                        if phase == "before"
                        and (step, resource, "after") not in phases
                    }
                    if incomplete:
                        raise ActivationConflict(
                            "failed terminal recovery has ambiguous journal mutations"
                        )

            if receipt is not None:
                phases = self._reconcile_verified_journal(
                    operation_id=operation_id,
                    fence_generation=int(receipt["generation"]),
                    events=self.journal.read(operation_id),
                )
            evidence = {
                "control_revision": control_revision,
                "control_digest": _digest(control),
                "receipt_digest": _digest(receipt) if receipt is not None else None,
                "journal_digest": _digest(
                    {
                        "phases": [
                            list(phase) for phase in sorted(phases)
                        ]
                    }
                ),
            }
            return self._write_terminal_recovery_result(
                operation_id=operation_id,
                revision=revision,
                operation=terminal,
                status="completed" if receipt is not None else "failed",
                receipt=receipt,
                error=None if receipt is not None else str(terminal["error"]),
                result=result,
                evidence=evidence,
            )
        except Exception as error:
            if not _is_deterministic_activation_failure(error):
                self._mark_terminal_recovery_retry(
                    operation_id=operation_id,
                    revision=revision,
                    operation=terminal,
                    error=error,
                )
                raise
            try:
                self.invalidate_cached_projection(error)
            except Exception as invalidation_error:
                self._mark_terminal_recovery_retry(
                    operation_id=operation_id,
                    revision=revision,
                    operation=terminal,
                    error=invalidation_error,
                )
                raise
            return self._write_terminal_recovery_result(
                operation_id=operation_id,
                revision=revision,
                operation=terminal,
                status="failed",
                receipt=None,
                error=str(error),
                result="failed",
                evidence={
                    "prior_status": terminal["status"],
                    "prior_receipt_digest": terminal.get("receipt_digest"),
                    "error": str(error),
                },
            )

    def _recover(self, operation_id: str) -> dict[str, Any]:
        operation_revision, operation = self.operations.read(operation_id)
        if operation is None:
            raise ActivationError(f"unknown activation operation: {operation_id}")
        if operation.get("status") in {"completed", "failed"}:
            return self._recover_terminal(
                operation_id, operation_revision, operation
            )
        try:
            return self._recover_nonterminal(operation_id, operation)
        except Exception as error:
            if not _is_deterministic_activation_failure(error):
                raise
            failed, _changed = self._transition_operation(
                operation_id,
                expected_statuses={"accepted", "running", "recovery_required"},
                status="failed",
                expected_fence=(
                    int(operation["fence_generation"])
                    if operation.get("fence_generation") is not None
                    else None
                ),
                fence_generation=operation.get("fence_generation"),
                receipt=None,
                receipt_version=None,
                receipt_digest=None,
                error=str(error),
            )
            return self._operation_view(failed)

    def _recover_nonterminal(
        self, operation_id: str, operation: Mapping[str, Any]
    ) -> dict[str, Any]:
        journal_events = self.journal.read(operation_id)
        _control_revision, control = self.control.read()
        control_fence = int(
            control.get("fence_generation", control.get("generation", 0)) or 0
        )
        if (
            operation.get("status") == "running"
            and control.get("state") == "leased"
            and control.get("operation_id") == operation_id
            and float(control.get("lease_expires_at") or 0)
            - self.clock_skew_seconds
            > self.now()
        ):
            return self._operation_view(operation)
        journal_phases = self._journal_phases(journal_events, control_fence)
        if control.get("operation_id") == operation_id:
            self._close_verified_journal_after(
                phases=journal_phases,
                operation_id=operation_id,
                fence_generation=control_fence,
                step="lease",
                resource="control",
            )
        if control.get("completed_operation_id") == operation_id and isinstance(
            control.get("completed_receipt"), Mapping
        ):
            receipt = self._validated_terminal_receipt(
                control["completed_receipt"], operation_id
            )
            receipt = self._verify_completed_receipt(receipt, operation_id)
            verified_steps = {
                "lease",
                "lease_recovery",
                "lease_renewal",
                "anchor_page",
                "anchor_link",
                "generation_page",
                "generation_link",
                "manifest",
                "activate",
            }
            for step, resource, phase in tuple(journal_phases):
                if phase == "before" and step in verified_steps:
                    self._close_verified_journal_after(
                        phases=journal_phases,
                        operation_id=operation_id,
                        fence_generation=control_fence,
                        step=step,
                        resource=resource,
                    )
            completed = self._update_operation(
                operation_id,
                status="completed",
                fence_generation=int(receipt["generation"]),
                **self._completion_attestation(receipt, operation_id),
                recovery_journal_event_count=len(journal_events),
            )
            return self._operation_view(completed)
        operation_fence = int(operation.get("fence_generation") or 0)
        operation_phases = self._journal_phases(journal_events, operation_fence)
        if operation_fence and ("activate", "control", "after") in operation_phases:
            manifest_slug = self._manifest_slug(operation_fence, operation_id)
            manifest = self.brain.get_page(manifest_slug)
            if not isinstance(manifest, Mapping):
                raise ActivationContentConflict(
                    "activated operation manifest is missing"
                )
            receipt = {
                "generation": operation_fence,
                "manifest_slug": manifest_slug,
                "manifest_digest": _digest(manifest),
                "default_goal_link_count": 0,
            }
            receipt = self._verify_completed_receipt_graph(
                receipt, operation_id
            )
            completed = self._update_operation(
                operation_id,
                status="completed",
                fence_generation=operation_fence,
                **self._completion_attestation(receipt, operation_id),
                recovery_journal_event_count=len(journal_events),
            )
            return self._operation_view(completed)
        fence = operation.get("fence_generation")
        if fence is None and control.get("operation_id") == operation_id:
            fence = int(
                control.get("fence_generation", control.get("generation", 0)) or 0
            )
            operation = self._update_operation(
                operation_id,
                status="recovery_required",
                fence_generation=fence,
                recovery_journal_event_count=len(journal_events),
            )
        elif operation.get("status") != "recovery_required":
            operation = self._update_operation(
                operation_id,
                status="recovery_required",
                recovery_journal_event_count=len(journal_events),
            )
        return self._run(operation_id, recovering=True)


class OpenClawProfileActivationExecutor:
    """Background scanner that derives execution only from durable operation state."""

    def __init__(
        self,
        service_factory: Callable[[], OpenClawProfileActivation],
        *,
        scan_interval_seconds: float = 1.0,
        projection_validation_interval_seconds: float = 60.0,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        if scan_interval_seconds <= 0 or scan_interval_seconds > 60:
            raise ValueError("activation executor scan interval is invalid")
        if (
            projection_validation_interval_seconds <= 0
            or projection_validation_interval_seconds > 3600
        ):
            raise ValueError("active projection validation interval is invalid")
        self.service_factory = service_factory
        self.scan_interval_seconds = scan_interval_seconds
        self.projection_validation_interval_seconds = (
            projection_validation_interval_seconds
        )
        self.clock = clock
        self._stop = threading.Event()
        self._wake = threading.Event()
        self._projection_validation_requested = threading.Event()
        self._projection_validation_requested.set()
        self._last_projection_validation_at: float | None = None
        self._thread: threading.Thread | None = None
        self.last_error: str | None = None

    def run_once(self) -> list[str]:
        service = self.service_factory()
        processed: list[str] = []
        cycle_errors: list[str] = []
        try:
            operation_ids = service.pending_operation_ids()
        except Exception as error:
            operation_ids = []
            cycle_errors.append(f"operation scan failed: {error}")
        for operation_id in operation_ids:
            try:
                service.adopt(operation_id)
            except Exception as error:
                cycle_errors.append(f"operation {operation_id} failed: {error}")
                continue
            processed.append(operation_id)
        now = self.clock()
        if (
            self._projection_validation_requested.is_set()
            or self._last_projection_validation_at is None
            or now - self._last_projection_validation_at
            >= self.projection_validation_interval_seconds
        ):
            self._projection_validation_requested.clear()
            try:
                service.revalidate_active_projection()
            except Exception as error:
                try:
                    service.invalidate_cached_projection(error)
                except Exception:
                    pass
                self._projection_validation_requested.set()
                cycle_errors.append(
                    f"active projection validation failed: {error}"
                )
            else:
                self._last_projection_validation_at = self.clock()
        self.last_error = "; ".join(cycle_errors) or None
        return processed

    def _run_forever(self) -> None:
        while not self._stop.is_set():
            try:
                self.run_once()
            except Exception as error:  # The next durable scan retries safely.
                self.last_error = str(error)
            self._wake.wait(self.scan_interval_seconds)
            self._wake.clear()

    def start(self) -> None:
        if self._thread is not None and self._thread.is_alive():
            return
        self._stop.clear()
        self._thread = threading.Thread(
            target=self._run_forever,
            daemon=True,
            name="openclaw-activation-executor",
        )
        self._thread.start()

    def wake(self) -> None:
        self._wake.set()

    def request_projection_validation(self) -> None:
        self._projection_validation_requested.set()
        self.wake()

    def stop(self, timeout_seconds: float = 5.0) -> None:
        self._stop.set()
        self._wake.set()
        if self._thread is not None:
            self._thread.join(timeout_seconds)
            if self._thread.is_alive():
                raise ActivationError("activation executor did not stop")
        self._thread = None
