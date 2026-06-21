import os
import yaml
import shutil
import subprocess
import argparse
import sqlite3
import collections
import time
from datetime import datetime
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor, as_completed

from rich.console import Console
from rich.progress import Progress, SpinnerColumn, TextColumn, BarColumn, MofNCompleteColumn, TimeElapsedColumn
from rich.live import Live
from rich.panel import Panel
from rich.layout import Layout
from rich.text import Text

# Configuration
DB_PATH = Path(r"C:\Program Files\dBpoweramp")
CORE_CONVERTER = DB_PATH / "CoreConverter.exe"
PRESETS_FILE = Path("dbpoweramp_presets.yaml")
DEFAULT_LOG_DB = "conversion_history.db"

AUDIO_EXTENSIONS = {".flac", ".wav", ".m4a", ".mp3", ".ogg", ".opus", ".wma", ".aif", ".aiff"}
SIDECAR_EXTENSIONS = {".lrc", ".txt"}
COVER_PATTERNS = {"cover.jpg", "cover.png", "folder.jpg", "albumart.jpg"}

console = Console()

class ConversionDB:
    def __init__(self, db_path):
        self.db_path = Path(db_path).resolve()
        self._setup_db()

    def _setup_db(self):
        with sqlite3.connect(self.db_path) as conn:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS history (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    source_path TEXT,
                    dest_path TEXT,
                    command TEXT,
                    status TEXT,
                    error_msg TEXT,
                    stdout TEXT,
                    timestamp TEXT,
                    UNIQUE(source_path, dest_path)
                )
            """)

    def get_record(self, source_path, dest_path):
        try:
            with sqlite3.connect(self.db_path) as conn:
                cursor = conn.execute(
                    "SELECT command, status FROM history WHERE source_path = ? AND dest_path = ?", 
                    (str(source_path), str(dest_path))
                )
                return cursor.fetchone()
        except: return None

    def log_conversion(self, source_path, dest_path, command, status, error_msg=None, stdout=None):
        now = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        with sqlite3.connect(self.db_path) as conn:
            conn.execute("""
                INSERT OR REPLACE INTO history (source_path, dest_path, command, status, error_msg, stdout, timestamp)
                VALUES (?, ?, ?, ?, ?, ?, ?)
            """, (str(source_path), str(dest_path), command, status, error_msg, stdout, now))

def load_presets():
    if not PRESETS_FILE.exists(): return {}
    with open(PRESETS_FILE, "r") as f:
        return yaml.safe_load(f).get("presets", {})

def run_conversion_stream(infile: Path, outfile: Path, encoder: str, extra_args: str, verbose_queue):
    """Runs conversion and streams output line-by-line to the verbose queue."""
    outfile.parent.mkdir(parents=True, exist_ok=True)
    cmd = f'"{CORE_CONVERTER}" -infile="{infile}" -outfile="{outfile}" -convert_to="{encoder}" {extra_args}'
    
    # We don't use -silent so we can see the CoreConverter verbose output
    process = subprocess.Popen(
        cmd, 
        shell=True, 
        stdout=subprocess.PIPE, 
        stderr=subprocess.STDOUT, 
        text=True, 
        bufsize=1,
        encoding='utf-8',
        errors='replace'
    )
    
    full_output = []
    for line in iter(process.stdout.readline, ""):
        clean_line = line.strip()
        if clean_line:
            full_output.append(clean_line)
            if verbose_queue is not None:
                # Prefix with filename to distinguish workers
                verbose_queue.append(f"[dim]{infile.name[:20]}:[/] {clean_line}")
    
    process.stdout.close()
    return_code = process.wait()
    
    success = (return_code == 0)
    output_str = "\n".join(full_output)
    error_msg = None if success else f"Exit Code {return_code}"
    
    return success, cmd, output_str, error_msg

def process_single_file(infile: Path, input_root: Path, output_root: Path, config: dict, target_ext: str, db: ConversionDB, force: bool, verbose_queue, progress, master_task):
    encoder = config['encoder']
    extra_args = " ".join([str(a) for a in config.get('args', [])])
    
    if input_root.is_dir():
        try: rel_path = infile.relative_to(input_root)
        except ValueError: rel_path = Path(infile.name)
        outfile = (output_root / rel_path).with_suffix(target_ext)
    else:
        outfile = output_root / input_root.with_suffix(target_ext).name

    full_cmd = f'"{CORE_CONVERTER}" -infile="{infile}" -outfile="{outfile}" -convert_to="{encoder}" {extra_args}'
    
    # Resume Logic
    record = db.get_record(infile, outfile)
    if not force and record:
        old_cmd, status = record
        if status == "SUCCESS" and old_cmd == full_cmd and outfile.exists():
            progress.update(master_task, advance=1)
            return "SKIPPED", infile.name

    worker_task = progress.add_task(f"[cyan]Worker:[/] {infile.name[:25]}...", total=1)
    
    # Stream conversion
    success, actual_cmd, stdout, error_msg = run_conversion_stream(infile, outfile, encoder, extra_args, verbose_queue)
    
    if success:
        for ext in SIDECAR_EXTENSIONS:
            src = infile.with_suffix(ext)
            if src.exists(): shutil.copy2(src, outfile.with_suffix(ext))
        for pattern in COVER_PATTERNS:
            src = infile.parent / pattern
            if src.exists():
                dest = outfile.parent / pattern
                if not dest.exists(): shutil.copy2(src, dest)
        
        db.log_conversion(infile, outfile, actual_cmd, "SUCCESS", stdout=stdout)
        res = "SUCCESS"
    else:
        db.log_conversion(infile, outfile, actual_cmd, "FAILED", error_msg=error_msg, stdout=stdout)
        res = "FAILED"
        if verbose_queue is not None:
            verbose_queue.append(f"[bold red]ERROR {infile.name[:20]}:[/] {error_msg}")
    
    progress.update(worker_task, completed=1, visible=False)
    progress.remove_task(worker_task)
    progress.update(master_task, advance=1)
    return res, infile.name

def main():
    parser = argparse.ArgumentParser(description="dBpoweramp Batch Converter Pro (Live Stream Verbose)")
    parser.add_argument("-I", "--input", required=True, help="Input directory")
    parser.add_argument("-O", "--output", required=True, help="Output directory")
    parser.add_argument("-p", "--preset", required=True, help="Preset from YAML")
    parser.add_argument("-w", "--workers", type=int, default=os.cpu_count())
    parser.add_argument("-v", "--verbose", action="store_true", help="Show live conversion stream panel")
    parser.add_argument("--exclude", action="append", help="Folders to skip (can use multiple times or '|')")
    parser.add_argument("--db", default=DEFAULT_LOG_DB, help="History database path")
    parser.add_argument("--force", action="store_true", help="Re-convert everything")
    
    args = parser.parse_args()
    input_path, output_path = Path(args.input).resolve(), Path(args.output).resolve()
    db = ConversionDB(args.db)
    
    excludes = []
    if args.exclude:
        for item in args.exclude:
            excludes.extend([x.strip() for x in item.split("|") if x.strip()])

    presets = load_presets()
    config = presets.get(args.preset)
    if not config:
        console.print(f"[red]Error:[/] Preset '{args.preset}' not found."); return
    
    target_ext = config.get('ext', '.mp3')
    if not target_ext.startswith("."): target_ext = "." + target_ext

    files_to_process = []
    if input_path.is_file():
        files_to_process.append(input_path)
    else:
        for root, dirs, files in os.walk(input_path, followlinks=True):
            dirs[:] = [d for d in dirs if d not in excludes]
            for f in files:
                if Path(f).suffix.lower() in AUDIO_EXTENSIONS:
                    files_to_process.append(Path(root) / f)

    if not files_to_process:
        console.print("[red]No files found.[/]"); return

    # Setup UI
    progress = Progress(
        SpinnerColumn(),
        TextColumn("[progress.description]{task.description}"),
        BarColumn(),
        MofNCompleteColumn(),
        TimeElapsedColumn(),
        console=console
    )
    master_task = progress.add_task("[bold green]Total Progress", total=len(files_to_process))
    
    # Increase log buffer size for streaming lines
    verbose_log = collections.deque(maxlen=15) if args.verbose else None

    layout = Layout()
    layout.split(
        Layout(name="main", ratio=2),
        Layout(name="footer", ratio=1)
    )
    if not args.verbose:
        layout["footer"].visible = False

    with Live(layout, refresh_per_second=10, screen=False) as live:
        stats = {"SUCCESS": 0, "FAILED": 0, "SKIPPED": 0}
        
        with ThreadPoolExecutor(max_workers=args.workers) as executor:
            futures = [
                executor.submit(process_single_file, f, input_path, output_path, config, target_ext, db, args.force, verbose_log, progress, master_task) 
                for f in files_to_process
            ]
            
            while any(not f.done() for f in futures):
                log_text = Text.from_markup("\n".join(list(verbose_log))) if verbose_log else Text("")
                layout["main"].update(Panel(progress, title=f"dBpoweramp: {args.preset}", border_style="green"))
                layout["footer"].update(Panel(log_text, title="CoreConverter Live Verbose Stream", border_style="blue"))
                time.sleep(0.05)

            for future in as_completed(futures):
                status, _ = future.result()
                stats[status] += 1

    console.print(f"\n[bold green]Done![/] Success: {stats['SUCCESS']} | Skipped: {stats['SKIPPED']} | Failed: [red]{stats['FAILED']}[/]")

if __name__ == "__main__":
    main()
