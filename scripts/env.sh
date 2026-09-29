# Shared settings, sourced by the scripts in this directory and by the Makefile.
# Not meant to be executed directly; bash only (it uses BASH_SOURCE).
# shellcheck shell=bash
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
UPSTREAM_URL="${UPSTREAM_URL:-https://github.com/catern/rsyscall.git}"
UPSTREAM_COMMIT=2a362099610a664caeb7f06dd805e5a0fb80cd08
REF_DIR="$ROOT/reference"
UPSTREAM_DIR="$REF_DIR/upstream"
ORACLE_PREFIX="$REF_DIR/prefix"       # the unmodified upstream C, built by scripts/oracle-build.sh
NATIVE_PREFIX="$ROOT/native/prefix"   # the clean-room Rust implementation, installed by scripts/native-install.sh

# BACKEND selects which native implementation the venv, the smoke test, the tests and the baseline use:
#   c     the upstream C library in reference/prefix (the oracle)      -> .venv
#   rust  the Rust implementation in native/prefix                     -> .venv-rust
BACKEND="${BACKEND:-c}"
case "$BACKEND" in
    c)    PREFIX="$ORACLE_PREFIX"; VENV="$ROOT/.venv" ;;
    rust) PREFIX="$NATIVE_PREFIX"; VENV="$ROOT/.venv-rust" ;;
    *)    echo "env.sh: unknown BACKEND '$BACKEND' (expected c or rust)" >&2; return 1 2>/dev/null || exit 1 ;;
esac
PY="$VENV/bin/python"
export RSYSCALL_BACKEND="$BACKEND"
# The development flow builds the cffi extension against the prefix (setup.py, prefix mode)
# and finds the helper executables there (python/rsyscall/_native).
export RSYSCALL_NATIVE=prefix
export RSYSCALL_LIBEXEC_DIR="$PREFIX/libexec/rsyscall"
export PKG_CONFIG_PATH="$PREFIX/lib/pkgconfig${PKG_CONFIG_PATH:+:$PKG_CONFIG_PATH}"
# Searched before the RUNPATH baked into the cffi module, so this decides which librsyscall is loaded.
export LD_LIBRARY_PATH="$PREFIX/lib${LD_LIBRARY_PATH:+:$LD_LIBRARY_PATH}"
