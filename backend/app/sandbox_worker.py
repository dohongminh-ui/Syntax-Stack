"""Child-process entry point for running learner code. Started by ``sandbox.py``, never imported by the web app.

Reads one JSON job on stdin, writes one JSON result on stdout (ASCII only), then exits. On POSIX the
process first lowers its own resource limits (memory, CPU time, file size, processes, open files), so
a runaway program is killed by the kernel even if the parent is slow to notice. The parent adds a
wall-clock timeout on top. The validator (AST whitelist, step/time/output limits) still applies
inside this process.

Jobs:
    {"op": "generate", "code": str}                    -> custom_gen.generate(...)
    {"op": "diagnose", "code": str, "expected": str}   -> validator.diagnose(...), flattened
"""
from __future__ import annotations

import json
import sys

MEMORY_LIMIT_BYTES = 256 * 1024 * 1024
CPU_LIMIT_S = 3
FILE_SIZE_LIMIT_BYTES = 1024 * 1024
OPEN_FILES_LIMIT = 32
MAX_JOB_BYTES = 64 * 1024


def apply_limits(resource_module=None) -> dict:
    """Lower this process's rlimits. Returns ``{name: [soft, hard] | None}``; empty where unsupported (Windows)."""
    res = resource_module
    if res is None:
        try:
            import resource as res
        except ImportError:  # Windows
            return {}
    plan = [
        ("AS", MEMORY_LIMIT_BYTES, MEMORY_LIMIT_BYTES),
        ("CPU", CPU_LIMIT_S, CPU_LIMIT_S + 1),   # SIGXCPU at the soft limit, SIGKILL at the hard one
        ("FSIZE", FILE_SIZE_LIMIT_BYTES, FILE_SIZE_LIMIT_BYTES),
        ("NPROC", 0, 0),                          # no fork/clone: the worker never needs a child or thread
        ("NOFILE", OPEN_FILES_LIMIT, OPEN_FILES_LIMIT),
        ("CORE", 0, 0),
    ]
    applied: dict = {}
    for name, soft, hard in plan:
        which = getattr(res, f"RLIMIT_{name}", None)
        if which is None:
            applied[name] = None
            continue
        try:
            cur_soft, cur_hard = res.getrlimit(which)
            if cur_hard != res.RLIM_INFINITY:  # never raise a limit
                hard = min(hard, cur_hard)
                soft = min(soft, hard)
            res.setrlimit(which, (soft, hard))
            applied[name] = [soft, hard]
        except (ValueError, OSError):
            applied[name] = None
    return applied


def _flatten(diag) -> dict:
    run = diag.run
    return {
        "passed": diag.passed, "error_group": diag.error_group, "message": diag.message,
        "message_en": diag.message_en,
        "actual_output": diag.actual_output, "lineno": diag.lineno,
        "run_ok": bool(run.ok) if run is not None else False,
        "error_kind": run.error_kind if run is not None else None,
    }


def handle(job: dict) -> dict:
    from . import custom_gen
    from . import validator as V

    custom_gen.ENABLED = True
    op = job.get("op")
    if op == "generate":
        return custom_gen.generate(str(job["code"]))
    if op == "diagnose":
        return _flatten(V.diagnose(str(job["code"]), str(job["expected"])))
    return {"ok": False, "message": "Unknown job."}


def main() -> None:
    limits = apply_limits()
    raw = sys.stdin.buffer.read(MAX_JOB_BYTES + 1)
    if len(raw) > MAX_JOB_BYTES:
        sys.exit(2)
    result = handle(json.loads(raw))
    sys.stdout.buffer.write(json.dumps({"result": result, "limits": limits}).encode("ascii"))
    sys.stdout.buffer.flush()


if __name__ == "__main__":  # python -m app.sandbox_worker (the parent uses a bootstrap, see sandbox.py)
    main()
