#!/usr/bin/env rust

use std::fs::{read_to_string, write};

use anyhow::{Result, ensure};
use regex::Regex;
use shared::{config, run::run};

fn main() -> Result<()> {
    let config = config::read()?;

    run("rust ./build/ios/build-lib.rs")?;

    unsafe {
        std::env::remove_var("CFLAGS");
        std::env::remove_var("CXXFLAGS");
    }

    run("cargo install hilen-mobile --locked")?;

    let args: Vec<String> = std::env::args().skip(1).collect();
    run(format!("hilen-mobile {}", args.join(" ")).trim())?;

    // The generator's template has its own deployment target. Apply the app's
    // configured minimum after every regeneration, for local builds and fly.
    let project_path = format!("mobile/iOS/{}.xcodeproj/project.pbxproj", config.project_name);
    let project = read_to_string(&project_path)?;
    let target = Regex::new(r"IPHONEOS_DEPLOYMENT_TARGET = [0-9.]+;")?;
    ensure!(
        target.is_match(&project),
        "generated Xcode project has no iOS deployment target"
    );
    let setting = format!("IPHONEOS_DEPLOYMENT_TARGET = {};", config.ios_minimum_version);
    write(
        &project_path,
        target.replace_all(&project, setting.as_str()).as_bytes(),
    )?;

    // hilen-mobile bakes CFBundleShortVersionString 1.0 into the generated
    // Info.plist with no knob, so set the real version before the archive reads
    // it. Runs from the repo root, before the chdir below.
    run(&format!(
        "/usr/libexec/PlistBuddy -c \"Set :CFBundleShortVersionString {}\" mobile/iOS/{}/Info.plist",
        config.version, config.project_name
    ))?;

    std::env::set_current_dir("mobile/iOS")?;

    run("xcodebuild -showsdks")?;

    // An explicit destination fails with a clear "iOS is not installed" message
    // when the platform is missing. The -sdk flag instead falls back to a Mac
    // Catalyst destination and dies at link time with an arch mismatch.
    run(&format!(
        "xcodebuild -scheme {} -destination \"generic/platform=iOS Simulator\" build",
        config.project_name
    ))?;
    Ok(())
}
