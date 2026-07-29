import json
import os
from pathlib import Path
import sqlite3
import subprocess
import sys
import tempfile
import textwrap
import unittest


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts/automation/switch_stargraph_automation_host.py"


class StargraphAutomationHostSwitchTests(unittest.TestCase):
    def make_host(self, home: Path, automation_ids: list[str], status: str = "ACTIVE") -> Path:
        codex_home = home / ".codex"
        for automation_id in automation_ids:
            directory = codex_home / "automations" / automation_id
            directory.mkdir(parents=True, exist_ok=True)
            (directory / "automation.toml").write_text(
                textwrap.dedent(
                    f"""\
                    version = 1
                    id = "{automation_id}"
                    kind = "cron"
                    name = "{automation_id}"
                    status = "{status}"
                    rrule = "FREQ=DAILY;BYHOUR=0;BYMINUTE=0;BYSECOND=0"
                    """
                )
            )
        db_path = codex_home / "sqlite/codex-dev.db"
        db_path.parent.mkdir(parents=True, exist_ok=True)
        con = sqlite3.connect(db_path)
        con.execute(
            "create table automations (id text primary key, status text, updated_at integer)"
        )
        for automation_id in automation_ids:
            con.execute(
                "insert into automations (id, status, updated_at) values (?, ?, 0)",
                (automation_id, status),
            )
        con.commit()
        con.close()
        return codex_home

    def test_local_apply_updates_toml_and_scheduler_db(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            temp = Path(temp_dir)
            automation_ids = ["memory-stargraph-capture-link-drain", "gbrain-x-intelligence-capture"]
            tony_home = temp / "tony"
            codex_home = self.make_host(tony_home, automation_ids, "PAUSED")
            config = {
                "holder": "timmy",
                "updated_at": "2026-07-28T00:00:00-07:00",
                "automation_ids": automation_ids,
                "hosts": {
                    "tony": {
                        "kind": "local",
                        "codex_home": str(codex_home),
                        "project_root": "/tmp/tony-project",
                    }
                },
            }
            config_path = temp / "switch.json"
            config_path.write_text(json.dumps(config))

            result = subprocess.run(
                [
                    sys.executable,
                    str(SCRIPT),
                    "--config",
                    str(config_path),
                    "--holder",
                    "tony",
                    "--apply",
                    "--json",
                ],
                cwd=ROOT,
                text=True,
                capture_output=True,
                check=False,
            )

            self.assertEqual(result.returncode, 0, result.stderr)
            payload = json.loads(result.stdout)
            self.assertTrue(payload["applied"])
            self.assertEqual(payload["holder"], "tony")
            self.assertIn("holder_source", payload)
            for automation_id in automation_ids:
                toml = (codex_home / "automations" / automation_id / "automation.toml").read_text()
                self.assertIn('status = "ACTIVE"', toml)
            con = sqlite3.connect(codex_home / "sqlite/codex-dev.db")
            rows = dict(con.execute("select id, status from automations").fetchall())
            con.close()
            self.assertEqual(rows, {automation_ids[0]: "ACTIVE", automation_ids[1]: "ACTIVE"})
            self.assertEqual(json.loads(config_path.read_text())["holder"], "timmy")

    def test_status_reports_holder_without_mutation(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            config_path = Path(temp_dir) / "switch.json"
            config_path.write_text(
                json.dumps(
                    {
                        "holder": "timmy",
                        "automation_ids": ["memory-stargraph-capture-link-drain"],
                        "hosts": {
                            "tony": {
                                "kind": "local",
                                "codex_home": "/tmp/tony/.codex",
                                "project_root": "/tmp/tony/project",
                            },
                            "timmy": {
                                "kind": "ssh",
                                "ssh_target": "toddy@100.100.126.85",
                                "codex_home": "/Users/toddy/.codex",
                                "project_root": "/Users/toddy/memory-stargraph",
                            },
                        },
                    }
                )
            )

            result = subprocess.run(
                [
                    sys.executable,
                    str(SCRIPT),
                    "--config",
                    str(config_path),
                    "--status",
                    "--json",
                ],
                cwd=ROOT,
                text=True,
                capture_output=True,
                check=False,
            )

            self.assertEqual(result.returncode, 0, result.stderr)
            payload = json.loads(result.stdout)
            self.assertEqual(payload["holder"], "timmy")
            self.assertEqual(payload["hosts"]["timmy"]["target_status"], "ACTIVE")
            self.assertEqual(payload["hosts"]["tony"]["target_status"], "PAUSED")

    def test_status_reads_holder_from_stargraph_node_when_config_has_no_holder(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            temp = Path(temp_dir)
            bin_dir = temp / "bin"
            bin_dir.mkdir()
            curl = bin_dir / "curl"
            curl.write_text(
                textwrap.dedent(
                    """\
                    #!/usr/bin/env bash
                    printf '%s' '{"content":"# Coordination\\n\\nholder: tony\\n"}'
                    """
                )
            )
            curl.chmod(0o755)
            config_path = temp / "switch.json"
            config_path.write_text(
                json.dumps(
                    {
                        "coordination": {
                            "slug": "ops/memory-stargraph/automation-host-holder",
                            "default_holder": "timmy",
                            "default_stargraph_url": "http://stargraph.test:8788",
                        },
                        "automation_ids": ["memory-stargraph-capture-link-drain"],
                        "hosts": {
                            "tony": {
                                "kind": "local",
                                "codex_home": str(temp / "tony/.codex"),
                                "project_root": "/tmp/tony/project",
                            },
                            "timmy": {
                                "kind": "ssh",
                                "ssh_target": "toddy@100.100.126.85",
                                "codex_home": "/Users/toddy/.codex",
                                "project_root": "/Users/toddy/memory-stargraph",
                            },
                        },
                    }
                )
            )
            env = os.environ.copy()
            env["PATH"] = f"{bin_dir}:{env.get('PATH', '')}"

            result = subprocess.run(
                [
                    sys.executable,
                    str(SCRIPT),
                    "--config",
                    str(config_path),
                    "--status",
                    "--json",
                ],
                cwd=ROOT,
                env=env,
                text=True,
                capture_output=True,
                check=False,
            )

            self.assertEqual(result.returncode, 0, result.stderr)
            payload = json.loads(result.stdout)
            self.assertEqual(payload["holder"], "tony")
            self.assertEqual(payload["holder_source"]["source"], "stargraph")
            self.assertEqual(payload["hosts"]["tony"]["target_status"], "ACTIVE")

    def test_status_falls_back_to_timmy_when_stargraph_unreachable(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            temp = Path(temp_dir)
            bin_dir = temp / "bin"
            bin_dir.mkdir()
            curl = bin_dir / "curl"
            curl.write_text(
                textwrap.dedent(
                    """\
                    #!/usr/bin/env bash
                    exit 7
                    """
                )
            )
            curl.chmod(0o755)
            config_path = temp / "switch.json"
            config_path.write_text(
                json.dumps(
                    {
                        "coordination": {
                            "slug": "ops/memory-stargraph/automation-host-holder",
                            "default_holder": "timmy",
                            "default_stargraph_url": "http://stargraph.test:8788",
                        },
                        "automation_ids": ["memory-stargraph-capture-link-drain"],
                        "hosts": {
                            "tony": {
                                "kind": "local",
                                "codex_home": str(temp / "tony/.codex"),
                                "project_root": "/tmp/tony/project",
                            },
                            "timmy": {
                                "kind": "ssh",
                                "ssh_target": "toddy@100.100.126.85",
                                "codex_home": "/Users/toddy/.codex",
                                "project_root": "/Users/toddy/memory-stargraph",
                            },
                        },
                    }
                )
            )
            env = os.environ.copy()
            env["PATH"] = f"{bin_dir}:{env.get('PATH', '')}"

            result = subprocess.run(
                [
                    sys.executable,
                    str(SCRIPT),
                    "--config",
                    str(config_path),
                    "--status",
                    "--json",
                ],
                cwd=ROOT,
                env=env,
                text=True,
                capture_output=True,
                check=False,
            )

            self.assertEqual(result.returncode, 0, result.stderr)
            payload = json.loads(result.stdout)
            self.assertEqual(payload["holder"], "timmy")
            self.assertEqual(payload["holder_source"]["source"], "fallback")
            self.assertEqual(payload["hosts"]["timmy"]["target_status"], "ACTIVE")
            self.assertEqual(payload["hosts"]["tony"]["target_status"], "PAUSED")


if __name__ == "__main__":
    unittest.main()
