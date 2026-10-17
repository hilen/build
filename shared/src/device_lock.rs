//! 1 session at a time sends apps to the loader of a device, `make device`.
//! On 2026-10-17 a second agent session swapped its own app onto a phone in
//! the middle of a test of another one, and 2 bugs looked like 1.
//!
//! The lock is a file per device on this Mac. It names the agent session
//! that holds it and the pid of that agent. It is free again when that
//! agent no longer runs, or after `make device args=release`. A person at a
//! terminal, with no agent above the command, always takes it, and is told
//! whose it was.

use std::{
    env::var,
    fs::{create_dir_all, read_to_string, remove_file, write},
    path::{Path, PathBuf},
    process,
};

use anyhow::{Result, bail};

use crate::run::probe;

/// Who sends the app: an agent session, or a person at a terminal.
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct Holder {
    /// The session id of the agent, empty for a person.
    pub session: String,
    /// The pid of the agent, 0 for a person.
    pub pid:     u32,
    /// The app folder it sent.
    pub app:     String,
}

impl Holder {
    fn to_text(&self) -> String {
        format!("{}\n{}\n{}\n", self.session, self.pid, self.app)
    }

    fn from_text(text: &str) -> Option<Self> {
        let mut lines = text.lines();
        let session = lines.next()?.to_string();
        let pid = lines.next()?.trim().parse().ok()?;
        let app = lines.next().unwrap_or_default().to_string();
        Some(Self { session, pid, app })
    }

    fn is_person(&self) -> bool {
        self.pid == 0
    }

    fn same_agent(&self, other: &Self) -> bool {
        if self.session.is_empty() || other.session.is_empty() {
            self.pid == other.pid
        } else {
            self.session == other.session
        }
    }

    fn name(&self) -> String {
        if self.is_person() {
            "a person at a terminal".into()
        } else {
            format!("the agent session {} with pid {}", self.session, self.pid)
        }
    }
}

fn lock_path(device: &str) -> Result<PathBuf> {
    Ok(PathBuf::from(var("HOME")?).join(".cache/hilen/device-locks").join(device))
}

fn is_agent(command: &str) -> bool {
    Path::new(command.trim())
        .file_name()
        .is_some_and(|name| name == "claude" || name == "codex")
}

/// The parent pid and the command of a line of `ps -o ppid=,comm=`.
fn parse_ps(line: &str) -> Option<(u32, String)> {
    let (ppid, command) = line.trim().split_once(char::is_whitespace)?;
    Some((ppid.parse().ok()?, command.trim().to_string()))
}

/// The nearest claude or codex process above this one.
fn agent_pid(mut pid: u32) -> Option<u32> {
    for _ in 0..40 {
        let (parent, command) = parse_ps(&probe(&format!("ps -o ppid=,comm= -p {pid}")))?;
        if is_agent(&command) {
            return Some(pid);
        }
        if parent <= 1 {
            return None;
        }
        pid = parent;
    }
    None
}

fn alive(pid: u32) -> bool {
    is_agent(&probe(&format!("ps -o comm= -p {pid}")))
}

fn me(app: &str) -> Holder {
    let Some(pid) = agent_pid(process::id()) else {
        return Holder {
            session: String::new(),
            pid:     0,
            app:     app.into(),
        };
    };
    let session = ["CLAUDE_CODE_SESSION_ID", "CODEX_THREAD_ID", "CODEX_SESSION_ID"]
        .iter()
        .find_map(|name| var(name).ok().filter(|value| !value.is_empty()))
        .unwrap_or_default();
    Holder {
        session,
        pid,
        app: app.into(),
    }
}

/// Takes the loader of the device for this session, or stops when another
/// running agent session holds it.
pub fn take(device: &str, app: &str) -> Result<()> {
    let path = lock_path(device)?;
    let me = me(app);

    if let Some(held) = read_to_string(&path).ok().and_then(|text| Holder::from_text(&text))
        && !held.is_person()
        && !held.same_agent(&me)
        && alive(held.pid)
    {
        if !me.is_person() {
            bail!(
                "the loader of this device is held by {} for {}. It is free when that agent stops, \
                 or after `make device args=release` from that session. Ask the owner of the device \
                 before anything else",
                held.name(),
                held.app
            );
        }
        println!("[lock] {} held the loader for {}, a person takes it", held.name(), held.app);
    }

    if let Some(dir) = path.parent() {
        create_dir_all(dir)?;
    }
    write(&path, me.to_text())?;
    Ok(())
}

/// Frees the loader of the device for any session.
pub fn release(device: &str) -> Result<()> {
    let path = lock_path(device)?;
    if path.exists() {
        remove_file(&path)?;
    }
    println!("[lock] the loader of this device is free");
    Ok(())
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn a_holder_goes_through_its_file() {
        let holder = Holder {
            session: "a1b2".into(),
            pid:     4242,
            app:     "/Users/x/dev/apps/skaityk".into(),
        };
        assert_eq!(Holder::from_text(&holder.to_text()), Some(holder));
        assert_eq!(Holder::from_text("only a line"), None);
    }

    #[test]
    fn an_agent_is_told_by_its_command() {
        assert!(is_agent("claude"));
        assert!(is_agent("/opt/homebrew/bin/codex"));
        assert!(!is_agent("zsh"));
        assert!(!is_agent("claude-helper"));
    }

    #[test]
    fn a_ps_line_gives_the_parent_and_the_command() {
        assert_eq!(parse_ps("  812 /bin/zsh\n"), Some((812, "/bin/zsh".into())));
        assert_eq!(parse_ps(""), None);
    }

    #[test]
    fn the_same_session_is_the_same_agent() {
        let agent = |session: &str, pid| Holder {
            session: session.into(),
            pid,
            app: String::new(),
        };
        assert!(agent("s1", 10).same_agent(&agent("s1", 11)));
        assert!(!agent("s1", 10).same_agent(&agent("s2", 10)));
        assert!(agent("", 10).same_agent(&agent("s2", 10)));
    }
}
