from shared.release import Release

from shared import manifest

_RELEASE = Release(
    name="kukareker",
    bin="kukareker",
    version="0.2.0",
    bundle_id="vladas.kukareker",
    download_url="https://get.vladas.xyz/kukareker",
    host_deployment="get",
    target_subdir="kukareker",
    mac_targets=("aarch64-apple-darwin", "x86_64-apple-darwin"),
    self_update=True,
    daemons=(),
    link_scheme=None,
    camera_usage=None,
    bluetooth_usage=None,
    speech_usage=None,
)

_META = '{"size": 12, "sha256": "ab", "sig": "cd"}'


def _has(present: set[str]) -> manifest.Has:
    def has(suffix: str) -> str | None:
        name = _RELEASE.artifact(suffix)
        return name if name in present else None

    return has


def test_the_site_manifest_lists_what_is_there():
    has = _has({"kukareker-0.2.0-mac-universal.dmg", "kukareker-0.2.0-linux-x64.deb"})
    assert (
        manifest.site(_RELEASE, has)
        == """{
  "version": "0.2.0",
  "mac": "kukareker-0.2.0-mac-universal.dmg",
  "win": {},
  "linux": {
    "x64": {
      "deb": "kukareker-0.2.0-linux-x64.deb"
    },
    "arm64": {}
  }
}"""
    )


def test_the_updater_manifest_gives_both_mac_keys_to_the_universal_binary():
    has = _has({"kukareker-0.2.0-macos-universal"})
    entries = [*manifest.bare_entries(_RELEASE), *manifest.APPIMAGES]
    text = manifest.updater(_RELEASE, "0.2.0", entries, has, lambda _: _META)
    url = "https://get.vladas.xyz/kukareker/kukareker-0.2.0-macos-universal"
    platform = (
        f'{{\n      "url": "{url}",\n      "size": 12,\n'
        '      "sha256": "ab",\n      "sig": "cd"\n    }'
    )
    assert text == (
        '{\n  "version": "0.2.0",\n  "notes": "",\n  "platforms": {\n'
        f'    "macos-aarch64": {platform},\n    "macos-x86_64": {platform}\n  }}\n}}'
    )


def test_no_signed_artifact_no_updater_manifest():
    assert (
        manifest.updater(
            _RELEASE, "0.2.0", manifest.bare_entries(_RELEASE), _has(set()), lambda _: None
        )
        is None
    )
