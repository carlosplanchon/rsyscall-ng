#!/usr/bin/env python3
"""Generate docs/spec/abi-layouts.generated.md from the cdef text of python/ffibuilder.py.

The struct definitions are taken from the string arguments of every ``ffibuilder.cdef(...)``
call (found with the ``ast`` module), never from the C preamble passed to
``set_source_pkgconfig``.  They are fed to a fresh ``cffi.FFI()`` in ABI mode (``cdef`` only,
nothing is compiled), so the offsets are exactly what the Python client computes when it
serialises or parses these structs with its own ``ffi``.  Nothing here is hard-coded: every
offset, size and derived constant is asked from cffi.

Runs with the plain system ``python3`` (cffi installed) and with the project venv.

usage: abi-layouts.py                 print the Markdown to stdout
       abi-layouts.py --write FILE    write it to FILE
       abi-layouts.py --check FILE    exit 1 if FILE differs from the generated text
"""
from __future__ import annotations
import argparse
import ast
import pathlib
import re
import sys

import cffi

ROOT = pathlib.Path(__file__).resolve().parents[1]
FFIBUILDER = ROOT / "python" / "ffibuilder.py"
# Order here is the presentation order of the tables; dependencies are resolved separately.
ALLOWLIST = [
    "rsyscall_syscall",
    "rsyscall_trampoline_stack",
    "rsyscall_symbol_table",
    "rsyscall_bootstrap",
    "rsyscall_stdin_bootstrap",
    "rsyscall_unix_stub",
    "futex_node",
    "robust_list",
    "robust_list_head",
    "iovec",
    "msghdr",
]
# cffi does not know pid_t; the client's ffi gets it from the system headers in API mode.
PRELUDE = "typedef int pid_t;"
# The cdef declares struct cmsghdr with a trailing "...;" (a partial struct), which cannot be
# sized in ABI mode.  This complete mirror follows the x86-64 glibc layout of the header part.
CMSGHDR_MIRROR = "struct cmsghdr { size_t cmsg_len; int cmsg_level; int cmsg_type; };"
SCALARS = ["int", "long", "size_t", "pid_t", "void *"]
COMMAND = "python3 scripts/abi-layouts.py --write docs/spec/abi-layouts.generated.md"

STRUCT_RE = re.compile(r"struct\s+(\w+)\s*\{([^{}]*?)\};", re.S)


def cdef_strings(source: str) -> list[tuple[str, int, bool]]:
    "Return (text, file offset of the text, packed?) for every ffibuilder.cdef(<string literal>, ...) call."
    tree = ast.parse(source)
    found = []
    for node in ast.walk(tree):
        if not (isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
                and node.func.attr == "cdef" and isinstance(node.func.value, ast.Name)
                and node.func.value.id == "ffibuilder" and node.args):
            continue
        arg = node.args[0]
        if not (isinstance(arg, ast.Constant) and isinstance(arg.value, str)):
            continue
        packed = any(kw.arg == "packed" and isinstance(kw.value, ast.Constant) and kw.value.value
                     for kw in node.keywords)
        # The literals contain no escape sequences, so the text appears verbatim in the file.
        offset = source.find(arg.value)
        if offset < 0:
            sys.exit(f"could not locate a cdef literal starting at line {arg.lineno} in the file")
        found.append((arg.value, offset, packed))
    return found


def collect_structs(source: str) -> dict[str, dict]:
    "Map struct name -> {text, start_line, end_line, packed} for the allowlisted structs in the cdef text."
    structs: dict[str, dict] = {}
    for text, base, packed in cdef_strings(source):
        for m in STRUCT_RE.finditer(text):
            name = m.group(1)
            if name not in ALLOWLIST or name in structs:
                continue
            start = base + m.start()
            end = base + m.end()
            structs[name] = {
                "text": m.group(0),
                "start_line": source.count("\n", 0, start) + 1,
                "end_line": source.count("\n", 0, end) + 1,
                "packed": packed,
            }
    missing = [n for n in ALLOWLIST if n not in structs]
    if missing:
        sys.exit(f"structs not found in the cdef text: {missing}")
    return structs


def dependency_order(structs: dict[str, dict]) -> list[str]:
    "Emit a struct after every struct it embeds by value (cffi's parser needs complete member types)."
    order: list[str] = []
    seen: set[str] = set()

    def visit(name: str) -> None:
        if name in seen:
            return
        seen.add(name)
        body = STRUCT_RE.match(structs[name]["text"]).group(2)
        for dep in re.findall(r"struct\s+(\w+)\s+\w+\s*;", body):  # by-value members only
            if dep in structs and dep != name:
                visit(dep)
        order.append(name)

    for name in ALLOWLIST:
        visit(name)
    return order


def build_ffi(structs: dict[str, dict]) -> cffi.FFI:
    ffi = cffi.FFI()
    text = "\n".join([PRELUDE, CMSGHDR_MIRROR] + [structs[n]["text"] for n in dependency_order(structs)])
    ffi.cdef(text)
    return ffi


def render(structs: dict[str, dict], ffi: cffi.FFI) -> str:
    out: list[str] = []
    w = out.append
    w("# ABI layouts of the native-side structs (generated)")
    w("")
    w("<!-- GENERATED FILE: do not edit by hand. -->")
    w("")
    w(f"Generated by `{COMMAND}` (cffi {cffi.__version__}); checked by `make spec-check`.")
    w("")
    w("Source of truth: the string arguments of the `ffibuilder.cdef(...)` calls in")
    w("`python/ffibuilder.py`, parsed with a fresh `cffi.FFI()` in ABI mode (nothing is compiled).")
    w("The C preamble passed to `set_source_pkgconfig` is not consulted.")
    w("")
    w("Assumptions made by the generator:")
    w("")
    w(f"- prelude `{PRELUDE}` (cffi has no built-in `pid_t`; the client gets it from the system headers);")
    w(f"- `struct cmsghdr` is declared with `...;` in the cdef (`python/ffibuilder.py`) and cannot be")
    w(f"  sized in ABI mode, so the complete mirror `{CMSGHDR_MIRROR}` is used instead; it is a")
    w("  mirror of the x86-64 glibc header layout, not a copy of the cdef;")
    w("- the host is x86-64 LP64 little-endian, which is the only platform of v0.")
    w("")
    w("## Scalar sizes")
    w("")
    w("| C type | size |")
    w("|---|---|")
    for s in SCALARS:
        w(f"| `{s}` | {ffi.sizeof(s)} |")
    w("")
    w("## Structs")
    w("")
    w("Offsets and sizes are in bytes.  Padding rows are explicit; the client never writes or")
    w("reads padding bytes (see the specification for how receivers treat them).")
    w("")
    for name in ALLOWLIST:
        info = structs[name]
        ctype = f"struct {name}"
        size = ffi.sizeof(ctype)
        w(f"### `{ctype}`")
        w("")
        w(f"Source: `python/ffibuilder.py:{info['start_line']}-{info['end_line']}`"
          f"{' (packed)' if info['packed'] else ''}. sizeof = {size}, alignment = {ffi.alignof(ctype)}.")
        w("")
        w("| field | C type | offset | size |")
        w("|---|---|---|---|")
        cursor = 0
        for fname, field in ffi.typeof(ctype).fields:
            if field.offset > cursor:
                w(f"| *(padding)* | | {cursor} | {field.offset - cursor} |")
            fsize = ffi.sizeof(field.type)
            w(f"| `{fname}` | `{field.type.cname}` | {field.offset} | {fsize} |")
            cursor = field.offset + fsize
        if size > cursor:
            w(f"| *(tail padding)* | | {cursor} | {size - cursor} |")
        w("")
    w("## Derived constants")
    w("")
    w("| constant | value | how it is derived |")
    w("|---|---|---|")
    w(f"| `sizeof(struct rsyscall_syscall)` (request size) | {ffi.sizeof('struct rsyscall_syscall')} | table above |")
    w(f"| `sizeof(long)` (response size) | {ffi.sizeof('long')} | scalar table |")
    stack_image = ffi.sizeof("void *") + ffi.sizeof("struct rsyscall_trampoline_stack")
    w(f"| stack image size | {stack_image} | `sizeof(void *)` (the trampoline address) + `sizeof(struct rsyscall_trampoline_stack)` |")
    w(f"| `offsetof(struct futex_node, futex)` | {ffi.offsetof('struct futex_node', 'futex')} | table above; added to the node address to form the `ctid` argument of `clone` |")
    w(f"| `sizeof(struct futex_node)` | {ffi.sizeof('struct futex_node')} | table above |")
    w(f"| `sizeof(struct cmsghdr)` (mirror) | {ffi.sizeof('struct cmsghdr')} | mirror struct |")
    w(f"| `cmsg_len(n)` for `n` passed fds | {ffi.sizeof('struct cmsghdr')} + {ffi.sizeof('int')}n | `sizeof(struct cmsghdr) + n * sizeof(int)`; the client sets `msg_controllen` to the same value |")
    w(f"| `sizeof(struct rsyscall_bootstrap)` | {ffi.sizeof('struct rsyscall_bootstrap')} | table above |")
    w(f"| `sizeof(struct rsyscall_stdin_bootstrap)` | {ffi.sizeof('struct rsyscall_stdin_bootstrap')} | table above |")
    w(f"| `sizeof(struct rsyscall_unix_stub)` | {ffi.sizeof('struct rsyscall_unix_stub')} | table above |")
    w("")
    return "\n".join(out)


def main(argv: list[str]) -> int:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    g = p.add_mutually_exclusive_group()
    g.add_argument("--write", metavar="FILE")
    g.add_argument("--check", metavar="FILE")
    args = p.parse_args(argv)
    source = FFIBUILDER.read_text()
    structs = collect_structs(source)
    text = render(structs, build_ffi(structs))
    if args.write:
        pathlib.Path(args.write).write_text(text)
        return 0
    if args.check:
        path = pathlib.Path(args.check)
        if not path.exists():
            print(f"{path}: missing; run: {COMMAND}", file=sys.stderr)
            return 1
        if path.read_text() != text:
            print(f"{path}: out of date; run: {COMMAND}", file=sys.stderr)
            return 1
        print(f"{path}: up to date")
        return 0
    sys.stdout.write(text)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
