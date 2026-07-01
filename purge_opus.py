"""One-shot probe-and-purge script for Opus-in-m4a files.

dBpoweramp's Opus encoder writes .m4a containers but the inner codec is Opus,
so the extension alone isn't enough — we use mutagen to probe each .m4a file
and only delete the ones whose codec is 'opus'.

Run: py -3.14 purge_opus.py
"""
import os
import sys
from pathlib import Path

try:
    from mutagen import File as mutagen_file
except ImportError:
    sys.exit("mutagen is not installed. Run: pip install mutagen")

try:
    from rich.console import Console
    from rich.progress import (
        BarColumn,
        Progress,
        TextColumn,
        TimeElapsedColumn,
        TimeRemainingColumn,
        SpinnerColumn,
    )
except ImportError:
    sys.exit("rich is not installed. Run: pip install rich")


OUTPUT_ROOT = Path(r"D:\MusicLossy\AM-DL")

console = Console()

console.print(f"[bold]Opus purge[/bold]  root=[cyan]{OUTPUT_ROOT}[/cyan]")


# --- Phase 1: enumerate m4a files (cheap; uses os.scandir) ---
console.print("[dim]Phase 1: enumerating .m4a files...[/dim]")
m4a_files: list[Path] = []
for root, _dirs, files in os.walk(OUTPUT_ROOT):
    for fn in files:
        if fn.lower().endswith(".m4a"):
            m4a_files.append(Path(root) / fn)

total = len(m4a_files)
console.print(f"  found [bold]{total}[/bold] .m4a files to probe")

# --- Phase 2: probe each, delete the Opus ones ---
total_probed = 0
opus_found = 0
opus_deleted = 0
probe_errors = 0
other_codecs: dict[str, int] = {}

progress = Progress(
    SpinnerColumn(),
    TextColumn("[progress.description]{task.description}"),
    BarColumn(),
    TextColumn("[progress.percentage]{task.percentage:>3.0f}%"),
    TextColumn("[bold cyan]{task.completed}/{task.total}[/bold cyan]"),
    TimeElapsedColumn(),
    TextColumn("eta"),
    TimeRemainingColumn(),
    console=console,
    transient=False,
)

with progress:
    task_id = progress.add_task("Probing .m4a", total=total)

    for m4a_file in m4a_files:
        total_probed += 1

        try:
            audio = mutagen_file(m4a_file)
        except Exception as exc:
            probe_errors += 1
            console.print(f"  [red][ERROR][/red] probe failed: [dim]{m4a_file}[/dim]  {exc}")
            progress.update(task_id, advance=1)
            continue

        if audio is None:
            other_codecs["(unrecognised)"] = other_codecs.get("(unrecognised)", 0) + 1
            progress.update(task_id, advance=1)
            continue

        codec = (getattr(audio.info, "codec", "") or "").lower()
        other_codecs[codec] = other_codecs.get(codec, 0) + 1

        if codec == "opus":
            opus_found += 1
            size_kib = m4a_file.stat().st_size // 1024
            try:
                m4a_file.unlink()
                opus_deleted += 1
                console.print(
                    f"  [green][DELETE][/green] {m4a_file}  [dim]({size_kib} KiB)[/dim]"
                )
            except OSError as exc:
                probe_errors += 1
                console.print(
                    f"  [red][ERROR][/red] could not delete [dim]{m4a_file}[/dim]  {exc}"
                )
        progress.update(task_id, advance=1)


# --- Summary ---
console.rule("[bold]Summary[/bold]")
console.print(f"  Probed           [bold]{total_probed}[/bold]")
console.print(f"  Opus found       [bold yellow]{opus_found}[/bold yellow]")
console.print(f"  Opus deleted     [bold green]{opus_deleted}[/bold green]")
console.print(f"  Probe errors     [bold red]{probe_errors}[/bold red]")
console.print()
console.print("Other codecs seen:")
for codec, count in sorted(other_codecs.items(), key=lambda x: -x[1]):
    console.print(f"  [cyan]{codec:24s}[/cyan]  {count:>6d}")

if probe_errors > 0:
    sys.exit(1)