"""Re-exported from adc_acquisition.web_snapshot_client for backward
compatibility -- moved there when Job 12 (company press releases)
confirmed it needed the identical generic fetch-raw-bytes client. See
that module's docstring for the full rationale (same pattern as
jobs/wipo/client.py's move to adc_acquisition/ops_client.py)."""

from __future__ import annotations

from adc_acquisition.web_snapshot_client import DEFAULT_RATE_LIMIT as RATE_LIMIT
from adc_acquisition.web_snapshot_client import USER_AGENT
from adc_acquisition.web_snapshot_client import WebSnapshotClient as PipelineClient

__all__ = ["RATE_LIMIT", "USER_AGENT", "PipelineClient"]
