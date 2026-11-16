import sys
import threading

from app import rows as R
from app import validator as V


def test_concurrent_runs_are_correct_and_restore_the_recursion_limit():
    before = sys.getrecursionlimit()
    results = {}
    programs = {n: f"total = 0\nfor i in range({n + 2}):\n    total = total + i\nprint(total)" for n in range(8)}

    def work(n):
        results[n] = V.run_program(programs[n])

    threads = [threading.Thread(target=work, args=(n,)) for n in programs]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    for n in programs:
        assert results[n].ok and results[n].output.strip() == str(sum(range(n + 2)))
    assert sys.getrecursionlimit() == before


def test_level_without_indent_cols_defaults_to_two():
    lv = dict(R.get_level("r3"))
    lv.pop("indent_cols", None)
    assert R.public_level(lv)["indent_cols"] == 2
    assert R.assemble(lv, R.canonical_rows(R.get_level("r3")))
