#!/usr/bin/env rust

use anyhow::{Result, bail};
use shared::{config, inspect};
use shared::run::{probe, run};

fn main() -> Result<()> {
    let config = config::read()?;

    let args = std::env::args().skip(1).collect::<Vec<_>>().join(" ");
    let args = args.to_lowercase();
    let ios = args.contains("ios");
    let android = args.contains("android");

    println!("APP_NAME: {}", config.app_name);
    println!("PROJECT_NAME: {}", config.project_name);

    // The android build always runs inside docker, locally and in CI, so the
    // host needs no Android tooling. The env var marks being inside already.
    if android && std::env::var("HILEN_ANDROID_DOCKER_BUILD").is_err() {
        run("rust ./build/in_docker_android.rs")?;
        return Ok(());
    }

    let is_mac = cfg!(target_os = "macos");
    let is_linux = cfg!(target_os = "linux");
    let unix = is_mac || is_linux;

    let uname = if unix {
        probe("uname -a").to_lowercase()
    } else {
        String::new()
    };
    let release = if is_linux {
        std::fs::read_to_string("/etc/os-release")
            .unwrap_or_default()
            .to_lowercase()
    } else {
        String::new()
    };

    println!("uname: {uname}");
    println!("system: {}", std::env::consts::OS);
    println!("arch: {}", std::env::consts::ARCH);

    if android {
        return build_android();
    }

    if is_linux {
        println!("Lin setup");
        install_linux_deps(&release, &uname)?;
    }

    if unix {
        println!("Installing rustup:");
        run("curl https://sh.rustup.rs -sSf | sh -s -- -y")?;
        let home = std::env::var("HOME").unwrap_or_default();
        let path = std::env::var("PATH").unwrap_or_default();
        unsafe {
            std::env::set_var("PATH", format!("{home}/.cargo/bin:{path}"));
        }
    }

    if ios {
        run("rust ./build/ios/build-project.rs")?;
    } else {
        run("cargo build --all --profile=ci")?;
        run("cargo test --all --profile=ci")?;
    }
    Ok(())
}

fn build_android() -> Result<()> {
    run("rustup toolchain install")?;
    run(
        "rustup target add armv7-linux-androideabi aarch64-linux-android \
i686-linux-android x86_64-linux-android",
    )?;

    run("cargo install hilen-mobile --locked")?;
    run("hilen-mobile")?;

    fix_generated_project()?;

    let abi = std::env::var("HILEN_ANDROID_ABI").unwrap_or_default();
    if !abi.is_empty() {
        limit_targets(&abi)?;
    }

    // Gradle misses changed inputs on a docker bind mount even with vfs
    // watching off and packs a stale .so into the APK. Removing the jni
    // intermediates forces the merge, strip and package tasks every build.
    for dir in [
        "mobile/android/app/build/intermediates/merged_jni_libs",
        "mobile/android/app/build/intermediates/merged_native_libs",
        "mobile/android/app/build/intermediates/stripped_native_libs",
    ] {
        if std::path::Path::new(dir).exists() {
            std::fs::remove_dir_all(dir)?;
        }
    }

    std::env::set_current_dir("mobile/android")?;
    run("chmod +x ./gradlew")?;
    if abi.is_empty() {
        run("./gradlew build")?;
    } else {
        run("./gradlew assembleDebug")?;
    }
    // A test build of demo carries the inspect server on purpose, only a
    // shipped build is checked. Every ABI's .so sits under this folder.
    if inspect::is_release() {
        inspect::refuse("app/build/rustJniLibs/android")?;
    }
    Ok(())
}

/// The pending template fixes from docs/android.md. The template still misses
/// them, so a regeneration reverts them and they are reapplied after every
/// one. Each replace skips silently once the template itself carries the fix.
fn fix_generated_project() -> Result<()> {
    let gradle = "mobile/android/app/build.gradle.kts";
    let content = std::fs::read_to_string(gradle)?;

    // games-activity must match the version the android-activity crate
    // bundles, with 2.0.2 RegisterNatives aborts the process at startup.
    let content = replace_once(
        gradle,
        content,
        "androidx.games:games-activity:2.0.2",
        "androidx.games:games-activity:4.4.0",
    )?;

    // Packaging can run before the fresh .so lands unless the jni merge
    // tasks wait for the cargo build.
    let content = replace_once(
        gradle,
        content,
        "name == \"javaPreCompileDebug\" || name == \"javaPreCompileRelease\"",
        "name == \"javaPreCompileDebug\" || name == \"javaPreCompileRelease\" ||
            name == \"mergeDebugJniLibFolders\" || name == \"mergeReleaseJniLibFolders\"",
    )?;

    // The repo assets folder rides into the APK, filesystem::read_bytes
    // reads it back through the AAssetManager.
    let jni_debug = "        getByName(\"debug\") {
            jniLibs.srcDir(\"$buildDir/rustJniLibs/android\")
        }";
    let with_assets = "        getByName(\"debug\") {
            jniLibs.srcDir(\"$buildDir/rustJniLibs/android\")
        }
        getByName(\"main\") {
            assets.srcDir(\"../../../assets\")
        }";
    let content = replace_once(gradle, content, jni_debug, with_assets)?;

    std::fs::write(gradle, content)?;

    // Sockets are denied without the INTERNET permission, which fails the
    // Rest request test and the inspect listener.
    let manifest = "mobile/android/app/src/main/AndroidManifest.xml";
    let content = std::fs::read_to_string(manifest)?;
    if !content.contains("android.permission.INTERNET") {
        let content = replace_once(
            manifest,
            content,
            "    <application",
            "    <uses-permission android:name=\"android.permission.INTERNET\"/>

    <application",
        )?;
        std::fs::write(manifest, content)?;
    }

    // File watching cannot work in the container.
    let properties = "mobile/android/gradle.properties";
    let content = std::fs::read_to_string(properties)?;
    if !content.contains("org.gradle.vfs.watch") {
        std::fs::write(properties, format!("{content}\norg.gradle.vfs.watch=false\n"))?;
    }

    Ok(())
}

/// Applies one fix. The fix already present is fine, the template landed it.
/// Neither the old nor the new text found means the template changed shape
/// and the fix needs a fresh look, so that fails loudly.
fn replace_once(path: &str, content: String, from: &str, to: &str) -> Result<String> {
    if content.contains(to) {
        return Ok(content);
    }
    if !content.contains(from) {
        bail!("expected `{from}` in {path}");
    }
    Ok(content.replace(from, to))
}

/// The generated project always lists all four ABIs. An emulator build needs
/// only one, so the fresh gradle config is trimmed after every regeneration.
fn limit_targets(abi: &str) -> Result<()> {
    let path = "mobile/android/app/build.gradle.kts";
    let all = "targets = listOf(\"x86_64\", \"x86\", \"arm\", \"arm64\")";
    let one = format!("targets = listOf(\"{abi}\")");
    let content = std::fs::read_to_string(path)?;
    if !content.contains(all) {
        bail!("expected targets line not found in {path}");
    }
    std::fs::write(path, content.replace(all, &one))?;
    Ok(())
}

/// Amazon Linux is checked before Fedora on purpose. Its os-release carries
/// ID_LIKE="fedora", so testing Fedora first sends it down the dnf branch and
/// the yum packages it actually needs are never installed.
fn install_linux_deps(release: &str, uname: &str) -> Result<()> {
    let is_arch = std::path::Path::new("/etc/arch-release").exists();

    if release.contains("amazon") {
        println!("Amazon");
        run("sudo yum install -y gcc gcc-c++ alsa-lib-devel")?;
    } else if release.contains("fedora") {
        println!("Fedora");
        run(
            "sudo dnf install -y libXcursor-devel libXi-devel libXinerama-devel \
libXrandr-devel perl make cmake automake gcc gcc-c++ kernel-devel alsa-lib-devel-*",
        )?;
    } else if uname.contains("freebsd") {
        println!("Freebsd");
        run("sudo pkg update")?;
        run("sudo pkg install cmake xorg pkgconf alsa-utils")?;
    } else if is_arch {
        println!("Arch");
        run("sudo pacman -S gcc pkg-config cmake openssl make alsa-lib alsa-utils --noconfirm")?;
    } else if release.contains("ubuntu") || release.contains("debian") {
        println!("Debian");
        let mut deps = "cmake mesa-common-dev libgl1-mesa-dev libglu1-mesa-dev \
xorg-dev libasound2-dev pkg-config libssl-dev"
            .to_string();
        if std::env::consts::ARCH != "aarch64" {
            deps.push_str(" build-essential");
        }
        run("sudo apt update")?;
        run(&format!("sudo apt -y install {deps}"))?;
    } else if release.contains("opensuse") {
        println!("openSUSE");
        run("sudo zypper refresh")?;
        run("sudo zypper update")?;
        run("sudo zypper install -y --type pattern devel_basis")?;
        run("sudo zypper install -y --type pattern devel_C_C++")?;
        run("sudo zypper install -y alsa-lib llvm llvm-devel clang")?;
    } else {
        println!("Unknown distro");
        std::process::exit(1);
    }
    Ok(())
}
