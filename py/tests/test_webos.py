import pytest
from shared.util import ScriptError
from shared.webos import (
    bmp_top_left,
    classic_start_script,
    launcher_page,
    packaged_files,
    without_top_level_await,
)

_HOSTED = """<script type="module">
import init, * as bindings from '/app.js';
const wasm = await init({ module_or_path: '/app_bg.wasm' });
window.wasmBindings = bindings;
</script>"""

_PACKAGED = """<link rel="modulepreload" href="./app.js">
<script type="module">
import init, * as bindings from './app-1a2b.js';
const wasm = await init({ module_or_path: './app-1a2b_bg.wasm' });
window.wasmBindings = bindings;
</script>"""


def test_the_hosted_start_script_loses_its_top_level_await():
    fixed = without_top_level_await(_HOSTED)
    assert "await init(" not in fixed
    assert "init({ module_or_path: '/app_bg.wasm' }).then(function (wasm) {" in fixed
    assert fixed.rstrip().endswith("});\n</script>")


def test_a_changed_trunk_template_is_an_error():
    with pytest.raises(ScriptError):
        without_top_level_await("<script>start()</script>")
    with pytest.raises(ScriptError):
        packaged_files("<script>start()</script>")


def test_the_packaged_page_loads_a_classic_script():
    js, wasm = packaged_files(_PACKAGED)
    assert (js, wasm) == ("app-1a2b.js", "app-1a2b_bg.wasm")
    fixed = classic_start_script(_PACKAGED, js, wasm)
    assert '<script src="./app-1a2b.js"></script>' in fixed
    assert 'request.open("GET", "./app-1a2b_bg.wasm");' in fixed
    assert "modulepreload" not in fixed
    assert "await" not in fixed


def test_the_launcher_page_quotes_the_address():
    assert 'window.location.replace("https://tv.example.com/?a=\\"b\\"");' in launcher_page(
        "App", 'https://tv.example.com/?a="b"'
    )


def _bmp(depth: int, height: int, pixel: bytes) -> bytes:
    header = bytearray(54)
    header[:2] = b"BM"
    header[10:14] = (54).to_bytes(4, "little")
    header[18:22] = (1).to_bytes(4, "little")
    header[22:26] = height.to_bytes(4, "little", signed=True)
    header[28:30] = depth.to_bytes(2, "little")
    return bytes(header) + pixel + bytes(4 - len(pixel) % 4 if len(pixel) % 4 else 0)


def test_the_top_left_pixel_of_a_bmp():
    assert bmp_top_left(_bmp(24, 1, bytes([30, 20, 10]))) == (10, 20, 30)
    assert bmp_top_left(_bmp(32, -1, bytes([30, 20, 10, 255]))) == (10, 20, 30)
    assert bmp_top_left(_bmp(32, 1, bytes([30, 20, 10, 0]))) is None
    with pytest.raises(ScriptError):
        bmp_top_left(b"PNG" + bytes(60))
