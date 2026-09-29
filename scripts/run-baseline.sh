#!/usr/bin/env bash
# Run the test-suite against the oracle backend and record one status line per test
# into tests/baseline-c.txt (written by the hooks in python/rsyscall/tests/conftest.py).
# Extra arguments are passed to pytest.
set -euo pipefail
source "$(dirname "${BASH_SOURCE[0]}")/env.sh"

if [ ! -x "$PY" ]; then
    echo "no venv; run 'make venv' first" >&2
    exit 1
fi
OUT="${BASELINE_OUT:-$ROOT/tests/baseline-c.txt}"
LOG="$REF_DIR/baseline-c.log"
mkdir -p "$(dirname "$OUT")" "$REF_DIR"
cd "$ROOT"

set +e
# setsid: run without a controlling tty, so anything that would prompt (sudo in
# test_setuid) fails fast instead of hanging until the timeout.
RSYSCALL_BASELINE_OUT="$OUT" RSYSCALL_BACKEND="${RSYSCALL_BACKEND:-c}" \
    setsid --wait "$PY" -m pytest --continue-on-collection-errors -rA --tb=short "$@" 2>&1 | tee "$LOG"
rc=${PIPESTATUS[0]}
set -e
case $rc in
    0|1) ;;  # 0: all passed, 1: some tests failed. Both are valid baselines.
    *) echo "pytest exited with status $rc (interrupted, usage or internal error); baseline not trusted" >&2
       exit "$rc" ;;
esac
if ! grep -q -E '^(PASS|FAIL|SKIP|XFAIL|XPASS) ' "$OUT"; then
    echo "no test was executed (collection failed?); baseline not trusted" >&2
    exit 3
fi
echo
echo "wrote $OUT:"
head -3 "$OUT"
