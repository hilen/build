#!/usr/bin/env rust

// Hot reload of the app in the iOS simulator, `make hot`. See docs/hot-reload.md
// in hilen.
//
// Builds the app as 1 dynamic library, starts the loader app in the simulator
// of this Mac, then watches the sources. Every saved file is a new build, and
// the running app swaps to it with no install and no restart.

use std::{
    thread::sleep,
    time::{Duration, Instant},
};

use anyhow::Result;
use shared::{config, hot::Hot};

const POLL: Duration = Duration::from_millis(300);

fn step(message: &str) {
    println!("\n[hot] {message}");
}

fn main() -> Result<()> {
    let config = config::read()?;
    let hot = Hot::new(&config)?;

    step("building the library");
    hot.prepare()?;
    let library = hot.build_library(&config.app_name, "")?;
    hot.publish(&library, None)?;

    step("building the loader");
    let loader = hot.build_loader()?;

    step("starting the app");
    let device = hot.device()?;
    let pid = hot.launch(&device, &loader)?;
    step(&format!("{} runs as process {pid}. A saved file reloads it, Ctrl-C ends.", hot.bundle_id()));

    let mut sources = hot.sources()?;
    loop {
        sleep(POLL);
        let now = hot.sources()?;
        if now == sources {
            continue;
        }
        sources = now;

        let started = Instant::now();
        match hot.build_library(&config.app_name, "") {
            Ok(library) => {
                let name = hot.publish(&library, None)?;
                step(&format!("{name} is out after {:.1} s", started.elapsed().as_secs_f32()));
            }
            // The loader has no new file to load, the app keeps its code.
            Err(err) => step(&format!("the build failed, the app keeps the old code: {err}")),
        }
    }
}
