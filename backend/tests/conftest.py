import importlib.util
import sys
from pathlib import Path

import pytest

BACKEND = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND))

from app import bank  # noqa: E402


@pytest.fixture(scope="session", autouse=True)
def ensure_bank():
    """Generate the puzzle bank if it has not been generated yet."""
    if not bank.DB_PATH.exists():
        spec = importlib.util.spec_from_file_location("generate_bank", BACKEND / "scripts" / "generate_bank.py")
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        assert mod.main(["--out", str(bank.DB_PATH)]) == 0
    yield


@pytest.fixture(autouse=True)
def _reset_tutor_state():
    """Tutor cache and daily counters are process-wide; isolate every test."""
    from app import tutor
    tutor.reset()
    yield
    tutor.reset()


@pytest.fixture(scope="session")
def client():
    from fastapi.testclient import TestClient
    from app.main import app
    return TestClient(app)


@pytest.fixture(scope="session")
def all_rows():
    import json
    import sqlite3
    con = sqlite3.connect(bank.DB_PATH)
    con.row_factory = sqlite3.Row
    rows = []
    for r in con.execute("SELECT * FROM puzzles ORDER BY id"):
        d = dict(r)
        d["hints"] = json.loads(d["hints"])
        d["data"] = json.loads(d["data"])
        rows.append(d)
    con.close()
    return rows
