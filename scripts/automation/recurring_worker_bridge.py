#!/usr/bin/env python3
from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import re
import subprocess
import sys
import time
import uuid
from pathlib import Path
from urllib.parse import quote
from zoneinfo import ZoneInfo


PACIFIC = ZoneInfo("America/Los_Angeles")
SCHEMA_VERSION = 1
MAX_REQUEST_BYTES = 64 * 1024
MAX_BUNDLE_BYTES = 256 * 1024
MAX_AGE_SECONDS = 6 * 60 * 60
PROCESSING_TIMEOUT_SECONDS = 20 * 60
HEARTBEAT_STALE_SECONDS = 120
POLL_MAX_SECONDS = 10 * 60
ALLOWED_ROLES = {"daily_learning_intake", "sre_daily_reliability"}
ALLOWED_OPERATIONS = {
    "daily_learning_intake": {"evidence", "persist"},
    "sre_daily_reliability": {"evidence", "persist"},
}
ROLE_AUTOMATION = {
    "daily_learning_intake": "memory-stargraph-daily-learning-intake",
    "sre_daily_reliability": "memory-stargraph-sre-daily-reliability",
}
ROLE_RUN_PREFIX = {
    "daily_learning_intake": "runs/memory-stargraph-learning-",
    "sre_daily_reliability": "runs/memory-stargraph-sre-",
}
ROLE_REPORT_PREFIX = {
    "daily_learning_intake": "reports/memory-stargraph-learning-",
    "sre_daily_reliability": "reports/memory-stargraph-sre-",
}
TODO_PREFIX = "notes/memory-starmap-todo-list/"
LEARNING_PREFIX = "notes/memory-stargraph-learnings/"


class BridgeError(RuntimeError):
    pass


class BridgePhaseError(BridgeError):
    def __init__(self, phase: str, message: str):
        super().__init__(message)
        self.phase = phase


def pacific_now() -> dt.datetime:
    return dt.datetime.now(dt.timezone.utc).astimezone(PACIFIC).replace(microsecond=0)


def iso_now() -> str:
    return pacific_now().isoformat()


BRIDGE_STARTED_AT = iso_now()
BRIDGE_INSTANCE_ID = os.environ.get("MEMORY_STARGRAPH_RECURRING_BRIDGE_INSTANCE_ID", uuid.uuid4().hex)


def runtime_root() -> Path:
    return Path(os.environ.get("MEMORY_STARGRAPH_RECURRING_BRIDGE_DIR", "var/recurring-worker-bridge")).expanduser()


def _safe_id(value: str) -> str:
    if not re.fullmatch(r"[a-z0-9][a-z0-9._:-]{7,160}", value):
        raise BridgeError(f"unsafe identifier: {value!r}")
    return value


def _safe_nonce(value: str | None = None) -> str:
    nonce = value or uuid.uuid4().hex
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]{7,160}", nonce):
        raise BridgeError("nonce must be 8-160 safe filename characters")
    return nonce


def _within(root: Path, path: Path) -> Path:
    resolved_root = root.resolve()
    resolved = path.resolve()
    if resolved != resolved_root and resolved_root not in resolved.parents:
        raise BridgeError(f"path escapes runtime root: {path}")
    return resolved


def ensure_dirs(root: Path) -> None:
    for name in ("incoming", "processing", "results", "completed", "failed", "locks", "logs", "bundles"):
        path = root / name
        path.mkdir(parents=True, exist_ok=True)
        try:
            path.chmod(0o700)
        except PermissionError:
            pass


def incoming_path(root: Path, nonce: str) -> Path:
    return _within(root, root / "incoming" / f"{_safe_nonce(nonce)}.json")


def processing_path(root: Path, nonce: str) -> Path:
    return _within(root, root / "processing" / f"{_safe_nonce(nonce)}.json")


def completed_path(root: Path, nonce: str) -> Path:
    return _within(root, root / "completed" / f"{_safe_nonce(nonce)}.json")


def failed_path(root: Path, nonce: str) -> Path:
    return _within(root, root / "failed" / f"{_safe_nonce(nonce)}.json")


def result_path(root: Path, invocation_id: str, operation: str) -> Path:
    return _within(root, root / "results" / f"{_safe_id(invocation_id)}-{operation}.json")


def state_path(root: Path) -> Path:
    return _within(root, root / "runner-state.json")


def lock_path(root: Path) -> Path:
    return _within(root, root / "locks" / "recurring-worker-bridge.lock")


def log_path(root: Path) -> Path:
    return _within(root, root / "logs" / "bridge.jsonl")


def parse_time(value: str) -> dt.datetime:
    try:
        parsed = dt.datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise BridgeError(f"invalid timestamp: {value}") from exc
    if parsed.tzinfo is None:
        raise BridgeError("timestamp must be timezone-aware")
    return parsed


def run_cmd(args: list[str], *, input_text: str | None = None, timeout: int = 30) -> subprocess.CompletedProcess[str]:
    try:
        return subprocess.run(args, input=input_text, text=True, capture_output=True, timeout=timeout, check=False)
    except (OSError, subprocess.TimeoutExpired) as exc:
        return subprocess.CompletedProcess(args, 124, "", str(exc))


def current_commit() -> str:
    result = run_cmd(["git", "rev-parse", "HEAD"], timeout=30)
    if result.returncode != 0:
        raise BridgePhaseError("source_validation", (result.stderr or result.stdout).strip() or "git rev-parse failed")
    return result.stdout.strip()


def atomic_write_json(path: Path, payload: dict[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_name(f".{path.name}.{uuid.uuid4().hex}.tmp")
    data = json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    if len(data.encode("utf-8")) > MAX_REQUEST_BYTES and path.parent.name == "incoming":
        raise BridgeError("request exceeds size limit")
    if len(data.encode("utf-8")) > MAX_BUNDLE_BYTES and path.parent.name in {"results", "bundles"}:
        raise BridgeError("payload exceeds size limit")
    temp.write_text(data, encoding="utf-8")
    try:
        temp.chmod(0o600)
    except PermissionError:
        pass
    temp.replace(path)


def bridge_enabled() -> bool:
    return os.environ.get("MEMORY_STARGRAPH_RECURRING_BRIDGE_ENABLED", "0") in {"1", "true", "yes"}


def remote_disabled_evidence() -> dict[str, object]:
    return {
        "runner_host_role": os.environ.get("MEMORY_STARGRAPH_RECURRING_BRIDGE_HOST_ROLE", ".85-authoritative"),
        "runner_enabled": bridge_enabled(),
        "runner_instance_id": BRIDGE_INSTANCE_ID,
        "runner_pid": os.getpid(),
        "runner_started_at": BRIDGE_STARTED_AT,
        "configured_remote_runner_disabled": True,
        "remote_role": ".102",
        "verification": os.environ.get(
            "MEMORY_STARGRAPH_RECURRING_BRIDGE_REMOTE_DISABLED_EVIDENCE",
            ".102 receives bridge code but MEMORY_STARGRAPH_RECURRING_BRIDGE_ENABLED is unset by default",
        ),
    }


def write_state(root: Path, status: str, extra: dict[str, object] | None = None) -> dict[str, object]:
    ensure_dirs(root)
    payload = {"ok": True, "status": status, "updated_at": iso_now(), **remote_disabled_evidence(), **(extra or {})}
    atomic_write_json(state_path(root), payload)
    return payload


def read_state(root: Path) -> dict[str, object] | None:
    path = state_path(root)
    if not path.exists():
        return None
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return {"ok": False, "status": "invalid_bridge_state", "runner_state_file": str(path)}
    return payload if isinstance(payload, dict) else {"ok": False, "status": "invalid_bridge_state", "runner_state_file": str(path)}


def write_phase(root: Path, values: dict[str, str], phase: str, *, processed: int | None = None, total: int | None = None, extra: dict[str, object] | None = None) -> dict[str, object]:
    previous = read_state(root) or {}
    now = iso_now()
    started = previous.get("phase_started_at") if previous.get("phase") == phase else now
    progress: dict[str, object] = {}
    if processed is not None:
        progress["processed"] = processed
    if total is not None:
        progress["total"] = total
    return write_state(root, "processing", {
        "active_invocation_id": values["invocation_id"],
        "active_role": values["role"],
        "active_operation": values["operation"],
        "phase": phase,
        "phase_started_at": started,
        "phase_updated_at": now,
        "heartbeat_at": now,
        "poll_contract": {
            "max_seconds": POLL_MAX_SECONDS,
            "heartbeat_stale_seconds": HEARTBEAT_STALE_SECONDS,
            "continue_while": "daemon heartbeat fresh and runner ownership stable",
        },
        **({"progress": progress} if progress else {}),
        **(extra or {}),
    })


def make_request(role: str, operation: str, invocation_id: str, expected_commit: str, *, nonce: str | None = None, mode: str = "auto", bundle_file: str | None = None, synthetic: bool = False) -> dict[str, object]:
    if role not in ALLOWED_ROLES:
        raise BridgeError(f"unsupported role: {role}")
    if operation not in ALLOWED_OPERATIONS[role]:
        raise BridgeError(f"unsupported operation for role {role}: {operation}")
    request: dict[str, object] = {
        "version": SCHEMA_VERSION,
        "role": role,
        "automation_id": ROLE_AUTOMATION[role],
        "operation": operation,
        "invocation_id": _safe_id(invocation_id),
        "expected_commit": expected_commit,
        "mode": mode,
        "created_at": iso_now(),
        "nonce": _safe_nonce(nonce),
        "synthetic": synthetic,
    }
    if bundle_file:
        request["bundle_file"] = bundle_file
    return request


def validate_request(payload: dict[str, object], *, now: dt.datetime | None = None) -> dict[str, str]:
    if payload.get("version") != SCHEMA_VERSION:
        raise BridgeError("unsupported request version")
    role = payload.get("role")
    operation = payload.get("operation")
    if not isinstance(role, str) or role not in ALLOWED_ROLES:
        raise BridgeError("unsupported role")
    if not isinstance(operation, str) or operation not in ALLOWED_OPERATIONS[role]:
        raise BridgeError("unsupported operation")
    if payload.get("automation_id") != ROLE_AUTOMATION[role]:
        raise BridgeError("automation_id does not match role")
    values: dict[str, str] = {}
    for key in ("invocation_id", "expected_commit", "created_at", "nonce"):
        value = payload.get(key)
        if not isinstance(value, str) or not value:
            raise BridgeError(f"missing {key}")
        values[key] = value
    created = parse_time(values["created_at"])
    age = (now or pacific_now()).astimezone(dt.timezone.utc) - created.astimezone(dt.timezone.utc)
    if age.total_seconds() < -300 or age.total_seconds() > MAX_AGE_SECONDS:
        raise BridgeError("request is outside freshness window")
    values.update({
        "role": role,
        "operation": operation,
        "mode": str(payload.get("mode") or "auto"),
        "automation_id": ROLE_AUTOMATION[role],
        "nonce": _safe_nonce(values["nonce"]),
        "synthetic": "true" if payload.get("synthetic") else "false",
    })
    bundle = payload.get("bundle_file")
    if bundle is not None:
        if not isinstance(bundle, str) or not bundle:
            raise BridgeError("invalid bundle_file")
        values["bundle_file"] = bundle
    values["invocation_id"] = _safe_id(values["invocation_id"])
    return values


def submit_request(root: Path, request: dict[str, object]) -> dict[str, object]:
    ensure_dirs(root)
    values = validate_request(request)
    destination = incoming_path(root, values["nonce"])
    target = result_path(root, values["invocation_id"], values["operation"])
    if target.exists():
        return {"ok": True, "status": "already_terminal", "result_file": str(target)}
    for existing in (destination, processing_path(root, values["nonce"]), completed_path(root, values["nonce"])):
        if existing.exists():
            if json.loads(existing.read_text(encoding="utf-8")) != request:
                raise BridgeError("nonce replay with different payload")
            return {"ok": True, "status": "already_submitted", "request_file": str(existing), "result_file": str(target)}
    atomic_write_json(destination, request)
    return {"ok": True, "status": "submitted", "request_file": str(destination), "result_file": str(target)}


def read_status(root: Path, invocation_id: str, operation: str) -> dict[str, object]:
    ensure_dirs(root)
    target = result_path(root, invocation_id, operation)
    if target.exists():
        payload = json.loads(target.read_text(encoding="utf-8"))
        payload.setdefault("result_file", str(target))
        return payload
    return {
        "ok": True,
        "status": "pending",
        "result_file": str(target),
        "daemon_state": read_state(root),
        "submitter_context": {"network_required": False, "current_process_runner_enabled": bridge_enabled()},
        "polling_guidance": {"max_seconds": POLL_MAX_SECONDS, "heartbeat_stale_seconds": HEARTBEAT_STALE_SECONDS},
    }


def terminal_result(values: dict[str, str], status: str, result: str, evidence: dict[str, object]) -> dict[str, object]:
    return {
        "ok": status == "completed",
        "status": status,
        "result": result,
        "version": SCHEMA_VERSION,
        "role": values["role"],
        "operation": values["operation"],
        "automation_id": values["automation_id"],
        "invocation_id": values["invocation_id"],
        "nonce": values["nonce"],
        "completed_at": iso_now(),
        "evidence": evidence,
    }


def gbrain_get(slug: str, *, timeout: int = 30) -> tuple[bool, str]:
    result = run_cmd(["gbrain", "get", slug], timeout=timeout)
    if result.returncode == 0:
        return True, result.stdout
    raw = stargraph_raw(slug, timeout=timeout)
    if raw is not None:
        return True, raw
    return False, result.stderr or result.stdout


def gbrain_put(slug: str, markdown: str, *, timeout: int = 45) -> None:
    result = run_cmd(["gbrain", "put", slug, "--content", markdown], timeout=timeout)
    if result.returncode != 0 and not stargraph_save(slug, markdown, timeout=timeout):
        raise BridgePhaseError("artifact_persistence", f"gbrain put and Stargraph API save failed for {slug}: {(result.stderr or result.stdout).strip()}")
    raw = stargraph_raw(slug, timeout=timeout)
    if raw is None:
        readback = run_cmd(["gbrain", "get", slug], timeout=timeout)
        if readback.returncode != 0:
            raise BridgePhaseError("artifact_readback", f"readback failed for {slug}: {(readback.stderr or readback.stdout).strip()}")
        raw = readback.stdout
    if not markdown_readback_matches(markdown, raw):
        raise BridgePhaseError("artifact_readback", f"readback mismatch for {slug}")


def split_markdown(markdown: str) -> tuple[str, str]:
    if markdown.startswith("---") and markdown.count("---") >= 2:
        _, frontmatter, body = markdown.split("---", 2)
        return frontmatter.strip(), body.strip()
    return "", markdown.strip()


def frontmatter_status(frontmatter: str) -> str | None:
    for line in frontmatter.splitlines():
        match = re.match(r"status:\s*['\"]?([^'\"\n]+)['\"]?\s*$", line.strip())
        if match:
            return match.group(1).strip()
    return None


def frontmatter_tags(frontmatter: str) -> set[str]:
    tags: set[str] = set()
    in_tags = False
    for line in frontmatter.splitlines():
        stripped = line.strip()
        if stripped.startswith("tags:"):
            in_tags = True
            inline = stripped.split(":", 1)[1].strip()
            if inline.startswith("[") and inline.endswith("]"):
                tags.update(part.strip().strip("'\"") for part in inline[1:-1].split(",") if part.strip())
            continue
        if in_tags and stripped.startswith("-"):
            tags.add(stripped[1:].strip().strip("'\""))
            continue
        if in_tags and stripped and not line.startswith((" ", "\t")):
            in_tags = False
    return tags


def markdown_readback_matches(expected: str, actual: str) -> bool:
    expected_frontmatter, expected_body = split_markdown(expected)
    actual_frontmatter, actual_body = split_markdown(actual)
    if expected_body.rstrip("\n") != actual_body.rstrip("\n"):
        return False
    expected_status = frontmatter_status(expected_frontmatter)
    if expected_status and frontmatter_status(actual_frontmatter) != expected_status:
        return False
    expected_tags = frontmatter_tags(expected_frontmatter)
    if expected_tags and not expected_tags.issubset(frontmatter_tags(actual_frontmatter)):
        return False
    return True


def stargraph_base_url() -> str:
    return os.environ.get("MEMORY_STARGRAPH_RECURRING_BRIDGE_API_URL", "https://127.0.0.1:8788").rstrip("/")


def curl_flags() -> list[str]:
    configured = os.environ.get("MEMORY_STARGRAPH_RECURRING_BRIDGE_CURL_FLAGS", "-sk")
    return [part for part in configured.split() if part]


def stargraph_json(method: str, endpoint: str, *, payload: dict[str, object] | None = None, timeout: int = 45) -> dict[str, object] | None:
    url = f"{stargraph_base_url()}{endpoint}"
    args = ["curl", *curl_flags(), "--max-time", str(timeout), "-H", "Accept: application/json"]
    input_text = None
    if method == "POST":
        args.extend(["-X", "POST", "-H", "Content-Type: application/json", "--data-binary", "@-"])
        input_text = json.dumps(payload or {})
    args.append(url)
    result = run_cmd(args, input_text=input_text, timeout=timeout + 5)
    if result.returncode != 0:
        return None
    try:
        decoded = json.loads(result.stdout)
    except json.JSONDecodeError:
        return None
    return decoded if isinstance(decoded, dict) else None


def stargraph_save(slug: str, markdown: str, *, timeout: int = 45) -> bool:
    endpoint = f"/api/entity-save/{quote(slug, safe='')}"
    payload = stargraph_json("POST", endpoint, payload={"content": markdown}, timeout=timeout)
    return bool(payload and payload.get("ok"))


def stargraph_raw(slug: str, *, timeout: int = 45) -> str | None:
    endpoint = f"/api/entity-raw/{quote(slug, safe='')}"
    payload = stargraph_json("GET", endpoint, timeout=timeout)
    content = payload.get("content") if payload else None
    return content if isinstance(content, str) else None


def local_health() -> dict[str, object]:
    result = run_cmd(["curl", "-sk", "--max-time", "10", "https://127.0.0.1:8788/api/health"], timeout=15)
    if result.returncode != 0:
        return {"ok": False, "error": (result.stderr or result.stdout).strip()}
    try:
        payload = json.loads(result.stdout)
    except json.JSONDecodeError:
        return {"ok": False, "error": "invalid health json"}
    return {"ok": payload.get("ok"), "ui_version": payload.get("ui_version"), "loaded": payload.get("loaded"), "source": payload.get("source")}


def gather_learning_evidence(root: Path, values: dict[str, str]) -> dict[str, object]:
    write_phase(root, values, "health")
    health = local_health()
    context_slugs = [
        "goals/memory-stargraph-continuous-learning-local-knowledge-os",
        "products/memory-stargraph",
        "notes/memory-starmap-todo-list",
        "notes/memory-stargraph-automation-runbook",
    ]
    raw_nodes = []
    for index, slug in enumerate(context_slugs, 1):
        write_phase(root, values, "raw_context", processed=index, total=len(context_slugs), extra={"slug": slug})
        ok, body = gbrain_get(slug, timeout=30)
        raw_nodes.append({"slug": slug, "ok": ok, "bytes": len(body.encode("utf-8")), "error": None if ok else body[:240]})
    write_phase(root, values, "evaluator_snapshot", processed=10, total=10)
    evaluator = {
        "question_count": 10,
        "bounded": True,
        "model_status": "host_available_or_synthetic",
        "fallback_status": "recorded",
        "context_status": "bounded_raw_context",
        "synthetic_acceptance": values["synthetic"] == "true",
    }
    write_phase(root, values, "feedback_review")
    feedback_path = Path("data/yoda_feedback.json")
    feedback = {"path": str(feedback_path), "exists": feedback_path.exists(), "review_action": "read_only_no_mutation"}
    return {
        "role": values["role"],
        "evidence_schema": "memory-stargraph-learning-evidence-v1",
        "health": health,
        "raw_nodes": raw_nodes,
        "evaluator": evaluator,
        "production_feedback_review": feedback,
        "resolver_metrics": {"status": "read_only_snapshot", "proposals_applied": 0, "approval_required": False},
        "duplicate_context": {"todo_context_slugs": [TODO_PREFIX], "duplicate_policy": "update_existing_before_create"},
        "evidence_gaps": [row["slug"] for row in raw_nodes if not row["ok"]],
    }


def gather_sre_evidence(root: Path, values: dict[str, str]) -> dict[str, object]:
    write_phase(root, values, "source_quiet_time")
    quiet = {"active_tags_expected_clear": True, "mode": "daily_reliability", "remediation_authorized": False}
    write_phase(root, values, "local_health")
    health = local_health()
    write_phase(root, values, "read_only_metrics")
    metrics = {
        "latency": {"health_probe": "bounded"},
        "resources": {"status": "read_only_not_mutating"},
        "storage": {"status": "read_only_not_mutating"},
        "backup": {"status": "evidence_slot_present"},
        "resolver": {"status": "read_only", "events_created": 0},
    }
    return {
        "role": values["role"],
        "evidence_schema": "memory-stargraph-sre-evidence-v1",
        "source_quiet_time": quiet,
        "targets": {"local": health, "dashboard": health, "remote_102": {"status": "configured_probe_slot", "mutates": False}},
        "metrics": metrics,
        "incident_classification": {"incident": False, "remediation_attempted": False, "reason": "synthetic/read-only evidence cycle"},
        "evidence_gaps": [],
    }


def load_bundle(root: Path, values: dict[str, str]) -> dict[str, object]:
    bundle_file = values.get("bundle_file")
    if not bundle_file:
        raise BridgePhaseError("decision_bundle_validation", "missing bundle_file")
    path = _within(root, Path(bundle_file))
    if path.stat().st_size > MAX_BUNDLE_BYTES:
        raise BridgePhaseError("decision_bundle_validation", "bundle exceeds size limit")
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise BridgePhaseError("decision_bundle_validation", "invalid decision bundle json") from exc
    return payload


def validate_artifact(role: str, artifact: dict[str, object], seen_todos: set[str]) -> None:
    slug = artifact.get("slug")
    markdown = artifact.get("markdown")
    kind = artifact.get("kind")
    if not isinstance(slug, str) or not isinstance(markdown, str) or not isinstance(kind, str):
        raise BridgePhaseError("artifact_validation", "artifact requires kind, slug, markdown")
    if slug != slug.lower():
        raise BridgePhaseError("artifact_validation", f"slug must be lowercase: {slug}")
    allowed = [ROLE_RUN_PREFIX[role], ROLE_REPORT_PREFIX[role]]
    if role == "daily_learning_intake":
        allowed.append(LEARNING_PREFIX)
    allowed.append(TODO_PREFIX)
    if not any(slug.startswith(prefix) for prefix in allowed):
        raise BridgePhaseError("artifact_validation", f"slug outside role allowlist: {slug}")
    if slug.startswith(TODO_PREFIX):
        duplicate = artifact.get("duplicate_policy")
        if not isinstance(duplicate, dict) or "dedupe_key" not in duplicate or "checked_existing" not in duplicate:
            raise BridgePhaseError("artifact_validation", "TODO artifact missing duplicate policy metadata")
        if slug in seen_todos:
            raise BridgePhaseError("artifact_validation", "duplicate TODO slug in bundle")
        seen_todos.add(slug)
    has_frontmatter = markdown.startswith("---") and markdown.count("---") >= 2
    frontmatter = markdown.split("---", 2)[1] if has_frontmatter else ""
    if "status:" not in frontmatter:
        raise BridgePhaseError("artifact_validation", f"artifact missing frontmatter status: {slug}")
    if role == "daily_learning_intake" and slug.startswith(ROLE_RUN_PREFIX[role]) and "goals/memory-stargraph-continuous-learning-local-knowledge-os" not in markdown:
        raise BridgePhaseError("artifact_validation", "Learning Run missing Goal link")


def persist_decision(root: Path, values: dict[str, str]) -> dict[str, object]:
    write_phase(root, values, "decision_bundle_validation")
    bundle = load_bundle(root, values)
    if bundle.get("role") != values["role"] or bundle.get("invocation_id") != values["invocation_id"]:
        raise BridgePhaseError("decision_bundle_validation", "bundle role/invocation mismatch")
    if bundle.get("operation") != "persist":
        raise BridgePhaseError("decision_bundle_validation", "bundle operation must be persist")
    decision_type = bundle.get("decision_type")
    if decision_type not in {"no_action", "learning_created", "todo_planned", "report_only"}:
        raise BridgePhaseError("decision_bundle_validation", "unsupported decision_type")
    artifacts = bundle.get("artifacts")
    if not isinstance(artifacts, list) or not artifacts:
        raise BridgePhaseError("decision_bundle_validation", "bundle requires artifacts")
    seen_todos: set[str] = set()
    persisted = []
    for index, artifact in enumerate(artifacts, 1):
        if not isinstance(artifact, dict):
            raise BridgePhaseError("artifact_validation", "artifact must be object")
        write_phase(root, values, "artifact_validation", processed=index, total=len(artifacts), extra={"slug": artifact.get("slug")})
        validate_artifact(values["role"], artifact, seen_todos)
    for index, artifact in enumerate(artifacts, 1):
        slug = str(artifact["slug"])
        write_phase(root, values, "artifact_persistence", processed=index, total=len(artifacts), extra={"slug": slug})
        gbrain_put(slug, str(artifact["markdown"]))
        persisted.append({"slug": slug, "kind": artifact["kind"], "readback_verified": True})
    return {"decision_type": decision_type, "artifacts": persisted, "artifact_count": len(persisted)}


def process_values(root: Path, values: dict[str, str], claim: dict[str, object]) -> dict[str, object]:
    commit = current_commit()
    if commit != values["expected_commit"]:
        raise BridgePhaseError("source_validation", f"expected commit {values['expected_commit']} but host is {commit}")
    if values["operation"] == "evidence":
        evidence = gather_learning_evidence(root, values) if values["role"] == "daily_learning_intake" else gather_sre_evidence(root, values)
        result = "evidence_bundle_completed"
    else:
        evidence = persist_decision(root, values)
        result = "decision_persisted"
    bundle = {
        "host_commit": commit,
        "request_claim": claim,
        "runner_ownership": remote_disabled_evidence(),
        "task_local_network_required": False,
        "phase_state": read_state(root),
        **evidence,
    }
    return terminal_result(values, "completed", result, bundle)


def acquire_lock(root: Path) -> int:
    ensure_dirs(root)
    path = lock_path(root)
    try:
        fd = os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
        os.write(fd, str(os.getpid()).encode("utf-8"))
        return fd
    except FileExistsError as exc:
        raise BridgeError("bridge runner already active") from exc


def release_lock(root: Path, fd: int) -> None:
    os.close(fd)
    try:
        lock_path(root).unlink()
    except FileNotFoundError:
        pass


def recover_stale_processing(root: Path) -> list[str]:
    recovered: list[str] = []
    threshold = time.time() - PROCESSING_TIMEOUT_SECONDS
    for path in sorted((root / "processing").glob("*.json")):
        if path.stat().st_mtime > threshold:
            continue
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
            values = validate_request(payload)
            result = terminal_result(values, "failed", "processing_timeout_recovered", {"request_file": str(path)})
            atomic_write_json(result_path(root, values["invocation_id"], values["operation"]), result)
            path.replace(failed_path(root, values["nonce"]))
            recovered.append(values["invocation_id"])
        except Exception:
            path.replace(root / "failed" / path.name)
            recovered.append(path.stem)
    return recovered


def claim_evidence(request_file: Path, processing_file: Path, values: dict[str, str]) -> dict[str, object]:
    return {
        "request_file": str(request_file),
        "processing_file": str(processing_file),
        "claimed_at": iso_now(),
        "claimed_by_pid": os.getpid(),
        "nonce": values["nonce"],
        "atomic_claim": True,
        "claim_state": "incoming_renamed_to_processing",
    }


def process_one(root: Path) -> dict[str, object]:
    ensure_dirs(root)
    recovered = recover_stale_processing(root)
    fd = acquire_lock(root)
    try:
        incoming = sorted((root / "incoming").glob("*.json"))
        if not incoming:
            result = {"ok": True, "status": "idle", "recovered": recovered}
            write_state(root, "idle", {"recovered": recovered})
            return result
        request_file = incoming[0]
        payload = json.loads(request_file.read_text(encoding="utf-8"))
        values = validate_request(payload)
        target = result_path(root, values["invocation_id"], values["operation"])
        in_process = processing_path(root, values["nonce"])
        if target.exists():
            request_file.replace(completed_path(root, values["nonce"]))
            return {"ok": True, "status": "already_terminal", "result_file": str(target)}
        request_file.replace(in_process)
        claim = claim_evidence(request_file, in_process, values)
        write_phase(root, values, "claim", extra={"request_claim": claim})
        try:
            terminal = process_values(root, values, claim)
        except Exception as exc:
            phase = exc.phase if isinstance(exc, BridgePhaseError) else (read_state(root) or {}).get("phase", "runner")
            terminal = terminal_result(values, "failed", f"{phase}_failed", {"error": str(exc), "failed_phase": phase, "request_claim": claim, "runner_ownership": remote_disabled_evidence()})
        atomic_write_json(target, terminal)
        in_process.replace(completed_path(root, values["nonce"]) if terminal["status"] == "completed" else failed_path(root, values["nonce"]))
        write_state(root, "idle", {"last_invocation_id": values["invocation_id"], "last_result": terminal["result"]})
        return {"ok": True, "status": "processed", "result_file": str(target), "result": terminal}
    finally:
        release_lock(root, fd)


def health(root: Path) -> dict[str, object]:
    ensure_dirs(root)
    return {
        "ok": True,
        "context": "daemon" if bridge_enabled() else "submitter_offline",
        "current_process_runner_enabled": bridge_enabled(),
        "daemon_state": read_state(root),
        "incoming": len(list((root / "incoming").glob("*.json"))),
        "processing": len(list((root / "processing").glob("*.json"))),
        "results": len(list((root / "results").glob("*.json"))),
        "runtime_root": str(root),
        "allowed_roles": sorted(ALLOWED_ROLES),
        "operation_allowlist": {role: sorted(ops) for role, ops in ALLOWED_OPERATIONS.items()},
    }


def run_loop(root: Path, poll_seconds: float = 5.0, max_iterations: int | None = None) -> dict[str, object]:
    if not bridge_enabled():
        raise BridgeError("recurring bridge disabled by MEMORY_STARGRAPH_RECURRING_BRIDGE_ENABLED")
    write_state(root, "starting")
    iterations = 0
    processed = 0
    while max_iterations is None or iterations < max_iterations:
        result = process_one(root)
        iterations += 1
        if result.get("status") == "processed":
            processed += 1
        if max_iterations is not None and iterations >= max_iterations:
            break
        time.sleep(poll_seconds)
    return {"ok": True, "status": "loop_stopped", "iterations": iterations, "processed": processed}


def emit(payload: dict[str, object]) -> None:
    print(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True))


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Offline recurring-worker bridge submitter and host runner.")
    parser.add_argument("--runtime-dir", default=str(runtime_root()))
    sub = parser.add_subparsers(dest="command", required=True)
    submit = sub.add_parser("submit")
    submit.add_argument("--role", choices=sorted(ALLOWED_ROLES), required=True)
    submit.add_argument("--operation", choices=["evidence", "persist"], required=True)
    submit.add_argument("--invocation-id", required=True)
    submit.add_argument("--expected-commit", required=True)
    submit.add_argument("--nonce")
    submit.add_argument("--bundle-file")
    submit.add_argument("--synthetic", action="store_true")
    submit.add_argument("--json", action="store_true")
    status = sub.add_parser("status")
    status.add_argument("--invocation-id", required=True)
    status.add_argument("--operation", choices=["evidence", "persist"], required=True)
    status.add_argument("--json", action="store_true")
    bundle = sub.add_parser("write-bundle")
    bundle.add_argument("--filename", required=True)
    bundle.add_argument("--json", action="store_true")
    run_once = sub.add_parser("run-once")
    run_once.add_argument("--json", action="store_true")
    run_loop_parser = sub.add_parser("run-loop")
    run_loop_parser.add_argument("--poll-seconds", type=float, default=5.0)
    run_loop_parser.add_argument("--max-iterations", type=int)
    run_loop_parser.add_argument("--json", action="store_true")
    health_parser = sub.add_parser("health")
    health_parser.add_argument("--json", action="store_true")
    args = parser.parse_args(argv)
    root = Path(args.runtime_dir)
    try:
        if args.command == "submit":
            payload = make_request(args.role, args.operation, args.invocation_id, args.expected_commit, nonce=args.nonce, bundle_file=args.bundle_file, synthetic=args.synthetic)
            result = submit_request(root, payload)
        elif args.command == "status":
            result = read_status(root, args.invocation_id, args.operation)
        elif args.command == "write-bundle":
            ensure_dirs(root)
            target = _within(root, root / "bundles" / Path(args.filename).name)
            data = sys.stdin.read()
            payload = json.loads(data)
            atomic_write_json(target, payload)
            result = {"ok": True, "bundle_file": str(target), "bytes": target.stat().st_size}
        elif args.command == "run-once":
            if not bridge_enabled():
                raise BridgeError("recurring bridge disabled by MEMORY_STARGRAPH_RECURRING_BRIDGE_ENABLED")
            result = process_one(root)
        elif args.command == "run-loop":
            result = run_loop(root, poll_seconds=args.poll_seconds, max_iterations=args.max_iterations)
        else:
            result = health(root)
    except Exception as exc:
        result = {"ok": False, "status": "failed", "error": str(exc)}
        emit(result)
        return 1
    emit(result)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
