#!/usr/bin/env rust

use std::{
    fs::{read_to_string, write},
    path::Path,
};

use anyhow::{Result, ensure};
use regex::Regex;
use shared::{
    config, inspect, ios, local_network,
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

    // The template has a placeholder icon. An app keeps its own tvOS icon
    // set, the layered icon and the top shelf pictures, in
    // `assets/TVIcon.brandassets`, and it goes over the one of the template.
    let own_icon = Path::new("assets/TVIcon.brandassets");
    if own_icon.is_dir() {
        let template = format!(
            "mobile/tvOS/{}/Assets.xcassets/App Icon & Top Shelf Image.brandassets",
            config.project_name
        );
        run(&format!(
            "rm -rf \"{template}\" && cp -R \"{}\" \"{template}\"",
            own_icon.display()
        ))?;
    }

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
    ios::write_display_name(&plist, config.display_name.as_deref())?;

    // An Apple TV lets an app announce itself or browse on the local network
    // only for the types in these 2 keys, see docs/inspect.md in hilen. The
    // inspect server announces only in a build that carries it, a shipped
    // app has only the types of its [local_network] table.
    local_network::write_plist(
        &plist,
        config.local_network.as_ref(),
        inspect::has_server(&tvos::lib(tvos::SIMULATOR, &config.lib_name))?,
    )?;

    std::env::set_current_dir("mobile/tvOS")?;

    // An explicit destination fails with a clear "tvOS is not installed"
    // message when the platform is missing.
    run(&format!(
        "xcodebuild -scheme {} -destination \"generic/platform=tvOS Simulator\" -derivedDataPath build build",
        config.project_name
    ))?;
    Ok(())
}
