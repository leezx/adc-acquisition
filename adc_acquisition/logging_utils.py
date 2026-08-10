"""Per-job logging setup, including a dedicated failed-identifier log.

Prompt.md section 4 requires that jobs "log failed identifiers" and "never
silently drop failures" — a failure must show up in a durable log file, not
just stderr.
"""

from __future__ import annotations

import logging
from pathlib import Path


def _reset_handlers(logger: logging.Logger) -> None:
    for handler in list(logger.handlers):
        logger.removeHandler(handler)
        handler.close()


def setup_job_logging(job_name: str, output_dir: Path) -> tuple[logging.Logger, logging.Logger]:
    """Returns (job_logger, failure_logger). failure_logger writes only to
    DATA/logs/<job_name>_failures.log, one line per failed source_record_id.

    Logger objects are cached globally by name (logging.getLogger), so a
    second call with a different output_dir in the same process must replace
    the handlers rather than skip setup — otherwise logs keep going to the
    first output_dir ever used, which is wrong for --output overrides and
    for tests that run multiple jobs against different tmp dirs.
    """
    log_dir = Path(output_dir) / "logs"
    log_dir.mkdir(parents=True, exist_ok=True)

    job_logger = logging.getLogger(f"adc_acquisition.{job_name}")
    job_logger.setLevel(logging.INFO)
    _reset_handlers(job_logger)
    handler = logging.FileHandler(log_dir / f"{job_name}.log", encoding="utf-8")
    handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(message)s"))
    job_logger.addHandler(handler)
    stream_handler = logging.StreamHandler()
    stream_handler.setFormatter(logging.Formatter("%(levelname)s %(message)s"))
    job_logger.addHandler(stream_handler)

    failure_logger = logging.getLogger(f"adc_acquisition.{job_name}.failures")
    failure_logger.setLevel(logging.INFO)
    _reset_handlers(failure_logger)
    failure_handler = logging.FileHandler(log_dir / f"{job_name}_failures.log", encoding="utf-8")
    failure_handler.setFormatter(logging.Formatter("%(asctime)s %(message)s"))
    failure_logger.addHandler(failure_handler)
    failure_logger.propagate = False

    return job_logger, failure_logger
