//! The session key a shipped phone build bakes in. The engine seals the stored
//! login with it, see SessionStore in hilen. A release build of an app with a
//! login fails in the engine build script when the key is missing, so a phone
//! never ships the public development key.

use anyhow::{Context, Result, ensure};

use crate::{config::Config, run::capture};

pub const SESSION_KEY_ENV: &str = "HILEN_SESSION_KEY";

/// The key from the environment, set by with-secrets.sh, or else from the
/// Infisical project that hilen.toml names. None when neither is there, an app
/// with no login needs no key.
pub fn session_key(config: &Config) -> Result<Option<String>> {
    if let Ok(key) = std::env::var(SESSION_KEY_ENV)
        && !key.is_empty()
    {
        return Ok(Some(key));
    }
    let Some(project) = &config.infisical_project else {
        return Ok(None);
    };
    let key = capture(&format!(
        "infisical secrets get {SESSION_KEY_ENV} --projectId {project} --env prod --plain --silent"
    ))
    .with_context(|| format!("{SESSION_KEY_ENV} was not read from Infisical project {project}"))?;
    ensure!(
        !key.is_empty(),
        "{SESSION_KEY_ENV} is empty in Infisical project {project}"
    );
    Ok(Some(key))
}

/// The far job that builds a shipped lib. The key goes in on stdin, so the job
/// line, the far log and the process list never hold it.
pub fn far_job(build: &str, key: Option<&str>) -> String {
    let release = crate::inspect::RELEASE_ENV;
    match key {
        Some(_) => masked(&format!(
            "far --on mac 'read -r {SESSION_KEY_ENV} && export {SESSION_KEY_ENV} {release}=1 && {build}'"
        )),
        None => format!("far --on mac 'export {release}=1 && {build}'"),
    }
}

/// Runs `cmd` with its output filtered. cargo lipo prints the whole environment
/// of a failed build, the key with it. awk takes the key from its environment,
/// so it is not on any command line either. The caller sets the key in the
/// environment of this process first.
pub fn masked(cmd: &str) -> String {
    format!(
        "set -o pipefail; {cmd} 2>&1 | awk '{{ k = ENVIRON[\"{SESSION_KEY_ENV}\"]; if (k != \"\") gsub(k, \"[hidden]\"); print; fflush() }}'"
    )
}

#[cfg(test)]
mod test {
    use super::far_job;

    #[test]
    fn the_job_line_never_holds_the_key() {
        let job = far_job("cargo lipo -p app --release", Some("secret-key-value"));
        assert!(!job.contains("secret-key-value"));
        assert!(job.contains("read -r HILEN_SESSION_KEY"));
        assert!(job.contains("HILEN_RELEASE=1"));
    }

    #[test]
    fn the_mask_hides_the_key_and_keeps_the_exit_code() {
        use std::process::Command;

        let key = "0123abcd";
        let run = |cmd: &str| {
            Command::new("sh")
                .arg("-c")
                .arg(super::masked(cmd))
                .env(super::SESSION_KEY_ENV, key)
                .output()
                .unwrap()
        };
        let shown = run("echo HILEN_SESSION_KEY=\"$HILEN_SESSION_KEY\" and more");
        let text = String::from_utf8_lossy(&shown.stdout);
        assert_eq!(text.trim(), "HILEN_SESSION_KEY=[hidden] and more");
        assert!(shown.status.success());

        let failed = run("echo $HILEN_SESSION_KEY >&2; exit 3");
        assert!(!String::from_utf8_lossy(&failed.stdout).contains(key));
        assert!(!failed.status.success());
    }

    #[test]
    fn a_job_with_no_key_is_still_a_release() {
        let job = far_job("cargo lipo -p app --release", None);
        assert!(!job.contains("HILEN_SESSION_KEY"));
        assert!(job.contains("export HILEN_RELEASE=1 && cargo lipo"));
    }
}
