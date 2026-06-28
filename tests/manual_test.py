"""Manual test runner - writes results to a file."""
import sys
sys.path.insert(0, ".")

results = []

def log(msg):
    results.append(str(msg))

try:
    log("=== Testing imports ===")
    
    from src.audio.integrity import VerifyStatus, VerifyResult, verify_file
    log("OK: src.audio.integrity")
    
    from src.audio.verify_backends import verify_file as vb_verify, READ_BLOCK, SF_EXTS, MA_EXTS
    log("OK: src.audio.verify_backends")
    
    from src.history.schema import CREATE_HISTORY_TABLE_SQL, ADD_VERIFY_COLUMNS_SQL, INSERT_OR_REPLACE_HISTORY_SQL
    log("OK: src.history.schema")
    
    from src.history.migrations import SCHEMA_VERSION, get_schema_version, migrate_to_current, get_db_version, DbVersionInfo
    log(f"OK: src.history.migrations (SCHEMA_VERSION={SCHEMA_VERSION})")
    
    from src.history.conversion_db import ConversionDB
    log("OK: src.history.conversion_db")
    
    from src.execution.events import JobEventKind
    log(f"OK: src.execution.events (VERIFY_RESULT in enum: {hasattr(JobEventKind, 'VERIFY_RESULT')})")
    
    from src.execution.run_job import _verify_output_file
    log("OK: src.execution.run_job")
    
    from src.ui.progress.protocol import ProgressSink
    log("OK: src.ui.progress.protocol")
    
    from src.ui.progress.rich_sink import RichProgressSink
    log("OK: src.ui.progress.rich_sink")
    
    from src.ui.progress.verbose_sink import VerboseProgressSink
    log("OK: src.ui.progress.verbose_sink")
    
    from src.ui.progress.null_sink import NullProgressSink
    log("OK: src.ui.progress.null_sink")
    
    from src.execution.event_drain import _drain_events_into_ui
    log("OK: src.execution.event_drain")
    
    from src.cli.args import parse_args
    log("OK: src.cli.args")
    
    from src.cli.db_cmd import cmd_db_check, cmd_db_migrate, cmd_db_doctor
    log("OK: src.cli.db_cmd")
    
    from src.app.context import AppContext, build_context, MutablePhaseState
    log("OK: src.app.context")
    
    from src.app.backend import resolve_backend_name, supports
    log("OK: src.app.backend")
    
    from src.app.lifecycle.signals import install_signal_guard, SignalGuard
    log("OK: src.app.lifecycle.signals")
    
    from src.app.lifecycle.tempdir import setup_temp_dir, cleanup_index
    log("OK: src.app.lifecycle.tempdir")
    
    from src.app.lifecycle.scan_cache import open_scan_cache, create_scan_cache, close_scan_cache
    log("OK: src.app.lifecycle.scan_cache")
    
    from src.app.pipeline.scan import scan, ScanResult
    log("OK: src.app.pipeline.scan")
    
    from src.app.pipeline.enrich import enrich
    log("OK: src.app.pipeline.enrich")
    
    from src.app.pipeline.jobs import build_jobs, check_lossy_gate
    log("OK: src.app.pipeline.jobs")
    
    from src.app.pipeline.prefilter import prefilter_jobs
    log("OK: src.app.pipeline.prefilter")
    
    from src.app.pipeline.phases import run_jobs_by_phase
    log("OK: src.app.pipeline.phases")
    
    from src.app.pipeline.execute import execute_phases
    log("OK: src.app.pipeline.execute")
    
    from src.app.pipeline.reporting import format_bytes, print_summary
    log("OK: src.app.pipeline.reporting")
    
    from src.app.commands.build_index import run as bi_run
    log("OK: src.app.commands.build_index")
    
    from src.app.commands.run_from_index import run as rfi_run
    log("OK: src.app.commands.run_from_index")
    
    from src.app.commands.run_pipeline import run as rp_run
    log("OK: src.app.commands.run_pipeline")
    
    from src.app.commands.dry_run import run as dr_run
    log("OK: src.app.commands.dry_run")
    
    from src.app.commands.list_lossy import run as ll_run
    log("OK: src.app.commands.list_lossy")
    
    from src.app.commands.db_check import run as dbc_run
    log("OK: src.app.commands.db_check")
    
    from src.app.commands.db_migrate import run as dbm_run
    log("OK: src.app.commands.db_migrate")
    
    log("=== Testing VerifyResult ===")
    r = VerifyResult(status=VerifyStatus.OK, fmt="FLAC/PCM_16", duration_s=10.5)
    log(f"VerifyResult.short = {r.short!r}")
    assert r.short == "Okay"
    log("VerifyResult.OK short: PASS")
    
    r2 = VerifyResult(status=VerifyStatus.NOT_OK, reason="Truncated")
    log(f"VerifyResult.short (NOT_OK) = {r2.short!r}")
    assert r2.short == "Not - Truncated"
    log("VerifyResult.NOT_OK short: PASS")
    
    r3 = VerifyResult(status=VerifyStatus.UNSUPPORTED, reason="no decoder")
    log(f"VerifyResult.short (UNSUPPORTED) = {r3.short!r}")
    assert r3.short == "Skipped - no decoder"
    log("VerifyResult.UNSUPPORTED short: PASS")
    
    log("=== Testing migration ===")
    import tempfile
    from pathlib import Path
    import sqlite3
    
    with tempfile.TemporaryDirectory() as tmpdir:
        db_path = Path(tmpdir) / "test.db"
        
        # Create v1 DB
        conn = sqlite3.connect(str(db_path))
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA busy_timeout=5000")
        conn.executescript(CREATE_HISTORY_TABLE_SQL)
        conn.execute(
            "INSERT INTO history (source_path, dest_path, job_type, command, status, timestamp) VALUES (?, ?, ?, ?, ?, ?)",
            ("/src.flac", "/dst.flac", "convert", "ffmpeg", "SUCCESS", "2026-01-01T00:00:00Z")
        )
        conn.commit()
        conn.close()
        
        # Check v1
        v1_ver = get_schema_version(sqlite3.connect(str(db_path)))
        log(f"V1 DB version: {v1_ver}")
        assert v1_ver == 1
        log("test_get_schema_version_v1: PASS")
        
        # Migrate
        result = migrate_to_current(db_path)
        log(f"Migration result: version={result.version}, rows={result.rows_migrated}, backup={result.backup_path}")
        assert result.version == 2
        log("test_migrate_v1_to_v2: PASS")
        
        # Check v2
        v2_ver = get_schema_version(sqlite3.connect(str(db_path)))
        log(f"V2 DB version: {v2_ver}")
        assert v2_ver == 2
        log("test_get_schema_version_v2: PASS")
        
        # Check DbVersionInfo
        info = get_db_version(db_path)
        log(f"DbVersionInfo up_to_date={info.up_to_date}, current={info.current_version}, target={info.target_version}")
        assert info.up_to_date is True
        assert info.current_version == 2
        log("test_get_db_version_str: PASS")
        log(f"__str__:\n{info}")
        
        # Test ConversionDB with verify columns
        db = ConversionDB(db_path)
        record = db.get_record("/src.flac", "/dst.flac")
        db.close()
        log(f"Record verify_status={record.get('verify_status')}, verify_reason={record.get('verify_reason')}")
        assert "verify_status" in record
        assert record["verify_status"] is None  # old row, no verify data
        log("test_backward_compat_get_record: PASS")
        
        # Test log_conversion with verify kwargs
        db = ConversionDB(db_path)
        db.log_conversion(
            source="/src2.flac", dest="/dst2.flac",
            job_type="convert", command="ffmpeg", status="SUCCESS",
            verify_status="OK", verify_reason=None,
            verify_format="FLAC/PCM_16", verify_duration_s=180.5
        )
        db.close()
        
        db2 = ConversionDB(db_path)
        rec = db2.get_record("/src2.flac", "/dst2.flac")
        db2.close()
        log(f"New record verify_status={rec['verify_status']}, verify_format={rec['verify_format']}, verify_duration_s={rec['verify_duration_s']}")
        assert rec["verify_status"] == "OK"
        assert rec["verify_format"] == "FLAC/PCM_16"
        assert rec["verify_duration_s"] == 180.5
        log("test_log_conversion_with_verify_kwargs: PASS")
    
    log("=== All tests passed! ===")
    
except Exception as e:
    import traceback
    log(f"ERROR: {e}")
    log(traceback.format_exc())

with open("tests/manual_test_results.txt", "w") as f:
    f.write("\n".join(results))
