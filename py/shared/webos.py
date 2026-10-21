# What the LG webOS build needs. The package comes from project_name in
# hilen.toml, its folder and version from cargo metadata, the rest from the
# `[webos]` table of hilen.toml, every key of it optional:
#
#   url               where the TV loads the app from
#   title             the name on the TV, project_name when left out
#   icon              a square png, assets/icon.png when left out
#   features          cargo features of the build, webgl when left out
#   default_features  false leaves the default features out
#   packaged          true packs the whole dist, url is then not used

import re
from dataclasses import dataclass
from pathlib import Path
from typing import Final

import msgspec

from shared import cargo, config, toml
from shared.util import bail, group


@dataclass(frozen=True, slots=True)
class Webos:
    # cargo package name
    name: str
    # the folder of the app crate, where trunk runs and `dist` lands
    crate_dir: str
    version: str
    # the webOS app id, the bundle id in lower case
    id: str
    title: str
    # The address the packaged app loads. Without it only the dist is built.
    url: str | None
    icon: str
    features: str
    default_features: bool
    # The .ipk holds the whole dist and loads nothing from a server to start.
    packaged: bool


class _Table(msgspec.Struct, frozen=True):
    url: str | None = None
    title: str | None = None
    icon: str = "assets/icon.png"
    features: str = "webgl"
    default_features: bool = True
    packaged: bool = False


class _Toml(msgspec.Struct, frozen=True):
    webos: _Table = msgspec.field(default_factory=_Table)


# Read from the repo root, before any chdir.
def read() -> Webos:
    app = config.read()
    table = toml.decode(toml.read_text(), _Toml, "[webos] table").webos
    package = cargo.find(cargo.packages(), app.app_name)
    if package is None:
        bail(f"no cargo package named {app.app_name}, the project_name of hilen.toml")
    return Webos(
        name=package.name,
        crate_dir=str(Path(package.manifest_path).parent),
        version=package.version,
        id=app.bundle_id.lower(),
        title=table.title or app.project_name,
        url=None if table.url is None else table.url.rstrip("/"),
        icon=table.icon,
        features=table.features,
        default_features=table.default_features,
        packaged=table.packaged,
    )


# -- the page for Chromium 79 --------------------------------------------------

_HOSTED_START: Final = re.compile(r"(?s)const wasm = await init\((.*?)\);(.*?)</script>")
_PACKAGED_START: Final = re.compile(
    r"(?s)<script type=.module.>\s*import init, \* as bindings from '\./([^']+\.js)';\s*"
    r"const wasm = await init\(\{ module_or_path: '\./([^']+\.wasm)' \}\);.*?</script>"
)
_PRELOAD: Final = re.compile(r'<link rel="(modulepreload|preload)" [^>]*>\n?')
_BMP_HEADER: Final = 54
_DEPTHS: Final = (24, 32)
_OPAQUE_DEPTH: Final = 24


# The start script trunk writes uses a top level `await`, which came in Chrome 89.
# Chromium 79 stops with `Unexpected reserved word`. The same script with `then`
# runs everywhere.
def without_top_level_await(page: str) -> str:
    if _HOSTED_START.search(page) is None:
        bail(
            "the page has no trunk start script with `const wasm = await init(...)`, trunk "
            "changed its template"
        )
    return _HOSTED_START.sub(
        lambda m: f"init({m[1]}).then(function (wasm) {{{m[2]}}});\n</script>", page, count=1
    )


# The 2 files the trunk start script of a packaged app loads, the js and the wasm.
def packaged_files(page: str) -> tuple[str, str]:
    found = _PACKAGED_START.search(page)
    if found is None:
        bail(
            "the page has no trunk start script that imports init and bindings, trunk changed "
            "its template"
        )
    return group(found, 1), group(found, 2)


# The page of a packaged app loads the classic script and reads the wasm by XHR.
# A file:// page on the TV can neither import a module nor fetch, and the preload
# links would fetch too.
def classic_start_script(page: str, js: str, wasm: str) -> str:
    start = f"""<script src="./{js}"></script>
<script>
(function () {{
    var request = new XMLHttpRequest();
    request.open("GET", "./{wasm}");
    request.responseType = "arraybuffer";
    request.onloadend = function () {{
        if (!request.response) {{
            console.error("Failed to read ./{wasm}");
            return;
        }}
        wasm_bindgen({{ module_or_path: request.response }}).then(function (wasm) {{
            window.wasmBindings = wasm_bindgen;
            dispatchEvent(new CustomEvent("TrunkApplicationStarted", \
{{ detail: {{ wasm: wasm }} }}));
        }});
    }};
    request.send();
}})();
</script>"""
    return _PRELOAD.sub("", _PACKAGED_START.sub(lambda _: start, page, count=1))


# The page inside the package. It only sends the TV on to the served app, so the
# app on the TV is always the one the server has.
def launcher_page(title: str, url: str) -> str:
    address = msgspec.json.encode(url).decode()
    return f"""<!doctype html>
<html>
<head>
<meta charset="utf-8">
<title>{title}</title>
<style>body {{ margin: 0; background: #000; }}</style>
</head>
<body>
<script>window.location.replace({address});</script>
</body>
</html>
"""


# The top left pixel of a 24 or 32 bit BMP as red, green and blue, None when it
# is transparent. A BMP keeps its rows from the bottom up unless its height is
# negative.
def bmp_top_left(data: bytes) -> tuple[int, int, int] | None:
    if len(data) <= _BMP_HEADER or data[:2] != b"BM":
        bail("not a BMP")
    start = int.from_bytes(data[10:14], "little")
    width = int.from_bytes(data[18:22], "little")
    height = int.from_bytes(data[22:26], "little", signed=True)
    depth = int.from_bytes(data[28:30], "little")
    if depth not in _DEPTHS:
        bail(f"a BMP of {depth} bits")
    row = -(-(width * depth // 8) // 4) * 4
    at = start + (0 if height < 0 else (height - 1) * row)
    alpha = 255 if depth == _OPAQUE_DEPTH else data[at + 3]
    if alpha == 0:
        return None
    return data[at + 2], data[at + 1], data[at]
