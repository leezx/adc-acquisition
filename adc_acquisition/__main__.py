"""Dispatcher: python -m adc_acquisition <job> [options]

`run-all` (Prompt.md section 31) is intentionally not implemented yet — it
must only orchestrate independent jobs without coupling them, and right now
there is only one job to orchestrate.
"""

from __future__ import annotations

import sys

from jobs.pubmed.job import PubMedJob

JOBS = {
    "pubmed": PubMedJob,
}


def main(argv: list[str] | None = None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    if not argv or argv[0] in ("-h", "--help") or argv[0] not in JOBS:
        print("usage: python -m adc_acquisition <job> [options]")
        print(f"available jobs: {', '.join(sorted(JOBS))}")
        return 0 if argv[:1] in ([], ["-h"], ["--help"]) else 1

    job_name = argv[0]
    job_cls = JOBS[job_name]
    parser = job_cls.build_arg_parser()
    args = parser.parse_args(argv[1:])
    job = job_cls()
    result = job.run(args)
    print(result)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
