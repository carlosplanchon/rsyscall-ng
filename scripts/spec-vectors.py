#!/usr/bin/env python3
"""Generate docs/spec/vectors/v0.json, the byte-level conformance vectors of the v0 protocol.

Two modes that must agree:

  --pure     build every vector with ``struct.pack`` and the layouts documented in
             docs/spec/abi-layouts.generated.md; runs with the plain system ``python3``.
  (default)  additionally import the client classes from the project venv and assert that
             they produce (or decode) exactly the same bytes; this is how the vectors are
             tied to the Python client rather than to this script.

usage: spec-vectors.py [--pure] [--write FILE | --check FILE]

Vector format: {"vectors": [{"name", "hex", "meaning", "derived_from": ["python/...:L"],
"generator"}]}. "hex" is the little-endian byte sequence, one byte per token, with fields
separated by " | ". The ``clone_args`` vector describes syscall arguments rather than bytes:
its "hex" is null and the values are under "json".
"""
from __future__ import annotations
import argparse
import json
import pathlib
import struct
import sys
import types

COMMAND = "spec-vectors.py --write docs/spec/vectors/v0.json"

# x86-64 Linux constants used by the pure mode; the default mode cross-checks them against the
# client's cffi constants (rsyscall._raw.lib).
SYS_write, SYS_openat, SYS_sendto, SYS_recvfrom = 1, 257, 44, 45
MSG_WAITALL = 0x100
AT_FDCWD = -100
SOL_SOCKET, SCM_RIGHTS = 1, 1
CLONE_VM, CLONE_FS, CLONE_FILES, CLONE_SIGHAND = 0x100, 0x200, 0x400, 0x800
CLONE_PARENT, CLONE_CHILD_CLEARTID = 0x8000, 0x200000
SIGCHLD = 17
FUTEX_OFFSET_IN_NODE = 8  # offsetof(struct futex_node, futex); cross-checked with ffi.offsetof

# Layouts (see docs/spec/abi-layouts.generated.md); cross-checked with ffi.sizeof/ffi.cast.
FMT_REQUEST = "<7q"                 # int64 sys; int64 args[6]
FMT_RESPONSE = "<q"                 # long
FMT_TRAMPOLINE = "<6qQ"             # rdi rsi rdx rcx r8 r9; void *function
FMT_FUTEX_NODE = "<QI4x"            # struct robust_list *next; uint32 futex; tail padding
FMT_CMSGHDR = "<Qii"                # cmsg_len, cmsg_level, cmsg_type
FMT_DESCRIBE_BOOTSTRAP = "<4Q4iQ"   # symbols[4]; pid, listening_sock, syscall_sock, data_sock; envp_count
FMT_DESCRIBE_STDIN = "<4Q5i4xQ"     # symbols[4]; pid, syscall_fd, data_fd, futex_memfd, connecting_fd; pad; envp_count
FMT_DESCRIBE_STUB = "<4Q5i4x3Q"     # ... ; argc, envp_count, sigmask

SYMBOLS = (0x401000, 0x401100, 0x401200, 0x401300)  # server, persistent_server, futex_helper, trampoline
PID = 4242


def hexfields(*fields: bytes) -> str:
    return " | ".join(" ".join(f"{b:02x}" for b in f) for f in fields)


def cmsg_scm_rights(fds: list[int]) -> tuple[bytes, ...]:
    data = struct.pack(f"<{len(fds)}i", *fds)
    return (struct.pack(FMT_CMSGHDR, 16 + len(data), SOL_SOCKET, SCM_RIGHTS), data)


def pure_vectors() -> list[dict]:
    V: list[dict] = []

    def add(name: str, fields, meaning: str, derived_from: list[str], generator: str, json_value=None) -> None:
        if fields is None:
            V.append({"name": name, "hex": None, "json": json_value, "meaning": meaning,
                      "derived_from": derived_from, "generator": generator})
        else:
            V.append({"name": name, "hex": hexfields(*fields), "meaning": meaning,
                      "derived_from": derived_from, "generator": generator})

    # --- wire protocol -----------------------------------------------------------------
    req = struct.pack(FMT_REQUEST, SYS_write, 1, 0x1000, 12, 0, 0, 0)
    add("request_write", [req[0:8], req[8:16], req[16:24], req[24:32], req[32:56]],
        "struct rsyscall_syscall for write(1, 0x1000, 12): sys=1 | arg1=1 | arg2=0x1000 | arg3=12 | arg4..arg6=0 (unused arguments are sent as 0)",
        ["python/rsyscall/tasks/connection.py:35-38", "python/ffibuilder.py:1251-1254", "python/rsyscall/near/sysif.py:43"],
        "struct.pack('<7q', 1, 1, 0x1000, 12, 0, 0, 0)")
    req = struct.pack(FMT_REQUEST, SYS_openat, AT_FDCWD, 0x2000, 0, 0, 0, 0)
    add("request_negative_arg", [req[0:8], req[8:16], req[16:24], req[24:56]],
        "openat(AT_FDCWD=-100, 0x2000, 0, 0): sys=257 | arg1=-100 as two's-complement int64 | arg2=0x2000 | arg3..arg6=0",
        ["python/rsyscall/tasks/connection.py:35-38", "python/rsyscall/unistd/exec.py:19-22"],
        "struct.pack('<7q', 257, -100, 0x2000, 0, 0, 0, 0)")
    req = struct.pack(FMT_REQUEST, SYS_recvfrom, 14, 0x7f0000003000, 44, MSG_WAITALL, 0, 0)
    add("request_memory_write", [req[0:8], req[8:16], req[16:24], req[24:32], req[32:40], req[40:56]],
        "memory write into the server process: recvfrom(server_fd=14, dest=0x7f0000003000, len=44, MSG_WAITALL=0x100, 0, 0); the 44 raw bytes follow this request on the same stream and the response is 44",
        ["python/rsyscall/tasks/connection.py:158-168", "python/rsyscall/sys/socket.py:592-600", "python/rsyscall/sys/socket.py:679-681"],
        "struct.pack('<7q', 45, 14, 0x7f0000003000, 44, 0x100, 0, 0)")
    req = struct.pack(FMT_REQUEST, SYS_sendto, 14, 0x7f0000003000, 44, 0, 0, 0)
    add("request_memory_read", [req[0:8], req[8:16], req[16:24], req[24:32], req[32:56]],
        "memory read from the server process: sendto(server_fd=14, src=0x7f0000003000, len=44, flags=0, 0, 0); the server-to-client stream then carries the 44 bytes followed by the response 44",
        ["python/rsyscall/tasks/connection.py:179-188", "python/rsyscall/sys/socket.py:602-610", "python/rsyscall/sys/socket.py:683-685"],
        "struct.pack('<7q', 44, 14, 0x7f0000003000, 44, 0, 0, 0)")
    add("response_ok", [struct.pack(FMT_RESPONSE, 12)],
        "response for a syscall that returned 12: the raw kernel return value as int64",
        ["python/rsyscall/tasks/connection.py:69-76", "python/rsyscall/near/sysif.py:206-210"],
        "struct.pack('<q', 12)")
    add("response_enoent", [struct.pack(FMT_RESPONSE, -2)],
        "response for a syscall that failed with ENOENT: -2 as two's-complement int64; the client raises OSError(2)",
        ["python/rsyscall/tasks/connection.py:74-76", "python/rsyscall/near/sysif.py:206-210"],
        "struct.pack('<q', -2)")

    # --- native ABI --------------------------------------------------------------------
    tramp = struct.pack(FMT_TRAMPOLINE, 7, 7, 0, 0, 0, 0, 0x7f0000001000)
    add("trampoline_stack", [tramp[0:8], tramp[8:16], tramp[16:48], tramp[48:56]],
        "struct rsyscall_trampoline_stack for Trampoline(function=0x7f0000001000, args=[7, 7]) as used for rsyscall_server(sock, sock): rdi=7 | rsi=7 | rdx,rcx,r8,r9=0 | function",
        ["python/rsyscall/loader.py:59-79", "python/ffibuilder.py:1241-1249", "python/rsyscall/thread.py:276-278"],
        "struct.pack('<6qQ', 7, 7, 0, 0, 0, 0, 0x7f0000001000)")
    image = struct.pack("<Q", 0x7f0000002000) + tramp
    add("stack_image", [image[0:8], image[8:16], image[16:24], image[24:56], image[56:64]],
        "the 64-byte stack image passed to clone as child_stack: address of rsyscall_trampoline (0x7f0000002000) | rdi | rsi | rdx..r9 | target function; rsp points at byte 0 when the child starts",
        ["python/rsyscall/sched.py:57-82", "python/rsyscall/loader.py:135-137", "python/rsyscall/handle/pointer.py:239-254"],
        "struct.pack('<Q', 0x7f0000002000) + trampoline_stack")
    node = struct.pack(FMT_FUTEX_NODE, 0, 1)
    add("futex_node", [node[0:8], node[8:12], node[12:16]],
        "FutexNode(next=None, futex=1) as written before clone: next=NULL | futex=1 (uint32) | 4 bytes of tail padding (zero)",
        ["python/rsyscall/linux/futex.py:23-32", "python/rsyscall/tasks/clone.py:116", "python/ffibuilder.py:1349-1356"],
        "struct.pack('<QI4x', 0, 1)")
    add("clone_args", None,
        "arguments of the raw clone syscall issued by the client, in argument order (flags, child_stack, ptid, ctid, newtls)",
        ["python/rsyscall/sched.py:139-151", "python/rsyscall/tasks/clone.py:101-103", "python/rsyscall/tasks/clone.py:63",
         "python/rsyscall/tasks/persistent.py:291", "python/rsyscall/monitor.py:300-302", "python/rsyscall/handle/process.py:277-279"],
        "constants of linux/sched.h on x86-64 (cross-checked with rsyscall._raw.lib in venv mode)",
        json_value={
            "argument_order": ["flags", "child_stack", "ptid", "ctid", "newtls"],
            "normal_child": {"flags": ["CLONE_VM", "CLONE_CHILD_CLEARTID", "SIGCHLD"], "flags_value": hex(CLONE_VM | CLONE_CHILD_CLEARTID | SIGCHLD),
                             "optional_flags": ["CLONE_PARENT when the cloning task is not the monitoring task", "any CLONE_* the caller passes, e.g. CLONE_FILES"],
                             "child_stack": "address of the 64-byte stack image (16-byte aligned)", "ptid": 0,
                             "ctid": f"address of the FutexNode + {FUTEX_OFFSET_IN_NODE} (offsetof(struct futex_node, futex))", "newtls": 0},
            "futex_helper": {"flags": ["CLONE_VM", "CLONE_FILES", "SIGCHLD"], "flags_value": hex(CLONE_VM | CLONE_FILES | SIGCHLD),
                             "optional_flags": ["CLONE_PARENT"], "child_stack": "address of its own 64-byte stack image", "ptid": 0, "ctid": 0, "newtls": 0},
            "persistent_child": {"flags": ["CLONE_FILES", "CLONE_FS", "CLONE_SIGHAND", "CLONE_VM", "CLONE_CHILD_CLEARTID", "SIGCHLD"],
                                 "flags_value": hex(CLONE_FILES | CLONE_FS | CLONE_SIGHAND | CLONE_VM | CLONE_CHILD_CLEARTID | SIGCHLD),
                                 "optional_flags": ["CLONE_PARENT"], "ptid": 0, "ctid": f"address of the FutexNode + {FUTEX_OFFSET_IN_NODE}", "newtls": 0},
            "constants": {"CLONE_VM": hex(CLONE_VM), "CLONE_FS": hex(CLONE_FS), "CLONE_FILES": hex(CLONE_FILES), "CLONE_SIGHAND": hex(CLONE_SIGHAND),
                          "CLONE_PARENT": hex(CLONE_PARENT), "CLONE_CHILD_CLEARTID": hex(CLONE_CHILD_CLEARTID), "SIGCHLD": SIGCHLD},
        })

    # --- bootstrap handshakes ----------------------------------------------------------
    add("persistent_count", [struct.pack("<i", 2)],
        "Int32(2): the native int32 count of passed fds that opens the persistent reconnection handshake",
        ["python/rsyscall/tasks/persistent.py:323", "python/rsyscall/tasks/persistent.py:330", "python/rsyscall/struct.py:108-123"],
        "struct.pack('<i', 2)")
    add("persistent_reply", [struct.pack("<i", 5), struct.pack("<i", 6)],
        "the server's reply to a count of 2: exactly two native int32 fd numbers in the order the fds were passed; decodes to [5, 6] (fd[0] becomes the server's new infd/outfd)",
        ["python/rsyscall/tasks/persistent.py:327", "python/rsyscall/tasks/persistent.py:332-336", "python/rsyscall/struct.py:142-166"],
        "struct.pack('<2i', 5, 6)")
    for fds in ([5, 6], [5, 6, 7], [5, 6, 7, 8]):
        hdr, data = cmsg_scm_rights(fds)
        add(f"scm_rights_{len(fds)}fds", [hdr[0:8], hdr[8:12], hdr[12:16], data],
            f"control buffer the client sends to pass fds {fds}: cmsg_len={16 + 4 * len(fds)} (u64) | cmsg_level=SOL_SOCKET | cmsg_type=SCM_RIGHTS | {len(fds)} int32 fd numbers; msg_controllen equals cmsg_len; no CMSG_ALIGN padding",
            ["python/rsyscall/sys/socket.py:304-314", "python/rsyscall/sys/socket.py:328-329", "python/rsyscall/sys/socket.py:362-368", "python/rsyscall/sys/socket.py:389-398"],
            f"struct.pack('<Qii', {16 + 4 * len(fds)}, 1, 1) + struct.pack('<{len(fds)}i', {', '.join(map(str, fds))})")
    add("lp_string", [struct.pack("<Q", 9), b"PATH=/bin"],
        "a length-prefixed string as read by the client: u64 little-endian byte count | the bytes, no NUL terminator",
        ["python/rsyscall/epoller.py:769-776", "python/rsyscall/epoller.py:785-801"],
        "struct.pack('<Q', 9) + b'PATH=/bin'")
    d = struct.pack(FMT_DESCRIBE_STDIN, *SYMBOLS, PID, 3, 4, -1, 5, 2)
    add("describe_stdin", [d[0:32], d[32:36], d[36:40], d[40:44], d[44:48], d[48:52], d[52:56], d[56:64]],
        "struct rsyscall_stdin_bootstrap: symbols (4 code addresses 0x401000..0x401300) | pid=4242 | syscall_fd=3 | data_fd=4 | futex_memfd=-1 (value unspecified in v0; -1 is the recommended default) | connecting_fd=5 | padding | envp_count=2",
        ["python/ffibuilder.py:1269-1277", "python/rsyscall/tasks/stdin_bootstrap.py:97-99", "python/rsyscall/tasks/stdin_bootstrap.py:115-127"],
        "struct.pack('<4Q5i4xQ', 0x401000, 0x401100, 0x401200, 0x401300, 4242, 3, 4, -1, 5, 2)")
    d = struct.pack(FMT_DESCRIBE_STUB, *SYMBOLS, PID, 5, 6, 7, 8, 2, 2, 0x200)
    add("describe_stub", [d[0:32], d[32:36], d[36:40], d[40:44], d[44:48], d[48:52], d[52:56], d[56:64], d[64:72], d[72:80]],
        "struct rsyscall_unix_stub: symbols | pid=4242 | syscall_fd=5 | data_fd=6 | futex_memfd=7 (the third received fd) | connecting_fd=8 | padding | argc=2 | envp_count=2 | sigmask=0x200 (bit 9 set: SIGUSR1 blocked)",
        ["python/ffibuilder.py:1278-1288", "python/rsyscall/tasks/stub.py:139-142", "python/rsyscall/tasks/stub.py:157-164"],
        "struct.pack('<4Q5i4x3Q', 0x401000, 0x401100, 0x401200, 0x401300, 4242, 5, 6, 7, 8, 2, 2, 0x200)")
    d = struct.pack(FMT_DESCRIBE_BOOTSTRAP, *SYMBOLS, PID, 4, 5, 6, 2)
    add("describe_bootstrap", [d[0:32], d[32:36], d[36:40], d[40:44], d[44:48], d[48:56]],
        "struct rsyscall_bootstrap: symbols | pid=4242 | listening_sock=4 | syscall_sock=5 | data_sock=6 | envp_count=2",
        ["python/ffibuilder.py:1261-1268", "python/rsyscall/tasks/ssh.py:265-267", "python/rsyscall/tasks/ssh.py:281-288"],
        "struct.pack('<4Q4iQ', 0x401000, 0x401100, 0x401200, 0x401300, 4242, 4, 5, 6, 2)")
    add("sigmask_sigchld", [struct.pack("<Q", 0x10000)],
        "sigmask field 0x10000: bit 16 set means signal 17 (SIGCHLD) is blocked; the client refuses such a mask because it needs to block SIGCHLD itself",
        ["python/rsyscall/tasks/stub.py:164", "python/rsyscall/struct.py:100-105", "python/rsyscall/signal.py:127-131", "python/rsyscall/signal.py:281-283"],
        "struct.pack('<Q', 1 << 16)")
    return V


def unhex(h: str) -> bytes:
    return bytes(int(tok, 16) for tok in h.replace("|", " ").split())


def venv_check(vectors: list[dict]) -> None:
    "Rebuild every vector with the client's own classes and assert byte equality."
    from rsyscall._raw import ffi, lib  # type: ignore
    from rsyscall.tasks.connection import RsyscallSyscall, SyscallResponse
    from rsyscall.loader import Trampoline, TrampolineSerializer
    from rsyscall.sched import Stack, CLONE
    from rsyscall.linux.futex import FutexNode
    from rsyscall.struct import Int32, StructList, bits
    from rsyscall.sys.socket import CmsgList, CmsgSCMRights
    from rsyscall.sys.syscall import SYS
    from rsyscall.signal import SIG, Sigset

    by_name = {v["name"]: v for v in vectors}

    def check(name: str, produced: bytes) -> None:
        expected = unhex(by_name[name]["hex"])
        if produced != expected:
            raise SystemExit(f"vector {name}: client produced {produced.hex()} but the pure vector is {expected.hex()}")

    assert (int(SYS.write), int(SYS.openat), int(SYS.sendto), int(SYS.recvfrom)) == (SYS_write, SYS_openat, SYS_sendto, SYS_recvfrom), "syscall numbers differ from the pure constants"
    from rsyscall.sys.socket import MSG
    assert int(MSG.WAITALL) == MSG_WAITALL
    assert lib.AT_FDCWD == AT_FDCWD and lib.SOL_SOCKET == SOL_SOCKET and lib.SCM_RIGHTS == SCM_RIGHTS
    assert (lib.CLONE_VM, lib.CLONE_FS, lib.CLONE_FILES, lib.CLONE_SIGHAND, lib.CLONE_PARENT, lib.CLONE_CHILD_CLEARTID) == \
        (CLONE_VM, CLONE_FS, CLONE_FILES, CLONE_SIGHAND, CLONE_PARENT, CLONE_CHILD_CLEARTID), "CLONE constants differ"
    assert int(SIG.CHLD) == SIGCHLD and (CLONE.VM | CLONE.CHILD_CLEARTID | SIG.CHLD) == int(by_name["clone_args"]["json"]["normal_child"]["flags_value"], 16)
    assert ffi.offsetof("struct futex_node", "futex") == FUTEX_OFFSET_IN_NODE
    assert ffi.sizeof("struct rsyscall_syscall") == 56 and ffi.sizeof("long") == 8

    check("request_write", RsyscallSyscall(SYS.write, 1, 0x1000, 12, 0, 0, 0).to_bytes())
    check("request_negative_arg", RsyscallSyscall(SYS.openat, AT_FDCWD, 0x2000, 0, 0, 0, 0).to_bytes())
    assert RsyscallSyscall.from_bytes(unhex(by_name["request_negative_arg"]["hex"])).arg1 == -100
    check("request_memory_write", RsyscallSyscall(SYS.recvfrom, 14, 0x7f0000003000, 44, MSG.WAITALL, 0, 0).to_bytes())
    check("request_memory_read", RsyscallSyscall(SYS.sendto, 14, 0x7f0000003000, 44, 0, 0, 0).to_bytes())
    check("response_ok", SyscallResponse(12).to_bytes())
    check("response_enoent", SyscallResponse(-2).to_bytes())
    assert SyscallResponse.from_bytes(unhex(by_name["response_enoent"]["hex"])).value == -2

    fn = types.SimpleNamespace(near=0x7f0000001000)   # stands in for a Pointer[NativeFunction]
    tramp = Trampoline(fn, [7, 7])                    # type: ignore[arg-type]
    check("trampoline_stack", TrampolineSerializer().to_bytes(tramp))
    check("stack_image", Stack(types.SimpleNamespace(near=0x7f0000002000), tramp, TrampolineSerializer()).to_bytes())  # type: ignore[arg-type]
    check("futex_node", FutexNode(None, Int32(1)).to_bytes())

    check("persistent_count", Int32(2).to_bytes())
    sl = StructList(Int32, [Int32(5), Int32(6)])
    check("persistent_reply", sl.get_self_serializer(None).to_bytes(sl))
    assert [int(x) for x in sl.get_self_serializer(None).from_bytes(unhex(by_name["persistent_reply"]["hex"])).elems] == [5, 6]
    for fds in ([5, 6], [5, 6, 7], [5, 6, 7, 8]):
        cl = CmsgList([CmsgSCMRights(fds)])           # ints stand in for FileDescriptor handles
        check(f"scm_rights_{len(fds)}fds", CmsgList.get_serializer(None).to_bytes(cl))
        assert ffi.sizeof("struct cmsghdr") + 4 * len(fds) == 16 + 4 * len(fds)
    check("lp_string", bytes(ffi.buffer(ffi.new("size_t *", 9))) + b"PATH=/bin")

    for name, ctype, values in (
        ("describe_stdin", "struct rsyscall_stdin_bootstrap",
         {"pid": PID, "syscall_fd": 3, "data_fd": 4, "futex_memfd": -1, "connecting_fd": 5, "envp_count": 2}),
        ("describe_stub", "struct rsyscall_unix_stub",
         {"pid": PID, "syscall_fd": 5, "data_fd": 6, "futex_memfd": 7, "connecting_fd": 8, "argc": 2, "envp_count": 2, "sigmask": 0x200}),
        ("describe_bootstrap", "struct rsyscall_bootstrap",
         {"pid": PID, "listening_sock": 4, "syscall_sock": 5, "data_sock": 6, "envp_count": 2}),
    ):
        symbols = {"rsyscall_server": ffi.cast("void *", SYMBOLS[0]), "rsyscall_persistent_server": ffi.cast("void *", SYMBOLS[1]),
                   "rsyscall_futex_helper": ffi.cast("void *", SYMBOLS[2]), "rsyscall_trampoline": ffi.cast("void *", SYMBOLS[3])}
        check(name, bytes(ffi.buffer(ffi.new(ctype + " *", {"symbols": symbols, **values}))))
        # and read it back the way the client does (ffi.cast on the received bytes, field by field)
        data = unhex(by_name[name]["hex"])
        parsed = ffi.cast(ctype + " *", ffi.from_buffer(data))
        for field, value in values.items():
            assert getattr(parsed, field) == value, (name, field)
        assert [int(ffi.cast("ssize_t", getattr(parsed.symbols, k))) for k in symbols] == list(SYMBOLS)

    check("sigmask_sigchld", Sigset({SIG.CHLD}).to_bytes())
    assert {SIG(bit) for bit in bits(0x10000)} == {SIG.CHLD}


def render(vectors: list[dict]) -> str:
    return json.dumps({"vectors": vectors}, indent=2) + "\n"


def main(argv: list[str]) -> int:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--pure", action="store_true", help="do not import the client; struct.pack only")
    g = p.add_mutually_exclusive_group()
    g.add_argument("--write", metavar="FILE")
    g.add_argument("--check", metavar="FILE")
    args = p.parse_args(argv)
    vectors = pure_vectors()
    if not args.pure:
        venv_check(vectors)
    text = render(vectors)
    if args.write:
        pathlib.Path(args.write).write_text(text)
        return 0
    if args.check:
        path = pathlib.Path(args.check)
        if not path.exists() or path.read_text() != text:
            print(f"{path}: missing or out of date; run: {COMMAND}", file=sys.stderr)
            return 1
        print(f"{path}: up to date" + (" (pure mode)" if args.pure else " (client classes agree)"))
        return 0
    sys.stdout.write(text)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
