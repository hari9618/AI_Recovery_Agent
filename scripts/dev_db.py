"""Run a local PostgreSQL (with pgvector) without Docker.

Uses the Postgres binaries bundled in the ``pgserver`` wheel (dev dependency of apps/api),
which include the pgvector extension on Windows, macOS and Linux. Data lives in ``.devdb/``.

Usage (from repo root):
    uv run --project apps/api python scripts/dev_db.py start|stop|status|reset
"""

from __future__ import annotations

import argparse
import os
import shutil
import subprocess
import sys
import time
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
DATA_DIR = REPO_ROOT / ".devdb" / "data"
LOG_FILE = REPO_ROOT / ".devdb" / "postgres.log"
PORT = int(os.environ.get("DEV_DB_PORT", "5433"))
DATABASES = ("revenue_recovery", "revenue_recovery_test")
EXE = ".exe" if os.name == "nt" else ""


def _bin_dir() -> Path:
    try:
        import pgserver  # noqa: PLC0415
    except ImportError:
        sys.exit("pgserver is not installed. Run: uv sync --project apps/api")
    return Path(pgserver.__file__).parent / "pginstall" / "bin"


def _run(tool: str, *args: str, check: bool = True) -> subprocess.CompletedProcess[str]:
    # Pass argv as a list: the repo path may contain spaces.
    cmd = [str(_bin_dir() / f"{tool}{EXE}"), *args]
    return subprocess.run(cmd, check=check, capture_output=True, text=True)


def _is_running() -> bool:
    return _run("pg_isready", "-h", "127.0.0.1", "-p", str(PORT), "-U", "postgres", check=False).returncode == 0


def _psql(database: str, sql: str) -> None:
    _run("psql", "-h", "127.0.0.1", "-p", str(PORT), "-U", "postgres", "-d", database, "-c", sql)


def start() -> None:
    if not (DATA_DIR / "PG_VERSION").exists():
        DATA_DIR.mkdir(parents=True, exist_ok=True)
        print(f"Initialising cluster in {DATA_DIR} ...")
        _run("initdb", "-D", str(DATA_DIR), "-U", "postgres", "-A", "trust", "-E", "UTF8")
    if _is_running():
        print(f"PostgreSQL already running on port {PORT}")
    else:
        # The postmaster inherits our std handles; capturing them would block forever on Windows.
        subprocess.run(
            [str(_bin_dir() / f"pg_ctl{EXE}"), "-D", str(DATA_DIR), "-l", str(LOG_FILE), "-o", f"-p {PORT}", "start"],
            check=True, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
        )
        for _ in range(30):
            if _is_running():
                break
            time.sleep(1)
    for db in DATABASES:
        exists = _run(
            "psql", "-h", "127.0.0.1", "-p", str(PORT), "-U", "postgres", "-tAc",
            f"SELECT 1 FROM pg_database WHERE datname='{db}'", check=False,
        ).stdout.strip()
        if exists != "1":
            _run("createdb", "-h", "127.0.0.1", "-p", str(PORT), "-U", "postgres", db)
        _psql(db, "CREATE EXTENSION IF NOT EXISTS vector;")
    print(f"PostgreSQL + pgvector ready: postgresql://postgres@127.0.0.1:{PORT}/{DATABASES[0]}")


def stop() -> None:
    if _is_running():
        _run("pg_ctl", "-D", str(DATA_DIR), "-m", "fast", "stop")
        print("PostgreSQL stopped")
    else:
        print("PostgreSQL not running")


def status() -> None:
    print(f"running on port {PORT}" if _is_running() else "not running")


def reset() -> None:
    stop()
    shutil.rmtree(DATA_DIR, ignore_errors=True)
    start()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("command", choices=["start", "stop", "status", "reset"])
    args = parser.parse_args()
    {"start": start, "stop": stop, "status": status, "reset": reset}[args.command]()


if __name__ == "__main__":
    main()
