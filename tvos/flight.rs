#!/usr/bin/env rust

use std::fs::read_to_string;

use anyhow::{Result, ensure};
use shared::{
    config,
    run::{capture, run},
};

// Gebling Games Studio Infisical project, holds the Apple upload secret
const INFISICAL_PROJECT: &str = "e2dd64d9-130c-4072-bd3d-0a98331364cb";

fn main() -> Result<()> {
    let config = config::read()?;

    let args: Vec<String> = std::env::args().skip(1).collect();
    run(format!("rust ./build/tvos/build-project.rs {}", args.join(" ")).trim())?;

    unsafe {
        std::env::remove_var("CFLAGS");
        std::env::remove_var("CXXFLAGS");
    }

    let export_options = "export.plist";
    let archive_path = format!("build/{}.xcarchive", config.project_name);
    let ipa_path = format!("build/{}.ipa", config.project_name);

    std::env::set_current_dir("mobile/tvOS")?;

    println!("codesign identity:");
    run("security find-identity -p codesigning -v")?;

    // The archive is not signed. A signed one wants a development profile,
    // and Apple makes none for a team with no Apple TV registered: "Your
    // team has no devices from which to generate a provisioning profile".
    // The export below signs for the store, which needs no device.
    run(&format!(
        "xcodebuild -project \"{}\".xcodeproj -scheme \"{}\" \
-sdk appletvos -configuration Release archive -archivePath \"{archive_path}\" \
CODE_SIGNING_ALLOWED=NO",
        config.project_name, config.project_name
    ))?;
    println!("build: OK");

    // The IPA step shells out to rsync, and Xcode only works with Apple's own,
    // see build/ios/flight.rs.
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
    // build, so its output is kept and read.
    let upload_log = "build/upload.log";
    run(&format!(
        "xcrun altool --upload-app -f \"{ipa_path}\" -u 146100@gmail.com \
-p \"$APPLE_APP_SPECIFIC_PASSWORD\" --type appletvos 2>&1 | tee {upload_log}"
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
