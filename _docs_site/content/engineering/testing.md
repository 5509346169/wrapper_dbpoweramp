---
title: Testing
summary: How to run the test suite and the TDD workflow.
audience: [engineer]
weight: 50
---

This document explains how to run the test suite.

## Overview

The project includes a test suite covering:

- Lossy classification logic
- Conversion database operations
- Index builder operations
- Mutagen probe behaviour
- Progress view rendering

## Running tests

### Basic test run

```sh
pytest tests/
python -m pytest tests/
```

### Run specific test file

```sh
pytest tests/test_lossy_classify.py
pytest tests/test_conversion_db.py
pytest tests/test_index_builder.py
```

### Run specific test class

```sh
pytest tests/test_lossy_classify.py::TestClassify
pytest tests/test_lossy_classify.py::TestEnrichIndexRows
```

### Run specific test

```sh
pytest tests/test_lossy_classify.py::TestClassify::test_lossy_val_true_action_copy_sets_copy
```

## Test files

### `tests/conftest.py`

Pytest configuration that pre-imports mutagen to break import-lock deadlock on Windows.

```python
# Pre-import mutagen to release the import lock before workers are spawned
import mutagen
```

### `tests/test_lossy_classify.py`

Tests for lossy classification and job enrichment.

```python
class TestClassify:
    """Tests for _classify covering all LossyAction values and no_lossy_check."""

    def test_no_lossy_check_sets_job_type_convert(self)
    def test_lossy_val_true_no_action_sets_skip(self)
    def test_lossy_val_true_action_leave_sets_skip(self)
    def test_lossy_val_true_action_copy_sets_copy(self)
    def test_lossy_val_true_action_convert_sets_convert(self)
    def test_lossy_val_false_sets_convert(self)

class TestEnrichIndexRows:
    """Blocking tests for enrich_index_rows."""

    def test_no_lossy_check_skips_probe(self)
    def test_lossy_file_returned_in_result(self)
    def test_lossless_file_job_type_convert(self)
```

### `tests/test_conversion_db.py`

Tests for the history database.

- Tests logging conversions
- Tests resume check logic
- Tests database isolation

### `tests/test_index_builder.py`

Tests for the index builder.

- Tests row insertion
- Tests iteration
- Tests summary statistics
- Tests schema migration

### `tests/test_mutagen_probe.py`

Tests for mutagen audio probing.

- Tests lossy detection by codec
- Tests ambiguous extension handling
- Tests error handling

### `tests/test_progress_view.py`

Tests for the Rich progress view.

- Tests progress bar rendering
- Tests subtask management
- Tests log line display

## Test fixtures

Tests use pytest fixtures from `conftest.py`:

```python
@pytest.fixture
def temp_db(tmp_path):
    """Provide a temporary database path."""
    return tmp_path / "test.db"

@pytest.fixture
def sample_audio_file():
    """Provide a sample audio file path for testing."""
    # Returns path to test fixture
```

## Mocking

Tests use mocking to isolate units under test:

```python
from unittest.mock import patch, Mock

@patch("src.audio.inspector.probe_many")
@patch("src.jobs.builder.compute_output_path")
def test_no_lossy_check_skips_probe(
    self,
    mock_compute: object,
    mock_probe_many: object
) -> None:
    """no_lossy_check=True skips probe_many entirely."""
    mock_compute.return_value = Path("D:/output/test.mp3")
    mock_probe_many.return_value = {Path("D:/music/test.mp3"): True}

    # Test code...
```

## Coverage

To check test coverage:

```sh
pip install pytest-cov
pytest tests/ --cov=src --cov-report=html
open htmlcov/index.html
```

## Continuous integration

Tests run automatically on:

- Pull requests
- Push to main branch

The CI configuration lives in `.github/workflows/` and runs the same `pytest tests/` command on every change.

## Writing tests

### Test naming

Follow the pattern `test_<feature>_<scenario>`:

```python
def test_lossy_action_copy_sets_job_type_copy(self):
    """is_lossy=True with LossyAction.COPY sets job_type to 'copy'."""
```

### Test structure

```python
class TestFeatureName:
    """Description of the feature being tested."""

    def setup_method(self):
        """Set up test fixtures."""
        self.fixtures = setup()

    def teardown_method(self):
        """Clean up after each test."""
        cleanup()

    def test_scenario_description(self):
        """Expected behavior in this scenario."""
        # Arrange
        ...
        # Act
        ...
        # Assert
        assert result == expected
```

### Test documentation

Each test should have a docstring explaining:

1. What is being tested
2. The scenario
3. The expected behaviour

```python
def test_no_lossy_check_sets_job_type_convert(self, mock_compute: object) -> None:
    """no_lossy_check=True always sets job_type to 'convert'.

    When lossy checking is disabled, all files should be treated
    as candidates for conversion regardless of their actual codec.
    """
```

## Test data

### Audio fixtures

Place sample audio files in `tests/fixtures/`:

```text
tests/
├── fixtures/
│   ├── sample.flac
│   ├── sample.mp3
│   └── sample.m4a
└── conftest.py
```

### Database fixtures

Tests use temporary directories for database files:

```python
def test_with_temp_db(tmp_path):
    db_path = tmp_path / "test.db"
    # Test code...
```

## Performance testing

For large file tests, use `pytest.mark.slow`:

```python
@pytest.mark.slow
def test_large_library_probing():
    """Test probing with thousands of files."""
    # Performance test code...
```

Run slow tests separately:

```sh
pytest tests/ -m "not slow"
pytest tests/ -m slow
```

## Troubleshooting

### Import errors

If you see import errors, ensure:

1. Python path includes project root
2. `src/` is importable
3. Dependencies are installed

```sh
export PYTHONPATH="${PYTHONPATH}:$(pwd)"
pytest tests/
```

### Windows import deadlock

The `conftest.py` pre-imports mutagen to prevent import-lock deadlock on Windows. Don't remove this.

### Mutagen not found

```sh
pip install mutagen>=1.47.0
```

## Test-driven development

When adding new features:

1. Write tests first
2. Run tests (they should fail)
3. Implement the feature
4. Run tests (they should pass)
5. Refactor if needed

```sh
# TDD workflow
echo "Write test" && pytest tests/test_new_feature.py  # FAIL
echo "Implement feature"
pytest tests/test_new_feature.py  # PASS
```
