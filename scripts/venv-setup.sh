#!/usr/bin/env bash
# Create .venv and install python/ in editable mode, building the cffi extension
# rsyscall._raw against the oracle in reference/prefix.
set -euo pipefail
source "$(dirname "${BASH_SOURCE[0]}")/env.sh"

if [ ! -f "$PREFIX/lib/pkgconfig/rsyscall.pc" ]; then
    echo "oracle not built; run 'make oracle' first" >&2
    exit 1
fi
[ -x "$PY" ] || uv venv --python 3.14 "$VENV"

# Bake a RUNPATH into rsyscall/_raw*.so so `import rsyscall` works without LD_LIBRARY_PATH.
export LDFLAGS="-Wl,-rpath,$PREFIX/lib${LDFLAGS:+ $LDFLAGS}"
uv pip install --python "$PY" --reinstall-package rsyscall -e "$ROOT/python"
uv pip install --python "$PY" pytest pytest-timeout

"$PY" -c 'import rsyscall, rsyscall._raw; print("rsyscall imported from", rsyscall.__file__)'
if readelf -d "$ROOT"/python/rsyscall/_raw*.so | grep -qE 'RUNPATH|RPATH'; then
    echo "rpath baked into: $(ls "$ROOT"/python/rsyscall/_raw*.so)"
else
    echo "WARNING: no rpath in the cffi module; LD_LIBRARY_PATH=$PREFIX/lib is required at runtime" >&2
fi
