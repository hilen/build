#!/usr/bin/env bash
# Runs a command that needs docker, on a mac whose docker is Colima.
#
#   vm.sh <cmd> [<arg> ...]
#
# Colima keeps docker in a Linux VM. The VM never hands memory back to the
# mac while it runs: after a build that used 8 GB it still held 10 GB a
# minute later, and 0 after a stop. So the VM runs only while a build needs
# it. This script starts it before the command and stops it after the last
# command that used it, a start takes 10 to 20 seconds and a stop 2.
#
# A machine with no Colima, a Linux runner or a mac with Docker Desktop, runs
# the command as it is.
set -euo pipefail

if ! command -v colima > /dev/null 2>&1; then
    exec "$@"
fi

state="${TMPDIR:-/tmp}/hilen-vm"
mkdir -p "$state/users"

# mkdir either makes the folder or fails, so only one script holds the lock.
# A lock older than 5 minutes is from a script that was killed while it held
# it, a start or a stop never takes that long.
lock() {
    until mkdir "$state/lock" 2> /dev/null; do
        if [ -n "$(find "$state/lock" -maxdepth 0 -mmin +5 2> /dev/null)" ]; then
            rmdir "$state/lock" 2> /dev/null || true
        fi
        sleep 1
    done
}

unlock() {
    rmdir "$state/lock"
}

# The commands that use the VM now, one file per script, named by its pid.
# A file whose script is gone is dropped, a killed job must not keep the VM
# up forever.
users() {
    local file count=0
    for file in "$state/users"/*; do
        [ -e "$file" ] || continue
        if kill -0 "$(basename "$file")" 2> /dev/null; then
            count=$((count + 1))
        else
            rm -f "$file"
        fi
    done
    echo "$count"
}

leave() {
    lock
    rm -f "$state/users/$$"
    if [ "$(users)" = 0 ]; then
        echo "vm.sh: last build is done, stopping the VM"
        colima stop || true
    fi
    unlock
}

lock
touch "$state/users/$$"
trap leave EXIT
if ! colima status > /dev/null 2>&1; then
    echo "vm.sh: starting the VM"
    colima start --cpu "$(sysctl -n hw.ncpu)" --memory "${HILEN_VM_MEMORY:-16}" \
        --vm-type vz --mount-type virtiofs
fi
unlock

"$@"
