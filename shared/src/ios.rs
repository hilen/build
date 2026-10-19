//! What every xcodebuild of an iOS app passes, and the name an Apple app
//! shows under its icon.

use std::process::Command;

use anyhow::{Result, ensure};

/// Writes `CFBundleDisplayName` into a generated Info.plist. The template has
/// no such key, so it is added, or set when an earlier run added it. The name
/// goes past the shell, it may hold spaces.
pub fn write_display_name(plist: &str, name: Option<&str>) -> Result<()> {
    let Some(name) = name else { return Ok(()) };
    let buddy = |command: String| Command::new("/usr/libexec/PlistBuddy").args(["-c", &command, plist]).output();
    let set = buddy(format!("Set :CFBundleDisplayName {name}"))?;
    if !set.status.success() {
        let add = buddy(format!("Add :CFBundleDisplayName string {name}"))?;
        ensure!(add.status.success(), "the display name did not go into {plist}");
    }
    println!("CFBundleDisplayName {name}");
    Ok(())
}

/// The linker flags of the app. A setting on the command line replaces the
/// one of the project, so every xcodebuild call passes all of them.
///
/// The 2 weak frameworks carry modern data constants. On iOS 12 and 13 dyld
/// binds a strong data symbol eagerly, so a constant the device lacks, like
/// kCGColorSpaceExtendedDisplayP3 or kSecUseDataProtectionKeychain, kills the
/// app before main. Weak linking makes the missing constant NULL instead.
///
/// The rest is what the engine needs linked and a static library cannot ask
/// for by itself: the video decode of ffmpeg, zlib for it, and MediaPlayer
/// for the lock screen controls. An app with no video links them for nothing,
/// every iOS has them.
pub const LDFLAGS: &str = "-Wl,-weak_framework,CoreGraphics -Wl,-weak_framework,Security \
-framework VideoToolbox -framework CoreMedia -framework CoreVideo -framework MediaPlayer -lz";
