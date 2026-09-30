#!/usr/bin/env bash
# Usage: wheel-test.sh [DIST]      DIST: a wheel or an sdist (default: the newest wheel in dist/)
#
# Install a distribution into a throwaway venv and exercise it away from the source tree and
# without any of the development environment variables: import, loaded library, bundled
# helpers, the smoke test, and the package's own test-suite, recorded one interpreter per test
# like the baselines; its results must match tests/baseline-rust.txt (the wheel bundles the
# Rust native side). An sdist is first unpacked outside the repository and built into a wheel
# the way pip would, in an isolated PEP 517 environment, cargo build of native/ included.
# RSYSCALL_WHEEL_PYTHON selects the interpreter (default 3.14; wheels are abi3, CPython 3.12+).
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
DIST="${1:-$(ls -t "$ROOT"/dist/rsyscall_ng-*.whl | head -1)}"
VENV="$ROOT/.venv-wheel"
PYVER="${RSYSCALL_WHEEL_PYTHON:-3.14}"
clean() { env -u LD_LIBRARY_PATH -u PKG_CONFIG_PATH -u RSYSCALL_NATIVE -u RSYSCALL_LIBEXEC_DIR "$@"; }
rm -rf "$VENV"
uv venv --quiet --python "$PYVER" "$VENV"
case "$DIST" in
    *.whl) WHEEL="$DIST" ;;
    *.tar.gz)
        BUILD=$(mktemp -d -t rsyscall-ng-sdist.XXXXXX)
        trap 'status=$?; if [ $status -eq 0 ]; then rm -rf "$BUILD"; else echo "sdist build kept in $BUILD" >&2; fi; exit $status' EXIT
        tar -xzf "$DIST" -C "$BUILD" && SRC=$(echo "$BUILD"/rsyscall_ng-*)
        echo "== $DIST"
        echo "   unpacked in $SRC; building a wheel with CPython $PYVER in an isolated environment"
        start=$SECONDS
        (cd "$SRC" && clean uv build --quiet --wheel --python "$PYVER" --out-dir "$BUILD/wheel" .)
        echo "   built in $((SECONDS - start)) s; cargo ran in the unpacked tree:" \
             "$(ls "$SRC/native/target/release" | grep -c -E '^(librsyscall\.so|rsyscall-(bootstrap|stdin-bootstrap|unix-stub))$')/4 artefacts in native/target/release"
        WHEEL=$(ls "$BUILD"/wheel/rsyscall_ng-*.whl) ;;
    *) echo "wheel-test.sh: not a wheel or an sdist: $DIST" >&2; exit 2 ;;
esac
uv pip install --quiet --python "$VENV/bin/python" "$WHEEL" pytest pytest-timeout
echo "== $WHEEL"
unzip -l "$WHEEL" | grep -E '_native/|_raw|dist-info/METADATA' | awk '{print "  ", $4, "(" $1 " bytes)"}'
cd /tmp
run() { clean "$VENV/bin/python" "$@"; }
echo "== import, loaded library, helpers (CPython $("$VENV/bin/python" -c 'import platform; print(platform.python_version())'), no environment variables, cwd=/tmp)"
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
