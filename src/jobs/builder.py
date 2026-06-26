"""jobs/builder.py: Backward-compatibility shim.

The implementation has been split into:

* :mod:`src.jobs.classify`    — job_type decision and IndexRow mutation
* :mod:`src.jobs.enrich`      — streaming and blocking probe pipelines
* :mod:`src.jobs.build_jobs`  — ConversionJob list construction

This module re-exports the same public/private names from those locations
so existing imports (e.g. ``from src.jobs.builder import _classify, enrich_index_rows``)
continue to work. ``compute_output_path`` is also re-exported because the
original module imported it at top level (and tests monkey-patch it here).
"""

from src.jobs.build_jobs import build_jobs
from src.jobs.classify import classify as _classify
from src.jobs.enrich import enrich_index_rows, enrich_index_rows_streaming
from src.pathing.resolver import compute_output_path

__all__ = [
    "build_jobs",
    "compute_output_path",
    "enrich_index_rows",
    "enrich_index_rows_streaming",
    "_classify",
]
