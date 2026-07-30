import datetime as dt
import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from scripts.automation import capture_link_host_runner as runner


class CaptureLinkHostRunnerTests(unittest.TestCase):
    def make_request(self, **overrides):
        payload = runner.make_request(
            overrides.pop("invocation_id", "sg0176-test-0001"),
            overrides.pop("expected_commit", "abc123"),
            overrides.pop("mode", "auto"),
            overrides.pop("nonce", "nonce-0001"),
        )
        payload.update(overrides)
        return payload

    def lifecycle_mocks(self):
        return (
            mock.patch.object(runner, "put_entity"),
            mock.patch.object(runner, "mutate_tag"),
            mock.patch.object(runner, "read_tags", return_value=["capture-link", "curator", "host-runner", "completed"]),
        )

    def test_submit_writes_atomic_confined_request_and_status_pending(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            result = runner.submit_request(root, self.make_request())

            self.assertEqual(result["status"], "submitted")
            self.assertTrue((root / "incoming" / "nonce-0001.json").exists())
            self.assertEqual(runner.read_status(root, "sg0176-test-0001")["status"], "pending")

    def test_schema_rejects_unsupported_operation_and_old_request(self):
        old = (runner.pacific_now() - dt.timedelta(hours=7)).isoformat()
        with self.assertRaisesRegex(runner.RunnerError, "unsupported operation"):
            runner.validate_request(self.make_request(operation="shell"))
        with self.assertRaisesRegex(runner.RunnerError, "freshness"):
            runner.validate_request(self.make_request(created_at=old))

    def test_rejects_path_escape_identifiers_and_large_request(self):
        with self.assertRaisesRegex(runner.RunnerError, "unsafe identifier"):
            runner.validate_request(self.make_request(invocation_id="../escape"))
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            path = root / "incoming" / "huge.json"
            runner.ensure_dirs(root)
            path.write_text("x" * (runner.MAX_REQUEST_BYTES + 1), encoding="utf-8")
            with mock.patch.object(runner, "acquire_lock", return_value=os.open(root / "test.lock", os.O_CREAT | os.O_EXCL | os.O_WRONLY)):
                with self.assertRaises(runner.RunnerError):
                    runner.process_one(root)

    def test_duplicate_nonce_same_payload_is_idempotent_and_replay_diff_fails(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            request = self.make_request()
            first = runner.submit_request(root, request)
            second = runner.submit_request(root, dict(request))
            self.assertEqual(first["status"], "submitted")
            self.assertEqual(second["status"], "already_submitted")
            changed = dict(request)
            changed["mode"] = "capture_drain"
            with self.assertRaisesRegex(runner.RunnerError, "replay"):
                runner.submit_request(root, changed)

    def test_runner_lock_prevents_concurrent_processing(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            runner.ensure_dirs(root)
            fd = runner.acquire_lock(root)
            try:
                with self.assertRaisesRegex(runner.RunnerError, "already active"):
                    runner.acquire_lock(root)
            finally:
                runner.release_lock(root, fd)

    def test_crash_recovery_terminalizes_stale_processing(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            runner.ensure_dirs(root)
            request = self.make_request()
            processing = runner.processing_path(root, request["nonce"])
            processing.write_text(json.dumps(request), encoding="utf-8")
            old = runner.pacific_now().timestamp() - runner.PROCESSING_TIMEOUT_SECONDS - 10
            os.utime(processing, (old, old))

            recovered = runner.recover_stale_processing(root)

            self.assertEqual(recovered, ["sg0176-test-0001"])
            result = runner.read_status(root, "sg0176-test-0001")
            self.assertEqual(result["status"], "failed")
            self.assertEqual(result["result"], "processing_timeout_recovered")

    def test_run_once_empty_snapshot_compacts_snapshots_and_releases_lifecycle(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            request = self.make_request(expected_commit="abc123")
            runner.submit_request(root, request)
            with (
                mock.patch.object(runner, "current_commit", return_value="abc123"),
                mock.patch.object(runner.capture, "apply_compaction", side_effect=[
                    {"created_archives": [], "active_rows": 0, "failed_rows": 0},
                    {"created_archives": [], "active_rows": 0, "failed_rows": 0},
                ]),
                mock.patch.object(runner.capture, "create_snapshot", return_value={
                    "invocation_id": "sg0176-test-0001",
                    "started_at": "2026-07-30T11:59:00-07:00",
                    "rows": [],
                }),
                mock.patch.dict(os.environ, {"MEMORY_STARGRAPH_CAPTURE_RUNNER_ENABLED": "1"}),
                self.lifecycle_mocks()[0] as put_entity,
                self.lifecycle_mocks()[1] as mutate_tag,
                self.lifecycle_mocks()[2],
            ):
                processed = runner.process_one(root)

            self.assertEqual(processed["status"], "processed")
            result = runner.read_status(root, "sg0176-test-0001")
            self.assertEqual(result["status"], "completed")
            self.assertEqual(result["result"], "completed_empty_snapshot_noop")
            self.assertTrue(result["evidence"]["lifecycle_tags_released"])
            self.assertIn("run_slug", result["evidence"])
            self.assertIn("report_slug", result["evidence"])
            self.assertEqual(put_entity.call_count, 3)
            mutate_tag.assert_has_calls([
                mock.call("runs/memory-stargraph-capture-link-drain-sg0176-test-0001", "active", "add"),
                mock.call("runs/memory-stargraph-capture-link-drain-sg0176-test-0001", "active", "remove"),
            ])
            self.assertTrue((root / "logs" / "runner.jsonl").exists())

    def test_run_loop_is_disabled_by_default_and_processes_when_enabled(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            with self.assertRaisesRegex(runner.RunnerError, "disabled"):
                runner.run_loop(root, max_iterations=1)
            with (
                mock.patch.object(runner, "process_one", return_value={"ok": True, "status": "idle"}),
                mock.patch.dict(os.environ, {"MEMORY_STARGRAPH_CAPTURE_RUNNER_ENABLED": "1"}),
            ):
                result = runner.run_loop(root, poll_seconds=0, max_iterations=2)
            self.assertEqual(result["iterations"], 2)
            self.assertEqual(result["processed"], 0)

    def test_non_empty_snapshot_fails_closed_without_mutating_capture(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            runner.submit_request(root, self.make_request())
            with (
                mock.patch.object(runner, "current_commit", return_value="abc123"),
                mock.patch.object(runner.capture, "apply_compaction", return_value={"created_archives": []}),
                mock.patch.object(runner.capture, "create_snapshot", return_value={
                    "invocation_id": "sg0176-test-0001",
                    "started_at": "2026-07-30T11:59:00-07:00",
                    "rows": [{"id": "CAP-0001", "status": "planned"}],
                }),
                mock.patch.dict(os.environ, {"MEMORY_STARGRAPH_CAPTURE_RUNNER_ENABLED": "1"}),
                self.lifecycle_mocks()[0],
                self.lifecycle_mocks()[1],
                self.lifecycle_mocks()[2],
            ):
                runner.process_one(root)

            result = runner.read_status(root, "sg0176-test-0001")
            self.assertEqual(result["status"], "failed")
            self.assertEqual(result["result"], "non_empty_snapshot_requires_host_capture_extension")
            self.assertIn("run_slug", result["evidence"])

    def test_terminalize_lifecycle_rejects_active_tag_readback(self):
        values = runner.validate_request(self.make_request())
        with (
            mock.patch.object(runner, "put_entity"),
            mock.patch.object(runner, "mutate_tag"),
            mock.patch.object(runner, "read_tags", return_value=["active", "capture-link"]),
        ):
            with self.assertRaisesRegex(runner.RunnerError, "active tag release failed"):
                runner.terminalize_lifecycle(
                    values,
                    "runs/memory-stargraph-capture-link-drain-sg0176-test-0001",
                    "reports/memory-stargraph-capture-link-drain-2026-07-30-sg0176-test-0001",
                    "completed",
                    "completed_empty_snapshot_noop",
                    {"snapshot": {"rows": []}},
                )

    def test_read_tags_accepts_comma_separated_gbrain_output(self):
        completed = runner.subprocess.CompletedProcess(
            ["gbrain", "tags", "slug"],
            0,
            "capture-link, completed, curator, host-runner\n",
            "",
        )
        with mock.patch.object(runner, "run_gbrain", return_value=completed):
            self.assertEqual(
                runner.read_tags("slug"),
                ["capture-link", "completed", "curator", "host-runner"],
            )


if __name__ == "__main__":
    unittest.main()
