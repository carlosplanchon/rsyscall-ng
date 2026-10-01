#!/usr/bin/env bash
# Prepare a GitHub-hosted Ubuntu 24.04 runner for the oracle build and the test-suite; used by
# .github/workflows/ci.yml. Needs passwordless sudo, as on the hosted runners.
set -euo pipefail
export DEBIAN_FRONTEND=noninteractive
sudo apt-get update -qq
# autotools and pkg-config build the upstream C oracle; the OpenSSH server is for test_ssh and
# test_persistent, which run `sshd -i` as a ProxyCommand (no listening daemon is involved); socat
# is for test_net.
sudo apt-get install -y -qq --no-install-recommends autoconf automake libtool pkg-config openssh-server socat > /dev/null
# Ubuntu 24.04 lets AppArmor restrict unprivileged user namespaces, which the test-suite creates
# (clone with CLONE_NEWUSER); lift the restriction where the knob exists, then check.
if [ -e /proc/sys/kernel/apparmor_restrict_unprivileged_userns ]; then
    sudo sysctl -w kernel.apparmor_restrict_unprivileged_userns=0
fi
if ! unshare --user --map-root-user true; then
    echo "::error::unprivileged user namespaces are not available on this runner"
    exit 1
fi
echo "unprivileged user namespaces: available"
echo "kernel $(uname -r); $(gcc --version | head -n 1); $(python3 --version)"
for dev in /dev/fuse /dev/net/tun; do ls -l "$dev" 2> /dev/null || echo "$dev: absent"; done
echo "sshd: $(command -v sshd || echo /usr/sbin/sshd)"
