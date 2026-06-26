"""ui/progress_view.py: Backward-compatibility shim.

The implementation has been split into the ``src.ui.progress`` subpackage.
This module re-exports the same public/private names from the new location
so existing imports (e.g. ``from src.ui.progress_view import RichProgressSink``)
continue to work.
"""

from src.ui.progress.null_sink import NullProgressSink
from src.ui.progress.protocol import ProgressSink, SubtaskID, _STRIP_MARKUP_RE
from src.ui.progress.renderer import _BarState, _ProgressRenderer
from src.ui.progress.rich_sink import RichProgressSink
from src.ui.progress.verbose_sink import VerboseProgressSink

__all__ = [
    "NullProgressSink",
    "ProgressSink",
    "RichProgressSink",
    "SubtaskID",
    "VerboseProgressSink",
    "_BarState",
    "_ProgressRenderer",
    "_STRIP_MARKUP_RE",
]
