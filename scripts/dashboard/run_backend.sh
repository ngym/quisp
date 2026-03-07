#!/bin/sh
set -eu

ROOT_DIR=$(CDPATH= cd -- "$(dirname -- "$0")/../.." && pwd)

if [ -z "${QUTIP_PYTHON_EXECUTABLE:-}" ] && [ -x "$ROOT_DIR/.venv-qutip/bin/python" ]; then
  export QUTIP_PYTHON_EXECUTABLE="$ROOT_DIR/.venv-qutip/bin/python"
fi

export PYTHONPATH="$ROOT_DIR${PYTHONPATH:+:$PYTHONPATH}"

exec "${DASHBOARD_PYTHON:-python3}" -m scripts.dashboard.backend.app.main \
  --host "${DASHBOARD_HOST:-127.0.0.1}" \
  --port "${DASHBOARD_PORT:-8765}" \
  --workspace-root "${DASHBOARD_WORKSPACE_ROOT:-$ROOT_DIR}" \
  --log-dir "${DASHBOARD_LOG_DIR:-$ROOT_DIR/scripts/dashboard/runs}" \
  --audit-log "${DASHBOARD_AUDIT_LOG:-$ROOT_DIR/scripts/dashboard/dashboard_audit.log}" \
  --quisp-binary "${DASHBOARD_QUISP_BINARY:-$ROOT_DIR/quisp/quisp}" \
  "$@"
