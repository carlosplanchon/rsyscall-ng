#!/usr/bin/env bash
# Install the newest wheel in dist/ into a throwaway venv and exercise it away from the source
# tree and without any of the development environment variables: import, loaded library,
# bundled helpers, the smoke test, and the package's own test-suite, recorded one interpreter
# per test like the baselines; its results must match tests/baseline-rust.txt (the wheel
# bundles the Rust native side).
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
WHEEL=$(ls -t "$ROOT"/dist/rsyscall_ng-*.whl | head -1)
VENV="$ROOT/.venv-wheel"
PYVER="${RSYSCALL_WHEEL_PYTHON:-3.14}"
rm -rf "$VENV"
uv venv --quiet --python "$PYVER" "$VENV"
uv pip install --quiet --python "$VENV/bin/python" "$WHEEL" pytest pytest-timeout
echo "== $WHEEL"
unzip -l "$WHEEL" | grep -E '_native/|_raw|dist-info/METADATA' | awk '{print "  ", $4, "(" $1 " bytes)"}'
cd /tmp
run() { env -u LD_LIBRARY_PATH -u PKG_CONFIG_PATH -u RSYSCALL_NATIVE -u RSYSCALL_LIBEXEC_DIR "$VENV/bin/python" "$@"; }
echo "== import, loaded library, helpers (no environment variables, cwd=/tmp)"
run - <<'PY'
import rsyscall, rsyscall._raw, rsyscall._native as native
print("  rsyscall from", rsyscall.__file__)
print("  librsyscall loaded from", next(l.split()[-1] for l in open("/proc/self/maps") if "librsyscall" in l))
for h in native.HELPERS:
    print("  ", h, "->", native.helper(h))
PY
echo "== smoke test"
run "$ROOT/scripts/hello.py"
echo "== package test-suite from the installed wheel, one interpreter per test (scripts/baseline.py),"
echo "   compared with tests/baseline-rust.txt (test_repl deselected: it hangs, see tests/baseline-notes.md)"
TESTS_DIR=$("$VENV/bin/python" -c 'import os, rsyscall.tests; print(os.path.dirname(rsyscall.tests.__file__))')
: > "$VENV/pytest.ini"   # an empty config: the repository's pytest.ini must not apply, and the rootdir is the installed tests directory
RSYSCALL_TEST_CWD="$TESTS_DIR" RSYSCALL_PYTEST_ARGS="-c $VENV/pytest.ini --rootdir $TESTS_DIR" \
    RSYSCALL_BASELINE_LOGS="$VENV/baseline-logs" BASELINE_OUT="$VENV/results.txt" RSYSCALL_BACKEND=rust \
    run "$ROOT/scripts/baseline.py" -k "not test_repl" > "$VENV/baseline.log" 2>&1 || true
tail -n 4 "$VENV/baseline.log" | sed 's/^/   /'
python3 "$ROOT/scripts/baseline-compare.py" "$ROOT/tests/baseline-rust.txt" "$VENV/results.txt" --ignore test_repl
