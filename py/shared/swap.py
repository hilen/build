# 1 loader app in the iOS simulator or in the Apple TV simulator that swaps
# between several apps, `make swap`, see docs/hot-reload.md in hilen.
#
# Every app is built as 1 dynamic library, like for `make hot`. The loader
# starts the first one. Nothing swaps by itself, `to` puts the library of
# another app in front of the loader, which stops the app that runs and starts
# the other one in the same process.
#
# Every command returns, so a person and an agent use it the same way. What runs
# is kept in a file between the commands.

import time
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Final, Self

import msgspec

from shared import config
from shared.device import Device, Woke
from shared.hot import Hot, System, is_alive, memory_mb, open_files, sign_library, thread_count
from shared.run import run, run_allow_fail
from shared.util import bail

_EXECUTABLE: Final = "HilenSwap"
_BUNDLE_ID: Final = "hilen.swap"
# The libraries, the pointer file and the state, below the repo root.
_DIR: Final = "target/hot/swap"
# The same for an Apple TV, both simulators can run at the same time.
_TV_DIR: Final = "target/hot/tv/swap"
_STATE: Final = "state.json"
_PROJECT_FILE: Final = "hilen.toml"
# An app that just started still draws its first frames and loads its first
# data, the numbers of the process are read after that.
_SETTLE: Final = 3.0
# The name of the loader app on a phone or a TV.
_DEVICE_EXECUTABLE: Final = "Hilen"


class App(msgspec.Struct, frozen=True):
    # The cargo package, also the name `to` takes.
    name: str
    # The repo of the app, the folder with its `hilen.toml` and `assets`.
    root: str

    # The app whose crate is in `folder`.
    @classmethod
    def find(cls, folder: str) -> Self:
        try:
            path = Path(folder).resolve(strict=True)
        except OSError:
            bail(f"no folder {folder}")
        name = package_name(path)
        root = next((d for d in (path, *path.parents) if (d / _PROJECT_FILE).is_file()), None)
        if root is None:
            bail(f"no {_PROJECT_FILE} in {path} or above it")
        return cls(name, str(root))


# What runs, kept between the commands.
class _State(msgspec.Struct):
    device: str
    pid: int
    # The name of the app on the screen.
    current: str
    apps: tuple[App, ...]


class _Package(msgspec.Struct, frozen=True):
    name: str


class _Workspace(msgspec.Struct, frozen=True):
    default_members: tuple[str, ...] = msgspec.field(name="default-members", default=())


# A workspace root has no package, its app is the first of its default members.
class _Manifest(msgspec.Struct, frozen=True):
    package: _Package | None = None
    workspace: _Workspace | None = None


def _manifest(path: Path) -> _Manifest:
    try:
        text = path.read_text(encoding="utf-8")
    except OSError:
        bail(f"no {path}")
    try:
        return msgspec.toml.decode(text, type=_Manifest)
    except msgspec.MsgspecError as err:
        bail(f"{path} did not parse: {err}")


# The name of the package of the crate in `folder`, or of the first default
# member of the workspace there.
def package_name(folder: Path) -> str:
    path = folder / "Cargo.toml"
    manifest = _manifest(path)
    if manifest.package is not None:
        return manifest.package.name
    members = () if manifest.workspace is None else manifest.workspace.default_members
    if not members:
        bail(f"{path} names no package and no default member")
    member = _manifest(folder / members[0] / "Cargo.toml")
    if member.package is None:
        bail(f"the default member {members[0]} names no package")
    return member.package.name


def _step(message: str):
    print(f"\n[swap] {message}", flush=True)


def _names(apps: Sequence[App]) -> str:
    return ", ".join(app.name for app in apps)


# The app on the screen and what the process holds. A number that grows from swap
# to swap is something an old library did not give back.
def _report(state: _State):
    print()
    print(f"[swap] app      {state.current}")
    print(f"[swap] apps     {_names(state.apps)}")
    if not is_alive(state.pid):
        print(f"[swap] process  {state.pid}, gone")
        return
    print(f"[swap] process  {state.pid}")
    print(f"[swap] threads  {thread_count(state.pid)}")
    print(f"[swap] memory   {memory_mb(state.pid)} MB")
    print(f"[swap] files    {open_files(state.pid)}")


@dataclass(frozen=True, slots=True)
class Swap:
    # The repo the command runs in. The loader is built from its engine.
    here: Path
    loader: Hot
    system: System

    @classmethod
    def new(cls, system: System) -> Self:
        here = Path.cwd()
        folder = _DIR if system is System.IOS else _TV_DIR
        loader = Hot.at(here, _EXECUTABLE, _BUNDLE_ID).for_system(system).with_dir(folder)
        return cls(here, loader, system)

    # Builds every app, starts the loader and the first app in it.
    def start(self, folders: Sequence[str]):
        running = self._load_or_none()
        if running is not None and is_alive(running.pid):
            bail(f"process {running.pid} still runs {running.current}, `stop` it first")
        apps: list[App] = []
        for folder in folders:
            app = App.find(folder)
            if any(other.name == app.name for other in apps):
                bail(f"{app.name} is named 2 times")
            apps.append(app)
        if not apps:
            bail("no app folder given")
        first = apps[0]
        libraries: list[Path] = []
        for app in apps:
            _step(f"building {app.name}")
            libraries.append(self._build(app))

        _step("building the loader")
        loader = self.loader.build_loader()

        _step(f"starting {first.name}")
        name = self.loader.publish(libraries[0], Path(first.root))
        device = self.loader.simulator()
        # A device booted from the command line has no window.
        run(f"open -a Simulator --args -CurrentDeviceUDID {device}")
        pid = self.loader.launch(device, loader)
        state = _State(device, pid, first.name, tuple(apps))
        self._save(state)
        self.loader.wait_for_start(name)
        time.sleep(_SETTLE)
        _report(state)

    # Builds the app `name` again and swaps the running process to it.
    def to(self, name: str):
        state = self._load()
        if not is_alive(state.pid):
            bail(f"process {state.pid} is gone, `start` again")
        app = next((a for a in state.apps if a.name == name), None)
        if app is None:
            bail(f"no app {name}, started with: {_names(state.apps)}")
        _step(f"building {name}")
        library = self._build(app)
        _step(f"swapping from {state.current} to {name}")
        published = self.loader.publish(library, Path(app.root))
        self.loader.wait_for_start(published)
        state.current = name
        self._save(state)
        time.sleep(_SETTLE)
        _report(state)

    def status(self):
        _report(self._load())

    def stop(self):
        state = self._load()
        run_allow_fail(f"xcrun simctl terminate {state.device} {_BUNDLE_ID}")
        self._state_file().unlink()
        _step(f"stopped process {state.pid}")

    # Builds the loader for a real iPhone, iPad or Apple TV with the app of this
    # repo inside, installs it on `device` and starts it. The loader has the
    # bundle id of this repo, see "A real device" in docs/hot-reload.md.
    def device_install(self, device: Device):
        app_config = config.read()
        app = App(app_config.app_name, str(self.here))
        _step(f"building {app.name} for {device.name}")
        library = self._build_for_device(app)
        _step("building the loader")
        loader = (
            Hot.at(self.here, _DEVICE_EXECUTABLE, app_config.bundle_id)
            .for_system(self.system)
            .build_device_loader(library)
        )
        _step(f"installing on {device.name}")
        run(f'xcrun devicectl device install app --device {device.id} "{loader}"')
        run(
            f"xcrun devicectl device process launch --device {device.id} --terminate-existing "
            f"{app_config.bundle_id}"
        )

    # Builds the app in `folder`, with none the app of this repo, and swaps the
    # loader on `device` to it. A loader that does not answer is started first.
    def device_to(self, folder: str | None, device: Device):
        app_config = config.read()
        app = App(app_config.app_name, str(self.here)) if folder is None else App.find(folder)
        _step(f"building {app.name} for {device.name}")
        library = self._build_for_device(app)
        sign_library(library)
        if device.wake(app_config.bundle_id) is Woke.PLAIN:
            _step(f"the app in front on {device.name} is no hot build, installing the loader again")
            self.device_install(device)
            if device.wait() is Woke.PLAIN:
                bail(f"the new loader on {device.name} is no hot build either")
        _step(f"sending {app.name} to {device.name}")
        assets = Path(app.root) / "assets"
        assets_flag = f' --assets "{assets}"' if assets.is_dir() else ""
        run(device.inspect(f'hot-send "{library}" {app.name}{assets_flag}'))
        _step(f"{device.name} runs {app.name}, the inspector reaches it with:")
        print(device.inspect("tree"))

    def device_status(self, device: Device):
        run(device.inspect("hot-status"))

    # Run from the engine repo, an app of another repo gets the engine of this
    # folder, so both sides of a swap carry the same engine.
    def _with_engine(self, hot: Hot, app: App) -> Hot:
        engine_here = (self.here / "hilen/Cargo.toml").is_file()
        return hot.with_engine(self.here) if engine_here and Path(app.root) != self.here else hot

    def _build_for_device(self, app: App) -> Path:
        hot = Hot.at(Path(app.root), _EXECUTABLE, _BUNDLE_ID).for_system(self.system).for_device()
        return self._with_engine(hot, app).build_library(app.name, "")

    def _build(self, app: App) -> Path:
        hot = Hot.at(Path(app.root), _EXECUTABLE, _BUNDLE_ID).for_system(self.system)
        return self._with_engine(hot, app).build_library(app.name, "")

    def _state_file(self) -> Path:
        return self.loader.dir / _STATE

    def _load_or_none(self) -> _State | None:
        try:
            return msgspec.json.decode(self._state_file().read_bytes(), type=_State)
        except OSError, msgspec.MsgspecError:
            return None

    def _load(self) -> _State:
        try:
            text = self._state_file().read_bytes()
        except OSError:
            bail("nothing runs, `start` first")
        return msgspec.json.decode(text, type=_State)

    def _save(self, state: _State):
        self.loader.dir.mkdir(parents=True, exist_ok=True)
        self._state_file().write_bytes(msgspec.json.format(msgspec.json.encode(state), indent=2))
