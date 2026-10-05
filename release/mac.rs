#!/usr/bin/env rust

// The mac release: the binary, the .app bundle, Developer ID signing,
// notarization and the dmg. The binary is universal unless `mac_targets` in
// the [release] table of hilen.toml names 1 target, <arch> is then `arm64` or
// `x64`. A local run without the Apple secrets still produces an unsigned dmg
// to test the bundle with, but in CI a missing APPLE_SIGNING_IDENTITY fails
// the build so an unsigned release can never ship silently. Outputs in dist/:
//   <name>-<v>-mac-<arch>.dmg      first install
//   <name>-<v>-macos-<arch>        the bare binary the updater swaps in
//   <daemon>-<v>-macos-<arch>      each daemon of `daemons`, bare and signed

use anyhow::{Context, Result, bail};
use shared::inspect;
use shared::release::{self, Release};
use shared::run::{capture, run, run_secret};

const NOTARIZE_LIMIT_SECS: u32 = 900;

fn main() -> Result<()> {
    inspect::mark_release();
    let r = release::read()?;
    let arch = r.mac_arch()?;
    std::fs::create_dir_all("dist")?;
    // lipo writes here, and a fresh checkout that only built with --target has no such folder yet.
    std::fs::create_dir_all("target/release")?;
    let signing = std::env::var("APPLE_SIGNING_IDENTITY").ok().filter(|s| !s.is_empty());
    if signing.is_none() && std::env::var("CI").is_ok() {
        bail!("APPLE_SIGNING_IDENTITY is not set, refusing to build an unsigned release in CI");
    }
    if signing.is_some() {
        unlock_keychain()?;
    }

    // The runner shell starts without the interactive env, so cc has no
    // sysroot without this and native C deps fail to compile.
    let sdk = capture("xcrun --sdk macosx --show-sdk-path")?;
    unsafe {
        std::env::set_var("SDKROOT", sdk);
    }
    for target in &r.mac_targets {
        run(&format!("rustup target add {target}"))?;
        run(&format!(
            "cargo build --locked --release -p {} --bin {} --target {target}",
            r.name, r.bin
        ))?;
    }
    let universal = format!("target/release/{}-{arch}", r.name);
    let slices: Vec<String> = r
        .mac_targets
        .iter()
        .map(|target| format!("target/{target}/release/{}", r.bin))
        .collect();
    run(&format!("lipo -create -output {universal} {}", slices.join(" ")))?;
    inspect::refuse(&universal)?;

    let app = bundle(&r, &universal)?;
    if let Some(identity) = &signing {
        run(&format!(
            r#"codesign --force --deep --options runtime --timestamp --sign "{identity}" "{app}""#
        ))?;
        run(&format!(r#"codesign --force --options runtime --timestamp --sign "{identity}" "{universal}""#))?;
        notarize_app(&app)?;
    }

    let dmg = format!("dist/{}", r.artifact(&format!("mac-{arch}.dmg")));
    make_dmg(&r, &app, &dmg)?;
    if signing.is_some() {
        notarize(&dmg)?;
    }
    println!("built {dmg}");

    let bare = format!("dist/{}", r.artifact(&format!("macos-{arch}")));
    std::fs::copy(&universal, &bare)?;
    r.sign(&[&bare])?;
    println!("built {bare}");

    // A daemon is only the bare binary, signed with the identity so
    // Gatekeeper lets it run, no bundle, no dmg and no notarization.
    for daemon in &r.daemons {
        for target in &r.mac_targets {
            run(&format!(
                "cargo build --locked --release -p {} --bin {} --target {target}",
                daemon.name, daemon.bin
            ))?;
        }
        let universal = format!("target/release/{}-{arch}", daemon.name);
        let slices: Vec<String> = r
            .mac_targets
            .iter()
            .map(|target| format!("target/{target}/release/{}", daemon.bin))
            .collect();
        run(&format!("lipo -create -output {universal} {}", slices.join(" ")))?;
        inspect::refuse(&universal)?;
        if let Some(identity) = &signing {
            run(&format!(r#"codesign --force --options runtime --timestamp --sign "{identity}" "{universal}""#))?;
        }
        let bare = format!("dist/{}", daemon.artifact(&format!("macos-{arch}")));
        std::fs::copy(&universal, &bare)?;
        r.sign(&[&bare])?;
        println!("built {bare}");
    }
    Ok(())
}

fn unlock_keychain() -> Result<()> {
    // The password stays a shell variable, so it is never part of a printed command.
    std::env::var("APPLE_CI_KEYCHAIN_PASSWORD").context("APPLE_CI_KEYCHAIN_PASSWORD")?;
    let keychain = "~/Library/Keychains/ci-signing.keychain-db";
    run_secret(&format!(
        r#"security unlock-keychain -p "$APPLE_CI_KEYCHAIN_PASSWORD" {keychain}"#
    ))?;
    run_secret(&format!(
        r#"security set-key-partition-list -S apple-tool:,apple: -k "$APPLE_CI_KEYCHAIN_PASSWORD" {keychain} > /dev/null"#
    ))?;
    run(&format!(
        "security list-keychains -d user -s {keychain} ~/Library/Keychains/login.keychain-db"
    ))?;
    Ok(())
}

fn bundle(r: &Release, universal: &str) -> Result<String> {
    let app = format!("target/release/bundle/{}.app", r.name);
    let contents = format!("{app}/Contents");
    if std::path::Path::new(&app).exists() {
        std::fs::remove_dir_all(&app)?;
    }
    std::fs::create_dir_all(format!("{contents}/MacOS"))?;
    std::fs::create_dir_all(format!("{contents}/Resources"))?;
    std::fs::copy(universal, format!("{contents}/MacOS/{}", r.name))?;
    std::fs::copy("assets/icon.icns", format!("{contents}/Resources/icon.icns")).context("assets/icon.icns")?;
    std::fs::write(format!("{contents}/Info.plist"), info_plist(r))?;
    Ok(app)
}

fn info_plist(r: &Release) -> String {
    format!(
        r#"<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>CFBundleName</key><string>{name}</string>
  <key>CFBundleDisplayName</key><string>{name}</string>
  <key>CFBundleIdentifier</key><string>{bundle_id}</string>
  <key>CFBundleExecutable</key><string>{name}</string>
  <key>CFBundleIconFile</key><string>icon.icns</string>
  <key>CFBundlePackageType</key><string>APPL</string>
  <key>CFBundleShortVersionString</key><string>{version}</string>
  <key>CFBundleVersion</key><string>{version}</string>
  <key>LSMinimumSystemVersion</key><string>11.0</string>
  <key>LSApplicationCategoryType</key><string>public.app-category.developer-tools</string>
  <key>NSHighResolutionCapable</key><true/>
</dict>
</plist>
"#,
        name = r.name,
        bundle_id = r.bundle_id,
        version = r.version
    )
}

// The app is notarized on its own before it goes into the dmg, so the
// bundle carries a stapled ticket and launches offline after a drag install.
fn notarize_app(app: &str) -> Result<()> {
    let zip = format!("{app}.zip");
    run(&format!(r#"ditto -c -k --keepParent "{app}" "{zip}""#))?;
    notarize(&zip)?;
    run(&format!(r#"xcrun stapler staple "{app}""#))?;
    std::fs::remove_file(zip)?;
    Ok(())
}

fn notarize(file: &str) -> Result<()> {
    for var in ["APPLE_ID_EMAIL", "APPLE_APP_SPECIFIC_PASSWORD", "APPLE_TEAM_ID"] {
        std::env::var(var).context(var)?;
    }
    // The secrets stay shell variables and the command is not echoed, the
    // release logs once showed the password. notarytool has no limit on the
    // upload, a stalled one hung a release for 28 minutes, so perl's alarm
    // kills it. A normal upload and wait takes under 5 minutes.
    println!("notarizing {file}");
    run_secret(&format!(
        r#"perl -e 'alarm shift; exec @ARGV' {NOTARIZE_LIMIT_SECS} xcrun notarytool submit "{file}" --apple-id "$APPLE_ID_EMAIL" --password "$APPLE_APP_SPECIFIC_PASSWORD" --team-id "$APPLE_TEAM_ID" --wait"#
    ))
    .with_context(|| format!("notarizing {file} failed or took over {NOTARIZE_LIMIT_SECS} seconds"))?;
    if file.ends_with(".dmg") {
        run(&format!(r#"xcrun stapler staple "{file}""#))?;
    }
    Ok(())
}

fn make_dmg(r: &Release, app: &str, dmg: &str) -> Result<()> {
    let staging = "target/release/bundle/dmg";
    if std::path::Path::new(staging).exists() {
        std::fs::remove_dir_all(staging)?;
    }
    std::fs::create_dir_all(staging)?;
    run(&format!(r#"cp -R "{app}" {staging}/"#))?;
    run(&format!("ln -s /Applications {staging}/Applications"))?;
    if std::path::Path::new(dmg).exists() {
        std::fs::remove_file(dmg)?;
    }
    // Left to itself hdiutil sizes the image from the folder, and now and then
    // its guess is too small: `create failed - No space left on device`, on a
    // disk with 431 GB free, at blackforge v0.2.6. So the size is given, the
    // folder plus a third. The UDZO format packs the free space away.
    let used = capture(&format!("du -sk {staging}"))?;
    let kb: u64 = used
        .split_whitespace()
        .next()
        .with_context(|| format!("du gave no size for {staging}"))?
        .parse()
        .with_context(|| format!("du gave no number for {staging}: {used}"))?;
    let mb = kb / 1024 * 4 / 3 + 32;
    run(&format!(
        r#"hdiutil create -size {mb}m -volname "{}" -srcfolder {staging} -ov -format UDZO "{dmg}""#,
        r.name
    ))?;
    Ok(())
}
