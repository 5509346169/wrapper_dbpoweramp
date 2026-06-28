import sys
sys.path.insert(0, '.')

# Simple test: verify imports and basic logic work
results = []

def log(msg):
    results.append(str(msg))

try:
    log("=== Starting tests ===")
    
    # Test 1: VerifyResult
    log("Testing VerifyResult...")
    from src.audio.integrity import VerifyStatus, VerifyResult
    r1 = VerifyResult(status=VerifyStatus.OK)
    assert r1.short == "Okay", f"Expected 'Okay', got {r1.short!r}"
    log("  OK: VerifyStatus.OK short")
    
    r2 = VerifyResult(status=VerifyStatus.NOT_OK, reason="Truncated")
    assert r2.short == "Not - Truncated", f"Expected 'Not - Truncated', got {r2.short!r}"
    log("  OK: VerifyStatus.NOT_OK short")
    
    r3 = VerifyResult(status=VerifyStatus.UNSUPPORTED, reason="no decoder")
    assert r3.short == "Skipped - no decoder", f"Expected 'Skipped - no decoder', got {r3.short!r}"
    log("  OK: VerifyStatus.UNSUPPORTED short")
    
    # Test 2: Schema
    log("Testing schema...")
    from src.history.schema import CREATE_HISTORY_TABLE_SQL, ADD_VERIFY_COLUMNS_SQL, INSERT_OR_REPLACE_HISTORY_SQL
    assert "verify_status" in CREATE_HISTORY_TABLE_SQL
    assert "verify_duration_s" in CREATE_HISTORY_TABLE_SQL
    # Check INSERT has 13 placeholders
    q_count = INSERT_OR_REPLACE_HISTORY_SQL.count("?")
    assert q_count == 13, f"Expected 13 ?, got {q_count}"
    log("  OK: schema has verify columns")
    
    # Test 3: Events
    log("Testing events...")
    from src.execution.events import JobEventKind
    assert hasattr(JobEventKind, 'VERIFY_RESULT')
    assert JobEventKind.VERIFY_RESULT == "verify_result"
    log("  OK: VERIFY_RESULT in JobEventKind")
    
    # Test 4: args
    log("Testing args...")
    from src.cli.args import parse_args as _pa
    a1 = _pa(['-I', '/in', '-O', '/out', '-p', 'flac', '--verify-output', 'none', '--verify-skip'])
    assert a1.verify_output == 'none', f"Expected 'none', got {a1.verify_output!r}"
    assert a1.verify_skip is True
    log("  OK: --verify-output and --verify-skip")
    
    a2 = _pa(['--db-version'])
    assert a2.db_version is True
    log("  OK: --db-version")
    
    a3 = _pa(['db', 'check'])
    assert a3.command == 'db'
    assert a3.db_command == 'check'
    log("  OK: db subcommand")
    
    a4 = _pa(['db', 'migrate'])
    assert a4.db_command == 'migrate'
    log("  OK: db migrate")
    
    a5 = _pa(['db', 'doctor'])
    assert a5.db_command == 'doctor'
    log("  OK: db doctor")
    
    # Test 5: protocol
    log("Testing protocol...")
    from src.ui.progress.protocol import ProgressSink
    assert hasattr(ProgressSink, 'log_verify_result')
    log("  OK: log_verify_result in protocol")
    
    # Test 6: NullProgressSink
    log("Testing NullProgressSink...")
    from src.ui.progress.null_sink import NullProgressSink
    ns = NullProgressSink()
    ns.log_verify_result("test.flac", "OK", None, "FLAC", 10.0)
    log("  OK: NullProgressSink.log_verify_result()")
    
    # Test 7: RichProgressSink
    log("Testing RichProgressSink...")
    from src.ui.progress.rich_sink import RichProgressSink
    rs = RichProgressSink()
    rs.log_verify_result("test.flac", "OK", None, "FLAC/PCM_16", 10.5)
    assert len(rs._log_lines) == 1
    assert "[verify] Okay" in rs._log_lines[0]
    log("  OK: RichProgressSink.log_verify_result()")
    
    rs2 = RichProgressSink()
    rs2.log_verify_result("test.flac", "NOT_OK", "Truncated", "FLAC", 1.0)
    assert "[verify] Not - Truncated" in rs2._log_lines[0]
    log("  OK: RichProgressSink NOT_OK log")
    
    # Test 8: Context
    log("Testing context...")
    from src.app.context import AppContext, MutablePhaseState
    state = MutablePhaseState()
    state.prefilter_skips = ['j1', 'j2']
    assert len(state.prefilter_skips) == 2
    log("  OK: MutablePhaseState")
    
    # Test 9: Signals
    log("Testing signals...")
    from src.app.lifecycle.signals import install_signal_guard, SignalGuard
    import signal as _sig
    orig = _sig.getsignal(_sig.SIGINT)
    with install_signal_guard() as guard:
        assert isinstance(guard, SignalGuard)
        assert guard.interrupted is False
        curr = _sig.getsignal(_sig.SIGINT)
        assert curr != orig
    rest = _sig.getsignal(_sig.SIGINT)
    assert rest == orig
    log("  OK: SignalGuard install/restore")
    
    # Test 10: Migrations
    log("Testing migrations...")
    import sqlite3
    import tempfile
    from pathlib import Path
    
    from src.history.migrations import SCHEMA_VERSION, get_schema_version, migrate_to_current, get_db_version
    
    assert SCHEMA_VERSION == 2, f"Expected SCHEMA_VERSION=2, got {SCHEMA_VERSION}"
    log(f"  OK: SCHEMA_VERSION={SCHEMA_VERSION}")
    
    # Create v1 DB
    with tempfile.TemporaryDirectory() as tmpdir:
        db_path = Path(tmpdir) / "test.db"
        conn = sqlite3.connect(str(db_path))
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA busy_timeout=5000")
        conn.executescript(CREATE_HISTORY_TABLE_SQL)
        conn.execute(
            "INSERT INTO history (source_path, dest_path, job_type, command, status, timestamp) VALUES (?, ?, ?, ?, ?, ?)",
            ("/s", "/d", "convert", "cmd", "SUCCESS", "2026-01-01T00:00:00Z")
        )
        conn.commit()
        conn.close()
        
        v1 = get_schema_version(sqlite3.connect(str(db_path)))
        assert v1 == 1, f"Expected v1=1, got {v1}"
        log("  OK: v1 version detection")
        
        result = migrate_to_current(db_path)
        assert result.version == 2
        assert result.backup_path is not None
        assert result.backup_path.exists()
        log(f"  OK: migration v1->v2, backup={result.backup_path.name}")
        
        v2 = get_schema_version(sqlite3.connect(str(db_path)))
        assert v2 == 2, f"Expected v2=2, got {v2}"
        log("  OK: v2 version after migration")
        
        # Check DbVersionInfo
        info = get_db_version(db_path)
        assert info.up_to_date is True
        assert info.current_version == 2
        assert len(info.applied_migrations) >= 1
        s = str(info)
        assert "Schema:        v2" in s
        log(f"  OK: DbVersionInfo, __str__ contains 'Schema: v2'")
        
        # Idempotent second migration
        result2 = migrate_to_current(db_path)
        assert "up-to-date" in result2.messages[0]
        log("  OK: idempotent migration")
        
        # ConversionDB
        from src.history.conversion_db import ConversionDB
        db = ConversionDB(db_path)
        rec = db.get_record("/s", "/d")
        db.close()
        assert "verify_status" in rec
        assert rec["status"] == "SUCCESS"
        log("  OK: ConversionDB get_record with verify columns")
        
        # log_conversion with verify kwargs
        db = ConversionDB(db_path)
        db.log_conversion(
            source="/s2", dest="/d2",
            job_type="convert", command="cmd", status="SUCCESS",
            verify_status="OK", verify_reason=None,
            verify_format="FLAC/PCM_16", verify_duration_s=180.5
        )
        db.close()
        
        db2 = ConversionDB(db_path)
        rec2 = db2.get_record("/s2", "/d2")
        db2.close()
        assert rec2["verify_status"] == "OK"
        assert rec2["verify_format"] == "FLAC/PCM_16"
        assert rec2["verify_duration_s"] == 180.5
        log("  OK: ConversionDB log_conversion with verify kwargs")
    
    log("=== ALL TESTS PASSED ===")
    
except Exception as e:
    import traceback
    results.append(f"ERROR: {e}")
    results.append(traceback.format_exc())

output = "\n".join(results)
with open("test_results.txt", "w", encoding="utf-8") as f:
    f.write(output)
print(output)
