#!/usr/bin/env rust

use std::fs::{read_to_string, write};

use anyhow::{Result, ensure};
use regex::Regex;
use shared::{
    config, inspect,
    run::{has, run},
    tvos,
};

fn main() -> Result<()> {
    let config = config::read()?;

    run("rust ./build/tvos/build-lib.rs")?;

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

    let project_path = format!("mobile/tvOS/{}.xcodeproj/project.pbxproj", config.project_name);
    let project = read_to_string(&project_path)?;
    let target = Regex::new(r"TVOS_DEPLOYMENT_TARGET = [0-9.]+;")?;
    ensure!(
        target.is_match(&project),
        "generated Xcode project has no tvOS deployment target"
    );
    let setting = format!("TVOS_DEPLOYMENT_TARGET = {};", config.tvos_minimum_version);
    let project = target.replace_all(&project, setting.as_str()).to_string();
    write(&project_path, project.as_bytes())?;

    let plist = format!("mobile/tvOS/{}/Info.plist", config.project_name);
    run(&format!(
        "/usr/libexec/PlistBuddy -c \"Set :CFBundleShortVersionString {}\" {plist}",
        config.version
    ))?;

    // An Apple TV lets an app announce itself on the local network only with
    // these 2 keys, see docs/inspect.md in hilen. Only a build with the
    // inspect server announces, a shipped app has none of this.
    if inspect::has_server(&tvos::lib(tvos::SIMULATOR, &config.lib_name))? {
        for command in [
            "Add :NSLocalNetworkUsageDescription string The developer tools find this app on the local network.",
            "Add :NSBonjourServices array",
            "Add :NSBonjourServices:0 string _hilen-inspect._tcp",
        ] {
            run(&format!("/usr/libexec/PlistBuddy -c \"{command}\" {plist}"))?;
        }
    }

    std::env::set_current_dir("mobile/tvOS")?;

    // An explicit destination fails with a clear "tvOS is not installed"
    // message when the platform is missing.
    run(&format!(
        "xcodebuild -scheme {} -destination \"generic/platform=tvOS Simulator\" -derivedDataPath build build",
        config.project_name
    ))?;
    Ok(())
}
