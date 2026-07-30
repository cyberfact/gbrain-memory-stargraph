#!/usr/bin/env python3
"""Persist worker Run/report entities through the Memory Stargraph worker API.

The recurring workers run in environments where direct loopback access to
GBrain/PostgreSQL can be intermittently refused. This module keeps persistence
on the dashboard-managed HTTP route and verifies every mutation by raw readback.
It intentionally shells out to top-level curl so worker logs capture transport
failures exactly.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import shlex
import subprocess
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import quote


DEFAULT_WORKER_API_BASE_URL = "http://127.0.0.1:8788"
DEFAULT_RETRIES = 3


class WorkerPersistenceError(RuntimeError):
    """Raised when bounded worker persistence cannot be verified."""


@dataclass(frozen=True)
class WorkerRoute:
    base_url: str
    curl_flags: tuple[str, ...]
    source: str


def _parse_env_file(path: Path) -> dict[str, str]:
    values: dict[str, str] = {}
    if not path.exists():
        return values
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, raw_value = line.split("=", 1)
        key = key.strip()
        if not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", key):
            continue
        try:
            parsed = shlex.split(raw_value, comments=False, posix=True)
        except ValueError:
            parsed = [raw_value.strip().strip("'\"")]
        values[key] = parsed[0] if parsed else ""
    return values


def default_config_path() -> Path:
    configured = os.environ.get("MEMORY_STARGRAPH_AUTOMATION_CONFIG")
    if configured:
        return Path(configured).expanduser()
    codex_home = Path(os.environ.get("CODEX_HOME", Path.home() / ".codex")).expanduser()
    return codex_home / "automations" / "memory-stargraph-wish-to-reallity" / "deployment-targets.env"


def resolve_worker_route(config_path: Path | None = None) -> WorkerRoute:
    config = _parse_env_file(config_path or default_config_path())
    env_url = os.environ.get("MEMORY_STARGRAPH_WORKER_API_URL", "").strip()
    if env_url:
        return WorkerRoute(
            env_url.rstrip("/"),
            tuple(shlex.split(os.environ.get("MEMORY_STARGRAPH_WORKER_API_CURL_FLAGS", ""))),
            "MEMORY_STARGRAPH_WORKER_API_URL",
        )
    config_url = config.get("MEMORY_STARGRAPH_LOCAL_URL", "").strip()
    if config_url:
        return WorkerRoute(
            config_url.rstrip("/"),
            tuple(shlex.split(config.get("MEMORY_STARGRAPH_LOCAL_CURL_FLAGS", ""))),
            str(config_path or default_config_path()),
        )
    return WorkerRoute(DEFAULT_WORKER_API_BASE_URL, (), "default_loopback")


def _completed_error(result: subprocess.CompletedProcess[str]) -> str:
    return (result.stderr or result.stdout or "").strip()


def run_curl(
    route: WorkerRoute,
    args: list[str],
    input_text: str | None = None,
    timeout: int = 60,
) -> subprocess.CompletedProcess[str]:
    try:
        return subprocess.run(
            ["curl", "-sS", "--fail", *route.curl_flags, *args],
            input=input_text,
            text=True,
            capture_output=True,
            timeout=timeout,
            check=False,
        )
    except subprocess.TimeoutExpired as exc:
        return subprocess.CompletedProcess(
            args,
            124,
            exc.stdout or "",
            exc.stderr or f"timed out after {timeout}s",
        )


def _retry_delays(retries: int) -> list[float]:
    return [min(0.25 * (2**index), 2.0) for index in range(max(retries - 1, 0))]


def _request_json(
    route: WorkerRoute,
    args: list[str],
    input_text: str | None = None,
    retries: int = DEFAULT_RETRIES,
    timeout: int = 60,
) -> dict[str, object]:
    errors: list[str] = []
    delays = _retry_delays(retries)
    for attempt in range(retries):
        result = run_curl(route, args, input_text=input_text, timeout=timeout)
        if result.returncode == 0:
            try:
                payload = json.loads(result.stdout or "{}")
            except json.JSONDecodeError as exc:
                raise WorkerPersistenceError(f"invalid worker API JSON: {exc}") from exc
            if isinstance(payload, dict) and not payload.get("error"):
                return payload
            raise WorkerPersistenceError(f"worker API returned error payload: {payload!r}")
        errors.append(_completed_error(result) or f"curl exited {result.returncode}")
        if attempt < len(delays):
            time.sleep(delays[attempt])
    raise WorkerPersistenceError("; ".join(errors))


def read_raw(slug: str, route: WorkerRoute | None = None, retries: int = DEFAULT_RETRIES) -> str:
    chosen = route or resolve_worker_route()
    endpoint = f"{chosen.base_url}/api/entity-raw/{quote(slug, safe='')}"
    payload = _request_json(chosen, ["--max-time", "45", endpoint], retries=retries, timeout=60)
    content = payload.get("content")
    if not isinstance(content, str):
        raise WorkerPersistenceError(f"raw readback missing content for {slug}")
    return content


def _direct_gbrain_enabled() -> bool:
    return os.environ.get("MEMORY_STARGRAPH_DIRECT_GBRAIN_FALLBACK", "").strip() in {"1", "true", "yes"}


def _direct_gbrain_get(slug: str) -> str:
    result = subprocess.run(
        ["gbrain", "get", slug],
        text=True,
        capture_output=True,
        timeout=120,
        check=False,
    )
    if result.returncode != 0:
        raise WorkerPersistenceError(_completed_error(result) or f"gbrain get failed for {slug}")
    return result.stdout


def _direct_gbrain_put(slug: str, content: str) -> None:
    result = subprocess.run(
        ["gbrain", "put", slug],
        input=content,
        text=True,
        capture_output=True,
        timeout=180,
        check=False,
    )
    if result.returncode != 0:
        raise WorkerPersistenceError(_completed_error(result) or f"gbrain put failed for {slug}")


def read_raw_with_optional_direct_fallback(slug: str, route: WorkerRoute | None = None) -> str:
    try:
        return read_raw(slug, route=route)
    except WorkerPersistenceError:
        if not _direct_gbrain_enabled():
            raise
        return _direct_gbrain_get(slug)


def save_raw(
    slug: str,
    content: str,
    route: WorkerRoute | None = None,
    retries: int = DEFAULT_RETRIES,
) -> dict[str, object]:
    chosen = route or resolve_worker_route()
    endpoint = f"{chosen.base_url}/api/entity-save/{quote(slug, safe='')}"
    body = json.dumps({"content": content}, ensure_ascii=False)
    last_error: Exception | None = None
    for attempt in range(retries):
        try:
            _request_json(
                chosen,
                ["--max-time", "120", "-X", "POST", "-H", "Content-Type: application/json", "-d", "@-", endpoint],
                input_text=body,
                retries=1,
                timeout=135,
            )
            readback = read_raw(slug, route=chosen, retries=1)
            if _raw_readback_matches(content, readback):
                return {"ok": True, "slug": slug, "route_source": chosen.source, "attempts": attempt + 1}
            last_error = WorkerPersistenceError(f"raw readback mismatch for {slug}")
        except WorkerPersistenceError as exc:
            last_error = exc
            if _direct_gbrain_enabled() and attempt == retries - 1:
                _direct_gbrain_put(slug, content)
                if _direct_gbrain_get(slug) == content:
                    return {"ok": True, "slug": slug, "route_source": "direct_gbrain_fallback", "attempts": attempt + 1}
        if attempt < retries - 1:
            time.sleep(_retry_delays(retries)[attempt])
    raise WorkerPersistenceError(str(last_error) if last_error else f"save failed for {slug}")


def _frontmatter_tags(markdown: str) -> set[str]:
    if not markdown.startswith("---\n"):
        return set()
    end = markdown.find("\n---", 4)
    if end < 0:
        return set()
    tags: set[str] = set()
    lines = markdown[4:end].splitlines()
    for index, line in enumerate(lines):
        if re.match(r"^tags:\s*\[", line):
            inside = line.split("[", 1)[1].rsplit("]", 1)[0]
            tags.update(item.strip().strip("'\"") for item in inside.split(",") if item.strip())
        if line.strip() == "tags:":
            for nested in lines[index + 1 :]:
                if not nested.startswith((" ", "-")):
                    break
                match = re.match(r"^\s*-\s*(.+?)\s*$", nested)
                if match:
                    tags.add(match.group(1).strip().strip("'\""))
    return {tag for tag in tags if tag}


def _split_frontmatter(markdown: str) -> tuple[str, str]:
    if not markdown.startswith("---\n"):
        return "", markdown
    end = markdown.find("\n---", 4)
    if end < 0:
        return "", markdown
    body_start = end + len("\n---")
    if markdown[body_start : body_start + 1] == "\n":
        body_start += 1
    return markdown[4:end], markdown[body_start:]


def _frontmatter_scalars(markdown: str) -> dict[str, str]:
    frontmatter, _ = _split_frontmatter(markdown)
    values: dict[str, str] = {}
    for line in frontmatter.splitlines():
        if line.startswith((" ", "-")) or ":" not in line:
            continue
        key, raw_value = line.split(":", 1)
        value = raw_value.strip()
        if value and not value.startswith("["):
            values[key.strip()] = value.strip("'\"")
    return values


def _raw_readback_matches(expected: str, actual: str) -> bool:
    if expected == actual:
        return True
    expected_frontmatter, expected_body = _split_frontmatter(expected)
    actual_frontmatter, actual_body = _split_frontmatter(actual)
    if not expected_frontmatter or not actual_frontmatter or expected_body != actual_body:
        return False
    actual_scalars = _frontmatter_scalars(actual)
    for key, value in _frontmatter_scalars(expected).items():
        if key == "tags":
            continue
        if actual_scalars.get(key) != value:
            return False
    return _frontmatter_tags(expected).issubset(_frontmatter_tags(actual))


def mutate_tags(
    slug: str,
    add: list[str] | None = None,
    remove: list[str] | None = None,
    route: WorkerRoute | None = None,
    retries: int = DEFAULT_RETRIES,
) -> dict[str, object]:
    chosen = route or resolve_worker_route()
    add_tags = sorted({tag.strip() for tag in add or [] if tag.strip()})
    remove_tags = sorted({tag.strip() for tag in remove or [] if tag.strip()})
    if not add_tags and not remove_tags:
        raise WorkerPersistenceError("at least one tag mutation is required")
    endpoint = f"{chosen.base_url}/api/entity-tags/{quote(slug, safe='')}"
    body = json.dumps({"add": add_tags, "remove": remove_tags}, ensure_ascii=False)
    last_error: Exception | None = None
    for attempt in range(retries):
        try:
            _request_json(
                chosen,
                ["--max-time", "90", "-X", "POST", "-H", "Content-Type: application/json", "-d", "@-", endpoint],
                input_text=body,
                retries=1,
                timeout=105,
            )
            tags = _frontmatter_tags(read_raw(slug, route=chosen, retries=1))
            missing = [tag for tag in add_tags if tag not in tags]
            present = [tag for tag in remove_tags if tag in tags]
            if not missing and not present:
                return {
                    "ok": True,
                    "slug": slug,
                    "route_source": chosen.source,
                    "attempts": attempt + 1,
                    "tags": sorted(tags),
                }
            last_error = WorkerPersistenceError(f"tag readback mismatch missing={missing} present={present}")
        except WorkerPersistenceError as exc:
            last_error = exc
        if attempt < retries - 1:
            time.sleep(_retry_delays(retries)[attempt])
    raise WorkerPersistenceError(str(last_error) if last_error else f"tag mutation failed for {slug}")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Persist worker Run/report entities through the worker API.")
    parser.add_argument("--json", action="store_true")
    parser.add_argument("--config", help="Deployment env file used for route resolution.")
    subparsers = parser.add_subparsers(dest="command", required=True)

    routes_parser = subparsers.add_parser("routes")
    routes_parser.add_argument("--json", action="store_true", dest="command_json")

    read_parser = subparsers.add_parser("read")
    read_parser.add_argument("slug")
    read_parser.add_argument("--json", action="store_true", dest="command_json")

    save_parser = subparsers.add_parser("save")
    save_parser.add_argument("slug")
    save_parser.add_argument("--file", required=True)
    save_parser.add_argument("--json", action="store_true", dest="command_json")

    tag_parser = subparsers.add_parser("tags")
    tag_parser.add_argument("slug")
    tag_parser.add_argument("--add", action="append", default=[])
    tag_parser.add_argument("--remove", action="append", default=[])
    tag_parser.add_argument("--json", action="store_true", dest="command_json")

    args = parser.parse_args(argv)
    emit_json = bool(args.json or getattr(args, "command_json", False))
    route = resolve_worker_route(Path(args.config).expanduser() if args.config else None)
    try:
        if args.command == "routes":
            payload: object = {"base_url": route.base_url, "curl_flags": list(route.curl_flags), "source": route.source}
        elif args.command == "read":
            content = read_raw_with_optional_direct_fallback(args.slug, route=route)
            payload = {"ok": True, "slug": args.slug, "content": content, "route_source": route.source}
        elif args.command == "save":
            content = Path(args.file).read_text(encoding="utf-8")
            payload = save_raw(args.slug, content, route=route)
        elif args.command == "tags":
            payload = mutate_tags(args.slug, add=args.add, remove=args.remove, route=route)
        else:
            raise AssertionError(args.command)
    except WorkerPersistenceError as exc:
        if emit_json:
            print(json.dumps({"ok": False, "error": str(exc)}, indent=2, sort_keys=True))
        else:
            print(f"worker persistence failed: {exc}", file=sys.stderr)
        return 1

    if emit_json:
        print(json.dumps(payload, indent=2, sort_keys=True))
    else:
        if isinstance(payload, dict) and "content" in payload:
            print(payload["content"])
        else:
            print(payload)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
