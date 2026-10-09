"""Create private, consistent SQLite backups without reading credential contents."""

import argparse
import json
import sqlite3
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from uuid import uuid4


def backup_databases(data_dir: Path, keys_dir: Path) -> dict[str, Any]:
    sources = sorted(data_dir.glob("*.sqlite3"))
    if not sources or any(path.is_symlink() for path in sources):
        raise ValueError("No database files found, or unsafe database symlink")
    parent = data_dir / "backups"
    if parent.is_symlink():
        raise ValueError("Unsafe backup directory symlink")
    parent.mkdir(mode=0o700, exist_ok=True)
    parent.chmod(0o700)
    destination = parent / (datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ") + "-" + uuid4().hex)
    destination.mkdir(mode=0o700)
    result: dict[str, Any] = {
        "backup_directory": str(destination),
        "databases": {},
        "adb_credentials": {name: (keys_dir / name).is_file() for name in ("adbkey", "adbkey.pub")},
    }
    for source in sources:
        target = destination / source.name
        target.touch(mode=0o600, exist_ok=False)
        # The backup API includes committed WAL data and creates a coherent snapshot.
        with sqlite3.connect(source.resolve().as_uri() + "?mode=ro", uri=True) as original:
            with sqlite3.connect(target) as copied:
                original.backup(copied)
                integrity = copied.execute("PRAGMA integrity_check").fetchall()
                if integrity != [("ok",)]:
                    raise ValueError("Backup integrity check failed")
                tables = copied.execute(
                    "SELECT name FROM sqlite_master WHERE type='table' "
                    "AND name NOT LIKE 'sqlite_%' ORDER BY name"
                ).fetchall()
                counts = {
                    name: copied.execute(
                        'SELECT COUNT(*) FROM "' + name.replace('"', '""') + '"'
                    ).fetchone()[0]
                    for (name,) in tables
                }
                record: dict[str, Any] = {"integrity": "ok", "table_counts": counts}
                if source.name == "devices.sqlite3" and "devices" in counts:
                    record["device_identifiers"] = [
                        row[0] for row in copied.execute("SELECT id FROM devices ORDER BY id")
                    ]
                result["databases"][source.name] = record
    manifest = destination / "manifest.json"
    manifest.touch(mode=0o600, exist_ok=False)
    manifest.write_text(json.dumps(result, indent=2) + "\n")
    return result


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data-dir", type=Path, default=Path("/var/lib/android-fleet"))
    parser.add_argument("--keys-dir", type=Path, default=Path("/home/fleet/.android"))
    args = parser.parse_args()
    print(json.dumps(backup_databases(args.data_dir, args.keys_dir), indent=2))


if __name__ == "__main__":
    main()
