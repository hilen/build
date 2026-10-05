#!/usr/bin/env rust

use std::fs::read_to_string;

use anyhow::{Result, ensure};
use shared::{
    config, ios,
    run::{capture, run},
};

// Gebling Games Studio Infisical project, holds the Apple upload secret
const INFISICAL_PROJECT: &str = "e2dd64d9-130c-4072-bd3d-0a98331364cb";

fn main() -> Result<()> {
    let config = config::read()?;

    run("rust ./build/ios/build-project.rs")?;

    unsafe {
        std::env::remove_var("CFLAGS");
        std::env::remove_var("CXXFLAGS");
    }

    let export_options = "export.plist";
    let archive_path = format!("build/{}.xcarchive", config.project_name);
    let ipa_path = format!("build/{}.ipa", config.project_name);

    std::env::set_current_dir("mobile/iOS")?;

    println!("PROJECT_NAME: {}", config.project_name);
    println!("ARCHIVE_PATH: {archive_path}");
    println!("IPA_PATH: {ipa_path}");

    println!("codesign identity:");
    run("security find-identity -p codesigning -v")?;

    // hilen-mobile regenerates the project, so the linker flags are set here on
    // the archive command, see shared::ios::LDFLAGS for what they are.
    //
    // allowProvisioningUpdates is needed here as well as on the export below.
    // Archive signs too, and it runs first, so a bundle id that has never been
    // built on this machine dies here with "No profiles were found" long before
    // export gets a chance to mint one.
    run(&format!(
        "xcodebuild -project \"{}\".xcodeproj -scheme \"{}\" \
-sdk iphoneos -configuration Release archive -archivePath \"{archive_path}\" \
OTHER_LDFLAGS=\"{}\" \
-allowProvisioningUpdates",
        config.project_name, config.project_name, ios::LDFLAGS
    ))?;
    println!("build: OK");

    // The IPA step shells out to rsync, and Xcode only works with Apple's own.
    // A newer rsync earlier on PATH, from nix or homebrew, makes the export die
    // with a bare "Copy failed" and the real cause only appears in the
    // xcdistributionlogs bundle. Putting the system paths first avoids that.
    // allowProvisioningUpdates lets xcodebuild mint the Apple Distribution
    // certificate and the App Store profile for a first time app, otherwise
    // the export fails with "No profiles were found".
    run(&format!(
        "PATH=/usr/bin:/bin:/usr/sbin:/sbin:$PATH \
xcodebuild -exportArchive -archivePath \"{archive_path}\" \
-exportOptionsPlist \"{export_options}\" -exportPath \"build\" \
-allowProvisioningUpdates"
    ))?;
    println!("export: OK");

    let password = capture(&format!(
        "infisical secrets get APPLE_APP_SPECIFIC_PASSWORD --projectId {INFISICAL_PROJECT} \
--env prod --plain --silent"
    ))?;
    unsafe {
        std::env::set_var("APPLE_APP_SPECIFIC_PASSWORD", &password);
    }

    // The password stays a shell variable so it never gets printed in the
    // echoed command. altool exits 0 even when App Store Connect refuses the
    // build, so its output is kept and read. A rejected upload once printed
    // "upload: OK".
    let upload_log = "build/upload.log";
    run(&format!(
        "xcrun altool --upload-app -f \"{ipa_path}\" -u 146100@gmail.com \
-p \"$APPLE_APP_SPECIFIC_PASSWORD\" --type ios 2>&1 | tee {upload_log}"
    ))?;
    let output = read_to_string(upload_log)?;
    ensure!(
        !output.contains("UPLOAD FAILED")
            && (output.contains("UPLOAD SUCCEEDED") || output.contains("No errors uploading")),
        "upload failed, see the altool output above"
    );
    println!("upload: OK");
    Ok(())
}
