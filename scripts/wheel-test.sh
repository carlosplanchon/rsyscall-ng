#!/usr/bin/env bash
# Install the freshly built wheel into a throwaway venv and exercise it away from the source
# tree and without any of the development environment variables: import, loaded library,
# bundled helpers, the smoke test, and the package's own test-suite.
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
echo "== package test-suite from the installed wheel (test_repl hangs by design, see tests/baseline-notes.md)"
run -m pytest --pyargs rsyscall.tests -q -p no:cacheprovider --timeout=60 -k "not test_repl" 2>&1 | tail -4
