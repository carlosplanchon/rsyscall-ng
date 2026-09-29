"""Black-box probe of rsyscall_persistent_server through the Python client, finishing with raw sockets.

Run with the venv python. The client library is used to create the persistent process and for one
reconnection; everything after the manual shutdown uses only standard-library sockets so that the
client's disconnected-syscall blocking (persistent.py L10) cannot stall the probe.
"""
import trio, rsyscall, os, tempfile, socket, struct, array, time
from rsyscall.tasks.persistent import clone_persistent

SYS_getpid, SYS_exit, SYS_close = 39, 60, 3

def recv_exact(s, n):
    buf = b''
    while len(buf) < n:
        c = s.recv(n - len(buf))
        if not c:
            raise EOFError(f'EOF after {len(buf)} bytes: {buf!r}')
        buf += c
    return buf

def raw_reconnect(path, count, nfds, label):
    s = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM); s.settimeout(3)
    s.connect(path)
    pairs = [socket.socketpair() for _ in range(nfds)]
    s.sendall(struct.pack('i', count))
    s.sendmsg([b'\0'], [(socket.SOL_SOCKET, socket.SCM_RIGHTS, array.array('i', [p[1].fileno() for p in pairs]).tobytes())])
    for p in pairs: p[1].close()
    got = b''
    try:
        while len(got) < 4 * max(count, nfds):
            c = s.recv(4 * max(count, nfds) - len(got))
            if not c: break
            got += c
    except socket.timeout:
        got += b''
    nums = list(struct.unpack('<%di' % (len(got) // 4), got[:len(got) // 4 * 4]))
    print(f'[persist] {label}: sent count={count} fds={nfds}; reply {len(got)} bytes = {nums}', flush=True)
    s.close()
    return [p[0] for p in pairs], nums

async def main():
    d = tempfile.mkdtemp(prefix='persistprobe'); path = f'{d}/persist.sock'
    per = await clone_persistent(rsyscall.local_process, path)
    pid = per.task.pid.near.id
    print('[persist] pid', pid, 'getpid ->', await per.task.getpid(), 'server_fd', per.task.sysif.server_fd, flush=True)
    await per.prep_for_reconnect()
    await per.reconnect(rsyscall.local_process)
    print('[persist] client reconnect ok; getpid ->', await per.task.getpid(), 'new server_fd', per.task.sysif._conn.server_fd, flush=True)
    await trio.sleep(0.3)
    print('[persist] server fds after client reconnect:', sorted(int(f) for f in os.listdir(f'/proc/{pid}/fd')), flush=True)
    # disconnect; from here on only raw sockets talk to the server
    await per.task.sysif.shutdown_current_connection()
    await trio.sleep(0.3)
    print('[persist] server fds after client SHUT_WR:', sorted(int(f) for f in os.listdir(f'/proc/{pid}/fd')), flush=True)
    (sys_sock, data_sock), nums = raw_reconnect(path, 2, 2, 'well-formed raw, kept')
    sys_sock.settimeout(3)
    sys_sock.sendall(struct.pack('<7q', SYS_getpid, 0, 0, 0, 0, 0, 0))
    print('[persist] getpid over raw reconnection ->', struct.unpack('<q', recv_exact(sys_sock, 8))[0], flush=True)
    print('[persist] server fds now:', sorted(int(f) for f in os.listdir(f'/proc/{pid}/fd')), 'reply named', nums, flush=True)
    sys_sock.shutdown(socket.SHUT_RDWR); sys_sock.close(); data_sock.close()
    await trio.sleep(0.3)
    print('[persist] alive after EOF on raw connection?', os.path.exists(f'/proc/{pid}'), flush=True)
    fds, nums = raw_reconnect(path, 1, 2, 'count<fds')
    await trio.sleep(0.3)
    alive = os.path.exists(f'/proc/{pid}') and 'zombie' not in open(f'/proc/{pid}/status').read()
    print('[persist] alive after count<fds?', alive, flush=True)
    if alive:
        for f in fds: f.close()
        fds, nums = raw_reconnect(path, 3, 2, 'count>fds')
        await trio.sleep(0.3)
        alive = os.path.exists(f'/proc/{pid}') and 'zombie' not in open(f'/proc/{pid}/status').read()
        print('[persist] alive after count>fds?', alive, flush=True)
    if alive:
        (sys_sock, data_sock), nums = raw_reconnect(path, 2, 2, 'well-formed raw for exit')
        sys_sock.sendall(struct.pack('<7q', SYS_exit, 0, 0, 0, 0, 0, 0))
        try:
            print('[persist] read after exit request ->', sys_sock.recv(8), flush=True)
        except Exception as e:
            print('[persist] read after exit request ->', type(e).__name__, flush=True)
    await trio.sleep(0.5)
    print('[persist] socket path still exists after the process is gone?', os.path.exists(path), flush=True)
    try:
        s = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM); s.connect(path); print('[persist] connect after exit: succeeded?!', flush=True)
    except OSError as e:
        print('[persist] connect after exit ->', type(e).__name__, e, flush=True)

trio.run(main)
