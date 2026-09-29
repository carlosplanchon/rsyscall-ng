#!/usr/bin/env bash
# Check that the venv's cffi module resolves librsyscall from the selected backend's prefix.
# Both venvs share the in-tree python/rsyscall/_raw*.so; LD_LIBRARY_PATH (scripts/env.sh) decides
# which library is loaded, and this catches a stale or mis-set environment before running anything.
set -euo pipefail
source "$(dirname "${BASH_SOURCE[0]}")/env.sh"
if [ ! -x "$PY" ]; then
    echo "preflight: no venv for BACKEND=$BACKEND ($VENV); run 'make venv BACKEND=$BACKEND'" >&2
    exit 1
fi
loaded=$("$PY" - <<'PY'
import rsyscall._raw
for line in open("/proc/self/maps"):
    if "librsyscall" in line:
        print(line.split()[-1])
        break
PY
)
case "$loaded" in
    "$PREFIX"/*) echo "preflight: BACKEND=$BACKEND loads $loaded" ;;
    *) echo "preflight: BACKEND=$BACKEND but the interpreter loaded '$loaded' (expected a path under $PREFIX)" >&2; exit 1 ;;
esac
