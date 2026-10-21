# `make device` in an app repo: sends the app to a paired device, or with the
# command `install`, `status` or `release` works on the loader there.

import os
from pathlib import Path
from typing import Final

from shared import device_lock
from shared.device import Device
from shared.swap import Swap
from shared.util import bail

# The device the last `make device` of an app went to, below its root. Not
# `target/hot/device`, that is the folder of the loader build.
_KEPT: Final = "target/hot/picked-device"
# Names the engine repo when it is not found above the app.
_ENGINE_ENV: Final = "HILEN_REPO"
_ENGINE_CRATE: Final = "hilen/Cargo.toml"


# The engine repo on disk: the one `HILEN_REPO` names, the app itself, or a
# folder `hilen` next to a folder above the app, like `~/dev/hilen` for
# `~/dev/apps/game`.
def engine_repo(app: Path) -> Path:
    named = os.environ.get(_ENGINE_ENV)
    if named is not None:
        if (Path(named) / _ENGINE_CRATE).is_file():
            return Path(named)
        bail(f"{_ENGINE_ENV} names {named}, which has no {_ENGINE_CRATE}")
    if (app / _ENGINE_CRATE).is_file():
        return app
    found = next(
        (d / "hilen" for d in app.parents if (d / "hilen" / _ENGINE_CRATE).is_file()), None
    )
    if found is None:
        bail(f"no hilen repo found above {app}, name it with {_ENGINE_ENV}")
    return found


# `word` picks the device. With none it is the device of the last call, or the
# only paired one.
def make_device(app: Path, word: str | None, command: str | None):
    engine = engine_repo(app)
    kept = app / _KEPT
    named = word is not None
    if word is None:
        try:
            word = kept.read_text(encoding="utf-8").strip()
        except OSError:
            word = None

    # A release needs no device, the phone may be locked or away. The kept word
    # is the id the lock was taken for, a named word goes through the lookup.
    if command == "release" and not named and word is not None:
        device_lock.release(word)
        return

    # The loader is built from the engine repo, and so is the inspect tool.
    os.chdir(engine)
    device = Device.pick(engine, word)
    print(f"\n[device] {device.name}, {device.os}, {device.id}")
    kept.parent.mkdir(parents=True, exist_ok=True)
    kept.write_text(device.id, encoding="utf-8")

    if command == "release":
        device_lock.release(device.id)
        return
    if command != "status":
        device_lock.take(device.id, str(app))

    swap = Swap.new(device.system)
    match command:
        case "install":
            swap.device_install(device)
        case "status":
            swap.device_status(device)
        case _:
            swap.device_to(None if app == engine else str(app), device)
