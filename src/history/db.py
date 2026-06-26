"""history/db.py: Backward-compatibility shim.

The implementation has been split into:

* :mod:`src.history.schema`        — shared CREATE TABLE / pragmas
* :mod:`src.history.write_queue`   — async writer thread
* :mod:`src.history.conversion_db` — synchronous read/write wrapper

This module re-exports the same public/private names from those locations
so existing imports (e.g. ``from src.history.db import ConversionDB, DBWriteQueue``)
continue to work.
"""

from src.history.conversion_db import ConversionDB
from src.history.write_queue import DBWriteQueue

__all__ = [
    "ConversionDB",
    "DBWriteQueue",
]
