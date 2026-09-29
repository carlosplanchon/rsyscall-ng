#!/usr/bin/env python3
"""Black-box driver for the oracle helper executables. Uses only the standard library.

usage: probe_oracle.py <libexec-dir> stdin|stub|bootstrap
Mimics the Python client's handshakes (one 1-byte message carrying SCM_RIGHTS, then a
describe struct + u64-LE length-prefixed strings on the data socket), then speaks the
wire protocol on the syscall socket, then shuts the syscall socket down and reports the
process's exit status.
"""
import os, sys, socket, struct, array, subprocess, tempfile, time, signal

EXE_DIR = sys.argv[1]
MODE = sys.argv[2]
SYS_close, SYS_mmap, SYS_getpid, SYS_sendto, SYS_recvfrom, SYS_openat, SYS_accept4 = 3, 9, 39, 44, 45, 257, 288
MSG_WAITALL = 0x100

def recv_exact(sock, n):
    buf = b''
    while len(buf) < n:
        chunk = sock.recv(n - len(buf))
        if not chunk:
            raise EOFError(f'EOF after {len(buf)} of {n} bytes: {buf!r}')
        buf += chunk
    return buf

def read_lp_string(sock):
    (n,) = struct.unpack('<Q', recv_exact(sock, 8))
    return recv_exact(sock, n)

def send_fds(sock, fds):
    return sock.sendmsg([b'\0'], [(socket.SOL_SOCKET, socket.SCM_RIGHTS, array.array('i', fds).tobytes())])

def request(sock, nr, *args):
    args = list(args) + [0] * (6 - len(args))
    sock.sendall(struct.pack('<7q', nr, *args))

def response(sock):
    (ret,) = struct.unpack('<q', recv_exact(sock, 8))
    return ret

def syscall(sock, nr, *args):
    request(sock, nr, *args)
    return response(sock)

def fd_table(pid):
    out = []
    for fd in sorted(os.listdir(f'/proc/{pid}/fd'), key=int):
        try:
            out.append(f'{fd}->{os.readlink(f"/proc/{pid}/fd/{fd}")}')
        except OSError as e:
            out.append(f'{fd}->?{e.errno}')
    return ' '.join(out)

def fd_flags(pid):
    out = []
    for fd in sorted(os.listdir(f'/proc/{pid}/fd'), key=int):
        try:
            with open(f'/proc/{pid}/fdinfo/{fd}') as f:
                flags = [l.split()[1] for l in f if l.startswith('flags:')][0]
            v = int(flags, 8)
            out.append(f'{fd}:{"CLOEXEC" if v & 0o2000000 else "-"}{"|NONBLOCK" if v & 0o4000 else ""}')
        except OSError:
            out.append(f'{fd}:?')
    return ' '.join(out)

def sigmask_of(pid):
    with open(f'/proc/{pid}/status') as f:
        for line in f:
            if line.startswith('SigBlk:'):
                return line.split()[1]

def exercise_wire(sys_sock, server_fd, label):
    "Speak the wire protocol like the client does and print what the server answers."
    print(f'[{label}] getpid -> {syscall(sys_sock, SYS_getpid)}')
    addr = syscall(sys_sock, SYS_mmap, 0, 4096, 3, 0x21, -1, 0)
    print(f'[{label}] mmap -> {addr:#x}')
    # memory write: recvfrom(server_fd, addr, 13, MSG_WAITALL) followed inline by the bytes
    request(sys_sock, SYS_recvfrom, server_fd, addr, 13, MSG_WAITALL, 0, 0)
    sys_sock.sendall(b'/nonexistent\0')
    print(f'[{label}] memory write (recvfrom WAITALL) -> {response(sys_sock)}')
    # memory read: sendto(server_fd, addr, 13, 0): data then result
    request(sys_sock, SYS_sendto, server_fd, addr, 13, 0, 0, 0)
    data = recv_exact(sys_sock, 13)
    print(f'[{label}] memory read (sendto) data={data!r} result={response(sys_sock)}')
    # error passthrough: close(-1) -> -EBADF
    print(f'[{label}] close(-1) -> {syscall(sys_sock, SYS_close, -1)}')
    # negative argument: openat(AT_FDCWD=-100, "/nonexistent", O_RDONLY) -> -ENOENT
    print(f'[{label}] openat(-100, "/nonexistent") -> {syscall(sys_sock, SYS_openat, -100, addr, 0, 0)}')
    # request delivered in three pieces with pauses
    req = struct.pack('<7q', SYS_getpid, 0, 0, 0, 0, 0, 0)
    for piece in (req[:10], req[10:40], req[40:]):
        sys_sock.sendall(piece)
        time.sleep(0.05)
    print(f'[{label}] fragmented getpid -> {response(sys_sock)}')
    # two pipelined requests, responses read together
    request(sys_sock, SYS_getpid)
    request(sys_sock, SYS_close, -1)
    time.sleep(0.1)
    both = recv_exact(sys_sock, 16)
    print(f'[{label}] pipelined getpid,close(-1) -> {struct.unpack("<2q", both)}')

def finish(proc, sys_sock, label):
    sys_sock.shutdown(socket.SHUT_RDWR)
    try:
        rc = proc.wait(timeout=5)
    except subprocess.TimeoutExpired:
        print(f'[{label}] process did not exit within 5s after shutdown(SHUT_RDWR); killing')
        proc.kill(); rc = proc.wait()
    err = proc.stderr.read() if proc.stderr else b''
    out = proc.stdout.read() if proc.stdout else b''
    print(f'[{label}] after shutdown: returncode={rc} stdout={out!r} stderr={err!r}')

def probe_stdin():
    parent_sock, child_sock = socket.socketpair(socket.AF_UNIX, socket.SOCK_STREAM)
    def block_usr1():
        signal.pthread_sigmask(signal.SIG_BLOCK, {signal.SIGUSR1})
    proc = subprocess.Popen([f'{EXE_DIR}/rsyscall-stdin-bootstrap'], stdin=child_sock,
                            stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                            env={'FOO': 'bar', 'EMPTY': '', 'PATH': '/usr/bin'}, preexec_fn=block_usr1)
    child_sock.close()
    sys_a, sys_b = socket.socketpair(); data_a, data_b = socket.socketpair(); conn_a, conn_b = socket.socketpair()
    print('[stdin] sending fds', [sys_b.fileno(), data_b.fileno(), conn_b.fileno()])
    send_fds(parent_sock, [sys_b.fileno(), data_b.fileno(), conn_b.fileno()])
    sys_b.close(); data_b.close(); conn_b.close(); parent_sock.close()
    hdr = recv_exact(data_a, 64)
    syms = struct.unpack_from('<4Q', hdr, 0)
    pid, syscall_fd, data_fd, futex_memfd, connecting_fd = struct.unpack_from('<5i', hdr, 32)
    (envp_count,) = struct.unpack_from('<Q', hdr, 56)
    print(f'[stdin] symbols={[hex(s) for s in syms]} pid={pid} (popen pid {proc.pid}) syscall_fd={syscall_fd} data_fd={data_fd} futex_memfd={futex_memfd} connecting_fd={connecting_fd} pad@52={hdr[52:56].hex()} envp_count={envp_count}')
    env = [read_lp_string(data_a) for _ in range(envp_count)]
    print(f'[stdin] envp={env}')
    print(f'[stdin] fd table: {fd_table(pid)}')
    print(f'[stdin] fd flags: {fd_flags(pid)}')
    print(f'[stdin] SigBlk={sigmask_of(pid)}')
    exercise_wire(sys_a, syscall_fd, 'stdin')
    finish(proc, sys_a, 'stdin')

def probe_stub(long_path=False):
    d = tempfile.mkdtemp(prefix='stubprobe')
    if long_path:
        d = os.path.join(d, 'x' * 100); os.mkdir(d)
    path = f'{d}/stub.sock'
    print(f'[stub] socket path length {len(path)}')
    lsock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    if long_path:
        dirfd = os.open(d, os.O_PATH | os.O_DIRECTORY)
        lsock.bind(f'/proc/self/fd/{dirfd}/stub.sock')
    else:
        lsock.bind(path)
    lsock.listen(10)
    def block_usr1():
        signal.pthread_sigmask(signal.SIG_BLOCK, {signal.SIGUSR1})
    proc = subprocess.Popen([f'{EXE_DIR}/rsyscall-unix-stub', 'dummy_stub', 'arg1', 'arg two', ''],
                            env={'RSYSCALL_UNIX_STUB_SOCK_PATH': path, 'FOO': 'bar', 'NOEQ': 'x'},
                            stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.PIPE, preexec_fn=block_usr1)
    lsock.settimeout(5)
    try:
        conn, _ = lsock.accept()
    except socket.timeout:
        rc = proc.wait(timeout=2)
        print(f'[stub] no connection within 5s; returncode={rc} stderr={proc.stderr.read()!r}'); return
    sys_a, sys_b = socket.socketpair(); data_a, data_b = socket.socketpair(); conn_a, conn_b = socket.socketpair()
    memfd = os.memfd_create('child_robust_futex_list')
    print('[stub] sending fds', [sys_b.fileno(), data_b.fileno(), memfd, conn_b.fileno()])
    send_fds(conn, [sys_b.fileno(), data_b.fileno(), memfd, conn_b.fileno()])
    sys_b.close(); data_b.close(); conn_b.close(); conn.close()
    hdr = recv_exact(data_a, 80)
    syms = struct.unpack_from('<4Q', hdr, 0)
    pid, syscall_fd, data_fd, futex_memfd, connecting_fd = struct.unpack_from('<5i', hdr, 32)
    argc, envp_count, sigmask = struct.unpack_from('<3Q', hdr, 56)
    print(f'[stub] symbols={[hex(s) for s in syms]} pid={pid} (popen pid {proc.pid}) syscall_fd={syscall_fd} data_fd={data_fd} futex_memfd={futex_memfd} connecting_fd={connecting_fd} pad@52={hdr[52:56].hex()} argc={argc} envp_count={envp_count} sigmask={sigmask:#x}')
    argv = [read_lp_string(data_a) for _ in range(argc)]
    env = [read_lp_string(data_a) for _ in range(envp_count)]
    print(f'[stub] argv={argv}')
    print(f'[stub] envp={env}')
    print(f'[stub] fd table: {fd_table(pid)}')
    print(f'[stub] fd flags: {fd_flags(pid)}')
    print(f'[stub] SigBlk={sigmask_of(pid)}')
    exercise_wire(sys_a, syscall_fd, 'stub')
    finish(proc, sys_a, 'stub')

def probe_bootstrap():
    d = tempfile.mkdtemp(prefix='bootprobe')
    exe = f'{EXE_DIR}/rsyscall-bootstrap'
    sock_proc = subprocess.Popen([exe, 'socket'], cwd=d, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.PIPE, env={'FOO': 'bar'})
    line = sock_proc.stdout.readline()
    print(f'[boot] socket mode printed {line!r}; dir now contains {sorted(os.listdir(d))}')
    time.sleep(0.2)
    print(f'[boot] socket-mode process alive? {sock_proc.poll() is None}; its fd table: {fd_table(sock_proc.pid)}')
    rs_proc = subprocess.Popen([exe, 'rsyscall'], cwd=d, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.PIPE, env={'FOO': 'bar', 'PATH': '/usr/bin'})
    try:
        rc = sock_proc.wait(timeout=5)
        print(f'[boot] socket-mode process exited with {rc}; stdout rest={sock_proc.stdout.read()!r} stderr={sock_proc.stderr.read()!r}')
    except subprocess.TimeoutExpired:
        print('[boot] socket-mode process still running 5s after rsyscall mode started')
    print(f'[boot] dir now contains {sorted(os.listdir(d))}')
    c1 = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM); c1.connect(f'{d}/data')
    c2 = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM); c2.connect(f'{d}/data')
    hdr = recv_exact(c2, 56)
    syms = struct.unpack_from('<4Q', hdr, 0)
    pid, listening_sock, syscall_sock, data_sock = struct.unpack_from('<4i', hdr, 32)
    (envp_count,) = struct.unpack_from('<Q', hdr, 48)
    print(f'[boot] symbols={[hex(s) for s in syms]} pid={pid} (popen pid {rs_proc.pid}) listening_sock={listening_sock} syscall_sock={syscall_sock} data_sock={data_sock} envp_count={envp_count}')
    env = [read_lp_string(c2) for _ in range(envp_count)]
    print(f'[boot] envp={env}')
    print(f'[boot] fd table: {fd_table(pid)}')
    print(f'[boot] fd flags: {fd_flags(pid)}')
    print(f'[boot] SigBlk={sigmask_of(pid)}')
    exercise_wire(c1, syscall_sock, 'boot')
    # a third connection must be acceptable by the remote through the still-open listening fd
    c3 = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM); c3.connect(f'{d}/data')
    print(f'[boot] accept4(listening_sock) -> {syscall(c1, SYS_accept4, listening_sock, 0, 0, 0)}')
    finish(rs_proc, c1, 'boot')
    print(f'[boot] dir after exit contains {sorted(os.listdir(d))}')

if MODE == 'stdin':
    probe_stdin()
elif MODE == 'stub':
    probe_stub()
elif MODE == 'stublong':
    probe_stub(long_path=True)
elif MODE == 'bootstrap':
    probe_bootstrap()
