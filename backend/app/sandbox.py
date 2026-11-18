"""Run learner-supplied code in a throwaway child process (see docs/validator-and-safety.md section 5).

``validator.run_program`` executes in the calling process and cannot stop a single long C-level
operation, so free-form code never reaches it from the web server. It goes through ``run_job`` here:
one ``python -I`` child per job, a scrubbed environment, rlimits set by the child on POSIX
(``sandbox_worker.apply_limits``) and a wall-clock timeout enforced by the parent on every platform.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import threading
from pathlib import Path
from typing import Optional

from . import bank
from . import validator as V

BACKEND_ROOT = Path(__file__).resolve().parents[1]
GENERATION_TIMEOUT_S = 5.0   # one whole generation job (all candidate runs happen inside one child)
CHECK_TIMEOUT_S = 2.0        # one answer check
MAX_RESULT_BYTES = 512 * 1024
MAX_CONCURRENT = 4           # children alive at once; more requests wait briefly, then get 429
BUSY_WAIT_S = 3.0

_slots = threading.BoundedSemaphore(MAX_CONCURRENT)

# -I (isolated) ignores PYTHON* variables and does not put the working directory on sys.path, so the
# package root is added by hand. The root is passed as an argument rather than interpolated into code.
_BOOT = "import sys; sys.path.insert(0, sys.argv[1]); from app import sandbox_worker; sandbox_worker.main()"


class SandboxError(Exception):
    """The child did not return a usable result. ``kind``: timeout, killed, crash or bad_output."""

    def __init__(self, kind: str):
        super().__init__(kind)
        self.kind = kind


class SandboxBusy(bank.BankError):
    status = 429


def _executable() -> str:
    # A Windows venv's python.exe is a launcher that starts the real interpreter as a child; killing
    # the launcher on timeout could leave the real one running. The worker needs only the standard
    # library, so the base interpreter is used there.
    if os.name == "nt":
        return getattr(sys, "_base_executable", None) or sys.executable
    return sys.executable


def _child_env() -> dict:
    env = {"LANG": "C.UTF-8"}
    for key in ("SYSTEMROOT", "SystemRoot"):  # Windows needs it to start Python; nothing else is passed on
        if key in os.environ:
            env[key] = os.environ[key]
    return env


def run_job(job: dict, timeout: float) -> dict:
    """Run one job in a child process and return its ``result`` dict. Raises ``SandboxError`` / ``SandboxBusy``."""
    payload = json.dumps(job).encode("ascii")
    if not _slots.acquire(timeout=BUSY_WAIT_S):
        raise SandboxBusy("Máy chủ đang bận chạy mã của người khác. Hãy thử lại sau ít giây.")
    try:
        kwargs = {}
        if os.name == "nt":
            kwargs["creationflags"] = subprocess.CREATE_NO_WINDOW
        try:
            proc = subprocess.run(
                [_executable(), "-I", "-c", _BOOT, str(BACKEND_ROOT)], input=payload,
                capture_output=True, timeout=timeout, cwd=BACKEND_ROOT, env=_child_env(), **kwargs)
        except subprocess.TimeoutExpired:
            raise SandboxError("timeout") from None
        except OSError:
            raise SandboxError("crash") from None
    finally:
        _slots.release()
    if proc.returncode != 0:
        # POSIX: a negative code is a signal (SIGXCPU/SIGKILL from the rlimits, SIGSEGV...)
        raise SandboxError("killed" if proc.returncode < 0 else "crash")
    if len(proc.stdout) > MAX_RESULT_BYTES:
        raise SandboxError("bad_output")
    try:
        data = json.loads(proc.stdout)
        result = data["result"]
    except (ValueError, KeyError, TypeError):
        raise SandboxError("bad_output") from None
    if not isinstance(result, dict):
        raise SandboxError("bad_output")
    return result


def generate(code: str, timeout: Optional[float] = None) -> dict:
    return run_job({"op": "generate", "code": code}, GENERATION_TIMEOUT_S if timeout is None else timeout)


def diagnose(code: str, expected: str) -> V.Diagnosis:
    """Sandboxed drop-in for ``validator.diagnose``. A timeout or crash is reported as a wrong answer."""
    try:
        r = run_job({"op": "diagnose", "code": code, "expected": expected}, CHECK_TIMEOUT_S)
        run = V.RunResult(r["run_ok"], output=r["actual_output"] or "", error_kind=r["error_kind"],
                          error_group=r["error_group"], message=r["message"], lineno=r["lineno"])
        return V.Diagnosis(r["passed"], r["error_group"], r["message"], r["actual_output"], r["lineno"], run)
    except (SandboxError, KeyError, TypeError):
        msg = "Chương trình chạy quá lâu hoặc không kiểm tra được, có thể có vòng lặp vô hạn."
        run = V.RunResult(False, error_kind="limit", error_group="output_mismatch", message=msg, exc_name="sandbox")
        return V.Diagnosis(False, "output_mismatch", msg, None, None, run)
