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
import datetime as dt
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


def _is_loopback_url(url: str) -> bool:
    return bool(re.search(r"^https?://(127(?:\.\d+){3}|localhost)(?::|/|$)", url, flags=re.IGNORECASE))


def _candidate_routes(config: dict[str, str], config_source: str) -> list[WorkerRoute]:
    routes: list[WorkerRoute] = []
    dashboard_url = config.get("MEMORY_STARGRAPH_DASHBOARD_URL", "").strip()
    if dashboard_url:
        routes.append(
            WorkerRoute(
                dashboard_url.rstrip("/"),
                tuple(shlex.split(config.get("MEMORY_STARGRAPH_DASHBOARD_CURL_FLAGS", ""))),
                f"{config_source}:MEMORY_STARGRAPH_DASHBOARD_URL",
            )
        )
    local_url = config.get("MEMORY_STARGRAPH_LOCAL_URL", "").strip()
    if local_url:
        routes.append(
            WorkerRoute(
                local_url.rstrip("/"),
                tuple(shlex.split(config.get("MEMORY_STARGRAPH_LOCAL_CURL_FLAGS", ""))),
                f"{config_source}:MEMORY_STARGRAPH_LOCAL_URL",
            )
        )
    routes.append(WorkerRoute(DEFAULT_WORKER_API_BASE_URL, (), "default_loopback"))
    seen: set[tuple[str, tuple[str, ...]]] = set()
    deduped: list[WorkerRoute] = []
    for route in routes:
        identity = (route.base_url, route.curl_flags)
        if identity not in seen:
            seen.add(identity)
            deduped.append(route)
    return deduped


def _route_health_ok(route: WorkerRoute, timeout: int = 8) -> bool:
    result = run_curl(route, ["--max-time", str(timeout), f"{route.base_url}/api/health"], timeout=timeout + 5)
    if result.returncode != 0:
        return False
    try:
        payload = json.loads(result.stdout or "{}")
    except json.JSONDecodeError:
        return False
    return isinstance(payload, dict) and payload.get("ok") is True


def resolve_worker_route(config_path: Path | None = None) -> WorkerRoute:
    path = config_path or default_config_path()
    config = _parse_env_file(path)
    env_url = os.environ.get("MEMORY_STARGRAPH_WORKER_API_URL", "").strip()
    if env_url:
        return WorkerRoute(
            env_url.rstrip("/"),
            tuple(shlex.split(os.environ.get("MEMORY_STARGRAPH_WORKER_API_CURL_FLAGS", ""))),
            "MEMORY_STARGRAPH_WORKER_API_URL",
        )
    candidates = _candidate_routes(config, str(path))
    non_loopback = [route for route in candidates if not _is_loopback_url(route.base_url)]
    loopback = [route for route in candidates if _is_loopback_url(route.base_url)]
    for route in [*non_loopback, *loopback]:
        if _route_health_ok(route):
            return route
    if non_loopback:
        raise WorkerPersistenceError(
            "configured non-loopback worker API routes were unavailable; refusing loopback fallback"
        )
    for route in loopback:
        if _route_health_ok(route):
            return route
    raise WorkerPersistenceError("no healthy worker API route available")


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
    tags = _frontmatter_values(markdown).get("tags", [])
    if isinstance(tags, list):
        return {str(tag) for tag in tags if str(tag)}
    if isinstance(tags, str):
        return {tag.strip() for tag in tags.split(",") if tag.strip()}
    return set()


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
    return {
        key: str(value)
        for key, value in _frontmatter_values(markdown).items()
        if not isinstance(value, list)
    }


def _strip_yaml_quotes(value: str) -> str:
    stripped = value.strip()
    if len(stripped) >= 2 and stripped[0] == stripped[-1] and stripped[0] in {"'", '"'}:
        return stripped[1:-1]
    return stripped


def _parse_inline_list(value: str) -> list[str]:
    inside = value.strip()[1:-1]
    if not inside.strip():
        return []
    return [_normalize_scalar(item) for item in inside.split(",")]


def _fold_block(lines: list[str], style: str) -> str:
    cleaned = [line[2:] if line.startswith("  ") else line.lstrip() for line in lines]
    if style.startswith("|"):
        value = "\n".join(cleaned)
    else:
        paragraphs: list[str] = []
        current: list[str] = []
        for line in cleaned:
            if line == "":
                if current:
                    paragraphs.append(" ".join(current))
                    current = []
                paragraphs.append("")
            else:
                current.append(line)
        if current:
            paragraphs.append(" ".join(current))
        value = "\n".join(paragraphs)
    if not style.endswith("-"):
        value += "\n"
    return value


def _normalize_timestamp(value: str) -> str | None:
    candidate = value.strip()
    if not re.fullmatch(r"\d{4}-\d{2}-\d{2}([T ][0-9:.+-]+|Z)?", candidate):
        return None
    try:
        parsed = dt.datetime.fromisoformat(candidate.replace("Z", "+00:00"))
    except ValueError:
        try:
            return dt.date.fromisoformat(candidate).isoformat()
        except ValueError:
            return None
    if parsed.microsecond:
        return parsed.isoformat()
    return parsed.replace(microsecond=0).isoformat()


def _normalize_scalar(value: object) -> str:
    text = _strip_yaml_quotes(str(value))
    lowered = text.lower()
    if lowered in {"true", "false", "null"}:
        return lowered
    timestamp = _normalize_timestamp(text)
    if timestamp:
        return timestamp
    return text


def _frontmatter_values(markdown: str) -> dict[str, object]:
    frontmatter, _ = _split_frontmatter(markdown)
    values: dict[str, object] = {}
    lines = frontmatter.splitlines()
    index = 0
    while index < len(lines):
        line = lines[index]
        if not line or line.startswith((" ", "-")) or ":" not in line:
            index += 1
            continue
        key, raw_value = line.split(":", 1)
        key = key.strip()
        value = raw_value.strip()
        index += 1
        if value in {">", ">-", "|", "|-"}:
            block: list[str] = []
            while index < len(lines) and (lines[index].startswith(" ") or not lines[index]):
                block.append(lines[index])
                index += 1
            values[key] = _normalize_scalar(_fold_block(block, value))
            continue
        if value == "":
            items: list[str] = []
            while index < len(lines) and lines[index].startswith(" "):
                match = re.match(r"^\s*-\s*(.+?)\s*$", lines[index])
                if match:
                    items.append(_normalize_scalar(match.group(1)))
                index += 1
            values[key] = items
            continue
        if value.startswith("[") and value.endswith("]"):
            values[key] = _parse_inline_list(value)
            continue
        values[key] = _normalize_scalar(value)
    return values


def _body_matches(expected: str, actual: str) -> bool:
    if expected == actual:
        return True
    expected_without_final = expected[:-1] if expected.endswith("\n") else expected
    actual_without_final = actual[:-1] if actual.endswith("\n") else actual
    return expected_without_final == actual_without_final


def _raw_readback_matches(expected: str, actual: str) -> bool:
    if expected == actual:
        return True
    expected_frontmatter, expected_body = _split_frontmatter(expected)
    actual_frontmatter, actual_body = _split_frontmatter(actual)
    if not expected_frontmatter or not actual_frontmatter or not _body_matches(expected_body, actual_body):
        return False
    expected_values = _frontmatter_values(expected)
    actual_values = _frontmatter_values(actual)
    for key, value in expected_values.items():
        if key == "tags":
            continue
        if actual_values.get(key) != value:
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
