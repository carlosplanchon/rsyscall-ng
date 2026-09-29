#!/usr/bin/env bash
# Build the unmodified upstream C library and helper programs (the test "oracle")
# from a clone pinned to UPSTREAM_COMMIT into reference/prefix. Idempotent.
set -euo pipefail
source "$(dirname "${BASH_SOURCE[0]}")/env.sh"

if [ -f "$PREFIX/lib/pkgconfig/rsyscall.pc" ] && [ -z "${FORCE:-}" ]; then
    echo "oracle already built in $PREFIX (FORCE=1 to rebuild)"
    exit 0
fi
mkdir -p "$REF_DIR"
if [ ! -d "$UPSTREAM_DIR/.git" ]; then
    git clone --no-checkout "$UPSTREAM_URL" "$UPSTREAM_DIR"
fi
git -C "$UPSTREAM_DIR" cat-file -e "$UPSTREAM_COMMIT^{commit}" 2>/dev/null || git -C "$UPSTREAM_DIR" fetch origin
git -C "$UPSTREAM_DIR" checkout -q --detach "$UPSTREAM_COMMIT"

cd "$UPSTREAM_DIR/c"
autoreconf -fi
./configure --prefix="$PREFIX"
make -j"$(nproc)"
make install

echo "pkg-config rsyscall version: $(pkg-config --modversion rsyscall)"
for exe in rsyscall-server rsyscall-bootstrap rsyscall-stdin-bootstrap rsyscall-unix-stub; do
    test -x "$PREFIX/libexec/rsyscall/$exe"
done
echo "oracle built: $PREFIX"
