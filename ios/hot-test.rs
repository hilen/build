#!/usr/bin/env rust

// The hot reload lane of hilen, `make hot-test`, and `make hot-test args="tv"`
// for the Apple TV simulator. See docs/hot-reload.md there.
//
// Builds the `hot-test` app 2 times as a dynamic library, the second time as
// the same app after a change. It starts the first through the loader, then
// swaps the 2 several times in the one running process. After every swap it
// checks that the new code runs, that the screen shows it, that the process
// is still the same, and that no thread of an old library stayed behind.

use std::{env::args, fs::copy, path::Path, thread::sleep, time::Duration};

use anyhow::{Result, bail};
use shared::{
    hot::{Hot, System, is_alive, screen_color, thread_count},
    run::run_quiet,
};

const PACKAGE: &str = "hot-test";
const EXECUTABLE: &str = "HotTest";
const BUNDLE_ID: &str = "hilen.hot-test";
const MARKER: &str = "hot-generation";
const RELOADS: usize = 6;

/// What a build leaves behind when it runs.
struct Build {
    name:    &'static str,
    feature: &'static str,
    color:   (u8, u8, u8),
}

const FIRST: Build = Build {
    name:    "first",
    feature: "",
    color:   (255, 0, 0),
};
const SECOND: Build = Build {
    name:    "second",
    feature: ",second",
    color:   (0, 255, 0),
};

fn step(message: &str) {
    println!("\n[hot-test] {message}");
}

fn main() -> Result<()> {
    if !cfg!(target_os = "macos") {
        println!("[hot-test] not macOS, skipping the hot reload lane.");
        return Ok(());
    }

    let mut args: Vec<String> = args().skip(1).collect();
    let hot = Hot::named(EXECUTABLE, BUNDLE_ID)?.for_system(System::take(&mut args));
    hot.prepare()?;

    // Both builds land in the same file, so each is put aside.
    let mut libraries = vec![];
    for build in [&SECOND, &FIRST] {
        step(&format!("building the {} library", build.name));
        let built = hot.build_library(PACKAGE, build.feature)?;
        let kept = built.with_extension(build.name);
        copy(&built, &kept)?;
        libraries.push(kept);
    }
    let second = &libraries[0];
    let first = &libraries[1];

    step("building the loader");
    let loader = hot.build_loader()?;

    step("starting the first library");
    hot.publish(first, None)?;
    let device = hot.device()?;
    let result = swap(&hot, &device, &loader, first, second);
    hot.release_device(&device);
    result
}

fn swap(hot: &Hot, device: &str, loader: &Path, first: &Path, second: &Path) -> Result<()> {
    let pid = hot.launch(device, loader)?;
    check(hot, device, pid, &FIRST)?;

    let mut threads = vec![];
    for reload in 1..=RELOADS {
        let (build, library) = if reload % 2 == 1 {
            (&SECOND, second)
        } else {
            (&FIRST, first)
        };
        step(&format!("reload {reload}, the {} library", build.name));
        hot.publish(library, None)?;
        check(hot, device, pid, build)?;
        threads.push(thread_count(pid)?);
    }

    println!("[hot-test] threads after each reload: {threads:?}");
    // The first reloads can still start a thread that every later library
    // reuses, like one of the OS. From then on the count must not grow.
    let settled = threads[1];
    let last = threads[RELOADS - 1];
    if last > settled {
        bail!("an old library left threads behind: {settled} after reload 2, {last} after reload {RELOADS}");
    }

    run_quiet(&format!("xcrun simctl terminate {device} {BUNDLE_ID}"))?;
    step(&format!("ok: {RELOADS} reloads in process {pid}"));
    Ok(())
}

/// The library that was put out runs, shows on the screen, and the process
/// is the one the loader started.
fn check(hot: &Hot, device: &str, pid: u32, build: &Build) -> Result<()> {
    hot.wait_for_marker(device, MARKER, build.name)?;
    if !is_alive(pid) {
        bail!("process {pid} is gone, the app did not survive the {} library", build.name);
    }
    // The marker is written before the first frame is out.
    let mut color = (0, 0, 0);
    for _ in 0..20 {
        color = screen_color(device)?;
        if color == build.color {
            return Ok(());
        }
        sleep(Duration::from_millis(250));
    }
    bail!("the screen shows {color:?}, the {} library draws {:?}", build.name, build.color)
}
