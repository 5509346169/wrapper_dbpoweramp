"""conftest.py: pytest configuration — pre-import mutagen to break import-lock deadlock.

On Windows, Python's import machinery can deadlock when:
  1. Thread A holds the import lock and tries to import mutagen (which itself
     may lock on Windows file access), while
  2. Thread B waits for the import lock.

Pre-importing mutagen here (in the main thread, before workers are spawned)
releases the lock so tests can safely patch src.audio.inspector.MutagenFile.
"""
import mutagen  # noqa: F401
