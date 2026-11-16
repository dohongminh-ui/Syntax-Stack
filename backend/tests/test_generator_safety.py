import importlib.util
import sqlite3

from tests.conftest import BACKEND


def _load_generator():
    spec = importlib.util.spec_from_file_location("generate_bank_safety", BACKEND / "scripts" / "generate_bank.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_failed_coverage_leaves_existing_bank_untouched(tmp_path, monkeypatch, capsys):
    out = tmp_path / "puzzles.sqlite"
    con = sqlite3.connect(out)
    con.execute("CREATE TABLE sentinel (x)")
    con.execute("INSERT INTO sentinel VALUES (42)")
    con.commit()
    con.close()
    before = out.read_bytes()

    gen = _load_generator()
    monkeypatch.setattr(gen, "MIN_TEMPLATE_VARIANTS", 10_000)  # force a coverage failure
    assert gen.main(["--out", str(out)]) == 1
    assert "PROBLEM" in capsys.readouterr().out
    assert out.read_bytes() == before
    assert [p.name for p in tmp_path.iterdir()] == ["puzzles.sqlite"]  # temp file removed


def test_successful_run_replaces_bank_and_leaves_no_temp_file(tmp_path):
    out = tmp_path / "puzzles.sqlite"
    out.write_bytes(b"old")
    assert _load_generator().main(["--out", str(out)]) == 0
    con = sqlite3.connect(out)
    assert con.execute("SELECT COUNT(*) FROM puzzles").fetchone()[0] > 500
    con.close()
    assert [p.name for p in tmp_path.iterdir()] == ["puzzles.sqlite"]
