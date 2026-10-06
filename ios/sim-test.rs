#!/usr/bin/env rust

// Runs the whole UI suite on an iOS simulator and exits non zero on any failure.
//
// The oldest iPhone this toolchain can boot is the iPhone 8 on iOS 16.4. Older
// devices cap at iOS 15, which no simulator runtime supports on this macOS, and
// the simulator renders on the host GPU so an even older chip would prove nothing
// the render pipeline does not already show here.
//
// The app is x86_64 only for the simulator. The project excludes arm64 there, so
// it runs under Rosetta, and building the scheme instead falls back to Mac
// Catalyst arm64 and fails to link. So this builds the target against the
// iphonesimulator SDK directly with ARCHS=x86_64.
//
// Tests are triggered by HILEN_RUN_TESTS, not the inspector. The app runs the suite
// on a worker task, prints a result marker and exits, so there is no mDNS to
// disambiguate against the desktop lane running at the same time.
//
// On its own the suite streams live, so each test shows up as it runs and a hang
// names the test it stuck on. The app logs through NSLog, which tags every
// console line with a timestamp and a process name, so the stream strips that
// prefix to read like the desktop runner.
//
// Under make ui this lane runs in parallel with the desktop lanes, which would
// mangle three streams into one. That run sets HILEN_IOS_QUIET, and the lane goes
// back to buffering and printing only [ios] milestones. A failed command dumps
// its captured output either way.

use std::{
    io::{BufRead, BufReader},
    process::{Command, Stdio},
    thread::sleep,
    time::Duration,
};

use anyhow::{Result, bail};
use regex::Regex;
use shared::{
    config, ios,
    run::{probe, run_quiet},
};

const DEVICE_NAME: &str = "te-iPhone8-16.4";
const DEVICE_TYPE: &str = "com.apple.CoreSimulator.SimDeviceType.iPhone-8";
const RUNTIME: &str = "com.apple.CoreSimulator.SimRuntime.iOS-16-4";
const RUNTIME_HINT: &str = "iOS 16.4";
const SHUTDOWN_WAIT_SECONDS: u64 = 60;

// The XCUITest of the mobile project that taps the screen and the keys of the
// screen keyboard for a test, see `system_input` in the engine. It listens on
// this port of the Mac, which the simulator shares.
const SYSTEM_INPUT_SCHEME: &str = "SystemInput";
const SYSTEM_INPUT_PORT: u16 = 47815;
const HARDWARE_KEYBOARD: &str = "com.apple.iphonesimulator ConnectHardwareKeyboard";

// A separate cargo target dir so this build never blocks on the desktop lane's
// target lock, which is what lets the two lanes truly run in parallel. It sits
// under target so the existing ignore of target contents already covers it.
const IOS_TARGET_DIR: &str = "target/ios";
const SIM_TRIPLE: &str = "x86_64-apple-ios";

fn step(message: &str) {
    println!("\n[ios] {message}");
}

/// Stream a command's combined output live and capture it, so the run stays
/// watchable and the result marker can still be parsed from the text after.
///
/// The app logs through NSLog, which the simulator console tags with a
/// timestamp and a process name in front of every line. Strip that so the
/// stream reads clean like the desktop runner. The app's own stdout lines,
/// such as the result marker, carry no such prefix and pass through untouched.
fn stream(command: &str) -> Result<String> {
    let prefix = Regex::new(r"^\d{4}-\d\d-\d\d \d\d:\d\d:\d\d\.\d+ \S+\[\d+:\d+\] ")?;
    let mut child = Command::new("sh")
        .arg("-c")
        .arg(format!("{command} 2>&1"))
        .stdout(Stdio::piped())
        .spawn()?;
    let stdout = child.stdout.take().expect("stdout was piped");
    let mut output = String::new();
    for line in BufReader::new(stdout).lines() {
        let line = prefix.replace(&line?, "").into_owned();
        println!("{line}");
        output.push_str(&line);
        output.push('\n');
    }
    child.wait()?;
    Ok(output)
}

fn main() -> Result<()> {
    if !cfg!(target_os = "macos") {
        println!("[ios] not macOS, skipping the iOS simulator lane.");
        return Ok(());
    }

    let config = config::read()?;

    // `--human` is the simulator spelling of the desktop `--human`. The app
    // holds after every check and every test until a tap on the screen.
    let human = std::env::args().skip(1).any(|arg| arg == "--human");

    // `--present` shows the one view named by HILEN_TEST_ONLY full screen on
    // the phone and keeps the simulator up until ctrl-c.
    let present = std::env::args().skip(1).any(|arg| arg == "--present");
    if present && std::env::var("HILEN_TEST_ONLY").is_err() {
        bail!("[ios] --present needs HILEN_TEST_ONLY naming exactly one test");
    }

    let lib = format!("{IOS_TARGET_DIR}/{SIM_TRIPLE}/release/{}", config.lib_name);
    let linked_lib = format!("target/universal/release/{}", config.lib_name);
    let symroot = format!(
        "{}/{IOS_TARGET_DIR}/sim-build",
        std::env::current_dir()?.display()
    );
    let app = format!("{symroot}/Release-iphonesimulator/{}.app", config.project_name);
    let xcodeproj = format!("mobile/iOS/{}.xcodeproj", config.project_name);

    step("adding the iOS simulator rust target");
    run_quiet(&format!("rustup target add {SIM_TRIPLE}"))?;

    // --lib only. The bin target fails to link on iOS, it needs a symbol the
    // UIKit shell provides, and only the staticlib is wanted here. Release, so
    // the suite runs at real speed. The Xcode project links the lib from
    // target/universal/release.
    step("building the engine for iOS, this takes a while");
    run_quiet(&format!(
        "env CARGO_TARGET_DIR={IOS_TARGET_DIR} IPHONEOS_DEPLOYMENT_TARGET=12.0 \
cargo build -p {} --lib --target {SIM_TRIPLE} --release",
        config.app_name
    ))?;
    run_quiet(&format!(
        "mkdir -p target/universal/release && cp {lib} {linked_lib}"
    ))?;

    // The generated project is gitignored, so regenerate it only when it is
    // missing or older than the system input helper, not on every run.
    let helper_scheme = format!("{xcodeproj}/xcshareddata/xcschemes/{SYSTEM_INPUT_SCHEME}.xcscheme");
    if !std::path::Path::new(&helper_scheme).exists() {
        run_quiet("cargo install hilen-mobile --locked")?;
        run_quiet("hilen-mobile")?;
    }

    step("building the simulator app");
    run_quiet(&format!(
        "xcodebuild -project {xcodeproj} -target {} -configuration Release \
-sdk iphonesimulator ARCHS=x86_64 VALID_ARCHS=x86_64 ONLY_ACTIVE_ARCH=NO \
SYMROOT={symroot} OTHER_LDFLAGS=\"{}\" build",
        config.project_name,
        ios::LDFLAGS
    ))?;

    let device = ensure_device()?;

    let helper_data = format!("{}/{IOS_TARGET_DIR}/system-input", std::env::current_dir()?.display());
    let helper_build = format!(
        "-project {xcodeproj} -scheme {SYSTEM_INPUT_SCHEME} -destination \"platform=iOS \
Simulator,id={device}\" -derivedDataPath {helper_data}"
    );

    step("building the system input helper");
    run_quiet(&format!("xcodebuild build-for-testing {helper_build}"))?;

    // With a hardware keyboard connected the simulator shows no screen
    // keyboard, and the keyboard tests have no keys to tap. The setting is
    // read when Simulator starts, and put back after the run.
    let hardware_keyboard = probe(&format!("defaults read {HARDWARE_KEYBOARD}"));
    probe("osascript -e 'tell application \"Simulator\" to quit'");
    run_quiet(&format!("defaults write {HARDWARE_KEYBOARD} -bool false"))?;

    step(&format!("booting {DEVICE_NAME}"));
    boot_device(&device)?;
    run_quiet("open -a Simulator")?;
    run_quiet(&format!("xcrun simctl install {device} \"{app}\""))?;

    // HILEN_RUN_TESTS makes the app run the suite and exit. --console streams its
    // stdout here, so the result marker arrives before the launch returns.
    step("running the UI suite on the simulator");

    // simctl passes only SIMCTL_CHILD_ prefixed variables into the app, so the
    // narrowing list and the human flag are forwarded under that prefix.
    let helper_log = format!("{IOS_TARGET_DIR}/system-input.log");
    let mut helper = Command::new("sh")
        .arg("-c")
        .arg(format!(
            "TEST_RUNNER_HILEN_BUNDLE_ID={} TEST_RUNNER_HILEN_SYSTEM_INPUT_PORT={SYSTEM_INPUT_PORT} exec \
xcodebuild test-without-building {helper_build} > {helper_log} 2>&1",
            config.bundle_id
        ))
        .spawn()?;

    let mut env = String::from(if present {
        "SIMCTL_CHILD_HILEN_PRESENT=1"
    } else {
        "SIMCTL_CHILD_HILEN_RUN_TESTS=1"
    });
    if let Ok(only) = std::env::var("HILEN_TEST_ONLY") {
        env.push_str(&format!(" SIMCTL_CHILD_HILEN_TEST_ONLY=\"{only}\""));
    }
    if human {
        env.push_str(" SIMCTL_CHILD_HILEN_HUMAN=1");
    }
    env.push_str(&format!(
        " SIMCTL_CHILD_HILEN_SYSTEM_INPUT=127.0.0.1:{SYSTEM_INPUT_PORT}"
    ));

    let launch = format!(
        "{env} xcrun simctl launch --console --terminate-running-process {device} {}",
        config.bundle_id
    );

    // Under make ui three lanes run at once, so this lane stays quiet to keep
    // the streams from mangling. Run on its own and it streams every test live
    // like the desktop runner. A human run always streams, it holds for the
    // user and the prompts are the only sign of where it stands.
    let output = if std::env::var("HILEN_IOS_QUIET").is_ok() && !human && !present {
        probe(&format!("{launch} 2>&1"))
    } else {
        stream(&launch)?
    };

    // The helper serves until it is stopped, the app is its only client.
    helper.kill()?;
    helper.wait()?;

    run_quiet(&format!("xcrun simctl shutdown {device} || true"))?;
    probe("osascript -e 'tell application \"Simulator\" to quit'");
    match hardware_keyboard.trim() {
        "0" => {}
        "1" => {
            run_quiet(&format!("defaults write {HARDWARE_KEYBOARD} -bool true"))?;
        }
        // It was never set, which reads as an error text.
        _ => {
            run_quiet(&format!("defaults delete {HARDWARE_KEYBOARD}"))?;
        }
    }

    if present {
        return Ok(());
    }

    let marker = Regex::new(r"HILEN_TEST_RESULT (\d+) tests, (\d+) failed")?;
    let Some(caps) = marker.captures(&output) else {
        eprintln!("{output}");
        bail!("[ios] sim run produced no result marker. See the launch output above.");
    };

    let total: i64 = caps[1].parse()?;
    let failed: i64 = caps[2].parse()?;

    if failed != 0 {
        eprintln!("{output}");
        step(&format!("FAILED: {total} tests, {failed} failed"));
        std::process::exit(1);
    }

    step(&format!("ok: {total} tests, 0 failed"));
    Ok(())
}

fn boot_device(device: &str) -> Result<()> {
    for elapsed in 0..SHUTDOWN_WAIT_SECONDS {
        let state = probe(&format!("xcrun simctl list devices | grep \"{DEVICE_NAME} (\""));
        if !state.contains("(Shutting Down)") {
            run_quiet(&format!("xcrun simctl bootstatus {device} -b"))?;
            return Ok(());
        }
        if elapsed == 0 {
            step(&format!("waiting for {DEVICE_NAME} to finish shutting down"));
        }
        sleep(Duration::from_secs(1));
    }

    bail!("{DEVICE_NAME} did not finish shutting down within {SHUTDOWN_WAIT_SECONDS} seconds")
}

fn ensure_device() -> Result<String> {
    let existing = probe(&format!("xcrun simctl list devices | grep \"{DEVICE_NAME} (\""));
    let id = Regex::new(r"\(([0-9A-F-]{36})\)")?;
    if let Some(caps) = id.captures(&existing) {
        return Ok(caps[1].to_string());
    }

    if !probe("xcrun simctl list runtimes").contains(RUNTIME_HINT) {
        bail!(
            "{RUNTIME_HINT} simulator runtime is not installed, so the iPhone 8 device cannot be \
created. Install it before running the iOS test lane."
        );
    }

    let created = run_quiet(&format!(
        "xcrun simctl create \"{DEVICE_NAME}\" {DEVICE_TYPE} {RUNTIME}"
    ))?;
    let created = created.trim().to_string();
    if created.is_empty() {
        bail!("Failed to create the simulator device");
    }
    Ok(created)
}
