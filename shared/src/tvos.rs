//! What the tvOS scripts share.

pub const DEVICE: &str = "aarch64-apple-tvos";
pub const SIMULATOR: &str = "aarch64-apple-tvos-sim";

/// The release staticlib of a target, the path the Xcode project links from.
pub fn lib(target: &str, lib_name: &str) -> String {
    format!("target/{target}/release/{lib_name}")
}
