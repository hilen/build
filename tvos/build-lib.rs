#!/usr/bin/env rust

use anyhow::Result;
use shared::{
    config, inspect,
    run::{has, run, run_with_input},
    secrets, tvos,
};

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
        // No Rust toolchain here. The libs are built on a mac builder and come
        // back, Xcode on this machine then links them. far does not pass the
        // environment on, a shipped build gets its marks in the job itself.
        match &key {
            Some(key) => run_with_input(&secrets::far_job(&build, Some(key)), key)?,
            None if release => run(&secrets::far_job(&build, None))?,
            None => run(&format!("far --on mac '{build}'"))?,
        }
        for target in [tvos::DEVICE, tvos::SIMULATOR] {
            run(&format!(
                "far --on mac get {}",
                tvos::lib(target, &config.lib_name)
            ))?;
        }
    }
    // A test build of demo carries the inspect server on purpose, only a
    // shipped build is checked.
    if inspect::is_release() {
        inspect::refuse(&tvos::lib(tvos::DEVICE, &config.lib_name))?;
    }
    Ok(())
}
