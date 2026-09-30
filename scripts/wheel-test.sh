#!/usr/bin/env bash
# Install the newest wheel in dist/ into a throwaway venv and exercise it away from the source
# tree and without any of the development environment variables: import, loaded library,
# bundled helpers, the smoke test, and the package's own test-suite, whose per-test results
# must match tests/baseline-rust.txt (the wheel bundles the Rust native side).
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
echo "== package test-suite from the installed wheel, compared with tests/baseline-rust.txt"
echo "   (test_repl deselected: it hangs and poisons the rest, see tests/baseline-notes.md)"
RSYSCALL_BASELINE_OUT="$VENV/results.txt" RSYSCALL_BACKEND=rust \
    run "$ROOT/scripts/pytest_session.py" "$VENV/pytest.log" --pyargs rsyscall.tests -q --timeout=60 -k "not test_repl" || true
tail -n 3 "$VENV/pytest.log" | sed 's/^/   /'
python3 "$ROOT/scripts/baseline-compare.py" "$ROOT/tests/baseline-rust.txt" "$VENV/results.txt" --ignore test_repl
