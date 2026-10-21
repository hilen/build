# Shared by release/linux.py and release/win.py. Builds the tool image and runs 1
# shell string inside it with the repo mounted, plus named volumes for the cargo
# caches so a second run does not start from zero. On a dev box the engine
# checkout next to the apps folder is mounted too, so a path dependency on it
# resolves inside the container the same way it does outside.

from dataclasses import dataclass
from pathlib import Path

from shared.run import capture, run


# 1 build lane: the app, the tool image, its platform, the name of the lane and
# the folder under target/ that the script writes for the host to read back.
@dataclass(frozen=True, slots=True)
class Lane:
    app: str
    image: str
    platform: str
    name: str
    stage: str


def build_image(name: str, dockerfile: str, platform: str):
    run(f"docker build --platform {platform} -f build/release/{dockerfile} -t {name} build/release")


# The download caches are shared by every app on the box, the target volume
# carries the app name so 2 apps never build into 1 folder.
def run_in(lane: Lane, script: str):
    app, image, platform, stage = lane.app, lane.image, lane.platform, lane.stage
    name = lane.name
    cwd = Path.cwd()
    engine = Path("../../hilen")
    engine_mount = f"-v {engine.resolve()}:/work/hilen" if engine.is_dir() else ""
    arch = platform.replace("/", "-")
    # The app embeds its Sentry DSN with option_env! at compile time, and the
    # compiler runs in the container. Only the name goes on the command line,
    # docker copies the value from the host env, so no log shows it. Unset on the
    # host means unset in the container.
    sentry = f"{app.upper().replace('-', '_')}_SENTRY_URL"
    # The engine build script masks HILEN_SESSION_KEY into an app with the
    # `login` feature, passed by name for the same reason as the DSN.
    # HILEN_RELEASE=1 makes it refuse the development key and the `inspect`
    # feature. It is set here, not taken from the host, so this lane is always a
    # release.
    # The container runs as root. On a Linux host the staged files would stay
    # root owned, and the next run or the runner cleanup could not touch them.
    uid = capture("id -u")
    gid = capture("id -g")
    run(
        f"docker run --rm --platform {platform} \\\n"
        f'  -v "{cwd}:/work/apps/app" \\\n'
        f"  {engine_mount} \\\n"
        f"  -v {app}-{name}-{arch}-target:/work/apps/app/target/{name} \\\n"
        f"  -v {name}-{arch}-cargo-registry:/usr/local/cargo/registry \\\n"
        f"  -v {name}-{arch}-cargo-git:/usr/local/cargo/git \\\n"
        f"  -v {name}-{arch}-rustup:/usr/local/rustup \\\n"
        f"  -e CARGO_TARGET_DIR=/work/apps/app/target/{name} \\\n"
        f"  -e {sentry} \\\n"
        "  -e HILEN_SESSION_KEY \\\n"
        "  -e HILEN_RELEASE=1 \\\n"
        f'  {image} bash -c \'trap "chown -R {uid}:{gid} /work/apps/app/target/{stage}" EXIT; '
        f"{script}'"
    )
