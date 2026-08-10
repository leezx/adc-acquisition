"""The acquisition job interface (Prompt.md sections 4 and 32).

Every source-specific job is an independent CLI-executable class. Sources
are heterogeneous enough (clean APIs vs. scraping a company's PDF pipeline
page) that we do not force a rigid discover/fetch template method here.
Instead, AcquisitionJob fixes what must be identical across every job:

- the CLI surface (--dry-run/--limit/--resume/--since/--until/--output)
- returning a JobRunResult summary that reports can render uniformly

and leaves `run()` free to use the shared http_utils/checkpoint/manifest/
logging_utils modules however fits that source.
"""

from __future__ import annotations

import argparse
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from pathlib import Path

DEFAULT_OUTPUT_DIR = Path("DATA")


@dataclass
class JobRunResult:
    job_name: str
    dry_run: bool
    queries_run: int = 0
    records_discovered: int = 0
    records_downloaded: int = 0
    records_skipped_unchanged: int = 0
    records_failed: int = 0
    manifest_path: str | None = None
    notes: list[str] = field(default_factory=list)


def add_common_arguments(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--dry-run", action="store_true", help="Discover record counts without downloading.")
    parser.add_argument("--limit", type=int, default=None, help="Cap the number of records processed.")
    parser.add_argument("--resume", action="store_true", help="Resume from the last checkpoint's date cursor.")
    parser.add_argument("--since", type=str, default=None, help="Only records published/released on or after this date (YYYY-MM-DD).")
    parser.add_argument("--until", type=str, default=None, help="Only records published/released on or before this date (YYYY-MM-DD).")
    parser.add_argument("--output", type=str, default=str(DEFAULT_OUTPUT_DIR), help="Root output directory (default: DATA).")


class AcquisitionJob(ABC):
    name: str

    @classmethod
    def build_arg_parser(cls) -> argparse.ArgumentParser:
        parser = argparse.ArgumentParser(prog=f"adc_acquisition {cls.name}")
        add_common_arguments(parser)
        cls.add_job_arguments(parser)
        return parser

    @classmethod
    def add_job_arguments(cls, parser: argparse.ArgumentParser) -> None:
        """Override to add source-specific CLI flags."""
        return

    @abstractmethod
    def run(self, args: argparse.Namespace) -> JobRunResult:
        """Execute the job for the given parsed args."""
        raise NotImplementedError
