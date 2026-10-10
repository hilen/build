#!/usr/bin/env rust

// The load test on a real device, `make load-test` for the paired iPhone and
// `make load-test args="tv"` for the paired Apple TV. See "What iOS allows"
// in docs/hot-reload.md in hilen. Run from the hilen repo.
//
// Builds a tiny app with the bundle id of this repo as a development build,
// installs it and starts it. The app copies 1 library with 3 kinds of
// signature into its data folder, loads each and prints what the system
// said. A hot swap on a device needs the last of the 3 to load.

use std::env::args;

use anyhow::Result;
use shared::{
    config,
    hot::{System, development_profile, paired, sign_identity},
    run::run,
};

const NATIVE: &str = "hilen/native/ios";
const EXECUTABLE: &str = "LoadTest";

fn step(message: &str) {
    println!("\n[load-test] {message}");
}

fn main() -> Result<()> {
    let mut args: Vec<String> = args().skip(1).collect();
    let system = System::take(&mut args);
    let config = config::read()?;
    let bundle_id = &config.bundle_id;

    let (folder, sdk, target, plist) = match system {
        System::Ios => ("target/hot/load-test", "iphoneos", "arm64-apple-ios14.0", "hot_loader.plist"),
        System::Tvos => ("target/hot/tv/load-test", "appletvos", "arm64-apple-tvos15.0", "hot_loader_tvos.plist"),
    };
    let app = format!("{folder}/{EXECUTABLE}.app");
    let profile = development_profile(bundle_id, system)?;
    let profile = profile.display();
    let identity = sign_identity()?;
    let clang = format!("xcrun -sdk {sdk} clang -target {target}");

    step("building the app and the 3 libraries");
    run(&format!("rm -rf {folder} && mkdir -p {app}/libs"))?;
    run(&format!("{clang} -dynamiclib {NATIVE}/load_test_lib.c -o {folder}/lib.dylib"))?;
    // The linker signs an arm64 library ad hoc by itself.
    run(&format!("cp {folder}/lib.dylib {app}/libs/none.bin && codesign --remove-signature {app}/libs/none.bin"))?;
    run(&format!("cp {folder}/lib.dylib {app}/libs/adhoc.bin && codesign -s - --force {app}/libs/adhoc.bin"))?;
    run(&format!(
        "cp {folder}/lib.dylib {app}/libs/development.bin && codesign -s {identity} --force {app}/libs/development.bin"
    ))?;
    run(&format!(
        "sed -e s/HILEN_EXECUTABLE/{EXECUTABLE}/g -e s/HILEN_BUNDLE_ID/{bundle_id}/g {NATIVE}/{plist} > {app}/Info.plist"
    ))?;
    run(&format!(
        "{clang} -fobjc-arc -Wall {NATIVE}/load_test.m -framework UIKit -framework Foundation -o {app}/{EXECUTABLE}"
    ))?;
    run(&format!("cp \"{profile}\" {app}/embedded.mobileprovision"))?;
    run(&format!(
        "security cms -D -i \"{profile}\" | plutil -extract Entitlements xml1 -o {folder}/entitlements.plist -"
    ))?;
    run(&format!("codesign -s {identity} --force --entitlements {folder}/entitlements.plist {app}"))?;

    step("installing and starting it");
    let device = paired(system)?;
    run(&format!("xcrun devicectl device install app --device {device} {app}"))?;
    run(&format!("xcrun devicectl device process launch --device {device} --console --terminate-existing {bundle_id}"))
}
