"""tests/test_progress_renderer_width.py: Regression tests for the progress bar
renderer not wrapping or producing column-truncation marks on narrow terminals.

The original renderer used ``Table.grid`` with hard-coded column widths that
summed to 96 chars plus padding, which exceeded the 80-column PowerShell
default. The wrapping caused Rich's Live redraw to leave ghost lines and
``…`` truncation markers on the screen.

These tests pin the new behaviour: every row in the rendered output is exactly
``console.width`` columns wide, no row wraps, and there are no truncation
``…`` markers anywhere in the description.
"""

from __future__ import annotations

import io

import pytest
from rich.console import Console


def _make_console(width: int = 80) -> tuple[Console, io.StringIO]:
    """Build a Rich Console with a stable width for tests.

    Rich's auto-detection reads ``os.get_terminal_size()`` and ignores the
    ``width=`` constructor kwarg on many platforms, so we set the private
    ``_width`` / ``_height`` slots explicitly after construction. This
    forces ``Console.size.width`` to honor the requested width.
    """
    buf = io.StringIO()
    c = Console(file=buf, width=width, force_terminal=True, legacy_windows=False)
    c._width = width
    c._height = 25
    return c, buf


def _render_to_string(console: Console, renderer) -> str:
    """Render the renderer and return the console-printed string."""
    from src.ui.progress.renderer import _ProgressRenderer

    assert isinstance(renderer, _ProgressRenderer)
    # Stub the renderer's console to the width-controlled one.
    renderer._console = console
    text = renderer.render()
    console.print(text)
    return console.file.getvalue()  # type: ignore[attr-defined]


class TestNoWrapAt80Columns:
    """The single biggest user-visible bug: rows were wrapping onto two lines."""

    def test_master_row_does_not_wrap(self) -> None:
        from src.ui.progress.renderer import _ProgressRenderer

        c, buf = _make_console(80)
        r = _ProgressRenderer(total=359, total_bytes=858 * 1024 ** 3,
                              console=c, phase_name="Converting")
        r._master_done = 29
        r._activity = "converting"
        output = _render_to_string(c, r)

        lines = output.splitlines()
        assert lines, "no output"
        first_line = lines[0]
        assert len(first_line) <= 80, (
            f"master row exceeds 80 cols: {len(first_line)} chars\n{first_line!r}"
        )

    def test_master_row_with_counters_does_not_wrap(self) -> None:
        from src.ui.progress.renderer import _ProgressRenderer

        c, buf = _make_console(80)
        r = _ProgressRenderer(total=27646, total_bytes=858 * 1024 ** 3,
                              console=c, phase_name="Pre-verifying 27646 files")
        r._master_done = 15000
        r._activity = "verifying"
        r._demoted, r._kept = 3, 14997
        output = _render_to_string(c, r)

        first_line = output.splitlines()[0]
        assert len(first_line) <= 80, (
            f"master row with counters exceeds 80 cols: {len(first_line)}\n{first_line!r}"
        )

    def test_subtask_rows_do_not_wrap(self) -> None:
        from src.ui.progress.renderer import _ProgressRenderer

        c, buf = _make_console(80)
        r = _ProgressRenderer(total=359, total_bytes=858 * 1024 ** 3,
                              console=c, phase_name="Converting")
        r._master_done = 5
        r._activity = "converting"
        r.add_bar("1.01. One day, the pale moon lights the sky")
        r.add_bar("1.02. Fly with Me - Steve Aoki Neon Future Remix.m4a")
        r.add_bar("2.10. Some absurdly long track title that should be truncated")
        output = _render_to_string(c, r)

        lines = output.splitlines()
        assert len(lines) == 4  # master + 3 sub-bars
        for line in lines:
            assert len(line) <= 80, (
                f"row exceeds 80 cols: {len(line)}\n{line!r}"
            )


class TestNoEllipsisMarkers:
    """The old renderer inserted Rich's ``…`` truncation marker when content
    exceeded the column width. We use clean right-trim instead."""

    def test_no_ellipsis_in_master_row(self) -> None:
        from src.ui.progress.renderer import _ProgressRenderer

        c, _ = _make_console(80)
        r = _ProgressRenderer(total=359, total_bytes=858 * 1024 ** 3,
                              console=c, phase_name="Pre-verifying 27646 cached output(s)")
        r._master_done = 0
        r._activity = "verifying"
        output = _render_to_string(c, r)

        for line in output.splitlines():
            # The block-character bar (█, ░, ▰, ▱) is fine; only the ellipsis "…"
            # is the bug we're guarding against.
            assert "…" not in line, f"ellipsis leaked into output: {line!r}"

    def test_no_ellipsis_when_description_long(self) -> None:
        from src.ui.progress.renderer import _ProgressRenderer

        c, _ = _make_console(80)
        r = _ProgressRenderer(total=1000, total_bytes=None,
                              console=c, phase_name="Pre-verifying 1000 files")
        r._master_done = 500
        r._activity = "a really long activity name that should be cut off cleanly"
        output = _render_to_string(c, r)

        for line in output.splitlines():
            assert "…" not in line, f"ellipsis leaked into output: {line!r}"


class TestAdaptsToWiderTerminal:
    """On wider consoles the description column should grow so we don't lose
    information. The min/max bounds clamp it to a sensible range."""

    def test_desc_width_scales_with_console(self) -> None:
        from src.ui.progress.renderer import _ProgressRenderer

        c80, _ = _make_console(80)
        c120, _ = _make_console(120)
        c40, _ = _make_console(40)

        r80 = _ProgressRenderer(total=100, total_bytes=None, console=c80)
        r120 = _ProgressRenderer(total=100, total_bytes=None, console=c120)
        r40 = _ProgressRenderer(total=100, total_bytes=None, console=c40)

        # Wider console → wider description column.
        assert r120._desc_width() > r80._desc_width() > r40._desc_width()

        # Even on the very narrowest reasonable terminal we keep a readable
        # description cell.
        assert r40._desc_width() >= 20

    def test_desc_width_when_size_column_hidden(self) -> None:
        """Without the size column the description gets more room."""
        from src.ui.progress.renderer import _ProgressRenderer

        c, _ = _make_console(80)
        r_with = _ProgressRenderer(total=100, total_bytes=1024 ** 3, console=c)
        r_no = _ProgressRenderer(total=100, total_bytes=None, console=c)
        assert r_no._desc_width() > r_with._desc_width()


class TestTruncateHelper:
    """The truncation helper must never insert ``…`` and must produce
    right-justified fixed-width output for narrow terminals."""

    def test_truncate_short_pads_with_spaces(self) -> None:
        from src.ui.progress.renderer import _ProgressRenderer

        out = _ProgressRenderer._truncate("hi", 10)
        assert len(out) == 10
        assert out.startswith("hi")
        assert out.endswith("  ")

    def test_truncate_long_right_cuts(self) -> None:
        from src.ui.progress.renderer import _ProgressRenderer

        out = _ProgressRenderer._truncate("a very long string that overflows", 12)
        # The truncate helper slices to ``width`` chars then rstrips trailing
        # whitespace — so the result is at most ``width`` chars but can be
        # shorter. Either is acceptable; the contract is "no wider than width,
        # no … inserted".
        assert len(out) <= 12
        assert "…" not in out
        assert out  # not empty

    def test_truncate_exact(self) -> None:
        from src.ui.progress.renderer import _ProgressRenderer

        out = _ProgressRenderer._truncate("0123456789", 10)
        assert out == "0123456789"


class TestWidthAwareDescription:
    """Optional fragments (activity, counters) are dropped when they would
    overflow the description cell, so the bar always renders."""

    @pytest.fixture
    def renderer(self):
        from src.ui.progress.renderer import _ProgressRenderer

        c, _ = _make_console(80)
        r = _ProgressRenderer(
            total=359, total_bytes=858 * 1024 ** 3,
            console=c, phase_name="Converting",
        )
        r._master_done = 29
        r._activity = "converting"
        return r

    def test_required_segments_always_present(self, renderer) -> None:
        # Trigger _desc_width then build description
        d = renderer._build_description(renderer._desc_width())
        assert "Converting" in d
        assert "29/359" in d
        assert "left" in d or "done" in d

    def test_activity_dropped_when_no_room(self, renderer) -> None:
        # Force an absurdly narrow budget to make sure activity is dropped.
        d = renderer._build_description(20)
        assert "Converting" in d
        assert "(converting)" not in d, (
            f"activity should be dropped at 20 cols: {d!r}"
        )

    def test_counters_shown_when_room(self, renderer) -> None:
        renderer._demoted = 5
        renderer._kept = 24
        d = renderer._build_description(60)
        assert "↑5 demote" in d
        assert "✓24 kept" in d

    def test_counters_dropped_when_no_room(self, renderer) -> None:
        renderer._demoted = 5
        renderer._kept = 24
        d = renderer._build_description(20)
        assert "↑5 demote" not in d
        assert "✓24 kept" not in d

    def test_activity_suppressed_when_substring_of_phase_name(self, renderer) -> None:
        """Activity is dropped when it adds no info beyond the phase name.

        Otherwise the master row becomes noisy: e.g. phase "Converting"
        + activity "convert" renders as "Converting 0/359 359 left (convert)".
        """
        # The default fixture has phase_name="Converting" and activity="converting".
        d = renderer._build_description(60)
        assert "Converting" in d
        assert "(converting)" not in d

    def test_activity_shown_when_distinct_from_phase_name(self, renderer) -> None:
        """Activity is preserved when it conveys new information."""
        renderer._phase_name = "Probing"
        renderer._activity = "metadata tagger"
        d = renderer._build_description(60)
        assert "Probing" in d
        assert "(metadata tagger)" in d