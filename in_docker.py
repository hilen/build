#!/usr/bin/env -S uv run -q --no-dev

# Runs the CI build of the app in a fresh docker container of 1 linux distro.

import os
import subprocess
import sys
from pathlib import Path
from typing import Final

from shared.util import bail, run_main

# Pinned so a container build is reproducible. Bump it on purpose, together with
# the uv of build/android/Dockerfile.
_UV_VERSION: Final = "0.13.1"


# A fresh container has no uv, so the command installs it first. uv then brings
# the Python the scripts need.
def bootstrap(build_command: str) -> str:
    return f"""
set -eo pipefail
cd /host
if command -v apt > /dev/null; then
    export DEBIAN_FRONTEND=noninteractive
    apt update
    apt install -y curl tar sudo git
elif command -v pacman > /dev/null; then
    pacman -Sy curl tar sudo git --noconfirm
elif command -v dnf > /dev/null; then
    dnf install -y tar sudo git
    if ! command -v curl > /dev/null; then
        dnf install -y curl
    fi
elif command -v yum > /dev/null; then
    yum install -y curl tar sudo git
elif command -v zypper > /dev/null; then
    zypper install -y curl tar sudo git
fi
git config --global --add safe.directory '*'
curl -LsSf https://astral.sh/uv/{_UV_VERSION}/install.sh | env UV_INSTALL_DIR=/usr/local/bin sh
{build_command}
"""


def main() -> int:
    given = sys.argv[1:]
    if not given:
        print("Usage: in_docker.py <image>")
        return 1
    image = given[0]
    host_dir = os.environ.get("HOST_DIR") or str(Path.cwd())
    print(f"Running in docker: {image}", flush=True)
    args = [
        "docker",
        "run",
        "--rm",
        "--mount",
        f"type=bind,source={host_dir},target=/host",
        "--cap-add=SYS_PTRACE",
        "--security-opt",
        "seccomp=unconfined",
        "-e",
        "SKIP_UI_TESTS",
        "-t",
        image,
        "/bin/bash",
        "-c",
        bootstrap("uv run -q --no-dev ./build/build.py"),
    ]
    if subprocess.run(args, check=False).returncode != 0:
        bail(f"docker run {image} failed")
    return 0


if __name__ == "__main__":
    run_main(main)
