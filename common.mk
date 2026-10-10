
ios:
	rust ./build/ios/build-project.rs

ios-lib:
	rust ./build/ios/build-lib.rs

# An Apple TV. `tvos` builds the libs for the device and the simulator, makes
# the Xcode project and builds it for the simulator. See hilen docs/tvos.md.
tvos:
	rust ./build/tvos/build-project.rs

tvos-lib:
	rust ./build/tvos/build-lib.rs

# Hot reload in the iOS simulator of this Mac: a saved file shows in the
# running app with no install and no restart. `make hot args="tv"` does it in
# the Apple TV simulator. See hilen docs/hot-reload.md.
hot:
	rust ./build/ios/hot.rs $(args)

# 1 loader in the iOS simulator that swaps between several apps, on a command:
# make swap args="start demo ../apps/skaityk", then args="to skaityk",
# args="status" and args="stop". With `tv` as the first word it is the Apple
# TV simulator, args="tv start demo ../apps/flixen". See hilen docs/hot-reload.md.
swap:
	rust ./build/ios/swap.rs $(args)

android:
	rust ./build/build.rs android

android-emu:
	HILEN_ANDROID_ABI=arm64 rust ./build/build.rs android

# An LG webOS TV. `webos-dist` builds the wasm dist an old TV browser can
# load, `webos` also packs the hosted app, an .ipk that loads the dist from
# the `url` of the [webos] table of hilen.toml. See hilen docs/webos.md.
webos:
	rust ./build/web/webos.rs

webos-dist:
	rust ./build/web/webos.rs --dist

test:
	cargo test --all
	echo debug test: OK
	cargo test --all --release
	echo release test: OK

# Uploads the iOS build to TestFlight, and the tvOS build after it when
# hilen.toml has `tvos = true`.
fly:
	rust ./build/ios/flight.rs

profile:
	rust ./build/scripts/profile.rs

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
	rust ./build/release/tag.rs patch

minor:
	rust ./build/release/tag.rs minor

release-mac:
	rust ./build/release/mac.rs

release-win:
	rust ./build/release/win.rs

release-linux:
	rust ./build/release/linux.rs

manifest:
	rust ./build/release/manifest.rs
