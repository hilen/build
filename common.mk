
ios:
	uv run -q --no-dev ./build/ios/build-project.py

ios-lib:
	uv run -q --no-dev ./build/ios/build-lib.py

# An Apple TV. `tvos` builds the libs for the device and the simulator, makes
# the Xcode project and builds it for the simulator. See hilen docs/tvos.md.
tvos:
	uv run -q --no-dev ./build/tvos/build-project.py

tvos-lib:
	uv run -q --no-dev ./build/tvos/build-lib.py

# Hot reload in the iOS simulator of this Mac: a saved file shows in the
# running app with no install and no restart. `make hot args="tv"` does it in
# the Apple TV simulator. See hilen docs/hot-reload.md.
hot:
	uv run -q --no-dev ./build/ios/hot.py $(args)

# The app of this folder on a paired iPhone, iPad or Apple TV, as a hot build
# with no install: `make device`. args=tv picks the device by a part of its
# name or kind, args=install puts the loader on it once, args=status asks it.
# See hilen docs/hot-reload.md.
device:
	uv run -q --no-dev ./build/ios/device.py $(args)

# 1 loader in the iOS simulator that swaps between several apps, on a command:
# make swap args="start demo ../apps/skaityk", then args="to skaityk",
# args="status" and args="stop". With `tv` as the first word it is the Apple
# TV simulator, args="tv start demo ../apps/flixen". See hilen docs/hot-reload.md.
swap:
	uv run -q --no-dev ./build/ios/swap.py $(args)

android:
	uv run -q --no-dev ./build/build.py android

android-emu:
	HILEN_ANDROID_ABI=arm64 uv run -q --no-dev ./build/build.py android

# An LG webOS TV. `webos-dist` builds the wasm dist an old TV browser can
# load, `webos` also packs the hosted app, an .ipk that loads the dist from
# the `url` of the [webos] table of hilen.toml. See hilen docs/webos.md.
webos:
	uv run -q --no-dev ./build/web/webos.py

# The same package with the inspector of hilen, for `hilen-inspect
# web-bridge`. Never ships.
webos-dev:
	uv run -q --no-dev ./build/web/webos.py --dev

webos-dist:
	uv run -q --no-dev ./build/web/webos.py --dist

test:
	cargo test --all
	echo debug test: OK
	cargo test --all --release
	echo release test: OK

# Uploads the iOS build to TestFlight, and the tvOS build after it when
# hilen.toml has `tvos = true`.
fly:
	uv run -q --no-dev ./build/ios/flight.py

profile:
	uv run -q --no-dev ./build/scripts/profile.py

pr:
	gh pr create --fill

fmt:
	cargo +nightly fmt --all

fmt-check:
	cargo +nightly fmt --all -- --check

updates:
	cargo install cargo-upgrades --locked
	cargo upgrades

# Install the system build deps and Rust on Linux and WSL. Idempotent.
setup:
	sh build/setup.sh

# Desktop release. `make patch` or `make minor` tags and pushes, CI builds
# from the tag with the release-* targets, one platform per runner. Every
# script reads Cargo.toml and the [release] table of hilen.toml.
patch:
	uv run -q --no-dev ./build/release/tag.py patch

minor:
	uv run -q --no-dev ./build/release/tag.py minor

release-mac:
	uv run -q --no-dev ./build/release/mac.py

release-win:
	uv run -q --no-dev ./build/release/win.py

release-linux:
	uv run -q --no-dev ./build/release/linux.py

manifest:
	uv run -q --no-dev ./build/release/manifest.py
