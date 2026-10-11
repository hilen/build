#!/usr/bin/env rust

// Runs the app of this folder on a paired iPhone, iPad or Apple TV as a hot
// build, `make device`. See docs/hot-reload.md in hilen.
//
// The device runs a loader app, installed once. This command builds the app
// as 1 dynamic library and sends it over the network, and the loader swaps
// to it with no install. Nothing watches the sources, a new build goes out
// on the next call.

use std::env::{args, current_dir};

use anyhow::{Result, bail};
use shared::device::make_device;

const USAGE: &str = r#"run the app of this folder on a paired iPhone, iPad or Apple TV

  make device                  build the app and swap the device to it
  make device args=status      the library the loader on the device runs
  make device args=install     build the loader, install it and start it, once per device

A word in front picks the device by a part of its name or kind, like
args=tv or args="ipad install". The next call with no word goes to the
same device."#;

fn main() -> Result<()> {
    let mut args: Vec<String> = args().skip(1).collect();
    let command = match args.last().map(String::as_str) {
        Some("install" | "status") => args.pop(),
        _ => None,
    };
    if args.len() > 1 || args.first().is_some_and(|word| word.starts_with('-')) {
        println!("{USAGE}");
        bail!("no such command");
    }
    make_device(&current_dir()?, args.first().map(String::as_str), command.as_deref())
}
