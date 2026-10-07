#!/usr/bin/env rust

use anyhow::Result;
use shared::{config, inspect};
use shared::run::{has, run};

fn main() -> Result<()> {
    let config = config::read()?;

    // A host CFLAGS leaks into the iOS cross build and breaks the C parts.
    unsafe {
        std::env::remove_var("CFLAGS");
        std::env::remove_var("CXXFLAGS");
    }

    let lib = format!("target/universal/release/{}", config.lib_name);
    let build = format!(
        "rustup target add aarch64-apple-ios x86_64-apple-ios && cargo install cargo-lipo && cargo lipo -p {} --release",
        config.app_name
    );
    if has("cargo") {
        run(&build)?;
    } else {
        // No Rust toolchain here. The lib is built on a mac builder and comes
        // back, Xcode on this machine then links it.
        run(&format!("far --on mac '{build}'"))?;
        run(&format!("far --on mac get {lib}"))?;
    }
    // A test build of demo carries the inspect server on purpose, only a
    // shipped build is checked.
    if inspect::is_release() {
        inspect::refuse(&lib)?;
    }
    Ok(())
}
