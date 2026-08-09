#!/usr/bin/env python3
"""Fail closed unless the dashboard-managed Python supplies activation dependencies."""
try:
    import nats
except ImportError as error:
    raise SystemExit("nats-py==2.15.0 is required by the dashboard runtime") from error
if getattr(nats, "__version__", "") != "2.15.0":
    raise SystemExit("dashboard runtime must use nats-py==2.15.0")
