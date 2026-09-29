# Shared settings, sourced by the scripts in this directory and by the Makefile.
# Not meant to be executed directly.
# shellcheck shell=bash
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
UPSTREAM_URL="${UPSTREAM_URL:-https://github.com/catern/rsyscall.git}"
UPSTREAM_COMMIT=2a362099610a664caeb7f06dd805e5a0fb80cd08
REF_DIR="$ROOT/reference"
UPSTREAM_DIR="$REF_DIR/upstream"
PREFIX="$REF_DIR/prefix"
VENV="$ROOT/.venv"
PY="$VENV/bin/python"
export PKG_CONFIG_PATH="$PREFIX/lib/pkgconfig${PKG_CONFIG_PATH:+:$PKG_CONFIG_PATH}"
export LD_LIBRARY_PATH="$PREFIX/lib${LD_LIBRARY_PATH:+:$LD_LIBRARY_PATH}"
