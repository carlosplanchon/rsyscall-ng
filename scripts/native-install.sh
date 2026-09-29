#!/usr/bin/env bash
# Build the clean-room Rust native side and install it into native/prefix with the same layout as
# the oracle prefix, then check the ELF properties the specification requires (native-abi.md §2, §9).
set -euo pipefail
source "$(dirname "${BASH_SOURCE[0]}")/env.sh"
NATIVE="$ROOT/native"
OUT="$NATIVE_PREFIX"
T="$NATIVE/target/release"

cargo build --release --manifest-path "$NATIVE/Cargo.toml" -p rsyscall-native

install -D -m 755 "$T/librsyscall.so" "$OUT/lib/librsyscall.so"
install -D -m 644 "$NATIVE/rsyscall/include/rsyscall.h" "$OUT/include/rsyscall.h"
for exe in rsyscall-bootstrap rsyscall-stdin-bootstrap rsyscall-unix-stub; do
    install -D -m 755 "$T/$exe" "$OUT/libexec/rsyscall/$exe"
done
mkdir -p "$OUT/lib/pkgconfig"
sed "s|@PREFIX@|$OUT|g" "$NATIVE/rsyscall/rsyscall.pc.in" > "$OUT/lib/pkgconfig/rsyscall.pc"

status=0
fail() { echo "CHECK FAILED: $*" >&2; status=1; }
so="$OUT/lib/librsyscall.so"
echo "== $so"
syms=$(nm -D --defined-only "$so" | awk '{print $NF}' | sort | tr '\n' ' ')
echo "exported: $syms"
[ "$syms" = "rsyscall_futex_helper rsyscall_persistent_server rsyscall_raw_syscall rsyscall_server rsyscall_trampoline " ] \
    || fail "exported symbols are not exactly the five of native-abi.md §3"
undef=$(nm -D --undefined-only "$so" | awk '{print $NF}' | tr '\n' ' ')
[ -z "$undef" ] || fail "undefined dynamic symbols: $undef"
readelf -d "$so" | grep -qE 'BIND_NOW|FLAGS_1.*NOW' || fail "no BIND_NOW / FLAGS_1 NOW in the dynamic section (-z now)"
needed=$(readelf -d "$so" | grep -c NEEDED || true)
[ "$needed" = 0 ] || echo "WARNING: $needed NEEDED entries in $so (expected none)"
readelf -lW "$so" | grep -qE '^\s*TLS' && fail "TLS program header present in $so" || true
readelf -lW "$so" | grep -qE '^\s*INTERP' && fail "INTERP program header present in $so" || true
for exe in rsyscall-bootstrap rsyscall-stdin-bootstrap rsyscall-unix-stub; do
    f="$OUT/libexec/rsyscall/$exe"; echo "== $f"
    readelf -h "$f" | grep -qE 'Type:\s+EXEC' || fail "$exe is not ET_EXEC (static, non-PIE expected)"
    readelf -lW "$f" | grep -qE '^\s*(INTERP|DYNAMIC)' && fail "$exe has INTERP/DYNAMIC (not static)" || true
    readelf -lW "$f" | grep -qE '^\s*TLS' && fail "$exe has a TLS program header" || true
done
echo "== pkg-config"
PKG_CONFIG_PATH="$OUT/lib/pkgconfig" pkg-config --cflags --libs rsyscall || fail "pkg-config cannot resolve rsyscall"
[ "$status" = 0 ] && echo "native installed: $OUT" || { echo "native installed with failed checks: $OUT" >&2; exit 1; }
