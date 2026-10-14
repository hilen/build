#!/usr/bin/env rust

use anyhow::Result;
use shared::{
    config, inspect,
    run::{has, run, run_with_input},
    secrets,
};

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
    let release = inspect::is_release();
    let key = if release {
        secrets::session_key(&config)?
    } else {
        None
    };
    if let Some(key) = &key {
        // Read by the build here, and by the output mask of the far job.
        unsafe {
            std::env::set_var(secrets::SESSION_KEY_ENV, key);
        }
    }
    if has("cargo") {
        match key {
            Some(_) => run(&secrets::masked(&build))?,
            None => run(&build)?,
        }
    } else {
        // No Rust toolchain here. The lib is built on a mac builder and comes
        // back, Xcode on this machine then links it. far does not pass the
        // environment on, a shipped build gets its marks in the job itself.
        match &key {
            Some(key) => run_with_input(&secrets::far_job(&build, Some(key)), key)?,
            None if release => run(&secrets::far_job(&build, None))?,
            None => run(&format!("far --on mac '{build}'"))?,
        }
        run(&format!("far --on mac get {lib}"))?;
    }
    // A test build of demo carries the inspect server on purpose, only a
    // shipped build is checked.
    if inspect::is_release() {
        inspect::refuse(&lib)?;
    }
    Ok(())
}
