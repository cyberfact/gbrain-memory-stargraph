#!/usr/bin/env python3
"""Switch Memory Stargraph recurring Codex automations between Tony and .85.

The project intentionally has automations installed on two hosts, but only one
host should run them at a time. This script reconciles both Codex automation
TOML files and the Codex app-server scheduler DB where present, because the
scheduler can keep stale project/status rows after TOML edits.
"""

from __future__ import annotations

import argparse
import base64
from dataclasses import dataclass
from datetime import datetime
import json
import os
from pathlib import Path
import re
import shlex
import sqlite3
import subprocess
import sys
from typing import Any
from urllib.parse import quote


ROOT = Path(__file__).resolve().parents[2]
DEFAULT_CONFIG = ROOT / "config/memory-stargraph-automation-host.json"
STATUS_RE = re.compile(r'(?m)^status\s*=\s*"(ACTIVE|PAUSED)"\s*$')
HOLDER_RE = re.compile(r"(?im)^\s*holder\s*:\s*(tony|timmy)\s*$")


@dataclass
class AutomationUpdate:
    host: str
    automation_id: str
    target_status: str
    toml_path: str
    toml_changed: bool
    db_path: str | None = None
    db_rows_changed: int = 0


def pacific_timestamp() -> str:
    # macOS ships zoneinfo; if unavailable, this still gives an explicit local offset.
    try:
        from zoneinfo import ZoneInfo

        return datetime.now(ZoneInfo("America/Los_Angeles")).isoformat(timespec="seconds")
    except Exception:
        return datetime.now().astimezone().isoformat(timespec="seconds")


def expand_user_path(value: str) -> Path:
    return Path(value).expanduser()


def replace_status(text: str, status: str) -> tuple[str, bool]:
    replacement = f'status = "{status}"'
    if STATUS_RE.search(text):
        updated = STATUS_RE.sub(replacement, text, count=1)
        return updated, updated != text
    lines = text.splitlines()
    insert_at = 0
    for index, line in enumerate(lines):
        if line.startswith("name = "):
            insert_at = index + 1
            break
    lines.insert(insert_at, replacement)
    return "\n".join(lines) + ("\n" if text.endswith("\n") else ""), True


def update_scheduler_db(codex_home: Path, automation_id: str, status: str, apply: bool) -> tuple[str | None, int]:
    db_path = codex_home / "sqlite/codex-dev.db"
    if not db_path.exists():
        return None, 0
    if not apply:
        return str(db_path), 0
    connection = sqlite3.connect(db_path)
    try:
        cursor = connection.execute(
            "update automations set status=?, updated_at=? where id=?",
            (status, int(datetime.now().timestamp() * 1000), automation_id),
        )
        connection.commit()
        return str(db_path), cursor.rowcount
    finally:
        connection.close()


def stargraph_base_url(config: dict[str, Any]) -> str:
    coordination = config.get("coordination", {})
    env_name = coordination.get("stargraph_url_env", "MEMORY_STARGRAPH_WORKER_API_URL")
    return os.environ.get(env_name, coordination.get("default_stargraph_url", "http://127.0.0.1:8788")).rstrip("/")


def coordination_slug(config: dict[str, Any]) -> str | None:
    slug = config.get("coordination", {}).get("slug")
    return slug if isinstance(slug, str) and slug else None


def run_curl(args: list[str], input_text: str | None = None, timeout: int = 30) -> subprocess.CompletedProcess[str]:
    try:
        return subprocess.run(
            ["curl", "-sS", *args],
            input=input_text,
            text=True,
            capture_output=True,
            timeout=timeout,
            check=False,
        )
    except subprocess.TimeoutExpired as exc:
        return subprocess.CompletedProcess(args, 124, exc.stdout or "", exc.stderr or f"timed out after {timeout}s")


def read_stargraph_node(config: dict[str, Any]) -> tuple[str | None, str | None]:
    slug = coordination_slug(config)
    if not slug:
        return None, "coordination slug missing"
    url = f"{stargraph_base_url(config)}/api/entity-raw/{quote(slug, safe='')}"
    result = run_curl(["--max-time", "20", url], timeout=25)
    if result.returncode != 0:
        return None, (result.stderr or result.stdout or f"curl exited {result.returncode}").strip()
    try:
        payload = json.loads(result.stdout)
    except json.JSONDecodeError as exc:
        return None, f"invalid JSON: {exc}"
    content = payload.get("content") if isinstance(payload, dict) else None
    if not isinstance(content, str):
        return None, "entity content missing"
    return content, None


def parse_holder(markdown: str) -> str | None:
    match = HOLDER_RE.search(markdown)
    if match:
        return match.group(1).lower()
    return None


def fallback_holder(config: dict[str, Any]) -> str:
    holder = config.get("holder") or config.get("coordination", {}).get("default_holder") or "timmy"
    if holder not in config["hosts"]:
        raise SystemExit(f"fallback holder {holder!r} is not a configured host")
    return holder


def read_holder(config: dict[str, Any]) -> tuple[str, dict[str, Any]]:
    content, error = read_stargraph_node(config)
    if content:
        holder = parse_holder(content)
        if holder in config["hosts"]:
            return holder, {"source": "stargraph", "slug": coordination_slug(config)}
        error = "holder field missing or invalid in coordination node"
    holder = fallback_holder(config)
    return holder, {"source": "fallback", "slug": coordination_slug(config), "error": error}


def render_coordination_node(config: dict[str, Any], holder: str, previous: str | None = None) -> str:
    slug = coordination_slug(config) or "ops/memory-stargraph/automation-host-holder"
    lines = [
        "# Memory Stargraph Automation Host Holder",
        "",
        f"holder: {holder}",
        f"updated_at: {pacific_timestamp()}",
        "source_kind: memory-stargraph-automation-coordination",
        "coordination_slug: " + slug,
        "",
        "## Meaning",
        "",
        "- `tony`: Tony's local Codex automations are ACTIVE and `.85`/timmy automations are PAUSED.",
        "- `timmy`: `.85`/timmy Codex automations are ACTIVE and Tony's local automations are PAUSED.",
        "",
        "## Host mapping",
    ]
    for name, host in config["hosts"].items():
        lines.append(f"- `{name}`: {host.get('label', name)} — `{host.get('project_root', '')}`")
    lines.extend(
        [
            "",
            "## Managed automations",
            "",
        ]
    )
    for automation_id in config["automation_ids"]:
        lines.append(f"- `{automation_id}`")
    if previous and previous.strip():
        lines.extend(["", "## Previous content snapshot", "", "```markdown", previous.strip(), "```"])
    return "\n".join(lines) + "\n"


def write_stargraph_holder(config: dict[str, Any], holder: str, apply: bool) -> tuple[bool, dict[str, Any]]:
    slug = coordination_slug(config)
    if not slug:
        return False, {"source": "none", "error": "coordination slug missing"}
    existing, read_error = read_stargraph_node(config)
    existing_holder = parse_holder(existing or "") if existing else None
    changed = existing_holder != holder
    if not apply:
        return changed, {"source": "stargraph", "slug": slug, "existing_holder": existing_holder, "read_error": read_error}
    content = render_coordination_node(config, holder, previous=existing if existing_holder and existing_holder != holder else None)
    url = f"{stargraph_base_url(config)}/api/entity-save/{quote(slug, safe='')}"
    result = run_curl(
        ["--max-time", "45", "-X", "POST", "-H", "Content-Type: application/json", "-d", "@-", url],
        input_text=json.dumps({"content": content}),
        timeout=60,
    )
    if result.returncode != 0:
        raise RuntimeError(f"failed to write Stargraph coordination node {slug}: {(result.stderr or result.stdout).strip()}")
    readback, readback_error = read_stargraph_node(config)
    readback_holder = parse_holder(readback or "") if readback else None
    if readback_holder != holder:
        raise RuntimeError(f"Stargraph coordination node readback mismatch: holder={readback_holder!r} error={readback_error!r}")
    return changed, {"source": "stargraph", "slug": slug, "readback_holder": readback_holder}


def update_host(
    *,
    host_name: str,
    host_config: dict[str, Any],
    automation_ids: list[str],
    holder: str,
    apply: bool,
) -> list[dict[str, Any]]:
    codex_home = expand_user_path(host_config["codex_home"])
    target_status = "ACTIVE" if host_name == holder else "PAUSED"
    updates: list[dict[str, Any]] = []
    for automation_id in automation_ids:
        toml_path = codex_home / "automations" / automation_id / "automation.toml"
        if not toml_path.exists():
            updates.append(
                {
                    "host": host_name,
                    "automation_id": automation_id,
                    "target_status": target_status,
                    "toml_path": str(toml_path),
                    "missing": True,
                }
            )
            continue
        original = toml_path.read_text()
        updated, toml_changed = replace_status(original, target_status)
        if apply and toml_changed:
            toml_path.write_text(updated)
        db_path, db_rows = update_scheduler_db(codex_home, automation_id, target_status, apply)
        updates.append(
            {
                "host": host_name,
                "automation_id": automation_id,
                "target_status": target_status,
                "toml_path": str(toml_path),
                "toml_changed": toml_changed,
                "db_path": db_path,
                "db_rows_changed": db_rows,
            }
        )
    return updates


REMOTE_WORKER = r"""
import json
import os
import pathlib
import re
import sqlite3
import sys
from datetime import datetime

payload = json.loads(sys.stdin.read())
status_re = re.compile(r'(?m)^status\s*=\s*"(ACTIVE|PAUSED)"\s*$')

def replace_status(text, status):
    replacement = f'status = "{status}"'
    if status_re.search(text):
        updated = status_re.sub(replacement, text, count=1)
        return updated, updated != text
    lines = text.splitlines()
    insert_at = 0
    for index, line in enumerate(lines):
        if line.startswith("name = "):
            insert_at = index + 1
            break
    lines.insert(insert_at, replacement)
    return "\n".join(lines) + ("\n" if text.endswith("\n") else ""), True

def update_scheduler_db(codex_home, automation_id, status, apply):
    db_path = codex_home / "sqlite/codex-dev.db"
    if not db_path.exists():
        return None, 0
    if not apply:
        return str(db_path), 0
    connection = sqlite3.connect(db_path)
    try:
        cursor = connection.execute(
            "update automations set status=?, updated_at=? where id=?",
            (status, int(datetime.now().timestamp() * 1000), automation_id),
        )
        connection.commit()
        return str(db_path), cursor.rowcount
    finally:
        connection.close()

codex_home = pathlib.Path(payload["codex_home"]).expanduser()
target_status = payload["target_status"]
apply = payload["apply"]
updates = []
for automation_id in payload["automation_ids"]:
    toml_path = codex_home / "automations" / automation_id / "automation.toml"
    if not toml_path.exists():
        updates.append({
            "host": payload["host"],
            "automation_id": automation_id,
            "target_status": target_status,
            "toml_path": str(toml_path),
            "missing": True,
        })
        continue
    original = toml_path.read_text()
    updated, toml_changed = replace_status(original, target_status)
    if apply and toml_changed:
        toml_path.write_text(updated)
    db_path, db_rows = update_scheduler_db(codex_home, automation_id, target_status, apply)
    updates.append({
        "host": payload["host"],
        "automation_id": automation_id,
        "target_status": target_status,
        "toml_path": str(toml_path),
        "toml_changed": toml_changed,
        "db_path": db_path,
        "db_rows_changed": db_rows,
    })
restart = payload.get("restart_command")
restart_result = None
if apply and restart:
    import subprocess
    completed = subprocess.run(restart, shell=True, text=True, capture_output=True, check=False)
    restart_result = {
        "returncode": completed.returncode,
        "stdout": completed.stdout.strip(),
        "stderr": completed.stderr.strip(),
    }
print(json.dumps({"updates": updates, "restart": restart_result}, sort_keys=True))
"""


def run_remote_update(
    *,
    host_name: str,
    host_config: dict[str, Any],
    automation_ids: list[str],
    holder: str,
    apply: bool,
) -> dict[str, Any]:
    target_status = "ACTIVE" if host_name == holder else "PAUSED"
    payload = {
        "host": host_name,
        "codex_home": host_config["codex_home"],
        "target_status": target_status,
        "automation_ids": automation_ids,
        "apply": apply,
        "restart_command": host_config.get("restart_command"),
    }
    encoded = base64.b64encode(REMOTE_WORKER.encode()).decode()
    remote_code = (
        "import base64; "
        f"code=base64.b64decode('{encoded}').decode(); "
        "ns={'__name__':'__main__'}; "
        "exec(compile(code, '<remote-switch-stargraph-automation-host>', 'exec'), ns)"
    )
    command = [
        "ssh",
        host_config["ssh_target"],
        "python3 -c " + shlex.quote(remote_code),
    ]
    completed = subprocess.run(
        command,
        input=json.dumps(payload),
        text=True,
        capture_output=True,
        check=False,
    )
    if completed.returncode != 0:
        return {
            "host": host_name,
            "target_status": target_status,
            "error": completed.stderr.strip() or completed.stdout.strip(),
            "returncode": completed.returncode,
        }
    try:
        parsed = json.loads(completed.stdout)
    except json.JSONDecodeError:
        parsed = {"raw_stdout": completed.stdout}
    parsed["host"] = host_name
    parsed["target_status"] = target_status
    return parsed


def load_config(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text())


def summarize(config: dict[str, Any], holder: str, holder_meta: dict[str, Any]) -> dict[str, Any]:
    return {
        "holder": holder,
        "holder_source": holder_meta,
        "active_host": holder,
        "inactive_hosts": sorted(name for name in config["hosts"] if name != holder),
        "automation_count": len(config["automation_ids"]),
        "hosts": {
            name: {
                "kind": host.get("kind"),
                "label": host.get("label"),
                "target_status": "ACTIVE" if name == holder else "PAUSED",
                "project_root": host.get("project_root"),
            }
            for name, host in config["hosts"].items()
        },
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, default=DEFAULT_CONFIG)
    parser.add_argument("--holder", choices=("tony", "timmy"))
    parser.add_argument("--apply", action="store_true", help="mutate Codex automation state")
    parser.add_argument("--json", action="store_true", help="print machine-readable JSON")
    parser.add_argument("--status", action="store_true", help="only show current holder summary")
    parser.add_argument("--skip-remote", action="store_true", help="only reconcile local host")
    args = parser.parse_args(argv)

    config = load_config(args.config)
    if args.holder:
        current_holder, holder_meta = args.holder, {"source": "argument"}
    else:
        current_holder, holder_meta = read_holder(config)
    if args.status and not args.holder:
        payload = summarize(config, current_holder, holder_meta)
        if args.json:
            print(json.dumps(payload, indent=2, sort_keys=True))
        else:
            print(f"holder={payload['holder']}")
            for name, host in payload["hosts"].items():
                print(f"{name}: {host['target_status']} {host['project_root']}")
        return 0

    holder = args.holder or current_holder
    if holder not in config["hosts"]:
        raise SystemExit(f"unknown holder {holder!r}")

    holder_changed, holder_write = write_stargraph_holder(config, holder, args.apply)
    results: list[Any] = []
    for host_name, host_config in config["hosts"].items():
        kind = host_config["kind"]
        if kind == "local":
            results.append(
                {
                    "host": host_name,
                    "target_status": "ACTIVE" if host_name == holder else "PAUSED",
                    "updates": update_host(
                        host_name=host_name,
                        host_config=host_config,
                        automation_ids=config["automation_ids"],
                        holder=holder,
                        apply=args.apply,
                    ),
                }
            )
        elif kind == "ssh" and not args.skip_remote:
            results.append(
                run_remote_update(
                    host_name=host_name,
                    host_config=host_config,
                    automation_ids=config["automation_ids"],
                    holder=holder,
                    apply=args.apply,
                )
            )

    payload = {
        "ok": not any("error" in item for item in results if isinstance(item, dict)),
        "applied": args.apply,
        "holder": holder,
        "holder_changed": holder_changed,
        "holder_source": holder_write,
        "results": results,
    }
    if args.json:
        print(json.dumps(payload, indent=2, sort_keys=True))
    else:
        mode = "applied" if args.apply else "dry_run"
        print(f"{mode}: holder={holder}")
        for item in results:
            print(f"{item.get('host')}: {item.get('target_status')}")
            if item.get("error"):
                print(f"  error: {item['error']}")
    return 0 if payload["ok"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
