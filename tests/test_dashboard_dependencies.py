import unittest
from importlib import metadata

from scripts.automation import check_dashboard_dependencies as checker


class DashboardDependencyTests(unittest.TestCase):
    def test_accepts_exact_nats_distribution_version(self):
        calls = []

        def version(distribution):
            calls.append(distribution)
            return "2.15.0"

        self.assertEqual(checker.main(version), 0)
        self.assertEqual(calls, ["nats-py"])

    def test_rejects_missing_or_wrong_nats_distribution_without_importing_module(self):
        def missing(_distribution):
            raise metadata.PackageNotFoundError("nats-py")

        for version in (missing, lambda _distribution: "2.14.4"):
            with self.subTest(version=version):
                with self.assertRaisesRegex(SystemExit, "nats-py==2.15.0"):
                    checker.main(version)


if __name__ == "__main__":
    unittest.main()
