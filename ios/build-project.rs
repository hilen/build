#!/usr/bin/env rust

use std::fs::{read_to_string, write};

use anyhow::{Result, ensure};
use regex::Regex;
use shared::{
    config, inspect, ios,
    run::{has, run},
};

fn main() -> Result<()> {
    let config = config::read()?;

    run("rust ./build/ios/build-lib.rs")?;

    unsafe {
        std::env::remove_var("CFLAGS");
        std::env::remove_var("CXXFLAGS");
    }

    if has("cargo") {
        run("cargo install hilen-mobile --locked")?;
    } else {
        // A machine with no Rust toolchain gets the generator ready built.
        ensure!(
            has("hilen-mobile"),
            "hilen-mobile is not installed and this machine has no cargo to install it"
        );
    }

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
    let mut project = target.replace_all(&project, setting.as_str()).to_string();
    if !has("cargo") {
        // The template has a build phase that runs `~/.cargo/bin/cargo lipo`
        // on archive. With no cargo here the archive would stop there. The lib
        // is already built and fresh, build-lib.rs ran above, so the phase is
        // emptied.
        let phase = Regex::new("shellScript = \"[^\"]*cargo lipo[^\"]*\";")?;
        ensure!(
            phase.is_match(&project),
            "generated Xcode project has no cargo lipo build phase to turn off"
        );
        project = phase
            .replace_all(&project, "shellScript = \"true\\n\";")
            .to_string();
    }
    write(&project_path, project.as_bytes())?;

    // hilen-mobile bakes CFBundleShortVersionString 1.0 into the generated
    // Info.plist with no knob, so set the real version before the archive reads
    // it. Runs from the repo root, before the chdir below.
    run(&format!(
        "/usr/libexec/PlistBuddy -c \"Set :CFBundleShortVersionString {}\" mobile/iOS/{}/Info.plist",
        config.version, config.project_name
    ))?;

    // An iPhone lets an app announce itself on the local network only with
    // these 2 keys, see docs/inspect.md in hilen. Only a build with the
    // inspect server announces, a shipped app has none of this.
    let lib = format!("target/universal/release/{}", config.lib_name);
    if inspect::has_server(&lib)? {
        let plist = format!("mobile/iOS/{}/Info.plist", config.project_name);
        for command in [
            "Add :NSLocalNetworkUsageDescription string The developer tools find this app on the local network.",
            "Add :NSBonjourServices array",
            "Add :NSBonjourServices:0 string _hilen-inspect._tcp",
        ] {
            run(&format!("/usr/libexec/PlistBuddy -c \"{command}\" {plist}"))?;
        }
    }

    std::env::set_current_dir("mobile/iOS")?;

    run("xcodebuild -showsdks")?;

    // An explicit destination fails with a clear "iOS is not installed" message
    // when the platform is missing. The -sdk flag instead falls back to a Mac
    // Catalyst destination and dies at link time with an arch mismatch.
    run(&format!(
        "xcodebuild -scheme {} -destination \"generic/platform=iOS Simulator\" OTHER_LDFLAGS=\"{}\" build",
        config.project_name,
        ios::LDFLAGS
    ))?;
    Ok(())
}
