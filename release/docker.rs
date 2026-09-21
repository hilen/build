//! Shared by linux.rs and win.rs. Builds the tool image and runs one shell
//! string inside it with the repo mounted, plus named volumes for the cargo
//! caches so a second run does not start from zero. On a dev box the engine
//! checkout next to the apps dir is mounted too, so a path dependency on it
//! resolves inside the container the same way it does outside.

use anyhow::Result;
use shared::run::{capture, run};

pub fn build_image(name: &str, dockerfile: &str, platform: &str) -> Result<()> {
    run(&format!(
        "docker build --platform {platform} -f build/release/{dockerfile} -t {name} build/release"
    ))
}

/// `stage` is the folder under target/ that the script writes for the host to
/// read back. The download caches are shared by every app on the box, the
/// target volume carries the app name so two apps never build into one folder.
pub fn run_in(app: &str, image: &str, platform: &str, lane: &str, stage: &str, script: &str) -> Result<()> {
    let cwd = std::env::current_dir()?;
    let cwd = cwd.display();
    let engine = std::path::Path::new("../../hilen");
    let engine_mount = if engine.is_dir() {
        format!("-v {}:/work/hilen", std::fs::canonicalize(engine)?.display())
    } else {
        String::new()
    };
    let arch = platform.replace('/', "-");
    // The app embeds its Sentry DSN with option_env! at compile time, and the
    // compiler runs in the container. Only the name goes on the command line,
    // docker copies the value from the host env, so no log shows it. Unset on
    // the host means unset in the container.
    let sentry = format!("{}_SENTRY_URL", app.to_uppercase().replace('-', "_"));
    // The engine build script masks HILEN_SESSION_KEY into an app with the
    // `login` feature, and HILEN_RELEASE makes it refuse the development key.
    // Both pass by name for the same reason as the DSN.
    // The container runs as root. On a Linux host the staged files would stay
    // root owned, and the next run or the runner cleanup could not touch them.
    let uid = capture("id -u")?;
    let gid = capture("id -g")?;
    run(&format!(
        r#"docker run --rm --platform {platform} \
  -v "{cwd}:/work/apps/app" \
  {engine_mount} \
  -v {app}-{lane}-{arch}-target:/work/apps/app/target/{lane} \
  -v {lane}-{arch}-cargo-registry:/usr/local/cargo/registry \
  -v {lane}-{arch}-cargo-git:/usr/local/cargo/git \
  -v {lane}-{arch}-rustup:/usr/local/rustup \
  -e CARGO_TARGET_DIR=/work/apps/app/target/{lane} \
  -e {sentry} \
  -e HILEN_SESSION_KEY \
  -e HILEN_RELEASE \
  {image} bash -c 'trap "chown -R {uid}:{gid} /work/apps/app/target/{stage}" EXIT; {script}'"#
    ))
}
