# Examples

Each script is self-contained and explains itself in its docstring. Each makes its system calls
through rsyscall process objects, and each cleans up the processes it starts.

| Script | What it shows |
|---|---|
| [`sandbox.py`](sandbox.py) | Run a shell in new user, mount and PID namespaces, with an empty tmpfs root holding only `/usr`, a fresh `/proc` and one of your directories, all set up with syscalls made from the parent before the exec. |
| [`network.py`](network.py) | Clone a process into a new network namespace, bring its loopback up with an ioctl, show that the host's network is unreachable from inside, and run a server and a client over the private loopback. |
| [`socket_activation.py`](socket_activation.py) | Pass a listening socket to a server at fd 3 with `LISTEN_FDS` and `LISTEN_PID`, the way systemd's socket activation does. |
| [`persistent.py`](persistent.py) | Drop the connection to a persistent process, reconnect through its Unix socket, and find the same process with its state intact. |
| [`ssh.py`](ssh.py) | Run syscalls on another machine over ssh: open and read a file there, fork a child there and exec `uname` in it. Without arguments it starts a throwaway local sshd. |

## Running them

They need Linux on x86_64 and rsyscall-ng installed, either from PyPI or as the development
venv of this repository:

```sh
pip install rsyscall-ng        # or: uv add rsyscall-ng
python3 examples/sandbox.py
```

From a checkout, `make examples` runs all of them with the development venv and reports
PASS, SKIP or FAIL for each; `make examples BACKEND=rust` does the same against the Rust
native side.

A script that finds a prerequisite missing prints why and exits with status 77, which
`make examples` reports as SKIP:

- `sandbox.py` and `network.py` need unprivileged user namespaces. On Ubuntu 24.04 AppArmor
  restricts them; see the `kernel.apparmor_restrict_unprivileged_userns` sysctl.
- `ssh.py` without a host argument needs `ssh`, `sshd` and `ssh-keygen` installed, but no
  running ssh server.
