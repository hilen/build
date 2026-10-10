#!/usr/bin/env rust

use anyhow::Result;
use shared::run::{has, run};
use shared::{config, inspect, tvos};

fn main() -> Result<()> {
    let config = config::read()?;

    // A host CFLAGS leaks into the tvOS cross build and breaks the C parts.
    unsafe {
        std::env::remove_var("CFLAGS");
        std::env::remove_var("CXXFLAGS");
    }

    // tvOS is a tier 3 target with no prebuilt std, so std is built too. There
    // is no universal lib, the device and the simulator are both arm64 and the
    // project picks the lib by its sdk.
    let build = format!(
        "TVOS_DEPLOYMENT_TARGET={} cargo build -p {} --lib --release --target {} --target {} -Z build-std=std,panic_abort",
        config.tvos_minimum_version,
        config.app_name,
        tvos::DEVICE,
        tvos::SIMULATOR
    );
    if has("cargo") {
        run(&build)?;
    } else {
        // No Rust toolchain here. The libs are built on a mac builder and come
        // back, Xcode on this machine then links them.
        run(&format!("far --on mac '{build}'"))?;
        for target in [tvos::DEVICE, tvos::SIMULATOR] {
            run(&format!("far --on mac get {}", tvos::lib(target, &config.lib_name)))?;
        }
    }
    // A test build of demo carries the inspect server on purpose, only a
    // shipped build is checked.
    if inspect::is_release() {
        inspect::refuse(&tvos::lib(tvos::DEVICE, &config.lib_name))?;
    }
    Ok(())
}
