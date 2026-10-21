import os
from pathlib import Path

import pytest
from shared.device import Device, Woke, seen
from shared.device_lock import Holder, is_agent, parse_ps
from shared.hot import System
from shared.make_device import engine_repo
from shared.swap import App
from shared.util import ScriptError


def test_a_device_is_read_from_a_line_of_the_inspect_tool():
    tool = Path("hilen-inspect")
    phone = Device.from_line("1E96\tiPhone\tMy iPhone\tiOS 27.0.1\t[fd00::1]:7435", tool)
    assert (phone.id, phone.name, phone.os) == ("1E96", "My iPhone", "iOS 27.0.1")
    assert phone.system is System.IOS
    assert phone.answers
    tv = Device.from_line("88F1\tappleTV\tBedroom TV\ttvOS 26.3\t-", tool)
    assert tv.system is System.TVOS
    assert not tv.answers
    with pytest.raises(ScriptError):
        Device.from_line("no tabs here", tool)


def test_an_app_that_answers_with_no_library_is_no_hot_build():
    hot = "loader   given at 192.168.0.208:7435\nlibrary  1791881864812.dylib"
    none = "Error: No hot build answers on My iPhone."
    stamp = "app code built: 1791644213\napp started:    1791881508"
    asleep = "Error: The app took the connection and gave no answer"
    assert seen(hot, "") is Woke.HOT
    assert seen(none, stamp) is Woke.PLAIN
    assert seen(none, asleep) is None


def test_the_engine_repo_is_found_above_an_app(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.delenv("HILEN_REPO", raising=False)
    app = tmp_path / "apps/game"
    app.mkdir(parents=True)
    (tmp_path / "hilen/hilen").mkdir(parents=True)
    (tmp_path / "hilen/hilen/Cargo.toml").write_text("")
    assert engine_repo(app) == tmp_path / "hilen"
    assert engine_repo(tmp_path / "hilen") == tmp_path / "hilen"


def test_a_holder_goes_through_its_file():
    holder = Holder("a1b2", 4242, "/Users/x/dev/apps/skaityk")
    assert Holder.from_text(holder.to_text()) == holder
    assert Holder.from_text("only a line") is None


def test_an_agent_is_told_by_its_command():
    assert is_agent("claude")
    assert is_agent("/opt/homebrew/bin/codex")
    assert not is_agent("zsh")
    assert not is_agent("claude-helper")


def test_a_ps_line_gives_the_parent_and_the_command():
    assert parse_ps("  812 /bin/zsh\n") == (812, "/bin/zsh")
    assert parse_ps("") is None


def test_the_same_session_is_the_same_agent():
    assert Holder("s1", 10, "").same_agent(Holder("s1", 11, ""))
    assert not Holder("s1", 10, "").same_agent(Holder("s2", 10, ""))
    assert Holder("", 10, "").same_agent(Holder("s2", 10, ""))


def test_an_app_is_found_from_the_folder_of_its_crate(tmp_path: Path):
    crate = tmp_path / "crates/game"
    crate.mkdir(parents=True)
    (tmp_path / "hilen.toml").write_text('project_name = "game"')
    (crate / "Cargo.toml").write_text('[package]\nname = "the-game"')
    app = App.find(str(crate))
    assert app.name == "the-game"
    assert app.root == os.path.realpath(tmp_path)


# `make device` runs at the repo root, which can be a workspace with the app
# crate in a folder of its own, like turnscan.
def test_a_workspace_root_names_the_app_by_its_default_member(tmp_path: Path):
    (tmp_path / "app").mkdir()
    (tmp_path / "hilen.toml").write_text('project_name = "game"')
    (tmp_path / "Cargo.toml").write_text(
        '[workspace]\nmembers = ["app", "crates/sim"]\ndefault-members = ["app"]'
    )
    (tmp_path / "app/Cargo.toml").write_text('[package]\nname = "the-game"')
    app = App.find(str(tmp_path))
    assert app.name == "the-game"
    assert app.root == os.path.realpath(tmp_path)
