#!/usr/bin/env rust

// 1 loader app in the iOS simulator or in the Apple TV simulator that swaps
// between several apps, `make swap`. See docs/hot-reload.md in hilen.
//
// Every command returns, so a person and an agent use it the same way.

use std::env::args;

use anyhow::{Result, bail};
use shared::{hot::System, swap::Swap};

const USAGE: &str = r"swap between apps in 1 process of the iOS simulator

  start <folder> <folder>..   build every app, start the first one
  to <name>                   build the app again and swap to it
  status                      the app on the screen and what the process holds
  stop                        end the process

the same in the Apple TV simulator, with the word tv in front:

  tv start <folder> <folder>..
  tv to <name>
  tv status
  tv stop

on a real Apple TV, paired with this Mac and on the same network:

  tv device install           like phone install
  tv device <folder>          like phone <folder>
  tv device status            like phone status

on a real iPhone, plugged in for the install, on the same network after it:

  phone install               build the loader with the app of this repo, install and start it
  phone <folder>              build the app and swap the phone to it
  phone status                the library the loader on the phone runs

A folder is the folder of the app crate. A name is its cargo package.";

fn main() -> Result<()> {
    let mut args: Vec<String> = args().skip(1).collect();
    let system = System::take(&mut args);
    let command = args.first().map(String::as_str).unwrap_or_default();
    let swap = Swap::new(system)?;

    match command {
        "start" if args.len() > 1 => swap.start(&args[1..]),
        "to" if args.len() == 2 => swap.to(&args[1]),
        "status" if args.len() == 1 => swap.status(),
        "stop" if args.len() == 1 => swap.stop(),
        "phone" | "device" if args.len() == 2 && (command == "device") == (system == System::Tvos) => {
            match args[1].as_str() {
                "install" => swap.device_install(),
                "status" => swap.device_status(),
                folder => swap.device_to(folder),
            }
        }
        _ => {
            println!("{USAGE}");
            bail!("no such command")
        }
    }
}
