import importlib.util
import sqlite3
import stat
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parents[2] / "scripts" / "backup_databases.py"
SPEC = importlib.util.spec_from_file_location("backup_databases", SCRIPT)
assert SPEC is not None and SPEC.loader is not None
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


def test_backup_includes_live_wal_and_private_manifest(tmp_path: Path) -> None:
    database = tmp_path / "devices.sqlite3"
    connection = sqlite3.connect(database)
    try:
        connection.execute("PRAGMA journal_mode=WAL")
        connection.execute("CREATE TABLE devices (id TEXT)")
        connection.execute("INSERT INTO devices VALUES ('registered-device')")
        connection.commit()
        keys = tmp_path / "keys"
        keys.mkdir()
        (keys / "adbkey").write_text("PRIVATE-CONTENT-MUST-NOT-LEAK")
        report = MODULE.backup_databases(tmp_path, keys)
        assert "PRIVATE-CONTENT" not in str(report)
        assert report["adb_credentials"] == {"adbkey": True, "adbkey.pub": False}
        record = report["databases"]["devices.sqlite3"]
        assert record["table_counts"] == {"devices": 1}
        assert record["device_identifiers"] == ["registered-device"]
        backup = Path(report["backup_directory"])
        assert stat.S_IMODE(backup.stat().st_mode) == 0o700
        assert stat.S_IMODE((backup / database.name).stat().st_mode) == 0o600
        assert stat.S_IMODE((backup / "manifest.json").stat().st_mode) == 0o600
        with sqlite3.connect(backup / database.name) as copied:
            assert copied.execute("SELECT id FROM devices").fetchall() == [("registered-device",)]
        second = MODULE.backup_databases(tmp_path, keys)
        assert second["backup_directory"] != report["backup_directory"]
    finally:
        connection.close()


def test_backup_rejects_missing_database_and_symlink(tmp_path: Path) -> None:
    with pytest.raises(ValueError):
        MODULE.backup_databases(tmp_path, tmp_path)
    (tmp_path / "devices.sqlite3").symlink_to(tmp_path / "missing")
    with pytest.raises(ValueError):
        MODULE.backup_databases(tmp_path, tmp_path)


def test_corrupt_database_never_reports_success(tmp_path: Path) -> None:
    (tmp_path / "devices.sqlite3").write_bytes(b"invalid SQLite")
    with pytest.raises(sqlite3.DatabaseError):
        MODULE.backup_databases(tmp_path, tmp_path)
