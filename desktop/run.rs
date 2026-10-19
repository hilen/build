#!/usr/bin/env rust

//! `make run` of a desktop app with a login: builds the release binary with
//! the real HILEN_SESSION_KEY of its Infisical project and starts it. A build
//! without the key seals the stored login with a public development key. The
//! arguments go to cargo, like `--features dev` for the inspect server.
//!
//! The build is not marked as a release, so the inspect server of a dev
//! build still works. On a machine with no Rust toolchain the build runs on a
//! far builder of the same system and the binary comes back.

use anyhow::Result;
use shared::{
    config,
    run::{has, run, run_with_input},
    secrets::{self, SESSION_KEY_ENV},
};

fn main() -> Result<()> {
    let config = config::read()?;
    let args: Vec<String> = std::env::args().skip(1).collect();
    let build = format!("cargo build --release -p {} {}", config.app_name, args.join(" "));
    let binary = format!("target/release/{}", config.app_name);
    let key = secrets::session_key(&config)?;
    if let Some(key) = &key {
        // Read by the build here, and by the output mask.
        unsafe {
            std::env::set_var(SESSION_KEY_ENV, key);
        }
    } else {
        println!("no infisical_project in hilen.toml, the build uses the development session key");
    }

    if has("cargo") {
        match key {
            Some(_) => run(&secrets::masked(&build))?,
            None => run(&build)?,
        }
    } else {
        let system = if cfg!(target_os = "macos") {
            "mac"
        } else if cfg!(target_os = "windows") {
            "windows"
        } else {
            "linux"
        };
        // The key goes in on stdin, so the job line and the far log never
        // hold it.
        match &key {
            Some(key) => run_with_input(
                &secrets::masked(&format!(
                    "far --on {system} 'read -r {SESSION_KEY_ENV} && export {SESSION_KEY_ENV} && {build}'"
                )),
                key,
            )?,
            None => run(&format!("far --on {system} '{build}'"))?,
        }
        run(&format!("far --on {system} get {binary}"))?;
    }
    run(&format!("./{binary}"))
}
