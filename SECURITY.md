# Security Policy

rsyscall-ng lets a program run arbitrary system calls in other processes, locally and over ssh,
and ships native code: a shared library and three static helper executables. Security reports are
taken seriously, within the limits of a community project. Thank you for reporting responsibly.

## Reporting a vulnerability

Please do **not** open a public issue or pull request for a security problem.

Report it privately through GitHub's private vulnerability reporting:

- Go to <https://github.com/carlosplanchon/rsyscall-ng/security/advisories/new>, or the
  repository's **Security** tab, then **Report a vulnerability**.
- If that is not possible, email **carlosplanchon@cognitialabs.com** with `[SECURITY]` in the
  subject.

Include what you can: a description, steps to reproduce, a proof of concept, the affected version
and your assessment of the impact. Reports in Spanish or English are equally welcome.

## What counts

By design, whoever holds a connection to an rsyscall syscall server can make the process at the
other end run any system call. The protection is that these connections stay private: they are
socketpairs, Unix sockets and ssh sessions that only the process which set them up should be able
to reach. Especially relevant areas, in rough order of severity:

- **Reaching someone else's connection**: any way for another user to get at a syscall
  connection, or at a socket, file or temporary directory involved in setting one up, and any
  way to make a helper executable accept a connection it should not.
- **Memory safety of the native side**: `librsyscall.so` and the helpers `rsyscall-bootstrap`,
  `rsyscall-stdin-bootstrap` and `rsyscall-unix-stub`, for example in how they handle the messages
  and file descriptors they receive.
- **Privilege escalation through `rsyscall-stdin-bootstrap`**, which is meant to be started under
  sudo or a similar tool.
- **Release integrity**: anything affecting the supply chain of the `rsyscall-ng` package on
  PyPI, which is published through trusted publishing with attestations.

Out of scope:

- What the API does by design for a process that legitimately holds a connection: it can do
  anything the process at the other end can do.
- Issues that require an already-compromised machine or account.
- The upstream C implementation of [catern/rsyscall](https://github.com/catern/rsyscall), which
  this project does not ship: report it there.
- Bugs in Linux, OpenSSH, CPython or trio: report them to those projects.

## What to expect

This is a community project with a single maintainer, so the process is honest rather than
corporate:

- Acknowledgment within **7 days**.
- An assessment and, when confirmed, a fix released as soon as practical, coordinated with you.
- Public disclosure through a GitHub security advisory once a fix is available, with credit to
  the reporter unless you prefer otherwise.

Only the **latest release on PyPI** receives security fixes.
