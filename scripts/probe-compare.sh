#!/usr/bin/env bash
# Run the black-box probe driver against both backends' helper executables and diff the normalised
# output (pids, addresses, temporary names and inode numbers vary from run to run).
set -uo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
C="$ROOT/reference/prefix/libexec/rsyscall"
R="$ROOT/native/prefix/libexec/rsyscall"
OUT="$ROOT/reference/probe-compare"
mkdir -p "$OUT"
norm() {
    sed -E 's/0x[0-9a-f]+/0xX/g; s/\bpid=[0-9]+/pid=N/g; s/popen pid [0-9]+/popen pid N/g; s/\bpid [0-9]+\b/pid N/g;
            s#/tmp/[A-Za-z0-9_./-]+#/tmp/T#g; s/(socket|pipe|anon_inode):\[[0-9]+\]/\1:[I]/g'
}
status=0
for m in stdin stub stublong bootstrap; do
    python3 "$ROOT/scripts/probes/probe_oracle.py" "$C" "$m" > "$OUT/c-$m.txt" 2>&1
    python3 "$ROOT/scripts/probes/probe_oracle.py" "$R" "$m" > "$OUT/rust-$m.txt" 2>&1
    if diff <(norm < "$OUT/c-$m.txt") <(norm < "$OUT/rust-$m.txt") > "$OUT/diff-$m.txt"; then
        echo "$m: identical after normalisation"
    else
        echo "$m: differences (c < > rust), see $OUT/diff-$m.txt:"; cat "$OUT/diff-$m.txt"; status=1
    fi
done
exit $status
