"""Tests for arena setup/cleanup. Each test runs in a throwaway git repo, never the real project."""

import json
import subprocess

import pytest

from arena import cleanup_battle, run_git, setup_battle

GLADIATORS = ["alpha", "beta"]


@pytest.fixture
def repo(tmp_path):
    """A tiny git repo with one commit on main, like a fresh Thunderdome clone."""
    run_git(tmp_path, "init", "-b", "main", "-q")
    run_git(tmp_path, "config", "user.email", "test@example.com")
    run_git(tmp_path, "config", "user.name", "Test")
    (tmp_path / ".gitignore").write_text("arena/\nbattles/\n")
    (tmp_path / "hello.py").write_text("print('hi')\n")
    run_git(tmp_path, "add", ".")
    run_git(tmp_path, "commit", "-q", "-m", "first")
    return tmp_path


def test_setup_gives_each_gladiator_its_own_worktree(repo):
    battle = setup_battle(repo, "demo", "build something", GLADIATORS)

    assert battle["id"] == "001-demo"
    for gladiator in GLADIATORS:
        worktree = repo / "arena" / gladiator / "001-demo"
        # The worktree holds a full copy of the committed code...
        assert (worktree / "hello.py").exists()
        # ...on the gladiator's own branch.
        assert run_git(worktree, "branch", "--show-current") == f"battle/001-demo/{gladiator}"


def test_hidden_tests_are_invisible_to_gladiators(repo):
    setup_battle(repo, "demo", "build something", GLADIATORS)
    (repo / "battles" / "001-demo" / "hidden_tests" / "test_secret.py").write_text("")

    worktree = repo / "arena" / "alpha" / "001-demo"
    assert not (worktree / "battles").exists()


def test_battle_record_is_saved_for_the_judge(repo):
    setup_battle(repo, "demo", "build something", GLADIATORS)

    record = json.loads((repo / "battles" / "001-demo" / "battle.json").read_text())
    assert record["task"] == "build something"
    assert set(record["gladiators"]) == set(GLADIATORS)


def test_battle_ids_count_up(repo):
    setup_battle(repo, "first", "task", GLADIATORS)
    second = setup_battle(repo, "second", "task", GLADIATORS)
    assert second["id"] == "002-second"


def test_cleanup_removes_worktrees_and_branches(repo):
    setup_battle(repo, "demo", "build something", GLADIATORS)
    cleanup_battle(repo, "001-demo")

    assert not (repo / "arena" / "alpha" / "001-demo").exists()
    assert run_git(repo, "branch", "--list", "battle/*") == ""
    # The record stays as battle history.
    assert (repo / "battles" / "001-demo" / "battle.json").exists()


def test_setup_fails_loudly_if_branch_already_exists(repo):
    run_git(repo, "branch", "battle/001-demo/alpha")
    with pytest.raises(subprocess.CalledProcessError):
        setup_battle(repo, "demo", "build something", GLADIATORS)
