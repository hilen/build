//! Running commands. Every command is a shell string, the same way the make
//! targets and the old scripts wrote them, so a pipe or a quoted argument keeps
//! working without being taken apart into an argv.

use std::process::{Command, Stdio};

use anyhow::{Result, bail};

/// The shell that runs a command string, cmd on Windows and sh elsewhere.
#[cfg(not(windows))]
fn shell(cmd: &str) -> Command {
    let mut c = Command::new("sh");
    c.arg("-c").arg(cmd);
    c
}

/// cmd does not read the `\"` that `arg` writes for a quote inside an argument,
/// so `git commit -m "release v1.2.3"` reached git as 2 broken words. The
/// string goes in untouched. With `/S` cmd strips only the outer pair of
/// quotes, so a command that itself starts with a quote survives too.
#[cfg(windows)]
fn shell(cmd: &str) -> Command {
    use std::os::windows::process::CommandExt;

    let mut c = Command::new("cmd");
    c.arg("/S").arg("/C").raw_arg(format!("\"{cmd}\""));
    c
}

/// Echo the command, run it inheriting the terminal, and fail on a non zero exit.
pub fn run(cmd: &str) -> Result<()> {
    println!("{cmd}");
    let status = shell(cmd).status()?;
    if !status.success() {
        bail!("command failed: {cmd}");
    }
    Ok(())
}

/// Like `run` but a non zero exit is expected and ignored, for cleanup steps.
pub fn run_allow_fail(cmd: &str) {
    println!("{cmd}");
    if let Err(e) = shell(cmd).status() {
        println!("ignoring: {e}");
    }
}

/// Capture stdout. stdout is piped rather than inherited, so a captured secret
/// never reaches the log.
pub fn capture(cmd: &str) -> Result<String> {
    println!("{cmd}");
    let out = shell(cmd).stdout(Stdio::piped()).stderr(Stdio::inherit()).output()?;
    if !out.status.success() {
        bail!("command failed: {cmd}");
    }
    Ok(String::from_utf8_lossy(&out.stdout).trim().to_string())
}

/// Run a command that reads a secret from the environment. The command is not
/// echoed, so write the secret as a shell variable like `$TOKEN`, never as its
/// value.
pub fn run_secret(cmd: &str) -> Result<()> {
    let status = shell(cmd).status()?;
    if !status.success() {
        bail!("credentialed command failed with {status}");
    }
    Ok(())
}

/// Capture stdout and stderr together and never fail, for probing commands whose
/// non zero exit is a normal answer.
pub fn probe(cmd: &str) -> String {
    let Ok(out) = shell(cmd).output() else {
        return String::new();
    };
    let mut text = String::from_utf8_lossy(&out.stdout).into_owned();
    text.push_str(&String::from_utf8_lossy(&out.stderr));
    text
}

/// Run quietly, printing the captured output only when the command fails. Keeps
/// a parallel lane's output from mangling another's.
pub fn run_quiet(cmd: &str) -> Result<String> {
    let out = shell(cmd).output()?;
    let mut text = String::from_utf8_lossy(&out.stdout).into_owned();
    text.push_str(&String::from_utf8_lossy(&out.stderr));
    if !out.status.success() {
        eprint!("{text}");
        bail!("command failed: {cmd}");
    }
    Ok(text)
}

#[cfg(test)]
mod tests {
    use anyhow::Result;

    use super::capture;

    // On Windows the inner quotes used to reach git escaped, as 2 words.
    #[test]
    fn a_quoted_argument_stays_one_argument() -> Result<()> {
        let out = capture(r#"git rev-parse --sq-quote "two words""#)?;
        assert_eq!(out, "'two words'");
        Ok(())
    }
}
