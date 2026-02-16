#!/usr/bin/env python3
"""Verify Python-side qutip/qutip-qip dependencies are importable."""

import os
import subprocess


def _python_executable() -> str:
    return os.environ.get("QUTIP_PYTHON_EXECUTABLE", "python3")


def main() -> int:
  python_executable = _python_executable()
  try:
    command = (
        "import importlib.util; "
        "import qutip, qutip_qip, qutip.qip; "
        "spec = importlib.util.find_spec('qutip'); "
        "assert spec is not None, 'qutip module not found'; "
        "spec = importlib.util.find_spec('qutip_qip'); "
        "assert spec is not None, 'qutip_qip module not found'; "
        "print(getattr(qutip, '__version__', 'unknown')) ; "
        "print(getattr(qutip_qip, '__version__', 'unknown'))"
    )
    result = subprocess.run([python_executable, "-c", command], check=False, capture_output=True, text=True)
    if result.returncode != 0:
      raise RuntimeError((result.stderr or result.stdout or "qutip import failed").strip() or "qutip import failed")
    version_lines = result.stdout.strip().splitlines()
    if len(version_lines) < 2:
      raise RuntimeError("failed to read qutip version from subprocess")
    qutip_version = version_lines[0].strip()
    qutip_qip_version = version_lines[1].strip()
  except Exception as exc:  # pragma: no cover - diagnostic output
    print(f"qutip import check failed: {exc}")
    return 1

  print(f"qutip: {qutip_version}")
  print(f"qutip_qip: {qutip_qip_version}")
  print("qutip import check ok")
  print(f"using python executable: {python_executable}")
  return 0


if __name__ == "__main__":
  raise SystemExit(main())
