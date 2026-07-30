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
from zoneinfo import ZoneInfo

if __package__ in {None, ""}:
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from scripts.automation import manage_capture_backlog as capture
from scripts.automation.worker_persistence import _raw_readback_matches


PACIFIC = ZoneInfo("America/Los_Angeles")
SCHEMA_VERSION = 1
OPERATION = "capture_link_drain"
AUTOMATION_ID = "memory-stargraph-capture-link-drain"
MAX_REQUEST_BYTES = 8192
MAX_AGE_SECONDS = 6 * 60 * 60
PROCESSING_TIMEOUT_SECONDS = 45 * 60
MAX_LOG_BYTES = 512 * 1024
DEFAULT_MODE = "auto"
ALLOWED_MODES = {"auto", "capture_drain", "empty_queue_enrichment"}


class RunnerError(RuntimeError):
    pass


def pacific_now() -> dt.datetime:
    return dt.datetime.now(dt.timezone.utc).astimezone(PACIFIC).replace(microsecond=0)


def iso_now() -> str:
    return pacific_now().isoformat()


def runtime_root() -> Path:
    configured = os.environ.get("MEMORY_STARGRAPH_CAPTURE_RUNNER_DIR")
    if configured:
        return Path(configured).expanduser()
    return Path("var") / "capture-link-runner"


def _safe_id(value: str) -> str:
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._:-]{7,127}", value):
        raise RunnerError(f"unsafe identifier: {value!r}")
    return value


def _safe_nonce(value: str | None = None) -> str:
    nonce = value or uuid.uuid4().hex
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]{7,127}", nonce):
        raise RunnerError("nonce must be 8-128 safe filename characters")
    return nonce


def _within(root: Path, path: Path) -> Path:
    resolved_root = root.resolve()
    resolved = path.resolve()
    if resolved != resolved_root and resolved_root not in resolved.parents:
        raise RunnerError(f"path escapes runtime root: {path}")
    return resolved


def ensure_dirs(root: Path) -> None:
    for name in ("incoming", "processing", "results", "completed", "failed", "locks", "logs"):
        path = root / name
        path.mkdir(parents=True, exist_ok=True)
        try:
            path.chmod(0o700)
        except PermissionError:
            pass


def result_path(root: Path, invocation_id: str) -> Path:
    return _within(root, root / "results" / f"{_safe_id(invocation_id)}.json")


def incoming_path(root: Path, nonce: str) -> Path:
    return _within(root, root / "incoming" / f"{_safe_nonce(nonce)}.json")


def processing_path(root: Path, nonce: str) -> Path:
    return _within(root, root / "processing" / f"{_safe_nonce(nonce)}.json")


def completed_path(root: Path, nonce: str) -> Path:
    return _within(root, root / "completed" / f"{_safe_nonce(nonce)}.json")


def failed_path(root: Path, nonce: str) -> Path:
    return _within(root, root / "failed" / f"{_safe_nonce(nonce)}.json")


def lock_path(root: Path) -> Path:
    return _within(root, root / "locks" / "capture_link_drain.lock")


def log_path(root: Path) -> Path:
    return _within(root, root / "logs" / "runner.jsonl")


def parse_time(value: str) -> dt.datetime:
    try:
        parsed = dt.datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise RunnerError(f"invalid timestamp: {value}") from exc
    if parsed.tzinfo is None:
        raise RunnerError("timestamp must be timezone-aware")
    return parsed


def current_commit() -> str:
    result = subprocess.run(["git", "rev-parse", "HEAD"], text=True, capture_output=True, check=False)
    if result.returncode != 0:
        raise RunnerError((result.stderr or result.stdout).strip() or "git rev-parse failed")
    return result.stdout.strip()


def run_gbrain(args: list[str], input_text: str | None = None, timeout: int = 120) -> subprocess.CompletedProcess[str]:
    try:
        return subprocess.run(
            ["gbrain", *args],
            input=input_text,
            text=True,
            capture_output=True,
            timeout=timeout,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        return subprocess.CompletedProcess(args, 127, "", str(exc))


def result_error(result: subprocess.CompletedProcess[str]) -> str:
    return (result.stderr or result.stdout).strip()


def put_entity(slug: str, markdown: str) -> None:
    result = run_gbrain(["put", slug], input_text=markdown, timeout=180)
    if result.returncode != 0:
        raise RunnerError(f"gbrain put failed for {slug}: {result_error(result)}")
    readback = run_gbrain(["get", slug], timeout=120)
    if readback.returncode != 0:
        raise RunnerError(f"gbrain get failed for {slug}: {result_error(readback)}")
    if not _raw_readback_matches(markdown, readback.stdout):
        raise RunnerError(f"gbrain readback mismatch for {slug}")


def mutate_tag(slug: str, tag: str, action: str) -> None:
    command = "tag" if action == "add" else "untag"
    result = run_gbrain([command, slug, tag], timeout=60)
    if result.returncode != 0 and not (action == "remove" and "not found" in result_error(result).lower()):
        raise RunnerError(f"gbrain {command} failed for {slug}: {result_error(result)}")


def read_tags(slug: str) -> list[str]:
    result = run_gbrain(["tags", slug], timeout=60)
    if result.returncode != 0:
        raise RunnerError(f"gbrain tags failed for {slug}: {result_error(result)}")
    tags: list[str] = []
    for line in result.stdout.splitlines():
        cleaned = line.strip().lstrip("-").strip()
        for item in cleaned.split(","):
            tag = item.strip()
            if tag:
                tags.append(tag)
    return tags


def lifecycle_slugs(values: dict[str, str]) -> tuple[str, str]:
    date = pacific_now().strftime("%Y-%m-%d")
    suffix = _safe_id(values["invocation_id"])
    return (
        f"runs/memory-stargraph-capture-link-drain-{suffix}",
        f"reports/memory-stargraph-capture-link-drain-{date}-{suffix}",
    )


def markdown_list(items: list[str]) -> str:
    return "\n".join(f"  - {item}" for item in items) if items else "  []"


def build_run_markdown(
    values: dict[str, str],
    run_slug: str,
    report_slug: str,
    *,
    status: str,
    result: str,
    evidence: dict[str, object] | None = None,
) -> str:
    active = status == "running"
    tags = ["capture-link", "curator", "host-runner"]
    if active:
        tags.append("active")
    else:
        tags.append(status)
    evidence_block = json.dumps(evidence or {}, ensure_ascii=False, indent=2, sort_keys=True)
    return f"""---
type: run
title: Capture Link host drain {values["invocation_id"]}
status: {status}
result: {result}
automation_id: {AUTOMATION_ID}
invocation_id: {values["invocation_id"]}
operation: {OPERATION}
expected_commit: {values["expected_commit"]}
curator_lease: {str(active).lower()}
active_change: false
started_at: '{values["created_at"]}'
completed_at: '{iso_now() if not active else ""}'
report_slug: {report_slug}
tags:
{markdown_list(tags)}
---

# Capture Link host drain {values["invocation_id"]}

Report: [[{report_slug}]]

## Evidence

```json
{evidence_block}
```
"""


def build_report_markdown(
    values: dict[str, str],
    run_slug: str,
    report_slug: str,
    *,
    status: str,
    result: str,
    evidence: dict[str, object],
) -> str:
    evidence_block = json.dumps(evidence, ensure_ascii=False, indent=2, sort_keys=True)
    return f"""---
type: report
title: Capture Link host runner report {values["invocation_id"]}
status: {status}
result: {result}
automation_id: {AUTOMATION_ID}
invocation_id: {values["invocation_id"]}
operation: {OPERATION}
run_slug: {run_slug}
created_at: '{iso_now()}'
tags:
- capture-link
- curator
- host-runner
- {status}
---

# Capture Link host runner report {values["invocation_id"]}

Run: [[{run_slug}]]

## Evidence

```json
{evidence_block}
```
"""


def create_active_lifecycle(values: dict[str, str]) -> tuple[str, str]:
    run_slug, report_slug = lifecycle_slugs(values)
    put_entity(
        run_slug,
        build_run_markdown(
            values,
            run_slug,
            report_slug,
            status="running",
            result="active",
            evidence={"request": values, "runner": "host-managed-spool"},
        ),
    )
    mutate_tag(run_slug, "active", "add")
    return run_slug, report_slug


def terminalize_lifecycle(
    values: dict[str, str],
    run_slug: str,
    report_slug: str,
    status: str,
    result: str,
    evidence: dict[str, object],
) -> dict[str, object]:
    lifecycle = {
        **evidence,
        "run_slug": run_slug,
        "report_slug": report_slug,
    }
    put_entity(
        run_slug,
        build_run_markdown(values, run_slug, report_slug, status=status, result=result, evidence=lifecycle),
    )
    put_entity(
        report_slug,
        build_report_markdown(values, run_slug, report_slug, status=status, result=result, evidence=lifecycle),
    )
    mutate_tag(run_slug, "active", "remove")
    tags = read_tags(run_slug)
    if "active" in tags:
        raise RunnerError(f"active tag release failed for {run_slug}")
    return {**lifecycle, "lifecycle_tags_released": True, "run_tags_after_release": tags}


def make_request(invocation_id: str, expected_commit: str, mode: str, nonce: str | None = None) -> dict[str, object]:
    if mode not in ALLOWED_MODES:
        raise RunnerError(f"unsupported mode: {mode}")
    return {
        "version": SCHEMA_VERSION,
        "operation": OPERATION,
        "invocation_id": _safe_id(invocation_id),
        "automation_id": AUTOMATION_ID,
        "expected_commit": expected_commit,
        "mode": mode,
        "created_at": iso_now(),
        "nonce": _safe_nonce(nonce),
    }


def validate_request(payload: dict[str, object], *, now: dt.datetime | None = None) -> dict[str, str]:
    values = {
        "version": payload.get("version"),
        "operation": payload.get("operation"),
        "invocation_id": payload.get("invocation_id"),
        "automation_id": payload.get("automation_id"),
        "expected_commit": payload.get("expected_commit"),
        "mode": payload.get("mode", DEFAULT_MODE),
        "created_at": payload.get("created_at"),
        "nonce": payload.get("nonce"),
    }
    if values["version"] != SCHEMA_VERSION:
        raise RunnerError("unsupported request version")
    if values["operation"] != OPERATION:
        raise RunnerError("unsupported operation")
    if values["automation_id"] != AUTOMATION_ID:
        raise RunnerError("unsupported automation_id")
    for key in ("invocation_id", "expected_commit", "mode", "created_at", "nonce"):
        if not isinstance(values[key], str) or not values[key]:
            raise RunnerError(f"missing {key}")
    if str(values["mode"]) not in ALLOWED_MODES:
        raise RunnerError("unsupported mode")
    created = parse_time(str(values["created_at"]))
    age = (now or pacific_now()).astimezone(dt.timezone.utc) - created.astimezone(dt.timezone.utc)
    if age.total_seconds() < -300 or age.total_seconds() > MAX_AGE_SECONDS:
        raise RunnerError("request is outside freshness window")
    return {
        "invocation_id": _safe_id(str(values["invocation_id"])),
        "expected_commit": str(values["expected_commit"]),
        "mode": str(values["mode"]),
        "created_at": str(values["created_at"]),
        "nonce": _safe_nonce(str(values["nonce"])),
    }


def atomic_write_json(path: Path, payload: dict[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_name(f".{path.name}.{uuid.uuid4().hex}.tmp")
    data = json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    if len(data.encode("utf-8")) > MAX_REQUEST_BYTES and path.parent.name == "incoming":
        raise RunnerError("request exceeds size limit")
    temp.write_text(data, encoding="utf-8")
    try:
        temp.chmod(0o600)
    except PermissionError:
        pass
    temp.replace(path)


def submit_request(root: Path, request: dict[str, object]) -> dict[str, object]:
    ensure_dirs(root)
    values = validate_request(request)
    destination = incoming_path(root, values["nonce"])
    existing_result = result_path(root, values["invocation_id"])
    if existing_result.exists():
        return {"ok": True, "status": "already_terminal", "result_file": str(existing_result)}
    for existing in (destination, processing_path(root, values["nonce"]), completed_path(root, values["nonce"])):
        if existing.exists():
            existing_payload = json.loads(existing.read_text(encoding="utf-8"))
            if existing_payload != request:
                raise RunnerError("nonce replay with different payload")
            return {
                "ok": True,
                "status": "already_submitted",
                "request_file": str(existing),
                "result_file": str(existing_result),
            }
    atomic_write_json(destination, request)
    return {"ok": True, "status": "submitted", "request_file": str(destination), "result_file": str(existing_result)}


def read_status(root: Path, invocation_id: str) -> dict[str, object]:
    ensure_dirs(root)
    target = result_path(root, invocation_id)
    if target.exists():
        payload = json.loads(target.read_text(encoding="utf-8"))
        payload.setdefault("result_file", str(target))
        return payload
    return {"ok": True, "status": "pending", "result_file": str(target)}


def acquire_lock(root: Path) -> int:
    ensure_dirs(root)
    path = lock_path(root)
    try:
        return os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
    except FileExistsError as exc:
        raise RunnerError("runner already active") from exc


def release_lock(root: Path, fd: int) -> None:
    os.close(fd)
    try:
        lock_path(root).unlink()
    except FileNotFoundError:
        pass


def recover_stale_processing(root: Path, now: dt.datetime | None = None) -> list[str]:
    ensure_dirs(root)
    recovered: list[str] = []
    threshold = (now or pacific_now()).timestamp() - PROCESSING_TIMEOUT_SECONDS
    for path in sorted((root / "processing").glob("*.json")):
        if path.stat().st_mtime > threshold:
            continue
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
            values = validate_request(payload, now=now)
            terminal = terminal_result(values, "failed", "processing_timeout_recovered", {"request_file": str(path)})
            atomic_write_json(result_path(root, values["invocation_id"]), terminal)
            path.replace(failed_path(root, values["nonce"]))
            recovered.append(values["invocation_id"])
        except Exception:
            path.replace(root / "failed" / path.name)
            recovered.append(path.stem)
    return recovered


def terminal_result(values: dict[str, str], status: str, result: str, evidence: dict[str, object]) -> dict[str, object]:
    return {
        "ok": status == "completed",
        "status": status,
        "result": result,
        "version": SCHEMA_VERSION,
        "operation": OPERATION,
        "automation_id": AUTOMATION_ID,
        "invocation_id": values["invocation_id"],
        "nonce": values["nonce"],
        "completed_at": iso_now(),
        "evidence": evidence,
    }


def log_event(root: Path, event: dict[str, object]) -> None:
    ensure_dirs(root)
    path = log_path(root)
    if path.exists() and path.stat().st_size > MAX_LOG_BYTES:
        archive = path.with_suffix(".jsonl.1")
        path.replace(archive)
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps({"at": iso_now(), **event}, ensure_ascii=False, sort_keys=True) + "\n")


def run_capture_link_drain(values: dict[str, str]) -> dict[str, object]:
    commit = current_commit()
    if commit != values["expected_commit"]:
        raise RunnerError(f"expected commit {values['expected_commit']} but host is {commit}")
    run_slug, report_slug = create_active_lifecycle(values)
    first_compaction = capture.apply_compaction()
    snapshot = capture.create_snapshot(invocation_id=values["invocation_id"])
    rows = snapshot.get("rows", [])
    if not isinstance(rows, list):
        raise RunnerError("snapshot rows malformed")
    mode = values["mode"]
    if mode == "capture_drain" and not rows:
        raise RunnerError("mode capture_drain requested but snapshot is empty")
    if mode == "empty_queue_enrichment" and rows:
        raise RunnerError("mode empty_queue_enrichment requested but snapshot is non-empty")
    if rows:
        # The host runner deliberately fails closed for non-empty capture queues until
        # source-specific capture skills are safely moved under the host-side critical section.
        result = "non_empty_snapshot_requires_host_capture_extension"
        status = "failed"
    else:
        result = "completed_empty_snapshot_noop"
        status = "completed"
    final_compaction = capture.apply_compaction()
    evidence = {
        "host_commit": commit,
        "first_compaction": first_compaction,
        "snapshot": snapshot,
        "final_compaction": final_compaction,
        "runner": "host-managed-spool",
        "task_local_network_required": False,
    }
    evidence = terminalize_lifecycle(values, run_slug, report_slug, status, result, evidence)
    return terminal_result(values, status, result, evidence)


def process_one(root: Path) -> dict[str, object]:
    ensure_dirs(root)
    recovered = recover_stale_processing(root)
    fd = acquire_lock(root)
    try:
        incoming = sorted((root / "incoming").glob("*.json"))
        if not incoming:
            result = {"ok": True, "status": "idle", "recovered": recovered}
            log_event(root, result)
            return result
        request_file = incoming[0]
        if request_file.stat().st_size > MAX_REQUEST_BYTES:
            request_file.replace(root / "failed" / request_file.name)
            raise RunnerError("request exceeds size limit")
        payload = json.loads(request_file.read_text(encoding="utf-8"))
        values = validate_request(payload)
        target_result = result_path(root, values["invocation_id"])
        in_process = processing_path(root, values["nonce"])
        if target_result.exists():
            request_file.replace(completed_path(root, values["nonce"]))
            result = {"ok": True, "status": "already_terminal", "result_file": str(target_result), "recovered": recovered}
            log_event(root, result)
            return result
        request_file.replace(in_process)
        try:
            result = run_capture_link_drain(values)
        except Exception as exc:
            result = terminal_result(values, "failed", "runner_error", {"error": str(exc)})
        atomic_write_json(target_result, result)
        in_process.replace(completed_path(root, values["nonce"]) if result.get("status") == "completed" else failed_path(root, values["nonce"]))
        processed = {"ok": True, "status": "processed", "result_file": str(target_result), "result": result, "recovered": recovered}
        log_event(root, {"status": "processed", "result_file": str(target_result), "terminal_status": result.get("status"), "terminal_result": result.get("result")})
        return processed
    finally:
        release_lock(root, fd)


def run_loop(root: Path, poll_seconds: float = 5.0, max_iterations: int | None = None) -> dict[str, object]:
    if os.environ.get("MEMORY_STARGRAPH_CAPTURE_RUNNER_ENABLED", "0") not in {"1", "true", "yes"}:
        raise RunnerError("host runner disabled by MEMORY_STARGRAPH_CAPTURE_RUNNER_ENABLED")
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


def health(root: Path) -> dict[str, object]:
    ensure_dirs(root)
    return {
        "ok": True,
        "runner_enabled": os.environ.get("MEMORY_STARGRAPH_CAPTURE_RUNNER_ENABLED", "0") in {"1", "true", "yes"},
        "runtime_root": str(root),
        "incoming": len(list((root / "incoming").glob("*.json"))),
        "processing": len(list((root / "processing").glob("*.json"))),
        "results": len(list((root / "results").glob("*.json"))),
        "log_file": str(log_path(root)),
        "operation": OPERATION,
    }


def emit(payload: dict[str, object]) -> None:
    print(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True))


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Offline submitter and host runner for Capture Link jobs.")
    parser.add_argument("--runtime-dir", default=str(runtime_root()))
    sub = parser.add_subparsers(dest="command", required=True)
    submit = sub.add_parser("submit", help="Submit an atomic local request file without network access.")
    submit.add_argument("--invocation-id", required=True)
    submit.add_argument("--expected-commit", required=True)
    submit.add_argument("--mode", choices=sorted(ALLOWED_MODES), default=DEFAULT_MODE)
    submit.add_argument("--nonce")
    submit.add_argument("--json", action="store_true")
    status = sub.add_parser("status", help="Read local terminal result.")
    status.add_argument("--invocation-id", required=True)
    status.add_argument("--json", action="store_true")
    run_once = sub.add_parser("run-once", help="Host-side runner processes one request.")
    run_once.add_argument("--json", action="store_true")
    run_loop_parser = sub.add_parser("run-loop", help="Host-side runner loop for launchd/dashboard management.")
    run_loop_parser.add_argument("--poll-seconds", type=float, default=5.0)
    run_loop_parser.add_argument("--max-iterations", type=int)
    run_loop_parser.add_argument("--json", action="store_true")
    health_parser = sub.add_parser("health", help="Report local spool readiness.")
    health_parser.add_argument("--json", action="store_true")
    args = parser.parse_args(argv)
    root = Path(args.runtime_dir)
    try:
        if args.command == "submit":
            payload = make_request(args.invocation_id, args.expected_commit, args.mode, args.nonce)
            result = submit_request(root, payload)
        elif args.command == "status":
            result = read_status(root, args.invocation_id)
        elif args.command == "run-once":
            if os.environ.get("MEMORY_STARGRAPH_CAPTURE_RUNNER_ENABLED", "0") not in {"1", "true", "yes"}:
                raise RunnerError("host runner disabled by MEMORY_STARGRAPH_CAPTURE_RUNNER_ENABLED")
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
